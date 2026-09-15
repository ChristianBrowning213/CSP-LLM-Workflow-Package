"""Render a paper/poster workflow artifact from a completed demo run bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import textwrap
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class VestaRenderError(RuntimeError):
    """Raised when a VESTA render stage fails."""

    def __init__(self, code: str, message: str, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics or {}


class VestaUnavailableError(VestaRenderError):
    """Raised when VESTA rendering is required but cannot be launched."""


_VESTA_RENDER_LOCK = threading.Lock()
_VESTA_BUILD_UUID = os.environ.get("VESTA_RENDER_BUILD_UUID") or uuid.uuid4().hex
_VESTA_STAGING_ROOT = Path(os.environ.get("VESTA_RENDER_STAGING_ROOT") or "artifacts/vesta_render_staging")


def _safe_slug(value: str) -> str:
    slug = "".join(ch.lower() for ch in value if ch.isalnum() or ch in {"_", "-"})
    return slug or "workflow"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return _to_float(value, default) if value not in {None, ""} else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return _to_int(value, default) if value not in {None, ""} else default


def _wrap(value: Any, width: int = 34, max_lines: int = 8) -> str:
    text = _stringify(value)
    if not text:
        return ""
    lines = textwrap.wrap(text, width=width, break_long_words=False, replace_whitespace=True)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["..."]
    return "\n".join(lines)


def _step(execution: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for step in execution.get("step_results", []) or []:
        if step.get("tool_name") == tool_name:
            return step
    return {}


def _artifact_ref(step: dict[str, Any], ref_name: str) -> str:
    for ref in step.get("artifact_refs", []) or []:
        if ref.get("ref_name") == ref_name:
            return str(ref.get("value") or "")
    return ""


def _candidate_paths_from_retrieval(step: dict[str, Any], limit: int = 5) -> list[Path]:
    paths: list[Path] = []
    candidate = _artifact_ref(step, "candidate_cif_path")
    if candidate:
        paths.append(Path(candidate))
    corpus_ref = _artifact_ref(step, "corpus_ref")
    if corpus_ref and Path(corpus_ref).exists():
        for path in sorted(Path(corpus_ref).glob("*.cif")):
            if path not in paths:
                paths.append(path)
            if len(paths) >= limit:
                break
    return paths[:limit]


def _formula_elements(formula: str) -> set[str]:
    return set(re.findall(r"[A-Z][a-z]?", formula or ""))


def _resolve_run_ref(path_text: str, run_dir: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    direct = Path.cwd() / path
    if direct.exists():
        return direct
    return run_dir / path


def _load_raw_step_response(step: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    raw_ref = str(step.get("raw_result_ref") or "")
    if not raw_ref:
        return {}
    return _read_json(_resolve_run_ref(raw_ref, run_dir))


def _read_pair_csv(path_text: str) -> list[str]:
    if not path_text:
        return []
    path = Path(path_text)
    if not path.is_file():
        return []
    try:
        import csv

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = csv.DictReader(handle)
            pairs = [str(row.get("pair") or row.get("spp_pair") or "").strip() for row in rows]
    except OSError:
        return []
    return [pair for pair in pairs if pair]


def _load_structure_image_manifest(path_text: str) -> dict[str, Any]:
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.is_file():
        return {}
    rows: list[dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return {}
    final_by_row: dict[str, str] = {}
    neighbours_by_row: dict[str, dict[int, str]] = {}
    for row in rows:
        if row.get("render_status") != "rendered":
            continue
        row_id = str(row.get("row_id") or "")
        png = str(row.get("desired_png_path") or "")
        if not row_id or not png:
            continue
        if row.get("cif_role") == "final_generated":
            final_by_row[row_id] = png
        elif row.get("cif_role") == "semantic_neighbour":
            rank = _to_int(row.get("neighbour_rank"), len(neighbours_by_row.get(row_id, {})) + 1)
            neighbours_by_row.setdefault(row_id, {})[rank] = png
    return {"final_by_row": final_by_row, "neighbours_by_row": neighbours_by_row, "manifest_path": path_text}


def _extract_json_payload(raw_response: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_response.get("result"), dict):
        return raw_response["result"]
    for item in raw_response.get("content", []) or []:
        if isinstance(item, dict) and isinstance(item.get("json"), dict):
            return item["json"]
    return raw_response


def _resolve_vesta_executable(vesta_path: str | Path | None = None) -> str:
    explicit = str(vesta_path or "").strip()
    candidates = [
        explicit,
        os.environ.get("VESTA_EXE", ""),
        os.environ.get("VESTA_PATH", ""),
        shutil.which("VESTA") or "",
        shutil.which("VESTA.exe") or "",
        "C:/Program Files/VESTA/VESTA.exe",
        "C:/Program Files (x86)/VESTA/VESTA.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return str(path.resolve())
    return ""


def _vesta_status(vesta_path: str | Path | None = None) -> dict[str, Any]:
    try:
        from qlip.visualization import vesta as qlip_vesta_module  # type: ignore

        qlip_vesta_found = bool(qlip_vesta_module)
    except Exception:
        qlip_vesta_found = False
    exe = _resolve_vesta_executable(vesta_path)
    return {
        "qlip_vesta_module_found": qlip_vesta_found,
        "vesta_executable": exe or "",
        "status": "available" if exe else "vesta_unavailable",
        "setup_instructions": "Install VESTA and add VESTA.exe to PATH, set VESTA_EXE/VESTA_PATH, or pass --vesta-path to enable true VESTA rendering.",
    }


def _json_text_for_diagnostics(*payloads: Any) -> str:
    chunks: list[str] = []
    for payload in payloads:
        if payload is None or payload == "":
            continue
        if isinstance(payload, str):
            chunks.append(payload)
            continue
        try:
            chunks.append(json.dumps(payload, sort_keys=True, default=str))
        except TypeError:
            chunks.append(str(payload))
    return "\n".join(chunks)


def _classify_qlip_failure(
    *,
    validation_step: dict[str, Any],
    validation_summary: dict[str, Any],
    solve_step: dict[str, Any],
    solve_summary: dict[str, Any],
    solve_payload: dict[str, Any],
    solve_observed: dict[str, Any],
    solution_cif: str,
    pot_root: str,
    missing_pairs: list[Any],
) -> dict[str, Any]:
    qlip_validate_status = (
        "valid"
        if validation_summary.get("valid") is True
        else validation_summary.get("package_validation_status")
        or validation_step.get("status")
        or ""
    )
    qlip_solve_status = (
        solve_summary.get("status")
        or solve_summary.get("qlip_status")
        or solve_observed.get("qlip_status")
        or solve_step.get("status")
        or ""
    )
    messages = solve_summary.get("qlip_error_messages") or []
    if isinstance(messages, str):
        messages = [messages]
    step_error = solve_step.get("error") if isinstance(solve_step.get("error"), dict) else {}
    text = _json_text_for_diagnostics(solve_summary, solve_payload, solve_step.get("warnings"), step_error, solve_observed)
    lowered = text.lower()
    solution_path = Path(solution_cif) if solution_cif else None
    solution_produced = bool(solution_path and solution_path.is_file())
    solve_started = bool(solve_step) and (solve_step.get("status") not in {"pending", "skipped", None} or bool(solve_summary) or bool(solve_payload))
    gurobi_available = (validation_summary.get("capabilities") or {}).get("gurobi_available")
    if gurobi_available is None:
        gurobi_available = validation_summary.get("gurobi_available")
    failure_message = "; ".join(str(message) for message in messages if message)
    if not failure_message:
        failure_message = str(step_error.get("message") or "")
    category = ""
    license_status = "unknown"
    status_lower = str(qlip_solve_status).lower()
    solve_failed = status_lower in {"error", "failed", "fail"} or bool(step_error) or (solve_started and not solution_produced and status_lower not in {"optimal", "succeeded", "success"})
    if solve_failed:
        if "license" in lowered and ("expired" in lowered or "has expired" in lowered):
            category = "gurobi_license_expired"
            license_status = "expired"
            failure_message = failure_message or "Gurobi license expired; QLIP solve could not run."
        elif gurobi_available is False:
            category = "gurobi_unavailable"
            license_status = "unavailable"
            failure_message = failure_message or "Gurobi was unavailable; QLIP solve could not run."
        elif missing_pairs:
            category = "missing_required_pot_pair"
        elif pot_root and not Path(str(pot_root)).exists():
            category = "invalid_pot_root"
        elif "invalid" in lowered and "request" in lowered:
            category = "qlip_request_invalid"
        elif "infeasible" in lowered:
            category = "qlip_infeasible"
        elif "model" in lowered and ("build" in lowered or "construction" in lowered):
            category = "qlip_model_build_failed"
        elif not solution_produced:
            category = "qlip_no_solution_cif"
        else:
            category = "unknown_qlip_failure"
    elif gurobi_available is True:
        license_status = "available_or_not_checked"

    if category == "gurobi_license_expired":
        user_visible_reason = "Gurobi license expired; QLIP solve could not run."
    elif category:
        user_visible_reason = failure_message or category
    else:
        user_visible_reason = ""

    return {
        "qlip_validate_status": qlip_validate_status,
        "qlip_solve_status": qlip_solve_status,
        "qlip_failure_category": category,
        "qlip_failure_message": failure_message,
        "qlip_failure_user_visible_reason": user_visible_reason,
        "gurobi_available": gurobi_available if gurobi_available is not None else "",
        "gurobi_license_status": license_status,
        "qlip_solve_started": solve_started,
        "qlip_solution_cif_produced": solution_produced,
        "qlip_solution_cif_path": str(solution_path) if solution_path else "",
    }


def _load_run_data(run_dir: Path, case_name: str) -> dict[str, Any]:
    evaluation = _read_json(run_dir / "report" / "workflow_evaluation.json")
    execution = _read_json(run_dir / "_raw_run" / "execution" / "execution_run.json")
    if not execution:
        execution = _read_json(run_dir / "execution" / "execution_run.json")
    retrieval_step = _step(execution, "crystal.csp_pack")
    spp_step = _step(execution, "spp.run_pipeline")
    validation_step = _step(execution, "qlip.validate_request")
    solve_step = _step(execution, "qlip.solve")

    retrieval_summary = retrieval_step.get("output_summary") or {}
    corpus_selection = retrieval_summary.get("corpus_selection") if isinstance(retrieval_summary.get("corpus_selection"), dict) else {}
    spp_summary = spp_step.get("output_summary") or {}
    validation_summary = validation_step.get("output_summary") or {}
    solve_summary = solve_step.get("output_summary") or {}
    solve_payload = _extract_json_payload(_load_raw_step_response(solve_step, run_dir))
    retrieval_payload = _extract_json_payload(_load_raw_step_response(retrieval_step, run_dir))
    export_items = (retrieval_payload.get("export") or {}).get("items") or []
    neighbors = retrieval_payload.get("neighbors") or []

    retrieval_observed = ((evaluation.get("evidence_checks") or {}).get("retrieval") or {}).get("observed") or {}
    spp_observed = ((evaluation.get("evidence_checks") or {}).get("spp_guidance") or {}).get("observed") or {}
    solve_observed = ((evaluation.get("execution_checks") or {}).get("solve") or {}).get("observed") or {}
    novelty_observed = (evaluation.get("novelty_assessment") or {}).get("observed") or {}

    solution_cif = (
        solve_summary.get("solution_cif_path")
        or solve_observed.get("solution_cif_path")
        or (evaluation.get("artifact_refs") or {}).get("solution_cif_path")
        or ""
    )
    gurobi_visuals = solve_summary.get("gurobi_visuals") if isinstance(solve_summary.get("gurobi_visuals"), dict) else {}
    gurobi_artifacts = {
        "constraint_matrix_spy_path": solve_summary.get("constraint_matrix_spy_path") or _artifact_ref(solve_step, "constraint_matrix_spy_path") or gurobi_visuals.get("constraint_matrix_spy_path"),
        "constraint_matrix_meta_path": solve_summary.get("constraint_matrix_meta_path") or _artifact_ref(solve_step, "constraint_matrix_meta_path") or gurobi_visuals.get("constraint_matrix_meta_path"),
        "mip_trace_plot_path": solve_summary.get("mip_trace_plot_path") or _artifact_ref(solve_step, "mip_trace_plot_path") or gurobi_visuals.get("mip_trace_plot_path"),
        "mip_trace_json_path": solve_summary.get("mip_trace_json_path") or _artifact_ref(solve_step, "mip_trace_json_path") or gurobi_visuals.get("mip_trace_json_path"),
        "mip_trace_csv_path": solve_summary.get("mip_trace_csv_path") or _artifact_ref(solve_step, "mip_trace_csv_path") or gurobi_visuals.get("mip_trace_csv_path"),
    }
    pot_root = spp_summary.get("selected_pot_root") or spp_summary.get("pot_root") or spp_observed.get("pot_root") or ""
    missing_pairs = spp_summary.get("qlip_package_missing_pairs") or spp_observed.get("missing_pairs") or []
    spp_pairs_csv_path = str(spp_summary.get("spp_pairs_csv_path") or "")
    row_specific_pairs = (
        list(spp_summary.get("row_specific_spp_pairs") or [])
        or _read_pair_csv(spp_pairs_csv_path)
        or list(spp_summary.get("qlip_package_required_pairs") or spp_observed.get("required_pairs") or [])
    )
    row_specific_spp_found = bool(spp_summary.get("row_specific_spp_found") or row_specific_pairs)
    universal_regulariser_root = str(spp_summary.get("universal_regulariser_root") or pot_root or "")
    universal_regulariser_used = bool(spp_summary.get("universal_regulariser_used") if "universal_regulariser_used" in spp_summary else universal_regulariser_root)
    source_mode = str(
        spp_summary.get("spp_panel_source_mode")
        or ("row_specific_plus_universal_regulariser" if row_specific_spp_found and universal_regulariser_used else "row_specific_retrieval_spp" if row_specific_spp_found else "universal_regulariser_only_fallback" if universal_regulariser_used else "spp_unavailable")
    )
    qlip_failure = _classify_qlip_failure(
        validation_step=validation_step,
        validation_summary=validation_summary,
        solve_step=solve_step,
        solve_summary=solve_summary,
        solve_payload=solve_payload,
        solve_observed=solve_observed,
        solution_cif=str(solution_cif or ""),
        pot_root=str(pot_root or ""),
        missing_pairs=list(missing_pairs or []),
    )
    return {
        "run_dir": str(run_dir),
        "case_name": case_name,
        "goal": evaluation.get("goal") or retrieval_summary.get("query") or "",
        "material_system": evaluation.get("material_system") or case_name,
        "figure_title": str(evaluation.get("figure_title") or ""),
        "paper_hero_mode": bool(evaluation.get("paper_hero_mode")),
        "retrieval_step": retrieval_step,
        "retrieved_cifs": _candidate_paths_from_retrieval(retrieval_step),
        "export_items": export_items,
        "neighbors": neighbors,
        "exported_cif_count": retrieval_summary.get("exported_cif_count") or retrieval_observed.get("exported_cif_count") or 0,
        "selected_evidence_for_spp_count": corpus_selection.get("selected_evidence_for_spp_count") or retrieval_summary.get("exported_cif_count") or retrieval_observed.get("exported_cif_count") or 0,
        "paper_display_neighbour_count": corpus_selection.get("paper_display_neighbour_count") or retrieval_summary.get("paper_display_neighbour_count") or retrieval_observed.get("paper_display_neighbour_count") or len(neighbors) or 0,
        "neighbor_count": retrieval_summary.get("neighbor_count") or retrieval_observed.get("neighbor_count") or len(neighbors) or "",
        "corpus_status": (retrieval_summary.get("corpus_selection") or {}).get("status") or retrieval_step.get("status") or "unknown",
        "pot_root": pot_root,
        "pot_root_source": spp_summary.get("pot_root_source") or ("unknown" if (spp_summary.get("selected_pot_root") or spp_observed.get("pot_root")) else "none"),
        "spp_source_label": spp_summary.get("spp_source_label") or spp_summary.get("pot_source_label") or spp_summary.get("pot_root_source") or "",
        "spp_summary_path": spp_summary.get("spp_summary_path") or "",
        "spp_pairs_csv_path": spp_pairs_csv_path,
        "extraction_mode": spp_summary.get("extraction_mode") or (spp_summary.get("fresh_generation") or {}).get("extraction_mode") or "unknown",
        "required_pairs": row_specific_pairs,
        "available_pairs": spp_summary.get("qlip_package_available_pairs") or spp_summary.get("available_pairs") or [],
        "missing_pairs": missing_pairs,
        "row_specific_spp_source_path": spp_summary.get("row_specific_spp_source_path") or spp_pairs_csv_path,
        "row_specific_spp_found": row_specific_spp_found,
        "row_specific_spp_pair_count": len(row_specific_pairs),
        "row_specific_spp_pairs": row_specific_pairs,
        "universal_regulariser_used": universal_regulariser_used,
        "universal_regulariser_root": universal_regulariser_root,
        "spp_panel_source_mode": source_mode,
        "qlip_valid": validation_summary.get("valid", ""),
        "qlip_validation_status": validation_summary.get("package_validation_status") or validation_step.get("status") or "",
        "qlip_status": solve_summary.get("status") or solve_summary.get("qlip_status") or solve_observed.get("qlip_status") or "",
        "objective_value": solve_summary.get("objective_value", solve_observed.get("objective_value", "")),
        "solution_cif": Path(solution_cif) if solution_cif else None,
        "novelty": novelty_observed.get("is_novel", ""),
        "final_crystal_caption": str(evaluation.get("final_crystal_caption") or ""),
        "sca_validation": evaluation.get("sca_validation")
        if isinstance(evaluation.get("sca_validation"), dict)
        else {},
        "gurobi_visual_artifacts": {key: str(value) for key, value in gurobi_artifacts.items() if value},
        **qlip_failure,
    }


def _parse_cif_atoms(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    atoms: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if lines[i].strip().lower() != "loop_":
            i += 1
            continue
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        headers: list[str] = []
        while i < len(lines):
            stripped = lines[i].strip()
            if not stripped:
                i += 1
                continue
            if not stripped.startswith("_"):
                break
            headers.append(stripped)
            i += 1
        if not any(h.startswith("_atom_site") for h in headers):
            continue
        def idx(*names: str) -> int | None:
            for name in names:
                for j, header in enumerate(headers):
                    if header.lower() == name.lower():
                        return j
            return None
        type_i = idx("_atom_site_type_symbol", "_atom_site_label")
        x_i = idx("_atom_site_fract_x", "_atom_site_Cartn_x")
        y_i = idx("_atom_site_fract_y", "_atom_site_Cartn_y")
        z_i = idx("_atom_site_fract_z", "_atom_site_Cartn_z")
        if type_i is None or x_i is None or y_i is None or z_i is None:
            continue
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            if line.startswith("_") or line.lower() == "loop_" or line.lower().startswith("data_"):
                break
            parts = line.split()
            if len(parts) > max(type_i, x_i, y_i, z_i):
                try:
                    symbol = re.sub(r"[^A-Za-z]", "", parts[type_i]) or parts[type_i]
                    atoms.append({"element": symbol, "x": float(parts[x_i].split("(")[0]), "y": float(parts[y_i].split("(")[0]), "z": float(parts[z_i].split("(")[0])})
                except ValueError:
                    pass
            i += 1
        if atoms:
            return atoms
    return atoms


def _atoms_formula(atoms: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for atom in atoms:
        element = str(atom.get("element") or "")
        if element:
            counts[element] = counts.get(element, 0) + 1
    return "".join(f"{element}{counts[element] if counts[element] != 1 else ''}" for element in sorted(counts))


def _safe_axis_text(ax: Any, x: float, y: float, text: str, **kwargs: Any) -> None:
    if hasattr(ax, "text2D"):
        ax.text2D(x, y, text, transform=ax.transAxes, **kwargs)
    else:
        ax.text(x, y, text, transform=ax.transAxes, **kwargs)


def _style_structure_axis(ax: Any) -> None:
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])
    ax.grid(False)
    try:
        ax.xaxis.pane.set_alpha(0.0)
        ax.yaxis.pane.set_alpha(0.0)
        ax.zaxis.pane.set_alpha(0.0)
    except Exception:
        pass


def _call_qlip_vesta_export(cif_path: Path, out_png: Path, vesta_path: str) -> Path:
    from qlip.visualization.vesta import _vesta_export_and_open  # type: ignore

    return Path(
        _vesta_export_and_open(
        str(cif_path),
        str(out_png),
        vesta_exe=vesta_path,
        template_vesta=None,
        scale=3,
        leave_open=False,
        )
    )


def _classify_image_error(message: str) -> str:
    lowered = message.lower()
    if "input file was not found" in lowered or "input file" in lowered and "not found" in lowered:
        return "vesta_input_file_not_found"
    if "dde" in lowered and "transaction" in lowered:
        return "vesta_dde_transaction_failed"
    if "truncated" in lowered:
        return "vesta_output_truncated"
    if "cannot identify image file" in lowered or "broken data stream" in lowered:
        return "vesta_output_unreadable"
    return "vesta_output_unreadable"


def _wait_for_complete_image(
    path: Path,
    *,
    timeout_s: float = 20.0,
    interval_s: float = 0.25,
    stabilization_required_identical_checks: int = 1,
    sleep_func: Any | None = None,
) -> dict[str, Any]:
    from PIL import Image

    sleeper = sleep_func or time.sleep
    started = time.monotonic()
    attempts = 0
    last_size = -1
    stable_count = 0
    last_error = ""
    last_code = "vesta_output_missing"
    ever_existed = False
    ever_had_bytes = False
    while time.monotonic() - started <= timeout_s:
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        ever_existed = ever_existed or exists
        ever_had_bytes = ever_had_bytes or size > 0
        if exists and size > 0:
            if size == last_size:
                stable_count += 1
            else:
                stable_count = 0
                last_size = size
            if stable_count >= stabilization_required_identical_checks:
                attempts += 1
                try:
                    with Image.open(path) as image:
                        image.verify()
                    return {
                        "vesta_output_exists": True,
                        "vesta_output_size_bytes": size,
                        "vesta_validation_attempts": attempts,
                    }
                except Exception as exc:
                    last_error = str(exc)
                    last_code = _classify_image_error(last_error)
        sleeper(interval_s)
    final_exists = path.exists()
    final_size = path.stat().st_size if final_exists else 0
    if final_exists and final_size > 0 and not last_error:
        attempts += 1
        try:
            with Image.open(path) as image:
                image.verify()
            return {
                "vesta_output_exists": True,
                "vesta_output_size_bytes": final_size,
                "vesta_validation_attempts": attempts,
            }
        except Exception as exc:
            last_error = str(exc)
            last_code = _classify_image_error(last_error)
    diagnostics = {
        "vesta_output_path": str(path),
        "vesta_output_exists": final_exists,
        "vesta_output_size_bytes": final_size,
        "vesta_validation_attempts": attempts,
        "vesta_validation_error": last_error,
        "vesta_output_ever_existed": ever_existed,
        "vesta_output_ever_had_bytes": ever_had_bytes,
        "vesta_output_last_size_bytes": last_size if last_size >= 0 else final_size,
    }
    if not ever_existed and not final_exists:
        code = "vesta_output_missing"
        message = "VESTA output image was not produced before timeout."
    elif last_error:
        code = last_code
        message = last_error
    elif ever_had_bytes or final_size > 0:
        code = "vesta_output_incomplete_or_unstable"
        message = "VESTA output image existed but did not stabilize before timeout."
    else:
        code = "vesta_output_missing"
        message = "VESTA output image was not produced before timeout."
    raise VestaRenderError(code, message, diagnostics)


def _load_vesta_png(path: Path) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    from PIL import Image, ImageFile

    diagnostics: dict[str, Any] = {
        "loader_used": "pil_strict",
        "truncated_tolerance_used": False,
        "image_size": [],
        "mode": "",
    }
    try:
        with Image.open(path) as image:
            image.load()
            loaded = image.convert("RGBA")
            diagnostics["image_size"] = list(loaded.size)
            diagnostics["mode"] = loaded.mode
            return np.asarray(loaded), diagnostics
    except Exception as strict_exc:
        strict_error = str(strict_exc)

    previous = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        with Image.open(path) as image:
            image.load()
            loaded = image.convert("RGBA")
            diagnostics.update(
                {
                    "loader_used": "pil_load_truncated_safe",
                    "truncated_tolerance_used": True,
                    "image_size": list(loaded.size),
                    "mode": loaded.mode,
                    "warnings": ["vesta_png_required_truncated_tolerance"],
                    "strict_loader_error": strict_error,
                }
            )
            return np.asarray(loaded), diagnostics
    except Exception as tolerant_exc:
        code = _classify_image_error(f"{strict_error}; {tolerant_exc}")
        raise VestaRenderError(
            code,
            str(tolerant_exc),
            {
                "vesta_output_path": str(path),
                "vesta_output_exists": path.exists(),
                "vesta_output_size_bytes": path.stat().st_size if path.exists() else 0,
                "strict_loader_error": strict_error,
                "tolerant_loader_error": str(tolerant_exc),
            },
        ) from tolerant_exc
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = previous


def _load_plot_image(path: Path) -> tuple[Any, dict[str, Any]]:
    return _load_vesta_png(path)


def _wait_for_ready_file(
    path: Path,
    *,
    timeout_s: float = 10.0,
    interval_s: float = 0.1,
    stable_checks: int = 2,
    sleep_func: Any | None = None,
) -> dict[str, Any]:
    sleeper = sleep_func or time.sleep
    started = time.monotonic()
    last_size = -1
    stable_count = 0
    attempts = 0
    while time.monotonic() - started <= timeout_s:
        attempts += 1
        exists = path.exists()
        is_file = path.is_file() if exists else False
        size = path.stat().st_size if is_file else 0
        if is_file and size > 0:
            try:
                with path.open("rb") as handle:
                    handle.read(1)
            except OSError:
                stable_count = 0
            else:
                if size == last_size:
                    stable_count += 1
                else:
                    stable_count = 1
                    last_size = size
                if stable_count >= stable_checks:
                    return {
                        "ready": True,
                        "exists": True,
                        "is_file": True,
                        "size_bytes": size,
                        "wait_ms": int((time.monotonic() - started) * 1000),
                        "attempts": attempts,
                    }
        sleeper(interval_s)
    exists = path.exists()
    is_file = path.is_file() if exists else False
    size = path.stat().st_size if is_file else 0
    return {
        "ready": False,
        "exists": exists,
        "is_file": is_file,
        "size_bytes": size,
        "wait_ms": int((time.monotonic() - started) * 1000),
        "attempts": attempts,
    }


def _copy_cif_to_staging(source: Path, staged: Path) -> None:
    staged.parent.mkdir(parents=True, exist_ok=False)
    with source.open("rb") as src, staged.open("wb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())


def _vesta_render_id(cif_path: Path, out_png: Path) -> str:
    digest = hashlib.sha1(f"{cif_path.resolve()}|{out_png.resolve()}|{time.time_ns()}".encode("utf-8")).hexdigest()[:12]
    return f"{_safe_slug(out_png.stem)}_{digest}"


def _render_cif_with_vesta(
    cif_path: Path,
    out_png: Path,
    vesta_path: str,
    *,
    timeout_s: float = 120.0,
    call_delay_s: float = 1.5,
    retries: int = 2,
    stabilization_poll_interval_s: float = 0.25,
    stabilization_required_identical_checks: int = 1,
    sleep_func: Any | None = None,
) -> dict[str, Any]:
    sleeper = sleep_func or time.sleep
    source_cif = Path(cif_path)
    requested_out_png = Path(out_png)
    render_id = _vesta_render_id(source_cif, requested_out_png)
    diagnostics: dict[str, Any] = {
        "build_uuid": _VESTA_BUILD_UUID,
        "render_id": render_id,
        "source_cif_path": str(source_cif),
        "source_exists": source_cif.exists(),
        "source_is_file": source_cif.is_file() if source_cif.exists() else False,
        "source_size_bytes": source_cif.stat().st_size if source_cif.is_file() else 0,
        "vesta_exe": vesta_path,
        "vesta_call_attempted": True,
        "vesta_command": "",
        "vesta_process_id": "",
        "vesta_output_path": str(requested_out_png),
        "requested_output_png_path": str(requested_out_png),
        "vesta_stdout": "",
        "vesta_stderr": "",
        "vesta_serial_rendering": True,
        "vesta_attempts": 0,
        "timeout_s": timeout_s,
        "call_delay_s": call_delay_s,
        "max_retries": retries,
        "stabilization_poll_interval_s": stabilization_poll_interval_s,
        "stabilization_required_identical_checks": stabilization_required_identical_checks,
        "output_exists_each_attempt": [],
        "output_size_bytes_each_attempt": [],
        "error_each_attempt": [],
        "dde_failure_detected": False,
        "staging_root": str(_VESTA_STAGING_ROOT),
        "staging_dir": "",
        "staged_cif_path": "",
        "staged_exists_before_launch": False,
        "staged_size_bytes": 0,
        "staged_ready_wait_ms": 0,
        "launch_timestamp": "",
        "completion_timestamp": "",
        "cleanup_timestamp": "",
        "cleanup_status": "",
        "retry_count": 0,
    }
    rendered_path = requested_out_png
    last_exc: VestaRenderError | None = None
    attempts = max(1, int(retries) + 1)
    with _VESTA_RENDER_LOCK:
        for attempt in range(1, attempts + 1):
            diagnostics["vesta_attempts"] = attempt
            diagnostics["retry_count"] = attempt - 1
            staging_dir = _VESTA_STAGING_ROOT / _VESTA_BUILD_UUID / _safe_slug(source_cif.parent.name) / render_id / f"attempt_{attempt:02d}"
            staged_cif = staging_dir / "input.cif"
            staged_png = staging_dir / "output.png"
            diagnostics["staging_dir"] = str(staging_dir)
            diagnostics["staged_cif_path"] = str(staged_cif)
            diagnostics["vesta_output_path"] = str(staged_png)
            diagnostics["vesta_command"] = f'"{vesta_path}" "{staged_cif}" -> "{staged_png}"'
            if call_delay_s > 0:
                sleeper(call_delay_s)
            try:
                if requested_out_png.exists():
                    requested_out_png.unlink()
                if staging_dir.exists():
                    shutil.rmtree(staging_dir)
                source_ready = _wait_for_ready_file(source_cif, timeout_s=10.0, interval_s=0.1, stable_checks=2, sleep_func=sleeper)
                diagnostics["source_ready_wait_ms"] = source_ready["wait_ms"]
                if not source_ready["ready"]:
                    raise VestaRenderError("vesta_source_cif_not_ready", f"Source CIF was not ready before timeout: {source_cif}", {**diagnostics, **source_ready})
                _copy_cif_to_staging(source_cif, staged_cif)
                staged_ready = _wait_for_ready_file(staged_cif, timeout_s=10.0, interval_s=0.1, stable_checks=2, sleep_func=sleeper)
                diagnostics["staged_exists_before_launch"] = bool(staged_ready["exists"])
                diagnostics["staged_size_bytes"] = int(staged_ready["size_bytes"])
                diagnostics["staged_ready_wait_ms"] = int(staged_ready["wait_ms"])
                if not staged_ready["ready"]:
                    raise VestaRenderError("vesta_staged_cif_not_ready", f"Staged CIF was not ready before VESTA launch: {staged_cif}", {**diagnostics, **staged_ready})
                diagnostics["launch_timestamp"] = _utc_timestamp()
                rendered_path = _call_qlip_vesta_export(staged_cif, staged_png, vesta_path)
                diagnostics["vesta_output_path"] = str(rendered_path)
                wait_status = _wait_for_complete_image(
                    rendered_path,
                    timeout_s=timeout_s,
                    interval_s=stabilization_poll_interval_s,
                    stabilization_required_identical_checks=stabilization_required_identical_checks,
                    sleep_func=sleeper,
                )
                diagnostics.update(wait_status)
                diagnostics["output_exists_each_attempt"].append(bool(wait_status.get("vesta_output_exists")))
                diagnostics["output_size_bytes_each_attempt"].append(int(wait_status.get("vesta_output_size_bytes") or 0))
                diagnostics["error_each_attempt"].append("")
                requested_out_png.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(rendered_path, requested_out_png)
                final_status = _wait_for_complete_image(
                    requested_out_png,
                    timeout_s=10.0,
                    interval_s=stabilization_poll_interval_s,
                    stabilization_required_identical_checks=stabilization_required_identical_checks,
                    sleep_func=sleeper,
                )
                diagnostics["published_output_png_path"] = str(requested_out_png)
                diagnostics["published_output_size_bytes"] = int(final_status.get("vesta_output_size_bytes") or 0)
                diagnostics["completion_timestamp"] = _utc_timestamp()
                try:
                    shutil.rmtree(staging_dir)
                    diagnostics["cleanup_status"] = "removed_after_successful_publication"
                except OSError as exc:
                    diagnostics["cleanup_status"] = f"cleanup_failed:{exc}"
                diagnostics["cleanup_timestamp"] = _utc_timestamp()
                rendered_path = requested_out_png
                last_exc = None
                break
            except VestaRenderError as exc:
                exists = rendered_path.exists()
                size = rendered_path.stat().st_size if exists else 0
                message = str(exc)
                code = exc.code
                if code == "vesta_output_missing" and attempt < attempts:
                    code = "vesta_output_missing_retrying"
                diagnostics["output_exists_each_attempt"].append(exists)
                diagnostics["output_size_bytes_each_attempt"].append(size)
                diagnostics["error_each_attempt"].append(f"{code}: {message}")
                diagnostics["dde_failure_detected"] = diagnostics["dde_failure_detected"] or code == "vesta_dde_transaction_failed" or ("dde" in message.lower() and "transaction" in message.lower())
                diagnostics["completion_timestamp"] = _utc_timestamp()
                diagnostics["cleanup_status"] = "retained_for_debugging"
                diagnostics["cleanup_timestamp"] = ""
                last_exc = VestaRenderError(exc.code, message, {**diagnostics, **exc.diagnostics})
                if exc.code not in {"vesta_output_missing", "vesta_output_truncated", "vesta_output_unreadable", "vesta_dde_transaction_failed", "vesta_output_missing_after_retries"}:
                    raise last_exc from exc
            except Exception as exc:
                exists = rendered_path.exists()
                size = rendered_path.stat().st_size if exists else 0
                message = str(exc)
                code = _classify_image_error(message)
                diagnostics["output_exists_each_attempt"].append(exists)
                diagnostics["output_size_bytes_each_attempt"].append(size)
                diagnostics["error_each_attempt"].append(f"{code}: {message}")
                diagnostics["dde_failure_detected"] = diagnostics["dde_failure_detected"] or code == "vesta_dde_transaction_failed"
                diagnostics["completion_timestamp"] = _utc_timestamp()
                diagnostics["cleanup_status"] = "retained_for_debugging"
                diagnostics["cleanup_timestamp"] = ""
                last_exc = VestaRenderError("vesta_export_failed" if code == "vesta_output_unreadable" else code, message, diagnostics.copy())
                if code == "vesta_dde_transaction_failed" and attempt < attempts:
                    continue
                if attempt >= attempts:
                    break
        else:
            pass
    if last_exc is not None:
        final_code = "vesta_dde_transaction_failed" if diagnostics["dde_failure_detected"] else "vesta_output_missing_after_retries"
        if any("vesta_input_file_not_found" in err for err in diagnostics["error_each_attempt"]):
            final_code = "vesta_input_file_not_found"
        if any("vesta_output_truncated" in err for err in diagnostics["error_each_attempt"]):
            final_code = "vesta_output_truncated"
        raise VestaRenderError(final_code, str(last_exc), {**diagnostics, **last_exc.diagnostics}) from last_exc
    return {
        "render_status": "rendered",
        "renderer_used": "qlip_vesta_renderer",
        "vesta_render_path": str(requested_out_png),
        **diagnostics,
    }


def _render_vesta_image_on_axis(ax: Any, cif_path: Path, *, title: str, out_png: Path, vesta_path: str) -> dict[str, Any]:
    ax.set_title(title, fontsize=9, pad=4)
    ax.set_axis_off()
    vesta = _vesta_status(vesta_path)
    status = _render_cif_with_vesta(
        cif_path,
        out_png,
        vesta_path,
        timeout_s=_to_float(getattr(ax, "_vesta_timeout_s", None), 120.0),
        call_delay_s=_to_float(getattr(ax, "_vesta_call_delay_s", None), 1.5),
        retries=_to_int(getattr(ax, "_vesta_retries", None), 2),
        stabilization_poll_interval_s=_to_float(getattr(ax, "_vesta_poll_interval_s", None), 0.25),
        stabilization_required_identical_checks=_to_int(getattr(ax, "_vesta_stabilization_checks", None), 1),
    )
    image, loader_status = _load_vesta_png(Path(status["vesta_render_path"]))
    ax.imshow(image, aspect="equal")
    height, width = image.shape[:2]
    pad_x = max(1, int(width * 0.04))
    pad_y = max(1, int(height * 0.04))
    ax.set_xlim(-pad_x, width + pad_x)
    ax.set_ylim(height + pad_y, -pad_y)
    warnings = list(status.get("warnings") or [])
    warnings.extend(loader_status.get("warnings") or [])
    status.update(
        {
            "source_artifact_path": str(cif_path),
            "data_status": "real_data",
            "vesta_status": vesta["status"],
            "vesta": vesta,
            "no_crop_image_mode": True,
            "image_padding_fraction": 0.04,
            **loader_status,
        }
    )
    if warnings:
        status["warnings"] = sorted(set(warnings))
    return status


def _render_cif_on_axis(ax: Any, cif_path: Path | None, *, title: str, max_atoms: int = 80, target_material: str = "") -> dict[str, Any]:
    ax.set_title(title, fontsize=9, pad=4)
    _style_structure_axis(ax)
    vesta = _vesta_status()

    if not cif_path or not cif_path.exists():
        _safe_axis_text(ax, 0.5, 0.5, "CIF missing", ha="center", va="center", fontsize=9)
        return {"render_status": "deferred_missing_cif", "source_artifact_path": str(cif_path or ""), "data_status": "missing", "renderer_used": "fallback_card", "vesta_status": vesta["status"], "vesta": vesta}
    atoms = _parse_cif_atoms(cif_path)
    if not atoms:
        _safe_axis_text(ax, 0.5, 0.5, "CIF artifact\nrender deferred", ha="center", va="center", fontsize=8)
        _safe_axis_text(ax, 0.5, 0.18, cif_path.name, ha="center", va="center", fontsize=7)
        return {"render_status": "deferred_unparsed_cif", "source_artifact_path": str(cif_path), "data_status": "real_artifact_unrendered", "renderer_used": "fallback_card", "vesta_status": vesta["status"], "vesta": vesta, "parser_errors": ["No atom-site coordinate loop could be parsed."]}
    atoms = atoms[:max_atoms]
    elements = sorted({str(atom["element"]) for atom in atoms})
    formula = _atoms_formula(atoms)
    target_elements = _formula_elements(target_material)
    contains_target_elements = bool(target_elements) and target_elements.issubset(set(elements))
    palette = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple", "tab:brown", "tab:pink", "tab:gray"]
    colors = {element: palette[i % len(palette)] for i, element in enumerate(elements)}
    for element in elements:
        subset = [atom for atom in atoms if atom["element"] == element]
        ax.scatter([a["x"] for a in subset], [a["y"] for a in subset], [a["z"] for a in subset], s=34, label=element, color=colors[element], depthshade=True)
    # Unit-cell cube in fractional coordinate space; harmless for cartesian fallback too.
    edges = [
        ((0, 0, 0), (1, 0, 0)), ((0, 0, 0), (0, 1, 0)), ((0, 0, 0), (0, 0, 1)),
        ((1, 1, 1), (0, 1, 1)), ((1, 1, 1), (1, 0, 1)), ((1, 1, 1), (1, 1, 0)),
        ((1, 0, 0), (1, 1, 0)), ((1, 0, 0), (1, 0, 1)), ((0, 1, 0), (1, 1, 0)),
        ((0, 1, 0), (0, 1, 1)), ((0, 0, 1), (1, 0, 1)), ((0, 0, 1), (0, 1, 1)),
    ]
    for start, end in edges:
        ax.plot([start[0], end[0]], [start[1], end[1]], [start[2], end[2]], color="0.6", linewidth=0.6)
    ax.view_init(elev=20, azim=35)
    if len(elements) <= 5:
        ax.legend(fontsize=6, loc="upper right", frameon=False)
    subtitle = formula or "formula unknown"
    if target_material and not contains_target_elements:
        subtitle += "\nanalogue, not target chemistry"
    subtitle += "\nfallback renderer"
    _safe_axis_text(ax, 0.03, 0.04, subtitle, ha="left", va="bottom", fontsize=7)
    return {
        "render_status": "rendered",
        "source_artifact_path": str(cif_path),
        "data_status": "real_data",
        "renderer_used": "matplotlib_cif_scatter",
        "vesta_status": vesta["status"],
        "vesta": vesta,
        "atom_count_rendered": len(atoms),
        "elements": elements,
        "extracted_formula": formula,
        "target_material": target_material,
        "contains_target_elements": contains_target_elements,
    }


def _render_cif_panel(
    fig: Any,
    spec: Any,
    cif_path: Path | None,
    *,
    title: str,
    data: dict[str, Any],
    max_atoms: int = 80,
    target_material: str = "",
    image_slug: str = "structure",
) -> dict[str, Any]:
    vesta_path = str(data.get("vesta_executable") or "")
    if vesta_path and cif_path and cif_path.exists():
        ax = fig.add_subplot(spec)
        ax._vesta_timeout_s = data.get("vesta_timeout_s", 120.0)
        ax._vesta_call_delay_s = data.get("vesta_call_delay_s", 1.5)
        ax._vesta_retries = data.get("vesta_retries", 2)
        ax._vesta_poll_interval_s = data.get("stabilization_poll_interval_s", 0.25)
        ax._vesta_stabilization_checks = data.get("stabilization_required_identical_checks", 1)
        out_png = Path(data["panels_dir"]) / f"{_safe_slug(image_slug)}_vesta.png"
        try:
            render = _render_vesta_image_on_axis(ax, cif_path, title=title, out_png=out_png, vesta_path=vesta_path)
        except VestaRenderError as exc:
            if data.get("require_vesta"):
                raise
            fig.delaxes(ax)
            fallback_ax = fig.add_subplot(spec, projection="3d")
            render = _render_cif_on_axis(fallback_ax, cif_path, title=title, max_atoms=max_atoms, target_material=target_material)
            render.update(
                {
                    "render_status": "rendered",
                    "renderer_used": "matplotlib_cif_scatter_after_vesta_failure",
                    "vesta_attempted": True,
                    "vesta_failure_status": exc.code,
                    "vesta_status": "available",
                    "vesta": _vesta_status(vesta_path),
                    **exc.diagnostics,
                    "parser_errors": [str(exc)],
                }
            )
        except Exception as exc:
            diagnostics = {"vesta_exe": vesta_path, "vesta_call_attempted": True, "vesta_output_path": str(out_png), "vesta_export_error": str(exc)}
            if data.get("require_vesta"):
                raise VestaRenderError("vesta_output_unreadable", str(exc), diagnostics) from exc
            fig.delaxes(ax)
            fallback_ax = fig.add_subplot(spec, projection="3d")
            render = _render_cif_on_axis(fallback_ax, cif_path, title=title, max_atoms=max_atoms, target_material=target_material)
            render.update(
                {
                    "render_status": "rendered",
                    "renderer_used": "matplotlib_cif_scatter_after_vesta_failure",
                    "vesta_attempted": True,
                    "vesta_failure_status": "vesta_output_unreadable",
                    "vesta_status": "available",
                    "vesta": _vesta_status(vesta_path),
                    **diagnostics,
                    "parser_errors": [str(exc)],
                }
            )
        return render
    ax = fig.add_subplot(spec, projection="3d")
    return _render_cif_on_axis(ax, cif_path, title=title, max_atoms=max_atoms, target_material=target_material)


def _classify_final_crystal_source_role(solution_cif: Path | None) -> str:
    if solution_cif is None:
        return "missing"
    normalized = str(solution_cif).replace("\\", "/").lower()
    if "/semantic_neighbour_cifs/" in normalized:
        return "semantic_neighbour"
    if "/crystal_csp_pack/" in normalized or "/csp_pack/cifs/" in normalized:
        return "retrieval_corpus"
    if "/spp" in normalized and normalized.endswith(".cif"):
        return "spp_corpus"
    if "qlip_solve" in normalized or "/solve" in normalized:
        return "qlip_solution"
    return "unknown"


def _validate_final_crystal_source(solution_cif: Path | None, run_dir: Path | str) -> dict[str, Any]:
    if solution_cif is None:
        return {
            "final_crystal_cif_path": "",
            "final_crystal_cif_role": "missing",
            "final_crystal_source_role": "missing",
            "final_crystal_source_validated": False,
            "final_crystal_source_role_validated": False,
            "final_crystal_file_exists": False,
            "final_crystal_source_warnings": [],
            "final_crystal_source_validation_reason": "no solution CIF path was recorded",
        }
    path_text = str(solution_cif)
    is_solution_cif = solution_cif.name.lower() == "solution.cif"
    source_role = _classify_final_crystal_source_role(solution_cif)
    file_exists = solution_cif.is_file()
    warnings: list[str] = []
    if source_role == "qlip_solution" and not is_solution_cif:
        warnings.append("noncanonical_solve_cif_name")
    if source_role == "qlip_solution":
        role = "canonical_qlip_solution_cif" if is_solution_cif else "qlip_solution_cif_noncanonical_name"
        validated = True
        reason = "QLIP solve-step CIF source"
    elif source_role in {"retrieval_corpus", "semantic_neighbour", "spp_corpus"}:
        role = "retrieval_or_semantic_neighbour_cif" if source_role in {"retrieval_corpus", "semantic_neighbour"} else "spp_corpus_cif"
        validated = False
        reason = "path points to a retrieval/corpus/semantic-neighbour/SPP corpus CIF, not a QLIP solve output"
    else:
        role = "unknown"
        validated = False
        reason = "final crystal source did not match a QLIP solve output role"
    return {
        "final_crystal_cif_path": path_text,
        "final_crystal_cif_role": role,
        "final_crystal_source_role": source_role,
        "final_crystal_source_validated": validated,
        "final_crystal_source_role_validated": validated,
        "final_crystal_file_exists": file_exists,
        "final_crystal_source_warnings": warnings,
        "final_crystal_source_validation_reason": reason,
    }


def _parse_pot_file(path: Path) -> tuple[list[float], list[float]] | None:
    try:
        from spp_maker.pot_io import read_pot_like_qlip  # type: ignore

        r_vals, u_vals = read_pot_like_qlip(path)
        xs = [float(v) for v in r_vals.tolist()]
        ys = [float(v) for v in u_vals.tolist()]
        if len(xs) >= 2:
            return xs, ys
    except Exception:
        pass

    xs: list[float] = []
    ys: list[float] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            continue
        if math.isfinite(x) and math.isfinite(y):
            xs.append(x)
            ys.append(y)
        if len(xs) >= 500:
            break
    if len(xs) < 5:
        return None
    return xs, ys


def _find_pot_for_pair(pot_root: str, pair: str) -> Path | None:
    if not pot_root:
        return None
    root = Path(pot_root)
    if not root.exists():
        return None
    pair_upper = pair.upper()
    pair_alt = pair.replace("-", "_")
    pair_alt_upper = pair_alt.upper()
    parts = pair.replace("_", "-").split("-")
    reversed_pair = "-".join(reversed(parts)) if len(parts) == 2 else ""
    reversed_upper = reversed_pair.upper()
    candidates = [
        root / f"{pair}.POT",
        root / f"{pair_upper}.POT",
        root / f"{pair_alt}.POT",
        root / f"{pair_alt_upper}.POT",
        root / pair / f"{pair}.POT",
        root / pair_upper / f"{pair_upper}.POT",
        root / pair_alt / f"{pair_alt}.POT",
        root / pair_alt_upper / f"{pair_alt_upper}.POT",
    ]
    if reversed_pair:
        candidates.extend([root / f"{reversed_pair}.POT", root / f"{reversed_upper}.POT", root / reversed_pair / f"{reversed_pair}.POT", root / reversed_upper / f"{reversed_upper}.POT"])
    for path in candidates:
        if path.exists():
            return path
    compact = pair.replace("-", "").lower()
    for path in root.rglob("*.POT"):
        if compact in path.stem.replace("_", "").replace("-", "").lower():
            return path
    return None


def _pot_metadata(data: dict[str, Any]) -> dict[str, Any]:
    required = [str(pair) for pair in data.get("row_specific_spp_pairs") or data.get("required_pairs") or []]
    pot_root = str(data.get("universal_regulariser_root") or data.get("pot_root") or "")
    root = Path(pot_root) if pot_root else None
    found: list[str] = []
    missing: list[str] = []
    paths: dict[str, str] = {}
    parseable: list[str] = []
    unparseable: list[str] = []
    for pair in required:
        path = _find_pot_for_pair(pot_root, pair)
        if path and path.is_file():
            found.append(pair)
            paths[pair] = str(path)
            if _parse_pot_file(path):
                parseable.append(pair)
            else:
                unparseable.append(pair)
        else:
            missing.append(pair)
    if not required:
        status = "not_requested"
    elif missing:
        status = "incomplete"
    else:
        status = "complete"
    return {
        "pot_root": pot_root,
        "pot_root_exists": bool(root and root.exists()),
        "pot_parser_available": bool(parseable),
        "pot_source_status": "recorded" if pot_root and root and root.exists() else "not_recorded",
        "pot_pairs_requested": required,
        "pot_pairs_found": found,
        "pot_pairs_missing": missing,
        "pot_pair_paths": paths,
        "pot_pairs_parseable": parseable,
        "pot_pairs_unparseable": unparseable,
        "pair_coverage_status": status,
        "spp_source_label": str(data.get("spp_source_label") or data.get("pot_root_source") or ""),
        "row_specific_spp_source_path": str(data.get("row_specific_spp_source_path") or ""),
        "row_specific_spp_found": bool(data.get("row_specific_spp_found")),
        "row_specific_spp_pair_count": int(_to_int(data.get("row_specific_spp_pair_count"), len(required))),
        "row_specific_spp_pairs": required,
        "universal_regulariser_used": bool(data.get("universal_regulariser_used")),
        "universal_regulariser_root": pot_root,
        "universal_regulariser_pairs_found": found,
        "spp_panel_source_mode": str(data.get("spp_panel_source_mode") or ""),
        "spp_summary_path": str(data.get("spp_summary_path") or ""),
        "spp_pairs_csv_path": str(data.get("spp_pairs_csv_path") or ""),
        "spp_score_sign_convention": SPP_SCORE_SIGN_CONVENTION,
        "spp_negative_values_allowed": SPP_NEGATIVE_VALUES_ALLOWED,
        "spp_lower_is_better": SPP_LOWER_IS_BETTER,
    }


def _render_pair_coverage(ax: Any, data: dict[str, Any]) -> dict[str, Any]:
    ax.set_axis_off()
    required = list(data["required_pairs"] or [])
    metadata = _pot_metadata(data)
    found = set(metadata["pot_pairs_found"])
    missing = set(metadata["pot_pairs_missing"])
    source_text = "Row-specific SPP from retrieved neighbours" if metadata["row_specific_spp_found"] else "Row-specific SPP: unavailable in trace"
    if metadata["pair_coverage_status"] == "complete":
        coverage_text = "Pair coverage: complete"
    elif metadata["pair_coverage_status"] == "incomplete":
        coverage_text = "Pair coverage: incomplete: " + ", ".join(metadata["pot_pairs_missing"])
    else:
        coverage_text = "Pair coverage: no requested pairs"
    ax.text(0.02, 0.95, "SPP/POT guidance", fontsize=10, fontweight="bold", transform=ax.transAxes, va="top")
    regulariser_text = "Universal regulariser: available" if metadata["universal_regulariser_used"] and metadata["pot_root_exists"] else "Universal regulariser: not used"
    ax.text(0.02, 0.82, f"{source_text}\n{coverage_text}\n{regulariser_text}", fontsize=8.5, transform=ax.transAxes, va="top")
    y = 0.54
    for pair in required[:8]:
        status = "POT file found" if str(pair) in found and str(pair) not in missing else "missing POT"
        ax.text(0.05, y, str(pair), fontsize=8, transform=ax.transAxes)
        ax.text(0.55, y, status, fontsize=8, transform=ax.transAxes)
        y -= 0.07
    if len(required) > 8:
        ax.text(0.05, y, f"+{len(required) - 8} more", fontsize=8, transform=ax.transAxes)
    return {"render_status": "metadata_pair_coverage", "data_status": "figure_metadata_pair_coverage", "source_artifact_path": data.get("row_specific_spp_source_path", ""), **metadata}


def _draw_query_panel(ax: Any, data: dict[str, Any]) -> dict[str, Any]:
    ax.set_axis_off()
    ax.set_facecolor("#f7f7f7")
    ax.set_title("Plain-text request" if data.get("paper_hero_mode") else "Plain-text Query", fontsize=12, fontweight="bold")
    ax.text(0.04, 0.84, _wrap(data["goal"], width=32, max_lines=8), va="top", fontsize=10, transform=ax.transAxes)
    ax.text(0.04, 0.18, f"Target: {data['material_system']}", fontsize=12, fontweight="bold", transform=ax.transAxes)
    return {"render_status": "rendered", "data_status": "real_metadata", "source_artifact_path": data["run_dir"]}


def _neighbor_formula_and_match(cif_path: str, target_material: str) -> tuple[str, bool | None]:
    if not cif_path:
        return "", None
    atoms = _parse_cif_atoms(Path(cif_path))
    if not atoms:
        return "", None
    formula = _atoms_formula(atoms)
    target_elements = _formula_elements(target_material)
    if not target_elements:
        return formula, None
    return formula, target_elements.issubset({str(atom.get("element") or "") for atom in atoms})


def _build_semantic_neighbor_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    export_items = data.get("export_items") or []
    neighbors = data.get("neighbors") or []
    if export_items:
        source_items = export_items
    else:
        source_items = neighbors
    if not source_items:
        retrieved = list(data.get("retrieved_cifs") or [])
        expected = max(_to_int(data.get("neighbor_count"), len(retrieved)), len(retrieved))
        source_items = [
            {
                "rank": index + 1,
                "score": "",
                "structure_id": path.stem if index < len(retrieved) else f"semantic_neighbor_{index + 1}",
                "source_id": "",
                "cif_path": str(path) if index < len(retrieved) else "",
                "export_status": "exported" if index < len(retrieved) else "not_exported_or_policy_blocked",
            }
            for index, path in enumerate(retrieved + [Path("")] * max(0, expected - len(retrieved)))
        ]
    exported_paths = {str(path) for path in data.get("retrieved_cifs") or []}
    target = data.get("material_system") or ""
    for index, item in enumerate(source_items):
        rank = item.get("rank") or item.get("neighbor_rank") or index + 1
        cif_path = str(item.get("cif_path") or item.get("exported_cif_path") or "")
        formula, match = _neighbor_formula_and_match(cif_path, target)
        export_status = str(item.get("export_status") or ("exported" if cif_path else "not_exported_or_policy_blocked"))
        selected_for_spp = item.get("selected_for_spp")
        if selected_for_spp in (None, ""):
            selected_for_spp = bool(cif_path and (cif_path in exported_paths or export_status == "exported"))
        rows.append(
            {
                "rank": rank,
                "score": item.get("paper_display_score", item.get("score", item.get("semantic_score", ""))),
                "structure_id": item.get("structure_id", item.get("id", "")),
                "source_id": item.get("source_id", item.get("source", "")),
                "formula": item.get("formula") or formula,
                "cif_path": cif_path,
                "exported_for_spp": bool(selected_for_spp),
                "selected_for_spp": bool(selected_for_spp),
                "selected_for_paper_display": bool(item.get("selected_for_paper_display", True)),
                "paper_display_rank": item.get("paper_display_rank", rank),
                "paper_display_score": item.get("paper_display_score", ""),
                "visual_similarity_reason": item.get("visual_similarity_reason", ""),
                "target_chemistry_match": match,
                "render_status": "pending" if cif_path else "metadata_only",
                "vesta_render_path": "",
                "cif_export_status": export_status if cif_path else "not_exported_or_policy_blocked",
            }
        )
    return rows


def _copy_vesta_ready_neighbor_cifs(rows: list[dict[str, Any]], panels_dir: Path) -> list[dict[str, Any]]:
    cif_dir = panels_dir / "semantic_neighbour_cifs"
    for row in rows:
        cif_path = str(row.get("cif_path") or "")
        if not cif_path:
            continue
        source = Path(cif_path)
        if not source.exists():
            row["cif_export_status"] = "missing_cif_artifact"
            continue
        cif_dir.mkdir(parents=True, exist_ok=True)
        target = cif_dir / f"neighbour_{int(_to_int(row.get('rank'), 0)):02d}.cif"
        try:
            shutil.copyfile(source, target)
            row["vesta_ready_cif_path"] = str(target)
        except OSError as exc:
            row["cif_export_status"] = "copy_failed"
            row["copy_error"] = str(exc)
    return rows


def _write_semantic_neighbor_sidecars(out_dir: Path, slug: str, rows: list[dict[str, Any]]) -> dict[str, str]:
    json_path = out_dir / f"workflow_artifact_{slug}_semantic_neighbours.json"
    csv_path = out_dir / f"workflow_artifact_{slug}_semantic_neighbours.csv"
    md_path = out_dir / f"workflow_artifact_{slug}_semantic_neighbours.md"
    _write_json(json_path, rows)
    fields = [
        "rank",
        "score",
        "structure_id",
        "source_id",
        "formula",
        "cif_path",
        "exported_for_spp",
        "target_chemistry_match",
        "render_status",
        "vesta_render_path",
        "cif_export_status",
        "vesta_ready_cif_path",
        "selected_for_spp",
        "selected_for_paper_display",
        "paper_display_rank",
        "paper_display_score",
        "visual_similarity_reason",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    lines = ["| rank | score | structure_id | formula | exported_for_spp | target_chemistry_match | cif_export_status |", "|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _stringify(row.get(field))
                for field in ("rank", "score", "structure_id", "formula", "exported_for_spp", "target_chemistry_match", "cif_export_status")
            )
            + " |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}


def _write_semantic_cif_manifest(out_dir: Path, rows: list[dict[str, Any]]) -> dict[str, str]:
    json_path = out_dir / "semantic_neighbour_cifs_manifest.json"
    csv_path = out_dir / "semantic_neighbour_cifs_manifest.csv"
    _write_json(json_path, rows)
    fields = [
        "rank",
        "score",
        "structure_id",
        "source_id",
        "formula",
        "source_cif_path",
        "resolved_source_cif_path",
        "cif_resolution_method",
        "cif_search_roots",
        "cif_search_matches",
        "copied_cif_path",
        "copy_status",
        "png_path",
        "png_render_status",
        "render_error",
        "render_diagnostics",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return {"json": str(json_path), "csv": str(csv_path)}


def _semantic_cif_manifest_path(panels_dir: Path) -> Path:
    return panels_dir / "semantic_neighbour_cifs" / "semantic_neighbour_cifs_manifest.json"


def _load_semantic_cif_manifest(panels_dir: Path) -> list[dict[str, Any]]:
    path = _semantic_cif_manifest_path(panels_dir)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _merge_semantic_render_manifest(rows: list[dict[str, Any]], panels_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    render_rows = _load_semantic_cif_manifest(panels_dir)
    by_rank = {_to_int(row.get("rank"), -1): row for row in render_rows if isinstance(row, dict)}
    merged: list[dict[str, Any]] = []
    rendered_png_count = 0
    cif_count = 0
    for row in rows:
        rank = _to_int(row.get("rank"), len(merged) + 1)
        enriched = dict(row)
        render_row = by_rank.get(rank)
        if render_row:
            for key in (
                "source_cif_path",
                "resolved_source_cif_path",
                "copied_cif_path",
                "copy_status",
                "png_path",
                "png_render_status",
                "cif_resolution_method",
                "cif_search_matches",
            ):
                if render_row.get(key) not in (None, ""):
                    enriched[key] = render_row.get(key)
            if render_row.get("copied_cif_path"):
                enriched["vesta_ready_cif_path"] = render_row.get("copied_cif_path")
            png_path = Path(str(render_row.get("png_path") or ""))
            if render_row.get("png_render_status") == "rendered" and png_path.is_file():
                enriched["semantic_neighbour_png_path"] = str(png_path)
                enriched["render_status"] = "rendered"
                rendered_png_count += 1
            copied = Path(str(render_row.get("copied_cif_path") or ""))
            if copied.is_file():
                cif_count += 1
        merged.append(enriched)
    return merged, {
        "semantic_neighbour_render_manifest_used": bool(render_rows),
        "semantic_neighbour_rendered_png_count": rendered_png_count,
        "semantic_neighbour_cif_count": cif_count,
        "semantic_neighbour_render_manifest_path": str(_semantic_cif_manifest_path(panels_dir)) if render_rows else "",
    }


def _semantic_render_manifest_complete(panels_dir: Path, expected_count: int) -> bool:
    rows = _load_semantic_cif_manifest(panels_dir)
    if expected_count <= 0 or len(rows) < expected_count:
        return False
    rendered = 0
    for row in rows:
        png_path = Path(str(row.get("png_path") or ""))
        if row.get("png_render_status") == "rendered" and png_path.is_file():
            rendered += 1
    return rendered >= expected_count


def _dedupe_existing_dirs(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved).lower()
        if key in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(key)
        result.append(resolved)
    return result


def _semantic_cif_search_roots(rows: list[dict[str, Any]], run_dir: Path, extra_roots: list[Path] | None = None) -> list[Path]:
    roots: list[Path] = []
    for row in rows:
        cif_text = str(row.get("cif_path") or row.get("vesta_ready_cif_path") or "")
        if cif_text:
            path = Path(cif_text)
            if path.is_file():
                roots.append(path.parent)
    run_csp_cifs = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
    roots.append(run_csp_cifs)
    if extra_roots:
        roots.extend(extra_roots)
    return _dedupe_existing_dirs(roots)


def _candidate_source_id_basenames(source_id: str) -> list[str]:
    if not source_id:
        return []
    basename = Path(source_id).name
    candidates = [basename]
    if not basename.lower().endswith(".cif"):
        candidates.append(f"{basename}.cif")
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def _search_cif_by_source_id(
    source_id: str,
    *,
    search_roots: list[Path],
    preferred_parent: Path | None = None,
    cache: dict[str, list[Path]],
) -> list[Path]:
    matches: list[Path] = []
    for basename in _candidate_source_id_basenames(source_id):
        cache_key = basename.lower()
        if cache_key not in cache:
            found: list[Path] = []
            for root in search_roots:
                direct = root / basename
                if direct.is_file():
                    found.append(direct)
                try:
                    found.extend(path for path in root.rglob(basename) if path.is_file())
                except OSError:
                    continue
            cache[cache_key] = list({str(path.resolve()).lower(): path for path in found}.values())
        matches.extend(cache[cache_key])

    unique = list({str(path.resolve()).lower(): path for path in matches}.values())

    def priority(path: Path) -> tuple[int, int, str]:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if preferred_parent:
            try:
                if resolved.parent.resolve() == preferred_parent.resolve():
                    return (0, len(str(resolved)), str(resolved).lower())
            except OSError:
                pass
        parts = {part.lower() for part in resolved.parts}
        parent_text = str(resolved.parent).lower()
        if "data" in parts and ("cif" in parent_text or "cifs" in parent_text):
            return (1, len(str(resolved)), str(resolved).lower())
        return (2, len(str(resolved)), str(resolved).lower())

    return sorted(unique, key=priority)


def _resolve_semantic_neighbor_cif(
    row: dict[str, Any],
    *,
    search_roots: list[Path],
    preferred_parent: Path | None,
    cache: dict[str, list[Path]],
) -> dict[str, Any]:
    source_cif_text = str(row.get("cif_path") or "")
    if source_cif_text:
        source_cif = Path(source_cif_text)
        if source_cif.is_file():
            return {
                "path": source_cif,
                "method": "existing_source_path",
                "matches": [str(source_cif)],
            }

    source_id = str(row.get("source_id") or "")
    matches = _search_cif_by_source_id(source_id, search_roots=search_roots, preferred_parent=preferred_parent, cache=cache)
    if matches:
        return {
            "path": matches[0],
            "method": "source_id_search",
            "matches": [str(path) for path in matches],
        }

    return {
        "path": None,
        "method": "not_found",
        "matches": [],
    }


def export_and_render_semantic_neighbour_cifs(
    run_dir: Path | str,
    out_dir: Path | str,
    case_name: str,
    semantic_neighbour_out_dir: Path | str,
    *,
    export_cifs: bool = True,
    render_pngs: bool = False,
    vesta_path: str | Path | None = None,
    require_vesta: bool = False,
    vesta_timeout_s: float | None = None,
    vesta_call_delay_s: float | None = None,
    vesta_retries: int | None = None,
    stabilization_poll_interval_s: float | None = None,
    stabilization_required_identical_checks: int | None = None,
    semantic_neighbour_cif_search_roots: list[Path | str] | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    target_dir = Path(semantic_neighbour_out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    data = _load_run_data(run_dir, case_name)
    rows = _build_semantic_neighbor_rows(data)
    extra_search_roots = [Path(root) for root in (semantic_neighbour_cif_search_roots or [])]
    search_roots = _semantic_cif_search_roots(rows, run_dir, extra_search_roots)
    preferred_parent = search_roots[0] if search_roots else None
    search_cache: dict[str, list[Path]] = {}
    timeout_s = _to_float(vesta_timeout_s, _env_float("VESTA_TIMEOUT_S", 180.0))
    call_delay_s = _to_float(vesta_call_delay_s, _env_float("VESTA_CALL_DELAY_S", 2.0))
    retries = _to_int(vesta_retries, _env_int("VESTA_RETRIES", 3))
    poll_interval_s = _to_float(stabilization_poll_interval_s, _env_float("VESTA_STABILIZATION_POLL_INTERVAL_S", 0.25))
    stabilization_checks = _to_int(stabilization_required_identical_checks, _env_int("VESTA_STABILIZATION_REQUIRED_IDENTICAL_CHECKS", 1))
    resolved_vesta = _resolve_vesta_executable(vesta_path)
    if render_pngs and require_vesta and not resolved_vesta:
        raise VestaUnavailableError("vesta_executable_unavailable", "provide --vesta-path, VESTA_EXE, or VESTA_PATH", {"vesta_exe": str(vesta_path or "")})

    manifest_rows: list[dict[str, Any]] = []
    copied_count = 0
    rendered_count = 0
    failed_renders: list[dict[str, Any]] = []
    for row in rows:
        rank = _to_int(row.get("rank"), len(manifest_rows) + 1)
        structure_id = str(row.get("structure_id") or f"neighbour_{rank}")
        resolution = _resolve_semantic_neighbor_cif(row, search_roots=search_roots, preferred_parent=preferred_parent, cache=search_cache)
        source_cif = resolution["path"]
        stem = f"rank_{rank:02d}_{_safe_slug(structure_id)}"
        copied_path = target_dir / f"{stem}.cif"
        png_path = target_dir / f"{stem}.png"
        entry = {
            **row,
            "source_cif_path": str(source_cif) if source_cif else "",
            "resolved_source_cif_path": str(source_cif) if source_cif else "",
            "cif_resolution_method": resolution["method"],
            "cif_search_roots": [str(root) for root in search_roots],
            "cif_search_matches": resolution["matches"],
            "copied_cif_path": "",
            "copy_status": "no_cif_available",
            "png_path": "",
            "png_render_status": "not_requested" if not render_pngs else "not_rendered",
            "render_error": "",
            "render_diagnostics": "",
        }
        if source_cif and source_cif.is_file() and export_cifs:
            try:
                shutil.copyfile(source_cif, copied_path)
                entry["copied_cif_path"] = str(copied_path)
                entry["copy_status"] = "copied"
                copied_count += 1
            except OSError as exc:
                entry["copy_status"] = "copy_failed"
                entry["render_error"] = str(exc)
        elif source_cif and source_cif.is_file():
            entry["copied_cif_path"] = str(source_cif)
            entry["copy_status"] = "source_available_not_copied"

        render_source_text = str(entry["copied_cif_path"] or "")
        render_source = Path(render_source_text) if render_source_text else None
        if render_pngs and render_source and render_source.is_file():
            if not resolved_vesta:
                entry["png_render_status"] = "vesta_executable_unavailable"
                entry["render_error"] = "VESTA executable unavailable."
                failed_renders.append(entry.copy())
                if require_vesta:
                    raise VestaUnavailableError("vesta_executable_unavailable", "provide --vesta-path, VESTA_EXE, or VESTA_PATH", {"vesta_exe": str(vesta_path or "")})
            else:
                try:
                    render_status = _render_cif_with_vesta(
                        render_source,
                        png_path,
                        resolved_vesta,
                        timeout_s=timeout_s,
                        call_delay_s=call_delay_s,
                        retries=retries,
                        stabilization_poll_interval_s=poll_interval_s,
                        stabilization_required_identical_checks=stabilization_checks,
                    )
                    entry["png_path"] = str(png_path)
                    entry["png_render_status"] = render_status.get("render_status", "rendered")
                    entry["render_diagnostics"] = json.dumps(render_status, sort_keys=True)
                    rendered_count += 1
                except VestaRenderError as exc:
                    entry["png_path"] = str(png_path)
                    entry["png_render_status"] = exc.code
                    entry["render_error"] = str(exc)
                    entry["render_diagnostics"] = json.dumps(exc.diagnostics, sort_keys=True)
                    failed_renders.append(entry.copy())
                    if require_vesta:
                        manifest_rows.append(entry)
                        _write_semantic_cif_manifest(target_dir, manifest_rows)
                        raise
        manifest_rows.append(entry)

    manifest_paths = _write_semantic_cif_manifest(target_dir, manifest_rows)
    return {
        "schema_version": "agentic_csp.semantic_neighbour_cifs.v1",
        "run_dir": str(run_dir),
        "case_name": case_name,
        "semantic_neighbour_out_dir": str(target_dir),
        "semantic_neighbours_found": len(rows),
        "cifs_copied": copied_count,
        "pngs_rendered": rendered_count,
        "failed_renders": failed_renders,
        "cif_search_roots": [str(root) for root in search_roots],
        "manifest_json": manifest_paths["json"],
        "manifest_csv": manifest_paths["csv"],
        "vesta_timeout_s": timeout_s,
        "vesta_call_delay_s": call_delay_s,
        "vesta_retries": retries,
        "stabilization_poll_interval_s": poll_interval_s,
        "stabilization_required_identical_checks": stabilization_checks,
        "vesta_serial_rendering": True,
    }


def _copy_image_asset(source: Path, target_dir: Path, *, case_slug: str, image_role: str, index: int | None = None) -> Path:
    suffix = source.suffix.lower() or ".png"
    name_bits = [case_slug, image_role]
    if index is not None:
        name_bits.append(f"{index:02d}")
    target = target_dir / f"{'_'.join(_safe_slug(bit) for bit in name_bits)}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def _add_doc_image_row(
    rows: list[dict[str, Any]],
    *,
    case_name: str,
    image_role: str,
    source_path: str,
    exported_path: Path | None,
    used_in_figure: bool,
    panel_name: str,
    caption_hint: str,
    render_status: str,
    renderer_used: str,
    extra: dict[str, Any] | None = None,
) -> None:
    row = {
        "case_name": case_name,
        "image_role": image_role,
        "source_path": source_path,
        "exported_path": str(exported_path or ""),
        "exists": bool(exported_path and Path(exported_path).is_file()),
        "used_in_figure": used_in_figure,
        "used_in_workflow_composite": used_in_figure,
        "panel_name": panel_name,
        "caption_hint": caption_hint,
        "render_status": render_status,
        "renderer_used": renderer_used,
    }
    if extra:
        row.update(extra)
    rows.append(row)


def _spp_ylim(xs: list[float], ys: list[float], scaling: str) -> tuple[float | None, float | None, bool]:
    if not ys or scaling not in {"percentile_clipped", "full_data_or_robust_safe"}:
        return None, None, False
    sorted_ys = sorted(ys)
    if scaling == "full_data_or_robust_safe":
        data_min = sorted_ys[0]
        data_max = sorted_ys[-1]
        if data_max <= data_min:
            return None, None, False
        p02 = sorted_ys[max(0, int(0.02 * (len(sorted_ys) - 1)))]
        p98 = sorted_ys[min(len(sorted_ys) - 1, int(0.98 * (len(sorted_ys) - 1)))]
        robust_span = max(p98 - p02, 1e-12)
        full_span = data_max - data_min
        if full_span <= 8 * robust_span:
            padding = 0.05 * full_span
            return data_min - padding, data_max + padding, False
        padding = 0.10 * robust_span
        return p02 - padding, p98 + padding, True
    lo = sorted_ys[max(0, int(0.02 * (len(sorted_ys) - 1)))]
    hi = sorted_ys[min(len(sorted_ys) - 1, int(0.98 * (len(sorted_ys) - 1)))]
    if hi <= lo:
        return None, None, False
    padding = 0.08 * (hi - lo)
    return lo - padding, hi + padding, min(ys) < lo or max(ys) > hi


def _spp_workflow_thumbnail_ylim(ys: list[float]) -> dict[str, Any]:
    if not ys:
        return {
            "workflow_thumbnail_y_clipped": False,
            "y_clip_percentiles": [],
            "original_y_min": None,
            "original_y_max": None,
            "thumbnail_y_min": None,
            "thumbnail_y_max": None,
        }
    sorted_ys = sorted(float(y) for y in ys)
    original_min = sorted_ys[0]
    original_max = sorted_ys[-1]
    if original_max <= original_min:
        return {
            "workflow_thumbnail_y_clipped": False,
            "y_clip_percentiles": [2, 95],
            "original_y_min": original_min,
            "original_y_max": original_max,
            "thumbnail_y_min": None,
            "thumbnail_y_max": None,
        }
    y_min = sorted_ys[max(0, int(0.02 * (len(sorted_ys) - 1)))]
    y_max = sorted_ys[min(len(sorted_ys) - 1, int(0.95 * (len(sorted_ys) - 1)))]
    if y_max <= y_min:
        return {
            "workflow_thumbnail_y_clipped": False,
            "y_clip_percentiles": [2, 95],
            "original_y_min": original_min,
            "original_y_max": original_max,
            "thumbnail_y_min": None,
            "thumbnail_y_max": None,
        }
    span = y_max - y_min
    pad = 0.08 * span
    lower = y_min - pad
    upper = y_max + pad
    return {
        "workflow_thumbnail_y_clipped": original_min < lower or original_max > upper,
        "y_clip_percentiles": [2, 95],
        "original_y_min": original_min,
        "original_y_max": original_max,
        "thumbnail_y_min": lower,
        "thumbnail_y_max": upper,
    }


def _prepare_spp_curve(xs: list[float], ys: list[float]) -> tuple[list[float], list[float], bool]:
    points: dict[float, list[float]] = {}
    for x, y in zip(xs, ys):
        try:
            x_f = float(x)
            y_f = float(y)
        except (TypeError, ValueError):
            continue
        points.setdefault(x_f, []).append(y_f)
    deduplicated = any(len(values) > 1 for values in points.values())
    ordered_xs = sorted(points)
    ordered_ys = [sum(points[x]) / len(points[x]) for x in ordered_xs]
    return ordered_xs, ordered_ys, deduplicated


SPP_WORKFLOW_DISPLAY_DEFAULTS: dict[str, Any] = {
    "spp_display_mode": "zoomed",
    "spp_layout_columns": 2,
    "spp_force_shared_y_scale": True,
    "spp_shared_y_quantile_low": 0.05,
    "spp_shared_y_quantile_high": 0.90,
    "spp_shared_y_pad_fraction": 0.30,
    "spp_shared_y_hard_min": -2.0,
    "spp_shared_y_hard_max": 3.0,
    "spp_y_limit_policy": "shared_robust_percentile",
    "spp_outlier_exclusion_strategy": "quantile",
    "spp_outlier_exclusion_top_fraction": 0.10,
    "spp_min_display_span": 2.0,
    "spp_zoom_upper_strategy": "post_drop_percentile",
    "spp_zoom_upper_percentile": 0.80,
    "spp_zoom_lower_percentile": 0.02,
    "spp_zoom_upper_absolute_max": None,
    "spp_zoom_hard_upper_cap": None,
    "spp_zoom_hard_lower_cap": None,
    "spp_zoom_ignore_initial_x_below": 1.0,
    "spp_zoom_min_upper": 1.0,
    "spp_zoom_pad_fraction": 0.08,
    "spp_zoom_padding_fraction": 0.08,
    "spp_min_display_range": 0.5,
    "spp_force_zoom_for_all_pairs": True,
    "spp_show_clipping_annotation": True,
    "spp_clip_annotation_enabled": True,
    "spp_clipping_annotation_meaning": "high repulsive values exceed the displayed y-limit",
    "spp_clipping_annotation_text": "^",
    "spp_show_full_scale_in_audit": True,
}

SPP_SCORE_SIGN_CONVENTION = "statistical-potential score; lower values are preferred; negative values indicate distances favoured relative to the reference/background; values are not probabilities"
SPP_NEGATIVE_VALUES_ALLOWED = True
SPP_LOWER_IS_BETTER = True


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    p = max(0.0, min(1.0, percentile))
    if len(ordered) == 1:
        return ordered[0]
    index = p * (len(ordered) - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _spp_workflow_display_limits(xs: list[float], ys: list[float], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = {**SPP_WORKFLOW_DISPLAY_DEFAULTS, **(config or {})}
    numeric = [(float(x), float(y)) for x, y in zip(xs, ys)]
    if not numeric:
        return {
            "display_y_min": None,
            "display_y_max": None,
            "y_axis_clipped": False,
            "original_y_min": None,
            "original_y_max": None,
            "spp_display_mode": cfg["spp_display_mode"],
            "spp_zoom_config": cfg,
        }
    all_ys = [y for _x, y in numeric]
    original_y_min = min(all_ys)
    original_y_max = max(all_ys)
    if cfg["spp_display_mode"] == "fixed_shared":
        display_lower = float(cfg["spp_fixed_y_min"])
        display_upper = float(cfg["spp_fixed_y_max"])
        if display_upper <= display_lower:
            raise ValueError("fixed SPP display upper limit must exceed lower limit")
        return {
            "display_y_min": display_lower,
            "display_y_max": display_upper,
            "y_axis_clipped": original_y_min < display_lower or original_y_max > display_upper,
            "original_y_min": original_y_min,
            "original_y_max": original_y_max,
            "spp_display_mode": "fixed_shared_raw",
            "spp_zoom_config": cfg,
            "spp_zoom_informative_point_count": len(all_ys),
        }
    if cfg["spp_display_mode"] != "zoomed":
        return {
            "display_y_min": original_y_min,
            "display_y_max": original_y_max,
            "y_axis_clipped": False,
            "original_y_min": original_y_min,
            "original_y_max": original_y_max,
            "spp_display_mode": "full",
            "spp_zoom_config": cfg,
        }

    threshold = float(cfg["spp_zoom_ignore_initial_x_below"])
    informative_ys = [y for x, y in numeric if x >= threshold]
    if not informative_ys:
        informative_ys = all_ys

    if cfg["spp_zoom_upper_strategy"] == "absolute" and cfg.get("spp_zoom_upper_absolute_max") is not None:
        upper = float(cfg["spp_zoom_upper_absolute_max"])
    else:
        upper = _percentile(informative_ys, float(cfg["spp_zoom_upper_percentile"]))
        if upper is None:
            upper = original_y_max

    lower = _percentile(informative_ys, float(cfg["spp_zoom_lower_percentile"]))
    if lower is None:
        lower = original_y_min
    if cfg.get("spp_zoom_hard_lower_cap") is not None:
        lower = max(float(lower), float(cfg["spp_zoom_hard_lower_cap"]))
    if cfg.get("spp_zoom_hard_upper_cap") is not None:
        upper = min(float(upper), float(cfg["spp_zoom_hard_upper_cap"]))

    min_upper = max(float(cfg["spp_zoom_min_upper"]), original_y_min + 1e-9)
    upper = max(float(upper), min_upper)
    lower = min(float(lower), original_y_min)
    span = max(float(upper) - float(lower), float(cfg["spp_min_display_range"]))
    pad = float(cfg.get("spp_zoom_pad_fraction", cfg["spp_zoom_padding_fraction"])) * span
    display_lower = float(lower) - pad
    display_upper = float(upper) + pad
    if display_upper - display_lower < float(cfg["spp_min_display_range"]):
        display_upper = display_lower + float(cfg["spp_min_display_range"])
    if not cfg.get("spp_force_zoom_for_all_pairs") and display_upper >= original_y_max:
        display_upper = original_y_max
    clipped = original_y_max > display_upper
    return {
        "display_y_min": display_lower,
        "display_y_max": display_upper,
        "y_axis_clipped": clipped,
        "original_y_min": original_y_min,
        "original_y_max": original_y_max,
        "spp_display_mode": "zoomed_raw",
        "spp_zoom_config": cfg,
        "spp_zoom_informative_point_count": len(informative_ys),
    }


def _spp_workflow_shared_display_limits(
    curves: list[tuple[str, Path, list[float], list[float], bool]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = {**SPP_WORKFLOW_DISPLAY_DEFAULTS, **(config or {})}
    numeric_by_pair: dict[str, list[tuple[float, float]]] = {}
    all_ys: list[float] = []
    informative_ys: list[float] = []
    threshold = float(cfg["spp_zoom_ignore_initial_x_below"])
    for pair, _path, xs, ys, _deduplicated in curves:
        numeric = [(float(x), float(y)) for x, y in zip(xs, ys)]
        numeric_by_pair[pair] = numeric
        all_ys.extend(y for _x, y in numeric)
        informative_ys.extend(y for x, y in numeric if x >= threshold)
    if not all_ys:
        return {
            "display_y_min": None,
            "display_y_max": None,
            "original_y_min": None,
            "original_y_max": None,
            "spp_display_mode": cfg["spp_display_mode"],
            "spp_zoom_config": cfg,
            "spp_zoom_informative_point_count": 0,
            "spp_shared_y_scale_used": True,
            "spp_shared_y_range": [],
        }
    if not informative_ys:
        informative_ys = list(all_ys)

    original_y_min = min(all_ys)
    original_y_max = max(all_ys)
    if cfg["spp_display_mode"] == "fixed_shared":
        display_lower = float(cfg["spp_fixed_y_min"])
        display_upper = float(cfg["spp_fixed_y_max"])
        if display_upper <= display_lower:
            raise ValueError("fixed SPP display upper limit must exceed lower limit")
        return {
            "display_y_min": display_lower,
            "display_y_max": display_upper,
            "original_y_min": original_y_min,
            "original_y_max": original_y_max,
            "spp_display_mode": "fixed_shared_raw",
            "spp_zoom_config": cfg,
            "spp_zoom_informative_point_count": len(all_ys),
            "spp_shared_y_scale_used": True,
            "spp_shared_y_range": [display_lower, display_upper],
            "spp_shared_original_y_range": [original_y_min, original_y_max],
        }
    if cfg["spp_display_mode"] != "zoomed":
        return {
            "display_y_min": original_y_min,
            "display_y_max": original_y_max,
            "original_y_min": original_y_min,
            "original_y_max": original_y_max,
            "spp_display_mode": "full",
            "spp_zoom_config": cfg,
            "spp_zoom_informative_point_count": len(informative_ys),
            "spp_shared_y_scale_used": True,
            "spp_shared_y_range": [original_y_min, original_y_max],
        }

    lower = _percentile(informative_ys, float(cfg["spp_shared_y_quantile_low"]))
    upper = _percentile(informative_ys, float(cfg["spp_shared_y_quantile_high"]))
    if lower is None:
        lower = original_y_min
    if upper is None:
        upper = original_y_max
    if cfg.get("spp_shared_y_hard_min") is not None:
        lower = max(float(lower), float(cfg["spp_shared_y_hard_min"]))
    if cfg.get("spp_shared_y_hard_max") is not None:
        upper = min(float(upper), float(cfg["spp_shared_y_hard_max"]))
    if float(upper) <= float(lower):
        upper = float(lower) + float(cfg["spp_min_display_span"])

    span = max(float(upper) - float(lower), float(cfg["spp_min_display_span"]))
    pad = float(cfg["spp_shared_y_pad_fraction"]) * span
    display_lower = float(lower) - pad
    display_upper = float(upper) + pad
    if display_upper - display_lower < float(cfg["spp_min_display_span"]):
        display_upper = display_lower + float(cfg["spp_min_display_span"])
    hard_min = cfg.get("spp_shared_y_hard_min")
    hard_max = cfg.get("spp_shared_y_hard_max")
    if hard_max is not None and original_y_min < float(hard_max):
        display_upper = min(display_upper, float(hard_max))
    if hard_min is not None and original_y_max > float(hard_min):
        display_lower = max(display_lower, float(hard_min))
    if display_upper - display_lower < float(cfg["spp_min_display_span"]):
        shortfall = float(cfg["spp_min_display_span"]) - (display_upper - display_lower)
        if hard_min is None or display_lower - shortfall >= float(hard_min):
            display_lower -= shortfall
        elif hard_max is None or display_upper + shortfall <= float(hard_max):
            display_upper += shortfall
    return {
        "display_y_min": display_lower,
        "display_y_max": display_upper,
        "original_y_min": original_y_min,
        "original_y_max": original_y_max,
        "spp_display_mode": "zoomed_raw",
        "spp_zoom_config": cfg,
        "spp_zoom_informative_point_count": len(informative_ys),
        "spp_shared_y_scale_used": True,
        "spp_shared_y_range": [display_lower, display_upper],
        "spp_shared_original_y_range": [original_y_min, original_y_max],
    }


def _render_standalone_spp_curve(
    pot_file: Path,
    out_png: Path,
    *,
    case_name: str,
    pair: str,
    y_axis_scaling: str,
) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    parsed = _parse_pot_file(pot_file)
    if not parsed:
        return {"render_status": "unparseable_pot", "spp_image_path": "", "x_range": []}
    xs, ys = parsed
    fig, ax = plt.subplots(figsize=(3.2, 3.2))
    ax.plot(xs, ys, linewidth=1.0, alpha=0.9)
    try:
        ax.set_box_aspect(1)
    except AttributeError:
        pass
    ax.set_title(f"{case_name} {pair}", fontsize=10)
    ax.set_xlabel("Distance (A)", fontsize=8)
    ax.set_ylabel("SPP value", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.margins(x=0.02, y=0.05)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)
    return {
        "render_status": "rendered",
        "render_mode": "standalone_scientific",
        "spp_render_mode": "raw_no_postprocess",
        "spp_image_path": str(out_png),
        "x_range": [min(xs), max(xs)] if xs else [],
        "y_min": min(ys) if ys else None,
        "y_max": max(ys) if ys else None,
        "y_axis_clipped": False,
        "deduplicated_repeated_x": False,
        "post_processing": "none",
        "curve_points": len(xs),
        "raw_point_count": len(xs),
    }


def _case_surface_seed(case_data: dict[str, Any]) -> int:
    payload = {
        "case_name": case_data.get("case_name") or case_data.get("material_system") or "",
        "material_system": case_data.get("material_system") or "",
        "objective_value": case_data.get("objective_value"),
        "required_pairs": list(case_data.get("required_pairs") or []),
        "novelty": case_data.get("novelty"),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def generate_projected_optimisation_surface(
    case_data: dict[str, Any],
    out_path: Path | str | None = None,
    *,
    display_mode: str = "standalone_scientific",
) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    import numpy as np

    out = Path(out_path) if out_path else None
    case_name = str(case_data.get("case_name") or case_data.get("material_system") or "workflow")
    material = str(case_data.get("material_system") or case_name)
    objective = case_data.get("objective_value")
    required_pairs = list(case_data.get("required_pairs") or [])
    novelty = case_data.get("novelty")
    has_objective = objective not in {None, ""}
    has_metadata = has_objective and bool(required_pairs)
    qlip_status = str(case_data.get("qlip_status") or case_data.get("qlip_solve_status") or "").lower()
    explicit_failure = bool(case_data.get("qlip_failure_category")) or qlip_status in {"error", "failed", "fail"}
    has_workflow_solution_flag = "qlip_solution_cif_produced" in case_data
    solution_available = (
        has_objective
        and not explicit_failure
        and (
            not has_workflow_solution_flag
            or bool(case_data.get("qlip_solution_cif_produced"))
            or qlip_status in {"optimal", "succeeded", "success"}
        )
    )
    seed = _case_surface_seed(case_data)
    rng = np.random.default_rng(seed)
    grid_n = 58
    x = np.linspace(-2.2, 2.2, grid_n)
    y = np.linspace(-2.2, 2.2, grid_n)
    xx, yy = np.meshgrid(x, y)
    angle = rng.uniform(0.0, np.pi)
    xr = np.cos(angle) * xx - np.sin(angle) * yy
    yr = np.sin(angle) * xx + np.cos(angle) * yy
    basin_x = rng.uniform(-0.75, 0.75)
    basin_y = rng.uniform(-0.75, 0.75)
    anisotropy_a = rng.uniform(0.18, 0.55)
    anisotropy_b = rng.uniform(0.25, 0.70)
    ripple_count = max(1, min(6, len(required_pairs) or 1))
    zz = anisotropy_a * (xr - basin_x) ** 2 + anisotropy_b * (yr - basin_y) ** 2
    for index, pair in enumerate(required_pairs[:6] or [material]):
        pair_seed = int(hashlib.sha256(str(pair).encode("utf-8")).hexdigest()[:6], 16)
        freq = 1.1 + (pair_seed % 7) * 0.16
        phase = ((pair_seed // 7) % 360) * np.pi / 180
        zz += (0.04 + 0.015 * index) * np.sin(freq * xx + phase) * np.cos((freq + 0.35) * yy - phase)
    try:
        objective_float = float(objective)
    except (TypeError, ValueError):
        objective_float = 0.0
    zz += 0.025 * np.tanh(objective_float) * (xx + yy)
    if novelty is False:
        zz += 0.04 * np.cos(1.7 * xx - 0.4) * np.cos(1.3 * yy)
    selected_x = float(np.clip(basin_x + 0.12 * np.sin(objective_float + ripple_count), -1.8, 1.8))
    selected_y = float(np.clip(basin_y + 0.12 * np.cos(objective_float - ripple_count), -1.8, 1.8))
    selected_z = float(np.interp(selected_x, x, zz[grid_n // 2, :]))
    surface_type = "projected_proxy" if has_metadata else "schematic_fallback"

    if out:
        is_thumbnail = display_mode == "workflow_thumbnail"
        fig = plt.figure(figsize=(3.8, 3.0) if is_thumbnail else (4.2, 3.4))
        ax = fig.add_subplot(111, projection="3d")
        ax.plot_surface(xx, yy, zz, cmap="cividis", alpha=0.95, linewidth=0, antialiased=True)
        if solution_available:
            ax.scatter(
                [selected_x],
                [selected_y],
                [selected_z + 0.14],
                marker="*",
                color="#ffd43b",
                edgecolors="black",
                linewidths=0.8,
                s=190 if not is_thumbnail else 150,
                depthshade=False,
                zorder=30,
            )
        objective_text = f"{objective}" if objective not in {None, ""} else "n/a"
        if solution_available:
            annotation_text = f"Selected optimum\nQLIP objective: {objective_text}"
        else:
            reason = case_data.get("qlip_failure_user_visible_reason") or case_data.get("qlip_failure_category") or "No optimum available"
            annotation_text = f"QLIP solve failed\n{reason}"
        fig.text(
            0.58 if is_thumbnail else 0.60,
            0.88 if is_thumbnail else 0.86,
            annotation_text,
            color="white",
            weight="bold",
            fontsize=8.0 if is_thumbnail else 9.0,
            ha="left",
            va="top",
            bbox={"boxstyle": "round,pad=0.28", "facecolor": "black", "alpha": 0.72, "edgecolor": "none"},
            path_effects=[pe.withStroke(linewidth=2.2, foreground="black")],
        )
        if not is_thumbnail:
            ax.set_title("Projected QLIP optimisation surface", fontsize=10)
            fig.text(0.50, 0.925, "proxy projection, not full MILP landscape", ha="center", va="top", fontsize=8)
            ax.set_xlabel("structural similarity projection", fontsize=7)
            ax.set_ylabel("constraint feasibility projection", fontsize=7)
            ax.set_zlabel("QLIP/SPP objective proxy", fontsize=7)
            ax.tick_params(labelsize=6)
        else:
            ax.set_axis_off()
        ax.view_init(elev=28, azim=38 + (seed % 55))
        fig.tight_layout(pad=0.4 if is_thumbnail else 0.8)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=220)
        plt.close(fig)

    return {
        "image_path": str(out or ""),
        "surface_type": surface_type,
        "display_mode": display_mode,
        "true_gurobi_landscape": False,
        "reason": "QLIP is a discrete MILP; Gurobi does not expose a continuous optimisation landscape.",
        "data_source": ["case_name", "objective_value", "required_pairs", "SPP pair labels", "novelty metadata"],
        "objective_value": objective,
        "selected_solution_marker": {"marker": "star", "x": selected_x, "y": selected_y, "z_proxy": selected_z} if solution_available else {"marker": "none"},
        "seed_used": seed,
        "grid_shape": [grid_n, grid_n],
        "axis_labels": {
            "x": "structural similarity projection",
            "y": "constraint feasibility projection",
            "z": "QLIP/SPP objective proxy",
        },
        "selected_optimum_label_style": "front_visible_2d_overlay_white_bold_black_box" if solution_available else "none",
        "optimum_annotation_mode": "front_visible_2d_overlay" if solution_available else "none",
        "objective_annotation_text": f"QLIP objective: {objective}" if solution_available else "No optimum available",
        "qlip_solution_available": solution_available,
        "qlip_failure_category": case_data.get("qlip_failure_category", ""),
        "notes": ["Projected/proxy visual for explanation only; not the true Gurobi search landscape."],
    }


def export_final_doc_images(
    figures_dir: Path | str,
    out_dir: Path | str,
    *,
    case_names: list[str] | None = None,
) -> dict[str, Any]:
    figures_dir = Path(figures_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = case_names or ["CoAs2", "CaTiO3", "BaTiO3"]
    rows: list[dict[str, Any]] = []
    gurobi_dir = out_dir / "gurobi_diagnostics"
    gurobi_dir.mkdir(parents=True, exist_ok=True)

    for case_name in cases:
        case_slug = _safe_slug(case_name)
        case_dir = out_dir / case_slug
        case_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = figures_dir / f"workflow_artifact_{case_slug}_manifest.json"
        manifest = _read_json(manifest_path)
        if not manifest:
            continue
        for role, key in (
            ("workflow_artifact_png", "png_path"),
            ("workflow_artifact_pdf", "pdf_path"),
            ("workflow_artifact_svg", "svg_path"),
        ):
            source = Path(str(manifest.get(key) or ""))
            exported = _copy_image_asset(source, case_dir, case_slug=case_slug, image_role=role) if source.is_file() else None
            _add_doc_image_row(
                rows,
                case_name=case_name,
                image_role=role,
                source_path=str(source) if str(source) else "",
                exported_path=exported,
                used_in_figure=bool(exported),
                panel_name="workflow_artifact",
                caption_hint=f"{case_name} full workflow artifact.",
                render_status="copied" if exported else "missing",
                renderer_used="workflow_artifact_export",
            )

        panels = manifest.get("panels") or {}
        corpus_children = ((panels.get("crystal_db_retrieved_corpus") or {}).get("children") or [])
        for index, child in enumerate(corpus_children, start=1):
            source = Path(str(child.get("vesta_render_path") or ""))
            if not source.is_file():
                continue
            exported = _copy_image_asset(source, case_dir, case_slug=case_slug, image_role="semantic_neighbour", index=index)
            rank = child.get("rank", index)
            _add_doc_image_row(
                rows,
                case_name=case_name,
                image_role="semantic_neighbour_thumbnail",
                source_path=str(source),
                exported_path=exported,
                used_in_figure=True,
                panel_name="crystal_db_retrieved_corpus",
                caption_hint=f"{case_name} Crystal-DB semantic neighbour rank {rank}.",
                render_status=str(child.get("render_status") or "rendered"),
                renderer_used=str(child.get("renderer_used") or ""),
            )

        final_panel = panels.get("final_generated_crystal") or {}
        final_source = Path(str(final_panel.get("vesta_render_path") or ""))
        if final_source.is_file():
            exported = _copy_image_asset(final_source, case_dir, case_slug=case_slug, image_role="final_generated_crystal")
            _add_doc_image_row(
                rows,
                case_name=case_name,
                image_role="final_generated_crystal",
                source_path=str(final_source),
                exported_path=exported,
                used_in_figure=True,
                panel_name="final_generated_crystal",
                caption_hint=f"{case_name} final generated CIF render.",
                render_status=str(final_panel.get("render_status") or "rendered"),
                renderer_used=str(final_panel.get("renderer_used") or ""),
            )

        spp_panel = panels.get("spp_pot_guidance") or {}
        y_axis_scaling = "raw_full_data_no_postprocess"
        for index, child in enumerate(spp_panel.get("children") or [], start=1):
            pair = str(child.get("pair") or f"pair_{index}")
            pot_file = Path(str(child.get("source_artifact_path") or ""))
            target = case_dir / f"spp_{_safe_slug(case_name)}_{_safe_slug(pair)}.png"
            render_status = {"render_status": "missing_pot", "spp_image_path": "", "x_range": []}
            workflow_panel_image = Path(str(child.get("workflow_panel_image_path") or ""))
            if workflow_panel_image.is_file():
                shutil.copyfile(workflow_panel_image, target)
                render_status = {
                    "render_status": "rendered",
                    "render_mode": child.get("render_mode", "standalone_scientific"),
                    "spp_image_path": str(target),
                    "x_range": child.get("x_range", []),
                    "y_min": child.get("y_min"),
                    "y_max": child.get("y_max"),
                    "y_axis_clipped": child.get("y_axis_clipped", False),
                    "curve_points": child.get("raw_point_count") or child.get("curve_points"),
                }
            elif pot_file.is_file():
                render_status = _render_standalone_spp_curve(
                    pot_file,
                    target,
                    case_name=case_name,
                    pair=pair,
                    y_axis_scaling=y_axis_scaling,
                )
            exported = Path(str(render_status.get("spp_image_path") or ""))
            _add_doc_image_row(
                rows,
                case_name=case_name,
                image_role="spp_pair_curve",
                source_path=str(pot_file) if str(pot_file) else "",
                exported_path=exported if exported.is_file() else None,
                used_in_figure=child.get("render_status") == "rendered",
                panel_name="spp_pot_guidance",
                caption_hint=f"{case_name} SPP pair potential for {pair}.",
                render_status=str(render_status.get("render_status") or "missing_pot"),
                renderer_used="standalone_spp_curve_renderer",
                extra={
                    "pair": pair,
                    "pot_file": str(pot_file) if str(pot_file) else "",
                    "spp_image_path": str(exported) if exported.is_file() else "",
                    "y_axis_scaling": y_axis_scaling,
                    "x_range": json.dumps(render_status.get("x_range") or []),
                    "x_min": (render_status.get("x_range") or [None, None])[0] if render_status.get("x_range") else None,
                    "x_max": (render_status.get("x_range") or [None, None])[-1] if render_status.get("x_range") else None,
                    "y_min": render_status.get("y_min"),
                    "y_max": render_status.get("y_max"),
                    "render_mode": render_status.get("render_mode", "standalone_scientific"),
                    "used_in_workflow_artifact": child.get("render_status") == "rendered",
                },
            )

        optimisation_panel = panels.get("qlip_optimisation_space") or {}
        gurobi_panel = optimisation_panel.get("gurobi_diagnostics") if isinstance(optimisation_panel.get("gurobi_diagnostics"), dict) else {}
        gurobi_sources = {
            "constraint_matrix_spy_path": optimisation_panel.get("constraint_matrix_spy_path") or gurobi_panel.get("constraint_matrix_spy_path"),
            "mip_trace_plot_path": optimisation_panel.get("mip_trace_plot_path") or gurobi_panel.get("mip_trace_plot_path"),
            "constraint_matrix_meta_path": optimisation_panel.get("constraint_matrix_meta_path") or gurobi_panel.get("constraint_matrix_meta_path"),
            "mip_trace_json_path": optimisation_panel.get("mip_trace_json_path") or gurobi_panel.get("mip_trace_json_path"),
            "mip_trace_csv_path": optimisation_panel.get("mip_trace_csv_path") or gurobi_panel.get("mip_trace_csv_path"),
        }
        for role, key, caption in (
                (
                    "gurobi_constraint_matrix_spy",
                    "constraint_matrix_spy_path",
                    "QLIP/Gurobi MILP constraint matrix sparsity diagnostic.",
                ),
                (
                    "gurobi_mip_trace",
                    "mip_trace_plot_path",
                    "QLIP/Gurobi MIP progress trace; sparse traces indicate very fast solves.",
                ),
                (
                    "gurobi_constraint_matrix_meta",
                    "constraint_matrix_meta_path",
                    "QLIP/Gurobi MILP constraint matrix metadata.",
                ),
                (
                    "gurobi_mip_trace_json",
                    "mip_trace_json_path",
                    "QLIP/Gurobi MIP progress trace metadata.",
                ),
                (
                    "gurobi_mip_trace_csv",
                    "mip_trace_csv_path",
                    "QLIP/Gurobi MIP progress trace table.",
                ),
        ):
            source = Path(str(gurobi_sources.get(key) or ""))
            if not source.is_file():
                continue
            suffix = source.suffix.lower()
            if role == "gurobi_constraint_matrix_spy":
                target = gurobi_dir / f"gurobi_constraint_matrix_spy_{_safe_slug(case_name)}{suffix}"
            elif role == "gurobi_mip_trace":
                target = gurobi_dir / f"gurobi_mip_trace_{_safe_slug(case_name)}{suffix}"
            elif role == "gurobi_constraint_matrix_meta":
                target = gurobi_dir / f"gurobi_constraint_matrix_meta_{_safe_slug(case_name)}{suffix}"
            elif role == "gurobi_mip_trace_json":
                target = gurobi_dir / f"gurobi_mip_trace_{_safe_slug(case_name)}{suffix}"
            else:
                target = gurobi_dir / f"gurobi_mip_trace_{_safe_slug(case_name)}{suffix}"
            shutil.copyfile(source, target)
            _add_doc_image_row(
                rows,
                case_name=case_name,
                image_role=role,
                source_path=str(source),
                exported_path=target,
                used_in_figure=False,
                panel_name="gurobi_diagnostics_appendix",
                caption_hint=caption,
                render_status="exported",
                renderer_used="real_gurobi_milp_diagnostics",
                extra={
                    "surface_type": "real_gurobi_milp_diagnostics",
                    "data_source": json.dumps([str(source)]),
                    "used_in_workflow_artifact": False,
                },
            )

        optimisation = optimisation_panel.get("optimisation_surface") or manifest.get("optimisation_surface") or {}
        surface_source = Path(str(optimisation.get("image_path") or ""))
        if surface_source.is_file():
            surface_target = case_dir / f"optimisation_surface_{_safe_slug(case_name)}.png"
            shutil.copyfile(surface_source, surface_target)
            _add_doc_image_row(
                rows,
                case_name=case_name,
                image_role="optimisation_surface",
                source_path=str(surface_source),
                exported_path=surface_target,
                used_in_figure=True,
                panel_name="qlip_optimisation_space",
                caption_hint="Projected QLIP/SPP optimisation surface; fallback proxy, not a true Gurobi landscape.",
                render_status="rendered",
                renderer_used="projected_proxy_surface_renderer",
                extra={
                    "surface_type": optimisation.get("surface_type", ""),
                    "data_source": json.dumps(optimisation.get("data_source") or []),
                    "used_in_workflow_artifact": True,
                },
            )

    json_path = out_dir / "final_doc_images_manifest.json"
    csv_path = out_dir / "final_doc_images_manifest.csv"
    readme_path = out_dir / "final_doc_images_readme.md"
    alias_json_path = out_dir / "manifest.json"
    alias_csv_path = out_dir / "manifest.csv"
    alias_readme_path = out_dir / "README.md"
    _write_json(json_path, rows)
    _write_json(alias_json_path, rows)
    fields = [
        "case_name",
        "image_role",
        "source_path",
        "exported_path",
        "exists",
        "used_in_figure",
        "used_in_workflow_composite",
        "panel_name",
        "caption_hint",
        "render_status",
        "renderer_used",
        "pair",
        "pot_file",
        "spp_image_path",
        "y_axis_scaling",
        "x_range",
        "x_min",
        "x_max",
        "y_min",
        "y_max",
        "render_mode",
        "used_in_workflow_artifact",
        "surface_type",
        "data_source",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with alias_csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Final Document Images",
        "",
        "Clean export folder for workflow/paper document image assets.",
        "",
        "| case | role | exported image | caption hint |",
        "|---|---|---|---|",
    ]
    for row in rows:
        exported_name = Path(str(row.get("exported_path") or "")).name
        lines.append(f"| {row['case_name']} | {row['image_role']} | {exported_name} | {row['caption_hint']} |")
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    alias_readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    gurobi_readme_path = out_dir / "gurobi_diagnostics_readme.md"
    gurobi_readme_path.write_text(
        "\n".join(
            [
                "# Gurobi Diagnostics Appendix",
                "",
                "These files are real QLIP/Gurobi MILP diagnostics exported during solve execution.",
                "",
                "They are retained as audit evidence rather than used as the main hero workflow panel because the demo MILPs are small and solve quickly, so progress traces are sparse and matrix plots are visually simple.",
                "",
                "The hero workflow figure uses a clearly labelled projected QLIP/SPP proxy surface for explanation; it is not presented as a true Gurobi landscape.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    note_path = out_dir / "optimisation_surface_note.md"
    note_path.write_text(
        "\n".join(
            [
                "# Projected Optimisation Surface Note",
                "",
                "QLIP is formulated and solved as a discrete MILP, so Gurobi does not provide a true continuous 3D objective landscape.",
                "",
                "The optimisation surface images are projected/proxy visuals for explanation. They are generated deterministically from case metadata: case name, material system, QLIP objective value, SPP pair labels, required-pair count, and novelty metadata.",
                "",
                "These visuals are safe for presentation because they are explicitly labelled as projected proxy surfaces and retain the real QLIP status/objective alongside the image.",
                "",
                "Future solver-grounded visualisations could use Gurobi incumbent/bound traces, MIP gap over time, or solution-pool feature projections.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    missing = [row for row in rows if not row.get("exported_path")]
    return {
        "schema_version": "agentic_csp.final_doc_images.v1",
        "out_dir": str(out_dir),
        "manifest_json": str(json_path),
        "manifest_csv": str(csv_path),
        "readme": str(readme_path),
        "alias_manifest_json": str(alias_json_path),
        "alias_manifest_csv": str(alias_csv_path),
        "alias_readme": str(alias_readme_path),
        "gurobi_diagnostics_dir": str(gurobi_dir),
        "gurobi_diagnostics_readme": str(gurobi_readme_path),
        "optimisation_surface_note": str(note_path),
        "image_count": sum(1 for row in rows if row.get("exported_path")),
        "missing_count": len(missing),
        "cases": cases,
    }


def _draw_corpus_panel(fig: Any, spec: Any, data: dict[str, Any]) -> dict[str, Any]:
    rows = list(data.get("semantic_neighbor_rows") or [])
    display_limit = max(1, min(10, _to_int(data.get("semantic_neighbour_target_count"), 10)))
    rows = rows[:display_limit]
    columns = 3 if data.get("paper_hero_mode") else 5
    sub = spec.subgridspec(3, columns, hspace=0.08, wspace=0.06, height_ratios=[0.28, 1.0, 1.0])
    statuses: list[dict[str, Any]] = []
    title_ax = fig.add_subplot(sub[0, :])
    title_ax.set_axis_off()
    title_ax.set_title("Semantic crystal retrieval" if data.get("paper_hero_mode") else "Paper-display neighbours", fontsize=11, fontweight="bold", pad=1)
    header_text = title_ax.text(
        0.02,
        0.78,
        f"Raw retrieval preserved: {data['neighbor_count']}\nSPP evidence structures: {data.get('selected_evidence_for_spp_count', data['exported_cif_count'])}\nPaper-display neighbours: pending",
        fontsize=8,
        va="top",
        transform=title_ax.transAxes,
    )

    for idx, row in enumerate(rows):
        grid_row = 1 + idx // columns
        grid_col = idx % columns
        rank = row.get("rank", idx + 1)
        structure_id = str(row.get("structure_id") or "")
        formula = str(row.get("formula") or "")
        score = row.get("score", "")
        exported = bool(row.get("exported_for_spp"))
        png_text = str(row.get("semantic_neighbour_png_path") or row.get("png_path") or "")
        png_path = Path(png_text) if png_text else None
        cif_text = str(row.get("vesta_ready_cif_path") or row.get("cif_path") or "")
        cif_path = Path(cif_text) if cif_text else None
        label = formula or structure_id[:14] or "metadata"
        title = f"#{rank} {label[:14]}"
        if png_path and png_path.is_file() and str(row.get("png_render_status") or "rendered") == "rendered":
            ax = fig.add_subplot(sub[grid_row, grid_col])
            ax.set_title(title, fontsize=6.5, pad=1)
            ax.set_axis_off()
            try:
                image, image_diag = _load_vesta_png(png_path)
                ax.imshow(image, aspect="equal")
                ax.set_xlim(0, image.shape[1])
                ax.set_ylim(image.shape[0], 0)
                badge = "SPP" if exported else "semantic only"
                color = "#1f6f43" if exported else "#555555"
                _safe_axis_text(ax, 0.02, 0.02, f"{badge}  {float(score):.2f}" if isinstance(score, (int, float)) else badge, fontsize=5.0, va="bottom", ha="left", color=color)
                status = {
                    "render_status": "rendered",
                    "data_status": "real_rendered_semantic_neighbour_png",
                    "renderer_used": "pre_rendered_vesta_png",
                    "source_artifact_path": str(row.get("copied_cif_path") or row.get("source_cif_path") or ""),
                    "vesta_render_path": str(png_path),
                    "rank": rank,
                    "structure_id": structure_id,
                    "score": score,
                    "exported_for_spp": exported,
                    "formula": formula,
                    **image_diag,
                }
                row["render_status"] = "rendered"
                row["vesta_render_path"] = str(png_path)
                row["renderer_used"] = "pre_rendered_vesta_png"
                statuses.append(status)
                continue
            except VestaRenderError as exc:
                status = {
                    "render_status": exc.code,
                    "data_status": "semantic_neighbour_png_unreadable",
                    "source_artifact_path": str(png_path),
                    "rank": rank,
                    "structure_id": structure_id,
                    "score": score,
                    "exported_for_spp": exported,
                    "formula": formula,
                    "warnings": [str(exc)],
                }
                statuses.append(status)

        if cif_path and cif_path.exists():
            render_data = data if data.get("render_semantic_neighbours_with_vesta", True) else {**data, "vesta_executable": ""}
            try:
                status = _render_cif_panel(
                    fig,
                    sub[grid_row, grid_col],
                    cif_path,
                    title=title,
                    data=render_data,
                    target_material=data["material_system"],
                    image_slug=f"semantic_neighbour_{idx + 1:02d}",
                )
                ax = fig.axes[-1]
                badge = "SPP" if exported else "semantic only"
                color = "#1f6f43" if exported else "#555555"
                _safe_axis_text(ax, 0.02, 0.02, f"{badge}  {float(score):.2f}" if isinstance(score, (int, float)) else badge, fontsize=5.0, va="bottom", ha="left", color=color)
                status.update({"rank": rank, "structure_id": structure_id, "score": score, "exported_for_spp": exported, "formula": formula})
                if data.get("require_vesta_images") and status.get("renderer_used") != "qlip_vesta_renderer":
                    status = {
                        **status,
                        "render_status": "missing_required_vesta_neighbour_png",
                        "data_status": "selected_evidence_vesta_render_failed",
                        "warnings": [f"Selected evidence neighbour {rank} was not rendered with VESTA: {cif_path}"],
                    }
            except VestaRenderError as exc:
                ax = fig.add_subplot(sub[grid_row, grid_col])
                ax.set_axis_off()
                _safe_axis_text(ax, 0.5, 0.5, "VESTA render failed", ha="center", va="center", fontsize=7, color="#8a1f11")
                status = {
                    "render_status": exc.code,
                    "data_status": "selected_evidence_vesta_render_failed",
                    "renderer_used": "vesta_failed_no_fallback",
                    "source_artifact_path": str(cif_path),
                    "rank": rank,
                    "structure_id": structure_id,
                    "score": score,
                    "exported_for_spp": exported,
                    "formula": formula,
                    "warnings": [str(exc)],
                }
            row["render_status"] = status.get("render_status")
            row["vesta_render_path"] = status.get("vesta_render_path", "")
            row["renderer_used"] = status.get("renderer_used", "")
            statuses.append(status)
            continue

        ax = fig.add_subplot(sub[grid_row, grid_col])
        ax.set_axis_off()
        ax.set_facecolor("#f7f7f7")
        _safe_axis_text(ax, 0.06, 0.84, f"#{rank}", fontsize=8, fontweight="bold")
        _safe_axis_text(ax, 0.06, 0.65, _wrap(structure_id or "semantic neighbour", width=15, max_lines=2), fontsize=6.5)
        _safe_axis_text(ax, 0.06, 0.43, f"score {float(score):.3f}" if isinstance(score, (int, float)) else "score n/a", fontsize=6.5)
        _safe_axis_text(ax, 0.06, 0.22, "no CIF export", fontsize=7, color="#8a5a00")
        _safe_axis_text(ax, 0.06, 0.08, "semantic only", fontsize=6.5, color="#555555")
        status = {"render_status": "metadata_card_no_cif_export", "data_status": "semantic_neighbor_metadata", "rank": rank, "structure_id": structure_id, "source_id": row.get("source_id", ""), "score": score, "exported_for_spp": exported, "source_artifact_path": ""}
        row["render_status"] = status["render_status"]
        statuses.append(status)
    if not rows:
        ax = fig.add_subplot(sub[1, :])
        ax.set_axis_off()
        _safe_axis_text(ax, 0.5, 0.5, "No retrieved CIF paths recorded", ha="center", va="center", fontsize=10)
        statuses.append({"render_status": "deferred_missing_corpus_cifs", "data_status": "missing", "source_artifact_path": ""})
    rendered_count = sum(1 for child in statuses if child.get("render_status") == "rendered")
    vesta_success_count = sum(1 for child in statuses if child.get("renderer_used") in {"qlip_vesta_renderer", "pre_rendered_vesta_png"} and child.get("render_status") == "rendered")
    fallback_count = sum(1 for child in statuses if str(child.get("renderer_used") or "").startswith("matplotlib_cif_scatter"))
    if data.get("paper_hero_mode"):
        header_text.set_text(
            f"{data.get('selected_evidence_for_spp_count', data['exported_cif_count'])} structures supplied periodic pair-distance evidence\n"
            f"{vesta_success_count} representative retrieved neighbours shown"
        )
    else:
        header_text.set_text(
            f"Raw retrieval preserved: {data['neighbor_count']}\n"
            f"SPP evidence structures: {data.get('selected_evidence_for_spp_count', data['exported_cif_count'])}\n"
            f"Paper-display neighbours: {vesta_success_count}"
        )
    without_cif_count = sum(1 for row in rows if not (row.get("cif_path") or row.get("vesta_ready_cif_path") or row.get("copied_cif_path")))
    spp_ids = [str(row.get("structure_id") or "") for row in rows if row.get("exported_for_spp")]
    return {
        "render_status": "rendered",
        "data_status": "real_artifacts_and_neighbor_metadata",
        "source_artifact_path": data["run_dir"],
        "semantic_neighbour_count": len(rows) or data["neighbor_count"],
        "semantic_neighbours_count": len(rows) or data["neighbor_count"],
        "semantic_neighbours_rendered_count": rendered_count,
        "semantic_neighbours_without_cif_count": without_cif_count,
        "spp_exported_cif_count": data["exported_cif_count"],
        "exported_cif_count": data["exported_cif_count"],
        "selected_evidence_for_spp_count": data.get("selected_evidence_for_spp_count", data["exported_cif_count"]),
        "paper_display_neighbour_count": len(rows),
        "spp_exported_neighbour_ids": spp_ids,
        "semantic_neighbours_sidecars": data.get("semantic_neighbours_sidecars", {}),
        "semantic_neighbour_render_manifest_used": bool(data.get("semantic_neighbour_render_manifest_used")),
        "semantic_neighbour_rendered_png_count": data.get("semantic_neighbour_rendered_png_count", 0),
        "semantic_neighbour_cif_count": data.get("semantic_neighbour_cif_count", 0),
        "semantic_neighbour_vesta_success_count": vesta_success_count,
        "semantic_neighbour_target_count": display_limit,
        "semantic_neighbour_selected_count": len(rows),
        "semantic_neighbour_vesta_png_count": vesta_success_count,
        "semantic_neighbour_fallback_count": fallback_count,
        "semantic_neighbour_labels": [str(row.get("formula") or row.get("structure_id") or "") for row in rows],
        "semantic_neighbour_cif_paths": [str(row.get("vesta_ready_cif_path") or row.get("cif_path") or "") for row in rows if row.get("vesta_ready_cif_path") or row.get("cif_path")],
        "semantic_neighbour_image_paths": [str(row.get("semantic_neighbour_png_path") or row.get("png_path") or "") for row in rows if row.get("semantic_neighbour_png_path") or row.get("png_path")],
        "semantic_neighbour_ranks": [row.get("rank", index + 1) for index, row in enumerate(rows)],
        "semantic_neighbour_scores": [row.get("score", "") for row in rows],
        "semantic_neighbour_render_manifest_path": data.get("semantic_neighbour_render_manifest_path", ""),
        "children": statuses,
    }


def _draw_spp_panel(fig: Any, spec: Any, data: dict[str, Any]) -> dict[str, Any]:
    required = list(data.get("row_specific_spp_pairs") or data["required_pairs"] or [])
    metadata = _pot_metadata(data)
    plotted: list[dict[str, Any]] = []
    curves: list[tuple[str, Path, list[float], list[float], bool]] = []
    display_pairs = required[:6]
    regulariser_root = str(data.get("universal_regulariser_root") or data["pot_root"])
    for pair in display_pairs:
        path = _find_pot_for_pair(regulariser_root, str(pair))
        parsed = _parse_pot_file(path) if path else None
        if path and parsed:
            curves.append((str(pair), path, parsed[0], parsed[1], False))
    if curves:
        n = min(len(curves), 6)
        display_config = dict(SPP_WORKFLOW_DISPLAY_DEFAULTS)
        if data.get("paper_hero_mode"):
            display_config.update({
                "spp_display_mode": "fixed_shared",
                "spp_fixed_y_min": -4.0,
                "spp_fixed_y_max": 10.0,
                "spp_y_limit_policy": "fixed_shared_paper_display",
                "spp_outlier_exclusion_strategy": "none_for_paper_display",
            })
        cols = min(3, n) if data.get("paper_hero_mode") else min(int(display_config["spp_layout_columns"]), n)
        rows = math.ceil(n / cols)
        layout = f"{rows}x{cols}"
        sub = spec.subgridspec(rows + 1, cols, height_ratios=[0.38] + [1.0] * rows, hspace=0.28 if rows > 1 else 0.15, wspace=0.24)
        header = fig.add_subplot(sub[0, :])
        header.set_axis_off()
        header.set_title(
            "SPP / solver guidance" if data.get("paper_hero_mode")
            else "Row-specific cross-pair SPP" if len(required) == 1
            else "Row-specific SPP/POT guidance",
            fontsize=11, fontweight="bold", pad=1,
        )
        regulariser_state = "available" if metadata["pot_source_status"] == "recorded" else "not used"
        displayed_text = ", ".join(str(pair) for pair, *_ in curves)
        if data.get("paper_hero_mode"):
            header.text(0.02, 0.72, "periodic pair-distance evidence from 30 retrieved structures", fontsize=7.4, va="top", transform=header.transAxes)
            header.text(0.02, 0.22, "dmytro_gr_v1 | six repaired pair potentials | 0-10 A", fontsize=7.1, va="top", transform=header.transAxes)
        else:
            header.text(
                0.02, 0.82,
                f"Row-specific SPP from retrieved neighbours\nRetrieved-evidence structures: {data.get('retrieved_evidence_count') or data.get('neighbor_count') or 'n/a'} | Row SPP pairs: {len(required)}",
                fontsize=7.4, va="top", transform=header.transAxes,
            )
            header.text(
                0.02, 0.22,
                f"Displayed pair{'s' if len(curves) != 1 else ''}: {displayed_text}\nUniversal regulariser: {regulariser_state}",
                fontsize=7.1, va="top", transform=header.transAxes,
            )
            header.text(
                0.58, 0.64,
                "Negative values indicate distances favoured relative to the reference/background.",
                fontsize=6.4, va="top", transform=header.transAxes, color="#404040",
            )
        y_axis_scaling = "fixed_shared_display_raw_curve" if data.get("paper_hero_mode") else "display_zoom_raw_curve"
        shared_display_limits = _spp_workflow_shared_display_limits(curves[:6], display_config)
        curve_points_per_pair: dict[str, int] = {}
        y_axis_by_pair: dict[str, dict[str, Any]] = {}
        offscale_annotation_added = False
        for i, (pair, path, xs, ys, deduplicated) in enumerate(curves[:6]):
            row_idx = i // cols
            col_idx = i % cols
            ax = fig.add_subplot(sub[row_idx + 1, col_idx])
            ax.plot(xs, ys, linewidth=0.9, alpha=0.92, color="#2f5f9f")
            display_limits = _spp_workflow_display_limits(xs, ys, display_config)
            display_y_min = shared_display_limits["display_y_min"]
            display_y_max = shared_display_limits["display_y_max"]
            if display_y_min is not None and display_y_max is not None:
                ax.set_ylim(display_y_min, display_y_max)
            if data.get("paper_hero_mode"):
                ax.set_xlim(0.0, 10.0)
            pair_y_max = max(ys) if ys else None
            clipped = bool(pair_y_max is not None and display_y_max is not None and pair_y_max > display_y_max)
            clipping_marker_shown = bool(
                clipped
                and not offscale_annotation_added
                and display_config["spp_show_clipping_annotation"]
                and display_config["spp_clip_annotation_enabled"]
            )
            if clipping_marker_shown:
                ax.text(
                    0.98,
                    0.96,
                    str(display_config["spp_clipping_annotation_text"]),
                    transform=ax.transAxes,
                    ha="right",
                    va="top",
                    fontsize=7.0,
                    fontweight="bold",
                    color="#8a3d00",
                )
                offscale_annotation_added = True
            try:
                ax.set_box_aspect(1)
            except AttributeError:
                ax.set_aspect("auto")
            ax.set_title("Row-specific cross-pair SPP" if len(required) == 1 else pair, fontsize=8.5, pad=2)
            ax.margins(x=0.02, y=0.05)
            if row_idx == rows - 1:
                ax.set_xlabel("r (A)", fontsize=6)
            else:
                ax.set_xticklabels([])
            if col_idx == 0:
                ax.set_ylabel("SPP score, lower preferred", fontsize=6)
            else:
                ax.set_yticklabels([])
            ax.tick_params(labelsize=5.5, length=2)
            ax.grid(True, linewidth=0.25, alpha=0.22)
            x_min = min(xs) if xs else None
            x_max = max(xs) if xs else None
            y_min = min(ys) if ys else None
            y_max = max(ys) if ys else None
            curve_points_per_pair[pair] = len(xs)
            y_axis_by_pair[pair] = {
                "original_y_min": display_limits["original_y_min"],
                "original_y_max": display_limits["original_y_max"],
                "display_y_min": display_y_min,
                "display_y_max": display_y_max,
                "y_axis_clipped": clipped,
                "spp_display_mode": display_limits["spp_display_mode"],
                "spp_zoom_informative_point_count": display_limits.get("spp_zoom_informative_point_count"),
                "spp_shared_y_scale_used": True,
            }
            plotted.append({
                "pair": pair,
                "spp_pair": pair,
                "source_artifact_path": str(path),
                "spp_source_data_path": str(path),
                "render_status": "rendered",
                "render_mode": "workflow_inline",
                "spp_render_source": "raw_data_inline_plot",
                "data_status": "real_data",
                "y_axis_scaling": y_axis_scaling,
                "y_axis_clipped": clipped,
                "box_aspect": "1:1",
                "curve_points": len(xs),
                "raw_point_count": len(xs),
                "deduplicated_repeated_x": False,
                "post_processing": "none",
                "workflow_panel_uses_standalone_style": False,
                "workflow_panel_image_path": "",
                "x_min": x_min,
                "x_max": x_max,
                "y_min": y_min,
                "y_max": y_max,
                "spp_display_mode": display_limits["spp_display_mode"],
                "spp_zoom_upper_strategy": display_config["spp_zoom_upper_strategy"],
                "spp_zoom_upper_percentile": display_config["spp_zoom_upper_percentile"],
                "spp_zoom_ignore_initial_x_below": display_config["spp_zoom_ignore_initial_x_below"],
                "spp_clipping_annotation": str(display_config["spp_clipping_annotation_text"]) if clipping_marker_shown else "",
                "spp_clipping_annotation_meaning": str(display_config["spp_clipping_annotation_meaning"]) if clipped else "",
                "spp_score_sign_convention": SPP_SCORE_SIGN_CONVENTION,
                "spp_negative_values_allowed": SPP_NEGATIVE_VALUES_ALLOWED,
                "spp_lower_is_better": SPP_LOWER_IS_BETTER,
                **y_axis_by_pair[pair],
            })
        if len(required) > 6:
            ax.text(0.98, 0.02, f"+{len(required) - 6} more", transform=ax.transAxes, ha="right", fontsize=8)
        return {
            "render_status": "rendered_curves",
            "data_status": "real_pot_curves",
            "source_artifact_path": str(data.get("row_specific_spp_source_path") or ""),
            "regulariser_source_artifact_path": regulariser_root,
            "parser_used": "spp_maker.pot_io.read_pot_like_qlip_or_local_fallback",
            **metadata,
            "displayed_spp_pairs": [child["pair"] for child in plotted],
            "spp_plot_layout": layout,
            "spp_axis_scaling": y_axis_scaling,
            "spp_box_aspect": "1:1",
            "spp_render_source": "raw_data_inline_plot",
            "spp_render_mode_workflow": "workflow_inline",
            "spp_workflow_uses_embedded_standalone_png": False,
            "spp_workflow_raw_data_reused": True,
            "spp_workflow_pair_count": len(plotted),
            "spp_workflow_layout": layout,
            "spp_workflow_x_range_by_pair": {child["pair"]: [child["x_min"], child["x_max"]] for child in plotted},
            "spp_workflow_y_range_by_pair": {child["pair"]: [child["display_y_min"], child["display_y_max"]] for child in plotted},
            "spp_workflow_original_y_range_by_pair": {child["pair"]: [child["original_y_min"], child["original_y_max"]] for child in plotted},
            "spp_layout_columns": display_config["spp_layout_columns"],
            "spp_force_shared_y_scale": display_config["spp_force_shared_y_scale"],
            "spp_shared_y_scale_used": True,
            "spp_shared_y_display_range": shared_display_limits.get("spp_shared_y_range", []),
            "spp_shared_original_y_range": shared_display_limits.get("spp_shared_original_y_range", []),
            "spp_shared_y_quantile_low": display_config["spp_shared_y_quantile_low"],
            "spp_shared_y_quantile_high": display_config["spp_shared_y_quantile_high"],
            "spp_y_limits": shared_display_limits.get("spp_shared_y_range", []),
            "spp_y_limit_policy": display_config["spp_y_limit_policy"],
            "spp_clipped_top_count": sum(1 for child in plotted if child.get("y_axis_clipped")),
            "spp_clipped_bottom_count": sum(
                1
                for child in plotted
                if child.get("original_y_min") is not None
                and child.get("display_y_min") is not None
                and child["original_y_min"] < child["display_y_min"]
            ),
            "spp_raw_curve_preserved": True,
            "raw_curve_unchanged": True,
            "display_only_clipping": True,
            "display_y_range": shared_display_limits.get("spp_shared_y_range", []),
            "spp_outlier_exclusion_strategy": display_config["spp_outlier_exclusion_strategy"],
            "spp_standalone_exports_present": True,
            "workflow_panel_uses_standalone_style": False,
            "spp_display_mode": shared_display_limits.get("spp_display_mode", "zoomed_raw"),
            "spp_display_mode_workflow": shared_display_limits.get("spp_display_mode", "zoomed_raw"),
            "spp_zoom_config": display_config,
            "spp_clipping_annotation_text": display_config["spp_clipping_annotation_text"],
            "spp_clipping_indicated": any(child.get("y_axis_clipped") for child in plotted) and bool(display_config["spp_show_clipping_annotation"]) and bool(display_config["spp_clip_annotation_enabled"]),
            "spp_zoom_note": "fixed display-only clipping; raw POT values unchanged" if data.get("paper_hero_mode") else "display-only zoom; raw POT values unchanged",
            "spp_score_sign_convention": SPP_SCORE_SIGN_CONVENTION,
            "spp_negative_values_allowed": SPP_NEGATIVE_VALUES_ALLOWED,
            "spp_lower_is_better": SPP_LOWER_IS_BETTER,
            "spp_plotting": {
                "render_mode": "workflow_inline",
                "source_style": "standalone_scientific",
                "layout": layout,
                "box_aspect": "square",
                "y_axis_scaling": y_axis_scaling,
                "axis_label_mode": "minimal_composite",
                "curve_points_per_pair": curve_points_per_pair,
                "deduplicated_repeated_x": False,
                "post_processing": "none",
                "y_axis_clipped": any(child.get("y_axis_clipped") for child in plotted),
                "y_axis_by_pair": y_axis_by_pair,
                "shared_y_scale_used": True,
                "shared_y_display_range": shared_display_limits.get("spp_shared_y_range", []),
                "shared_original_y_range": shared_display_limits.get("spp_shared_original_y_range", []),
                "spp_y_limit_policy": display_config["spp_y_limit_policy"],
                "spp_clipped_top_count": sum(1 for child in plotted if child.get("y_axis_clipped")),
                "spp_clipped_bottom_count": sum(
                    1
                    for child in plotted
                    if child.get("original_y_min") is not None
                    and child.get("display_y_min") is not None
                    and child["original_y_min"] < child["display_y_min"]
                ),
                "spp_raw_curve_preserved": True,
                "raw_curve_unchanged": True,
                "display_only_clipping": True,
                "display_y_range": shared_display_limits.get("spp_shared_y_range", []),
                "spp_display_mode": shared_display_limits.get("spp_display_mode", "zoomed_raw"),
                "spp_zoom_config": display_config,
                "clipping_annotation_shown": any(child.get("y_axis_clipped") for child in plotted) and bool(display_config["spp_show_clipping_annotation"]) and bool(display_config["spp_clip_annotation_enabled"]),
                "spp_clipping_marker": display_config["spp_clipping_annotation_text"],
                "spp_zoom_note": "fixed display-only clipping; raw POT values unchanged" if data.get("paper_hero_mode") else "display-only zoom; raw POT values unchanged",
                "spp_score_sign_convention": SPP_SCORE_SIGN_CONVENTION,
                "spp_negative_values_allowed": SPP_NEGATIVE_VALUES_ALLOWED,
                "spp_lower_is_better": SPP_LOWER_IS_BETTER,
            },
            "children": plotted,
        }
    ax = fig.add_subplot(spec)
    return _render_pair_coverage(ax, data)


def _draw_optimisation_panel(fig: Any, spec: Any, data: dict[str, Any]) -> dict[str, Any]:
    gurobi_artifacts = data.get("gurobi_visual_artifacts") if isinstance(data.get("gurobi_visual_artifacts"), dict) else {}
    matrix_path = Path(str(gurobi_artifacts.get("constraint_matrix_spy_path") or ""))
    trace_path = Path(str(gurobi_artifacts.get("mip_trace_plot_path") or ""))
    meta_path = Path(str(gurobi_artifacts.get("constraint_matrix_meta_path") or ""))
    trace_json_path = Path(str(gurobi_artifacts.get("mip_trace_json_path") or ""))
    trace_csv_path = Path(str(gurobi_artifacts.get("mip_trace_csv_path") or ""))
    sub = spec.subgridspec(2, 1, height_ratios=[3.0, 0.9], hspace=0.05)
    panels_dir = Path(str(data.get("panels_dir") or ""))
    workflow_surface_path = panels_dir / "optimisation_surface_workflow.png"
    standalone_surface_path = panels_dir / "optimisation_surface.png"
    workflow_surface = generate_projected_optimisation_surface(data, workflow_surface_path, display_mode="workflow_thumbnail")
    standalone_surface = generate_projected_optimisation_surface(data, standalone_surface_path, display_mode="standalone_scientific")
    ax = fig.add_subplot(sub[0, 0])
    ax.set_title("Projected QLIP/SPP surface", fontsize=11, fontweight="bold")
    ax.set_axis_off()
    try:
        image, _image_diag = _load_vesta_png(workflow_surface_path)
        ax.imshow(image, aspect="equal")
        ax.set_xlim(0, image.shape[1])
        ax.set_ylim(image.shape[0], 0)
    except VestaRenderError:
        _safe_axis_text(ax, 0.5, 0.5, "projected proxy surface\nrender unavailable", ha="center", va="center", fontsize=9)
    _safe_axis_text(ax, 0.05, 0.04, "proxy projection, not full MILP landscape", fontsize=7.5, va="bottom")
    card = fig.add_subplot(sub[1, 0])
    card.set_axis_off()
    card.set_facecolor("#f7f7f7")
    status = data["qlip_status"] or "unknown"
    objective = data["objective_value"]
    solution_available = bool(data.get("qlip_solution_cif_produced")) and objective not in {None, ""} and str(status).lower() in {"optimal", "succeeded", "success"}
    objective_text = f"{objective}" if objective != "" else "n/a"
    _safe_axis_text(card, 0.06, 0.70, f"QLIP status: {status}", fontsize=9, fontweight="bold", va="top")
    if solution_available:
        _safe_axis_text(card, 0.06, 0.34, f"QLIP objective: {objective_text}", fontsize=8.5, va="top")
    else:
        failure_reason = data.get("qlip_failure_user_visible_reason") or "No optimum available"
        _safe_axis_text(card, 0.06, 0.34, failure_reason, fontsize=8.0, va="top")
    return {
        "render_status": "rendered",
        "data_status": workflow_surface["surface_type"],
        "panel_type": "projected_proxy_surface",
        "optimisation_surface_type": "projected_proxy_surface",
        "display_mode": "workflow_thumbnail",
        "source_artifact_path": str(data["solution_cif"] or ""),
        "objective_card_used": True,
        "surface_annotation": "selected_optimum_only" if solution_available else "no_optimum_available",
        "optimisation_surface": standalone_surface,
        "workflow_optimisation_surface": workflow_surface,
        "true_gurobi_landscape": False,
        "optimum_marker": "star" if solution_available else "none",
        "optimum_label_mode": "external_2d_overlay" if solution_available else "none",
        "optimum_label_front_visible": bool(solution_available),
        "qlip_solution_cif_produced": bool(data.get("qlip_solution_cif_produced")),
        "qlip_failure_category": data.get("qlip_failure_category", ""),
        "qlip_failure_message": data.get("qlip_failure_message", ""),
        "standalone_surface_exported": True,
        "gurobi_diagnostics_available": any(path.is_file() for path in (matrix_path, trace_path, meta_path, trace_json_path, trace_csv_path)),
        "gurobi_diagnostics_exported": any(path.is_file() for path in (matrix_path, trace_path, meta_path, trace_json_path, trace_csv_path)),
        "gurobi_diagnostics": {
            "constraint_matrix_spy_path": str(matrix_path) if matrix_path.is_file() else "",
            "mip_trace_plot_path": str(trace_path) if trace_path.is_file() else "",
            "constraint_matrix_meta_path": str(meta_path) if meta_path.is_file() else "",
            "mip_trace_json_path": str(trace_json_path) if trace_json_path.is_file() else "",
            "mip_trace_csv_path": str(trace_csv_path) if trace_csv_path.is_file() else "",
        },
        "warnings": ["Hero panel uses projected proxy surface; real Gurobi/MILP diagnostics are exported as appendix evidence when available."],
    }


def _draw_final_panel(fig: Any, spec: Any, data: dict[str, Any]) -> dict[str, Any]:
    sub = spec.subgridspec(2, 1, height_ratios=[4.0, 0.8], hspace=0.04)
    source_validation = _validate_final_crystal_source(data.get("solution_cif"), data.get("run_dir", ""))
    final_image_path = Path(str(data.get("final_crystal_image_path") or ""))
    invalid_existing_source = (
        not source_validation["final_crystal_source_validated"]
        and data.get("solution_cif")
        and source_validation.get("final_crystal_source_role") in {"retrieval_corpus", "semantic_neighbour", "spp_corpus"}
    )
    if final_image_path.is_file():
        ax = fig.add_subplot(sub[0, 0])
        ax.set_title("Final Generated Crystal", fontsize=9, pad=2)
        ax.set_axis_off()
        try:
            image, image_diag = _load_vesta_png(final_image_path)
            ax.imshow(image, aspect="equal")
            ax.set_xlim(0, image.shape[1])
            ax.set_ylim(image.shape[0], 0)
            render = {
                "render_status": "rendered",
                "renderer_used": "pre_rendered_vesta_png",
                "source_artifact_path": str(data.get("solution_cif") or ""),
                "data_status": "real_vesta_prerendered_png",
                "vesta_render_path": str(final_image_path),
                "final_crystal_render_path": str(final_image_path),
                "final_crystal_renderer_used": "pre_rendered_vesta_png",
                "structure_image_source": "vesta_prerendered_png",
                "fallback_structure_rendering_used": False,
                **image_diag,
                **source_validation,
            }
        except VestaRenderError as exc:
            if data.get("require_vesta_images"):
                raise
            render = {"render_status": exc.code, "renderer_used": "pre_rendered_vesta_png_unreadable", "source_artifact_path": str(final_image_path), **source_validation}
    elif data.get("require_vesta_images") or data.get("no_fallback_structure_rendering"):
        raise VestaRenderError("missing_required_vesta_final_png", f"Missing required VESTA PNG for final generated crystal: {data.get('solution_cif')}", {"solution_cif": str(data.get("solution_cif") or "")})
    elif data.get("solution_cif") is None:
        ax = fig.add_subplot(sub[0, 0])
        ax.set_axis_off()
        _safe_axis_text(ax, 0.5, 0.58, "No solution CIF produced", ha="center", va="center", fontsize=10, fontweight="bold")
        reason = data.get("qlip_failure_user_visible_reason") or data.get("qlip_failure_category") or "QLIP solve did not record a solution CIF"
        _safe_axis_text(ax, 0.5, 0.40, _wrap(str(reason), width=28, max_lines=3), ha="center", va="center", fontsize=7.5)
        render = {
            "render_status": "deferred_missing_cif",
            "renderer_used": "fallback_card",
            "source_artifact_path": "",
            "data_status": "missing_solution_cif",
            "final_crystal_render_path": "",
            "final_crystal_renderer_used": "fallback_card",
            **source_validation,
        }
    elif invalid_existing_source:
        ax = fig.add_subplot(sub[0, 0])
        ax.set_axis_off()
        _safe_axis_text(ax, 0.5, 0.60, "wrong_final_crystal_source", ha="center", va="center", fontsize=9, fontweight="bold")
        _safe_axis_text(ax, 0.5, 0.42, source_validation["final_crystal_source_validation_reason"], ha="center", va="center", fontsize=7)
        render = {
            "render_status": "wrong_final_crystal_source",
            "renderer_used": "source_validation_guard",
            "source_artifact_path": str(data.get("solution_cif") or ""),
            "data_status": "invalid_final_crystal_source",
            "final_crystal_render_path": "",
            "final_crystal_renderer_used": "source_validation_guard",
            **source_validation,
        }
    else:
        render = _render_cif_panel(
            fig,
            sub[0, 0],
            data["solution_cif"],
            title="Final Generated Crystal",
            data=data,
            max_atoms=120,
            target_material=data["material_system"],
            image_slug="final_generated_crystal",
        )
        render.update(source_validation)
        render["final_crystal_render_path"] = render.get("vesta_render_path", "")
        render["final_crystal_renderer_used"] = render.get("renderer_used", "")
    text_ax = fig.add_subplot(sub[1, 0])
    text_ax.set_axis_off()
    novelty = "novel" if data["novelty"] is True else "rediscovery/non-novel" if data["novelty"] is False else "unknown"
    sca = data.get("sca_validation") or {}
    caption = str(data.get("final_crystal_caption") or "").strip()
    if sca:
        sca_status = str(sca.get("status") or "PASS" if sca.get("pre_dft_valid") else "CHECK")
        geometry = "PASS" if sca.get("geometry_ok") is True else str(sca.get("geometry_status") or "check")
        topology = str(sca.get("topology_status") or "check")
        contacts = sca.get("num_bad_contacts", "")
        lines = [
            caption,
            f"QLIP: {data['qlip_status']} | objective: {data['objective_value']}",
            f"SCA: {sca_status} | geometry {geometry} | topology {topology}",
            f"bad contacts: {contacts}" if contacts != "" else "",
        ]
        text_ax.text(0.04, 0.94, "\n".join(line for line in lines if line), fontsize=7.4, va="top", transform=text_ax.transAxes)
    else:
        text_ax.text(0.04, 0.88, f"QLIP: {data['qlip_status']}\nobjective: {data['objective_value']}\nnovelty: {novelty}", fontsize=9, va="top", transform=text_ax.transAxes)
    render["qlip_status"] = data["qlip_status"]
    render["objective_value"] = data["objective_value"]
    render["novelty"] = novelty
    render["qlip_validate_status"] = data.get("qlip_validate_status", "")
    render["qlip_solve_status"] = data.get("qlip_solve_status", "")
    render["qlip_failure_category"] = data.get("qlip_failure_category", "")
    render["qlip_failure_message"] = data.get("qlip_failure_message", "")
    render["gurobi_available"] = data.get("gurobi_available", "")
    render["gurobi_license_status"] = data.get("gurobi_license_status", "")
    render["qlip_solve_started"] = data.get("qlip_solve_started", "")
    render["qlip_solution_cif_produced"] = data.get("qlip_solution_cif_produced", False)
    render["qlip_solution_cif_path"] = data.get("qlip_solution_cif_path", "")
    render["final_crystal_render_status"] = render.get("render_status", "")
    return render


def visualise_workflow_artifact(
    run_dir: Path | str,
    out_dir: Path | str,
    case_name: str,
    *,
    vesta_path: str | Path | None = None,
    require_vesta: bool = False,
    vesta_timeout_s: float | None = None,
    vesta_call_delay_s: float | None = None,
    vesta_retries: int | None = None,
    stabilization_poll_interval_s: float | None = None,
    stabilization_required_identical_checks: int | None = None,
    ensure_semantic_neighbour_renders: bool = False,
    semantic_neighbour_cif_search_roots: list[Path | str] | None = None,
    include_projected_surface: bool = True,
    pot_root: str | Path | None = None,
    spp_source_label: str | None = None,
    render_semantic_neighbours_with_vesta: bool = True,
    final_crystal_image_path: str | Path | None = None,
    semantic_neighbour_image_manifest: str | Path | None = None,
    require_vesta_images: bool = False,
    no_fallback_structure_rendering: bool = False,
    semantic_neighbour_target_count: int = 10,
) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    panels_dir = out_dir / f"workflow_artifact_{_safe_slug(case_name)}_panels"
    panels_dir.mkdir(parents=True, exist_ok=True)
    data = _load_run_data(run_dir, case_name)
    slug = _safe_slug(case_name)
    data["case_name"] = case_name
    if pot_root:
        data["pot_root"] = str(pot_root)
        data["pot_root_source"] = "explicit_renderer_argument"
    if spp_source_label:
        data["spp_source_label"] = str(spp_source_label)
    resolved_vesta = _resolve_vesta_executable(vesta_path)
    if require_vesta and not resolved_vesta:
        raise VestaUnavailableError("vesta_executable_unavailable", "provide --vesta-path, VESTA_EXE, or VESTA_PATH", {"vesta_exe": str(vesta_path or "")})
    data["vesta_executable"] = resolved_vesta
    data["require_vesta"] = require_vesta
    data["vesta_timeout_s"] = _to_float(vesta_timeout_s, _env_float("VESTA_TIMEOUT_S", 120.0))
    data["vesta_call_delay_s"] = _to_float(vesta_call_delay_s, _env_float("VESTA_CALL_DELAY_S", 1.5))
    data["vesta_retries"] = _to_int(vesta_retries, _env_int("VESTA_RETRIES", 2))
    data["stabilization_poll_interval_s"] = _to_float(stabilization_poll_interval_s, _env_float("VESTA_STABILIZATION_POLL_INTERVAL_S", 0.25))
    data["stabilization_required_identical_checks"] = _to_int(stabilization_required_identical_checks, _env_int("VESTA_STABILIZATION_REQUIRED_IDENTICAL_CHECKS", 1))
    data["include_projected_surface"] = bool(include_projected_surface)
    data["render_semantic_neighbours_with_vesta"] = bool(render_semantic_neighbours_with_vesta)
    data["require_vesta_images"] = bool(require_vesta_images)
    data["no_fallback_structure_rendering"] = bool(no_fallback_structure_rendering)
    data["semantic_neighbour_target_count"] = semantic_neighbour_target_count
    data["panels_dir"] = str(panels_dir)
    row_id = run_dir.name
    image_manifest = _load_structure_image_manifest(str(semantic_neighbour_image_manifest or ""))
    if final_crystal_image_path:
        data["final_crystal_image_path"] = str(final_crystal_image_path)
    elif image_manifest:
        data["final_crystal_image_path"] = (image_manifest.get("final_by_row") or {}).get(row_id, "")
    data["semantic_neighbour_image_manifest"] = str(semantic_neighbour_image_manifest or "")
    base_neighbor_rows = _build_semantic_neighbor_rows(data)
    if ensure_semantic_neighbour_renders and not _semantic_render_manifest_complete(panels_dir, len(base_neighbor_rows)):
        export_and_render_semantic_neighbour_cifs(
            run_dir,
            out_dir,
            case_name,
            panels_dir / "semantic_neighbour_cifs",
            export_cifs=True,
            render_pngs=True,
            vesta_path=vesta_path,
            require_vesta=require_vesta,
            vesta_timeout_s=data["vesta_timeout_s"],
            vesta_call_delay_s=data["vesta_call_delay_s"],
            vesta_retries=data["vesta_retries"],
            stabilization_poll_interval_s=data["stabilization_poll_interval_s"],
            stabilization_required_identical_checks=data["stabilization_required_identical_checks"],
            semantic_neighbour_cif_search_roots=semantic_neighbour_cif_search_roots,
        )
    neighbor_rows = _copy_vesta_ready_neighbor_cifs(base_neighbor_rows, panels_dir)
    if image_manifest:
        row_images = (image_manifest.get("neighbours_by_row") or {}).get(row_id, {})
        for row in neighbor_rows:
            rank = _to_int(row.get("rank"), 0)
            if rank in row_images:
                row["semantic_neighbour_png_path"] = row_images[rank]
                row["png_render_status"] = "rendered"
        if require_vesta_images:
            image_ready_rows = [
                row for row in neighbor_rows
                if row.get("semantic_neighbour_png_path") and Path(str(row.get("semantic_neighbour_png_path"))).is_file()
            ]
            if image_ready_rows:
                neighbor_rows = image_ready_rows
    neighbor_rows, render_manifest_status = _merge_semantic_render_manifest(neighbor_rows, panels_dir)
    data.update(render_manifest_status)
    data["semantic_neighbor_rows"] = neighbor_rows
    # Write initial sidecars so the paths exist before drawing; rewrite after rendering
    # to include render_status and VESTA thumbnail paths populated by the corpus panel.
    data["semantic_neighbours_sidecars"] = _write_semantic_neighbor_sidecars(out_dir, slug, neighbor_rows)
    png_path = out_dir / f"workflow_artifact_{slug}.png"
    pdf_path = out_dir / f"workflow_artifact_{slug}.pdf"
    svg_path = out_dir / f"workflow_artifact_{slug}.svg"
    manifest_path = out_dir / f"workflow_artifact_{slug}_manifest.json"

    if include_projected_surface:
        fig = plt.figure(figsize=(24, 8), constrained_layout=False)
        grid = fig.add_gridspec(
            1,
            5,
            left=0.018,
            right=0.992,
            top=0.89,
            bottom=0.055,
            wspace=0.055,
            width_ratios=[0.85, 3.45, 1.40, 1.20, 1.10],
        )
        panels = {
            "query": _draw_query_panel(fig.add_subplot(grid[0, 0]), data),
            "crystal_db_retrieved_corpus": _draw_corpus_panel(fig, grid[0, 1], data),
            "spp_pot_guidance": _draw_spp_panel(fig, grid[0, 2], data),
            "qlip_optimisation_space": _draw_optimisation_panel(fig, grid[0, 3], data),
            "final_generated_crystal": _draw_final_panel(fig, grid[0, 4], data),
        }
        figure_size = [24, 8]
        top_level_panel_count = 5
    else:
        fig = plt.figure(figsize=(22, 8), constrained_layout=False)
        grid = fig.add_gridspec(
            1,
            4,
            left=0.018,
            right=0.992,
            top=0.89,
            bottom=0.055,
            wspace=0.055,
            width_ratios=[0.85, 3.65, 1.75, 1.35],
        )
        panels = {
            "query": _draw_query_panel(fig.add_subplot(grid[0, 0]), data),
            "crystal_db_retrieved_corpus": _draw_corpus_panel(fig, grid[0, 1], data),
            "spp_pot_guidance": _draw_spp_panel(fig, grid[0, 2], data),
            "final_generated_crystal": _draw_final_panel(fig, grid[0, 3], data),
        }
        figure_size = [22, 8]
        top_level_panel_count = 4
    fig.suptitle(data.get("figure_title") or f"Workflow artifact: {data['material_system']}", fontsize=14, fontweight="bold")
    if data.get("paper_hero_mode"):
        fig.text(
            0.5, 0.94,
            "REQUEST  \u2192  RETRIEVAL  \u2192  PAIR EVIDENCE / SPP  \u2192  QLIP CSP  \u2192  GENERATED CRYSTAL  \u2192  SCA PASS",
            ha="center", va="center", fontsize=8.5, color="#4f5b62",
        )
    fig.savefig(png_path, dpi=220)
    fig.savefig(pdf_path, format="pdf")
    fig.savefig(svg_path)
    plt.close(fig)
    data["semantic_neighbours_sidecars"] = _write_semantic_neighbor_sidecars(out_dir, slug, neighbor_rows)

    manifest = {
        "schema_version": "agentic_csp.visualise_workflow_artifact.v1",
        "case_name": case_name,
        "run_dir": str(run_dir),
        "png_path": str(png_path),
        "pdf_path": str(pdf_path),
        "svg_path": str(svg_path),
        "panels_dir": str(panels_dir),
        "vesta": _vesta_status(resolved_vesta),
        "vesta_serial_rendering": True,
        "render_semantic_neighbours_with_vesta": bool(render_semantic_neighbours_with_vesta),
        "require_vesta_images": bool(require_vesta_images),
        "no_fallback_structure_rendering": bool(no_fallback_structure_rendering),
        "fallback_structure_rendering_used": any(
            str(child.get("renderer_used") or "").startswith("matplotlib_cif_scatter")
            for panel in panels.values()
            for child in (panel.get("children") or [])
        )
        or str((panels.get("final_generated_crystal") or {}).get("renderer_used") or "").startswith("matplotlib_cif_scatter"),
        "structure_image_source": "vesta_prerendered_png" if require_vesta_images else "mixed_or_runtime",
        "final_crystal_image_path": data.get("final_crystal_image_path", ""),
        "semantic_neighbour_image_manifest": data.get("semantic_neighbour_image_manifest", ""),
        "vesta_timeout_s": data["vesta_timeout_s"],
        "vesta_call_delay_s": data["vesta_call_delay_s"],
        "vesta_retries": data["vesta_retries"],
        "stabilization_poll_interval_s": data["stabilization_poll_interval_s"],
        "stabilization_required_identical_checks": data["stabilization_required_identical_checks"],
        "semantic_neighbours_sidecars": data["semantic_neighbours_sidecars"],
        "semantic_neighbour_render_manifest_used": bool(data.get("semantic_neighbour_render_manifest_used")),
        "semantic_neighbour_rendered_png_count": data.get("semantic_neighbour_rendered_png_count", 0),
        "semantic_neighbour_cif_count": data.get("semantic_neighbour_cif_count", 0),
        "semantic_neighbour_render_manifest_path": data.get("semantic_neighbour_render_manifest_path", ""),
        "projected_surface_included": bool(include_projected_surface),
        "pot_root": data.get("pot_root", ""),
        "pot_metadata": _pot_metadata(data),
        "spp_score_sign_convention": SPP_SCORE_SIGN_CONVENTION,
        "spp_negative_values_allowed": SPP_NEGATIVE_VALUES_ALLOWED,
        "spp_lower_is_better": SPP_LOWER_IS_BETTER,
        "qlip_validate_status": data.get("qlip_validate_status", ""),
        "qlip_solve_status": data.get("qlip_solve_status", ""),
        "qlip_failure_category": data.get("qlip_failure_category", ""),
        "qlip_failure_message": data.get("qlip_failure_message", ""),
        "gurobi_available": data.get("gurobi_available", ""),
        "gurobi_license_status": data.get("gurobi_license_status", ""),
        "qlip_solve_started": data.get("qlip_solve_started", ""),
        "qlip_solution_cif_produced": data.get("qlip_solution_cif_produced", False),
        "qlip_solution_cif_path": data.get("qlip_solution_cif_path", ""),
        "top_level_panel_count": top_level_panel_count,
        "figure_size_inches": figure_size,
        "aspect_ratio": figure_size[0] / figure_size[1],
        "panels": panels,
    }
    if include_projected_surface:
        manifest["optimisation_surface"] = panels["qlip_optimisation_space"].get("optimisation_surface", {})
    _write_json(manifest_path, manifest)
    return {"png_path": str(png_path), "pdf_path": str(pdf_path), "svg_path": str(svg_path), "manifest_path": str(manifest_path), "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--case-name")
    parser.add_argument("--vesta-path", default=None)
    parser.add_argument("--require-vesta", action="store_true")
    parser.add_argument("--vesta-timeout-s", type=float, default=None)
    parser.add_argument("--vesta-call-delay-s", type=float, default=None)
    parser.add_argument("--vesta-retries", type=int, default=None)
    parser.add_argument("--stabilization-poll-interval-s", type=float, default=None)
    parser.add_argument("--stabilization-required-identical-checks", type=int, default=None)
    parser.add_argument("--export-semantic-neighbour-cifs-only", action="store_true")
    parser.add_argument("--render-semantic-neighbour-pngs-only", action="store_true")
    parser.add_argument("--semantic-neighbour-out-dir", type=Path, default=None)
    parser.add_argument("--semantic-neighbour-cif-search-root", action="append", type=Path, default=[])
    parser.add_argument("--ensure-semantic-neighbour-renders", action="store_true")
    parser.add_argument("--no-projected-surface", action="store_true")
    parser.add_argument("--pot-root", type=Path, default=None)
    parser.add_argument("--spp-source-label", default=None)
    parser.add_argument("--no-semantic-neighbour-vesta", action="store_true")
    parser.add_argument("--final-crystal-image-path", type=Path, default=None)
    parser.add_argument("--semantic-neighbour-image-manifest", type=Path, default=None)
    parser.add_argument("--require-vesta-images", action="store_true")
    parser.add_argument("--no-fallback-structure-rendering", action="store_true")
    parser.add_argument("--semantic-neighbour-target-count", type=int, default=5)
    parser.add_argument("--export-final-doc-images", action="store_true")
    parser.add_argument("--final-doc-images-out-dir", type=Path, default=None)
    parser.add_argument("--final-doc-image-case", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.export_final_doc_images:
            target_dir = args.final_doc_images_out_dir or (args.out_dir.parent / "final_doc_images")
            result = export_final_doc_images(args.out_dir, target_dir, case_names=args.final_doc_image_case or None)
            print(json.dumps(result, indent=2))
            return 0
        if args.run_dir is None or not args.case_name:
            parser.error("--run-dir and --case-name are required unless --export-final-doc-images is used")
        if args.export_semantic_neighbour_cifs_only or args.render_semantic_neighbour_pngs_only:
            semantic_out_dir = args.semantic_neighbour_out_dir or (args.out_dir / f"workflow_artifact_{_safe_slug(args.case_name)}_panels" / "semantic_neighbour_cifs")
            result = export_and_render_semantic_neighbour_cifs(
                args.run_dir,
                args.out_dir,
                args.case_name,
                semantic_out_dir,
                export_cifs=args.export_semantic_neighbour_cifs_only,
                render_pngs=args.render_semantic_neighbour_pngs_only,
                vesta_path=args.vesta_path,
                require_vesta=args.require_vesta,
                vesta_timeout_s=args.vesta_timeout_s,
                vesta_call_delay_s=args.vesta_call_delay_s,
                vesta_retries=args.vesta_retries,
                stabilization_poll_interval_s=args.stabilization_poll_interval_s,
                stabilization_required_identical_checks=args.stabilization_required_identical_checks,
                semantic_neighbour_cif_search_roots=args.semantic_neighbour_cif_search_root,
            )
            print(json.dumps(result, indent=2))
            return 0
        result = visualise_workflow_artifact(
            args.run_dir,
            args.out_dir,
            args.case_name,
            vesta_path=args.vesta_path,
            require_vesta=args.require_vesta,
            vesta_timeout_s=args.vesta_timeout_s,
            vesta_call_delay_s=args.vesta_call_delay_s,
            vesta_retries=args.vesta_retries,
            stabilization_poll_interval_s=args.stabilization_poll_interval_s,
            stabilization_required_identical_checks=args.stabilization_required_identical_checks,
            ensure_semantic_neighbour_renders=args.ensure_semantic_neighbour_renders,
            semantic_neighbour_cif_search_roots=args.semantic_neighbour_cif_search_root,
            include_projected_surface=not args.no_projected_surface,
            pot_root=args.pot_root,
            spp_source_label=args.spp_source_label,
            render_semantic_neighbours_with_vesta=not args.no_semantic_neighbour_vesta,
            final_crystal_image_path=args.final_crystal_image_path,
            semantic_neighbour_image_manifest=args.semantic_neighbour_image_manifest,
            require_vesta_images=args.require_vesta_images,
            no_fallback_structure_rendering=args.no_fallback_structure_rendering,
            semantic_neighbour_target_count=args.semantic_neighbour_target_count,
        )
    except VestaRenderError as exc:
        payload = {"error": exc.code, "message": str(exc)}
        if exc.diagnostics:
            payload["diagnostics"] = exc.diagnostics
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({k: result[k] for k in ("png_path", "pdf_path", "svg_path", "manifest_path")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
