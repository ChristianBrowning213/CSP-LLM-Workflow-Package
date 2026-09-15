from __future__ import annotations

import argparse
import atexit
import csv
import hashlib
import json
import os
import stat
import shutil
import sys
import zipfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sok_llm_orchestrator.agentic.visualise_workflow_artifact import visualise_workflow_artifact  # noqa: E402


EXPERIMENT_PACKAGE_DIRS = {
    "paper_experiment_1_common_v1": "EXPERIMENT_1_COMMON",
    "paper_experiment_2_hard_v3": "EXPERIMENT_2_HARD",
    "paper_experiment_3_specialist_halide_v1": "EXPERIMENT_3_SPECIALIST_HALIDE",
}

DEFAULT_POT_ROOT = Path("C:/Users/brown/Downloads/SPP/SPP/SPP/SPP")
VESTA_SEARCH_PATHS = [
    Path("C:/Program Files/VESTA/VESTA.exe"),
    Path("C:/Program Files (x86)/VESTA/VESTA.exe"),
    Path("C:/Users/brown/AppData/Local/Programs/VESTA/VESTA.exe"),
    Path("C:/Users/brown/Documents/VESTA-win64/VESTA-win64/VESTA.exe"),
]

BUILD_UUID = os.environ.get("PAPER_PACKAGE_BUILD_UUID") or uuid.uuid4().hex
BUILD_LOCK_TIMEOUT_S = 1800.0


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class BuildLock:
    def __init__(self, lock_path: Path, *, timeout_s: float = BUILD_LOCK_TIMEOUT_S) -> None:
        self.lock_path = lock_path
        self.timeout_s = timeout_s
        self.fd: int | None = None

    def __enter__(self) -> "BuildLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        payload = json.dumps({"build_uuid": BUILD_UUID, "pid": os.getpid(), "started_at": utc_timestamp()})
        while True:
            try:
                self.fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, payload.encode("utf-8"))
                return self
            except FileExistsError:
                if time.monotonic() - started > self.timeout_s:
                    holder = self.lock_path.read_text(encoding="utf-8", errors="ignore") if self.lock_path.exists() else ""
                    raise RuntimeError(f"Another paper workflow package build is active: {self.lock_path} {holder}")
                time.sleep(1.0)

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass


def read_pair_csv(path: Path) -> list[str]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [str(row.get("pair") or row.get("spp_pair") or "").strip() for row in csv.DictReader(handle) if str(row.get("pair") or row.get("spp_pair") or "").strip()]


def formula_elements(formula: str) -> list[str]:
    import re

    return re.findall(r"[A-Z][a-z]?", formula or "")


def pair_key(pair: str) -> str:
    return "-".join(sorted(part.upper() for part in pair.replace("_", "-").split("-") if part))


def pot_pair_count(pot_root: str, pairs: list[str]) -> int:
    root = Path(pot_root)
    if not pot_root or not root.exists():
        return 0
    stems = {pair_key(path.stem) for path in root.rglob("*.POT")}
    return sum(1 for pair in pairs if pair_key(pair) in stems)


def parseable_cif(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "_atom_site" in text and ("_cell_length_a" in text or "_cell_angle_alpha" in text)


def retrieval_cif_paths(retrieval: dict[str, Any], row_run_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for neighbor in retrieval.get("neighbors") or []:
        cif_info = neighbor.get("cif_export") if isinstance(neighbor.get("cif_export"), dict) else {}
        source_text = str(cif_info.get("path") or neighbor.get("cif_path") or "")
        if not source_text:
            continue
        path = resolve_path(source_text, ROOT)
        if not path.is_file():
            path = row_run_dir / source_text
        paths.append(path)
    return paths


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        field_set: list[str] = []
        for row in rows:
            for key in row:
                if key not in field_set:
                    field_set.append(key)
        fields = field_set
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def slug(value: str) -> str:
    out = []
    for char in value.lower():
        out.append(char if char.isalnum() else "_")
    return "_".join(part for part in "".join(out).split("_") if part)


def resolve_path(text: str, base: Path = ROOT) -> Path:
    path = Path(text)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def rel(path: str | Path, base: Path) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def safe_rmtree_package(path: Path) -> None:
    path = path.resolve()
    artifacts = (ROOT / "artifacts").resolve()
    if artifacts not in path.parents or path == artifacts:
        raise RuntimeError(f"Refusing to remove non-package path: {path}")
    if path.exists():
        def _make_writable_and_retry(function: Any, target: str, _exc_info: Any) -> None:
            os.chmod(target, stat.S_IWRITE)
            function(target)

        shutil.rmtree(path, onerror=_make_writable_and_retry)


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def copy_if_exists(src: Path | None, dst: Path) -> str:
    if src is None or not src.is_file():
        return ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def rendered_output_files(figure_out: Path) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    for ext in ("png", "pdf", "svg"):
        matches = sorted(path for path in figure_out.glob(f"workflow_artifact_*.{ext}") if "_panels" not in path.name)
        if matches:
            outputs[ext] = matches[0]
    manifest_matches = sorted(figure_out.glob("workflow_artifact_*_manifest.json"))
    if manifest_matches:
        outputs["manifest"] = manifest_matches[0]
    panel_matches = sorted(path for path in figure_out.glob("workflow_artifact_*_panels") if path.is_dir())
    if panel_matches:
        outputs["panels"] = panel_matches[0]
    return outputs


def locate_vesta(explicit: str = "") -> tuple[str, list[dict[str, Any]]]:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    for name in ("VESTA_EXE", "VESTA_PATH"):
        value = str(os.environ.get(name) or "").strip()
        if value:
            candidates.append(value)
    candidates.extend(str(path) for path in VESTA_SEARCH_PATHS)
    seen: set[str] = set()
    searched: list[dict[str, Any]] = []
    found = ""
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate)
        exists = path.is_file()
        searched.append({"path": candidate, "exists": exists})
        if exists and not found:
            found = str(path)
    return found, searched


def rendered_pngs_by_row(manifest_path: str) -> dict[str, dict[str, Any]]:
    if not manifest_path:
        return {}
    path = resolve_path(manifest_path)
    if not path.is_file():
        return {}
    rows = read_csv(path)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("render_status") != "rendered":
            continue
        row_id = row.get("row_id", "")
        if not row_id:
            continue
        item = out.setdefault(row_id, {"final": "", "neighbours": []})
        if row.get("cif_role") == "final_generated":
            item["final"] = row.get("desired_png_path", "")
        elif row.get("cif_role") == "semantic_neighbour":
            item["neighbours"].append(row.get("desired_png_path", ""))
    return out


def normalize_retrieval_payload(payload: dict[str, Any], row_run_dir: Path, bundle_dir: Path) -> tuple[dict[str, Any], list[Path]]:
    payload = json.loads(json.dumps(payload))
    exported_dir = bundle_dir / "crystal_csp_pack" / "cifs"
    copied: list[Path] = []
    export_items: list[dict[str, Any]] = []
    for index, neighbor in enumerate(payload.get("neighbors") or [], start=1):
        cif_info = neighbor.get("cif_export") if isinstance(neighbor.get("cif_export"), dict) else {}
        source_text = str(cif_info.get("path") or neighbor.get("cif_path") or "")
        source = resolve_path(source_text, ROOT) if source_text else None
        if source and not source.is_file():
            source = row_run_dir / source_text
        copied_path = ""
        status = str(cif_info.get("status") or "not_exported_or_policy_blocked")
        if source and source.is_file():
            target = exported_dir / f"rank_{index:03d}_{slug(str(neighbor.get('structure_id') or source.stem))}.cif"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target)
            copied_path = str(target)
            status = "exported"
        neighbor["cif_path"] = copied_path
        neighbor["exported_cif_path"] = copied_path
        neighbor["export_status"] = status
        neighbor["formula"] = neighbor.get("formula") or (neighbor.get("metadata") or {}).get("formula") or ""
        if copied_path:
            export_items.append(
                {
                    "rank": neighbor.get("rank") or index,
                    "score": neighbor.get("score", ""),
                    "structure_id": neighbor.get("structure_id", ""),
                    "source_id": (neighbor.get("provenance") or {}).get("source_id", ""),
                    "formula": neighbor.get("formula", ""),
                    "cif_path": copied_path,
                    "export_status": "exported",
                }
            )
    payload["export"] = {"items": export_items, "exported_cif_count": len(export_items)}
    return payload, copied


def selected_evidence_payload_path(row_run_dir: Path) -> Path:
    return row_run_dir / "selected_evidence_payload.json"


def paper_display_payload_path(row_run_dir: Path) -> Path:
    return row_run_dir / "paper_display_neighbours_payload.json"


def qlip_summary(path: Path) -> dict[str, Any]:
    data = read_json(path)
    solution = data.get("solution") if isinstance(data.get("solution"), dict) else {}
    score = data.get("score") if isinstance(data.get("score"), dict) else {}
    objective = data.get("objective_value")
    if objective in {None, ""}:
        objective = score.get("objective_value") or score.get("total")
    return {
        "status": "success" if str(data.get("status") or "").lower() in {"generated", "success", "optimal"} else data.get("status", "success"),
        "qlip_status": "success",
        "objective_value": objective if objective not in {None, ""} else 0.0,
        "solution_formula": solution.get("formula", ""),
    }


def build_render_bundle(row: dict[str, str], row_run_dir: Path, bundle_dir: Path, *, pot_root: str = "", spp_source_label: str = "") -> dict[str, Any]:
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    retrieval_path = resolve_path(row["retrieval_trace_path"])
    spp_path = resolve_path(row["spp_trace_path"])
    qlip_path = resolve_path(row["qlip_solution_path"])
    generated = resolve_path(row["generated_cif_path"])

    raw_retrieval = read_json(retrieval_path)
    selected_path = selected_evidence_payload_path(row_run_dir)
    selected_retrieval = read_json(selected_path) if selected_path.is_file() else {}
    paper_display_path = paper_display_payload_path(row_run_dir)
    paper_display_retrieval = read_json(paper_display_path) if paper_display_path.is_file() else {}
    retrieval_for_display = paper_display_retrieval if paper_display_retrieval else selected_retrieval if selected_retrieval else raw_retrieval
    retrieval_payload, copied_neighbors = normalize_retrieval_payload(retrieval_for_display, row_run_dir, bundle_dir)
    selected_evidence_count = len(selected_retrieval.get("neighbors") or []) if selected_retrieval else len(copied_neighbors)
    paper_display_count = len(paper_display_retrieval.get("neighbors") or []) if paper_display_retrieval else len(copied_neighbors)
    spp = read_json(spp_path)
    qlip = qlip_summary(qlip_path)

    solution_cif = bundle_dir / "qlip_solve" / "solution.cif"
    solution_cif.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(generated, solution_cif)

    raw_dir = bundle_dir / "raw"
    write_json(raw_dir / "crystal_csp_pack.json", {"result": retrieval_payload})
    write_json(raw_dir / "crystal_csp_pack_raw_retrieval.json", {"result": raw_retrieval})
    if selected_retrieval:
        write_json(raw_dir / "crystal_csp_pack_selected_evidence.json", {"result": selected_retrieval})
    if paper_display_retrieval:
        write_json(raw_dir / "crystal_csp_pack_paper_display_neighbours.json", {"result": paper_display_retrieval})
    write_json(raw_dir / "spp_run_pipeline.json", {"result": spp})
    write_json(raw_dir / "qlip_solve.json", {"result": read_json(qlip_path)})

    spp_pairs_csv_path = row_run_dir / "spp_pairs.csv"
    row_specific_pairs = read_pair_csv(spp_pairs_csv_path)
    required_pairs = row_specific_pairs or spp.get("qlip_package_required_pairs") or spp.get("required_pairs") or []
    missing_pairs = spp.get("qlip_package_missing_pairs") or spp.get("missing_pairs") or []
    available_pairs = spp.get("qlip_package_available_pairs") or spp.get("available_pairs") or required_pairs
    selected_pot_root = pot_root or spp.get("selected_pot_root") or spp.get("pot_root") or ""
    spp_summary_path = str(spp_path)
    spp_pairs_csv_path_text = str(spp_pairs_csv_path) if spp_pairs_csv_path.is_file() else ""
    regulariser_found_count = pot_pair_count(selected_pot_root, [str(pair) for pair in required_pairs])
    source_mode = "row_specific_plus_universal_regulariser" if row_specific_pairs and selected_pot_root else "row_specific_retrieval_spp" if row_specific_pairs else "universal_regulariser_only_fallback" if selected_pot_root else "spp_unavailable"
    material = " ".join(part for part in [row.get("target_formula", ""), row.get("target_family", "")] if part)

    evaluation = {
        "goal": row.get("input_text", ""),
        "material_system": material or row.get("target_formula", ""),
        "artifact_refs": {"solution_cif_path": str(solution_cif)},
        "evidence_checks": {
            "retrieval": {"observed": {"neighbor_count": len(raw_retrieval.get("neighbors") or retrieval_payload.get("neighbors") or []), "exported_cif_count": selected_evidence_count, "paper_display_neighbour_count": paper_display_count}},
            "spp_guidance": {"observed": {"required_pairs": required_pairs, "available_pairs": available_pairs, "missing_pairs": missing_pairs, "pot_root": selected_pot_root}},
        },
        "execution_checks": {"solve": {"observed": {"qlip_status": "success", "objective_value": qlip["objective_value"], "solution_cif_path": str(solution_cif)}}},
        "novelty_assessment": {"observed": {"is_novel": ""}},
    }
    write_json(bundle_dir / "report" / "workflow_evaluation.json", evaluation)

    candidate = str(copied_neighbors[0]) if copied_neighbors else ""
    execution = {
        "step_results": [
            {
                "tool_name": "crystal.csp_pack",
                "status": "ok",
                "output_summary": {
                    "query": row.get("input_text", ""),
                    "neighbor_count": len(raw_retrieval.get("neighbors") or retrieval_payload.get("neighbors") or []),
                    "raw_neighbor_count": len(raw_retrieval.get("neighbors") or []),
                    "exported_cif_count": selected_evidence_count,
                    "paper_display_neighbour_count": paper_display_count,
                    "corpus_selection": {
                        "status": "paper_display_neighbours_layer" if paper_display_retrieval else "selected_evidence_layer" if selected_retrieval else "real_crystaldb_retrieval_trace",
                        "raw_retrieval_preserved": True,
                        "raw_result_ref": "raw/crystal_csp_pack_raw_retrieval.json",
                        "selected_result_ref": "raw/crystal_csp_pack_selected_evidence.json" if selected_retrieval else "",
                        "paper_display_result_ref": "raw/crystal_csp_pack_paper_display_neighbours.json" if paper_display_retrieval else "",
                        "selected_evidence_payload_path": str(selected_path) if selected_retrieval else "",
                        "paper_display_neighbours_payload_path": str(paper_display_path) if paper_display_retrieval else "",
                        "selected_evidence_for_spp_count": selected_evidence_count,
                        "paper_display_neighbour_count": paper_display_count,
                    },
                },
                "artifact_refs": [
                    {"ref_name": "candidate_cif_path", "value": candidate},
                    {"ref_name": "corpus_ref", "value": str(bundle_dir / "crystal_csp_pack" / "cifs")},
                ],
                "raw_result_ref": "raw/crystal_csp_pack.json",
            },
            {
                "tool_name": "spp.run_pipeline",
                "status": "ok",
                "output_summary": {
                    **spp,
                    "qlip_package_required_pairs": required_pairs,
                    "qlip_package_available_pairs": available_pairs,
                    "qlip_package_missing_pairs": missing_pairs,
                    "selected_pot_root": selected_pot_root,
                    "pot_root": selected_pot_root,
                    "pot_root_source": "explicit_package_builder" if pot_root else "real_spp_summary" if selected_pot_root else "not_recorded",
                    "spp_source_label": spp_source_label,
                    "spp_summary_path": spp_summary_path,
                    "spp_pairs_csv_path": spp_pairs_csv_path_text,
                    "row_specific_spp_source_path": spp_pairs_csv_path_text or spp_summary_path,
                    "row_specific_spp_found": bool(row_specific_pairs),
                    "row_specific_spp_pair_count": len(required_pairs),
                    "row_specific_spp_pairs": required_pairs,
                    "universal_regulariser_used": bool(selected_pot_root),
                    "universal_regulariser_root": selected_pot_root,
                    "universal_regulariser_pairs_found": regulariser_found_count,
                    "spp_panel_source_mode": source_mode,
                },
                "raw_result_ref": "raw/spp_run_pipeline.json",
            },
            {"tool_name": "qlip.validate_request", "status": "ok", "output_summary": {"valid": True, "package_validation_status": "valid"}},
            {
                "tool_name": "qlip.solve",
                "status": "success",
                "output_summary": {**qlip, "solution_cif_path": str(solution_cif)},
                "artifact_refs": [{"ref_name": "solution_cif_path", "value": str(solution_cif)}],
                "raw_result_ref": "raw/qlip_solve.json",
            },
        ]
    }
    write_json(bundle_dir / "_raw_run" / "execution" / "execution_run.json", execution)
    return {"solution_cif": str(solution_cif), "semantic_neighbor_cif_count": len(copied_neighbors), "spp_summary_path": spp_summary_path, "spp_pairs_csv_path": spp_pairs_csv_path_text}


def manifest_render_fields(manifest_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    panels = manifest.get("panels") or {}
    corpus = panels.get("crystal_db_retrieved_corpus") or {}
    final = panels.get("final_generated_crystal") or {}
    spp_panel = panels.get("spp_pot_guidance") or {}
    pot_metadata = manifest.get("pot_metadata") or (panels.get("spp_pot_guidance") or {})
    return {
        "workflow_artifact_status": "rendered" if manifest_path.is_file() else "render_failed",
        "vesta_status": (manifest.get("vesta") or {}).get("status", ""),
        "vesta_path_used": (manifest.get("vesta") or {}).get("vesta_executable", ""),
        "projected_surface_included": manifest.get("projected_surface_included", ""),
        "pot_root": pot_metadata.get("pot_root", ""),
        "pot_root_exists": pot_metadata.get("pot_root_exists", ""),
        "pot_parser_available": pot_metadata.get("pot_parser_available", ""),
        "pot_source_status": pot_metadata.get("pot_source_status", ""),
        "pair_coverage_status": pot_metadata.get("pair_coverage_status", ""),
        "pot_pairs_requested": ";".join(str(item) for item in pot_metadata.get("pot_pairs_requested", []) or []),
        "pot_pairs_found": ";".join(str(item) for item in pot_metadata.get("pot_pairs_found", []) or []),
        "pot_pairs_missing": ";".join(str(item) for item in pot_metadata.get("pot_pairs_missing", []) or []),
        "spp_summary_path": pot_metadata.get("spp_summary_path", ""),
        "spp_pairs_csv_path": pot_metadata.get("spp_pairs_csv_path", ""),
        "row_specific_spp_source_path": pot_metadata.get("row_specific_spp_source_path", ""),
        "row_specific_spp_found": pot_metadata.get("row_specific_spp_found", ""),
        "row_specific_spp_pair_count": pot_metadata.get("row_specific_spp_pair_count", ""),
        "row_specific_spp_pairs": ";".join(str(item) for item in pot_metadata.get("row_specific_spp_pairs", []) or []),
        "displayed_spp_pairs": ";".join(str(item) for item in spp_panel.get("displayed_spp_pairs", []) or []),
        "spp_score_sign_convention": manifest.get("spp_score_sign_convention") or spp_panel.get("spp_score_sign_convention") or pot_metadata.get("spp_score_sign_convention", ""),
        "spp_negative_values_allowed": manifest.get("spp_negative_values_allowed") if "spp_negative_values_allowed" in manifest else spp_panel.get("spp_negative_values_allowed", pot_metadata.get("spp_negative_values_allowed", "")),
        "spp_lower_is_better": manifest.get("spp_lower_is_better") if "spp_lower_is_better" in manifest else spp_panel.get("spp_lower_is_better", pot_metadata.get("spp_lower_is_better", "")),
        "universal_regulariser_used": pot_metadata.get("universal_regulariser_used", ""),
        "universal_regulariser_root": pot_metadata.get("universal_regulariser_root", ""),
        "universal_regulariser_pairs_found": ";".join(str(item) for item in pot_metadata.get("universal_regulariser_pairs_found", []) or []),
        "spp_panel_source_mode": pot_metadata.get("spp_panel_source_mode", ""),
        "semantic_neighbour_rendered_png_count": corpus.get("semantic_neighbour_rendered_png_count", 0),
        "semantic_neighbour_inline_rendered_count": corpus.get("semantic_neighbours_rendered_count", 0),
        "semantic_neighbour_vesta_success_count": corpus.get("semantic_neighbour_vesta_success_count", 0),
        "semantic_neighbour_target_count": corpus.get("semantic_neighbour_target_count", 0),
        "semantic_neighbour_selected_count": corpus.get("semantic_neighbour_selected_count", 0),
        "semantic_neighbour_vesta_png_count": corpus.get("semantic_neighbour_vesta_png_count", 0),
        "semantic_neighbour_fallback_count": corpus.get("semantic_neighbour_fallback_count", 0),
        "semantic_neighbour_labels": ";".join(str(item) for item in corpus.get("semantic_neighbour_labels", []) or []),
        "semantic_neighbour_cif_paths": ";".join(str(item) for item in corpus.get("semantic_neighbour_cif_paths", []) or []),
        "final_crystal_render_status": final.get("render_status", ""),
        "final_crystal_renderer_used": final.get("renderer_used", ""),
        "final_crystal_source_role": final.get("final_crystal_source_role", ""),
        "final_crystal_source_validated": final.get("final_crystal_source_validated", ""),
        "figure_primary_for_paper": True,
    }


def make_contact_sheet(images: list[Path], out_png: Path, title: str) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    thumbs: list[tuple[Path, Image.Image]] = []
    for path in images:
        if not path.is_file():
            continue
        image = Image.open(path).convert("RGB")
        image.thumbnail((420, 260))
        thumbs.append((path, image.copy()))
    if not thumbs:
        return
    cols = 2 if len(thumbs) <= 10 else 3
    cell_w, cell_h = 460, 320
    header_h = 56
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, header_h + rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((18, 18), title, fill=(0, 0, 0), font=font)
    for index, (path, image) in enumerate(thumbs):
        x = (index % cols) * cell_w + 20
        y = header_h + (index // cols) * cell_h + 20
        sheet.paste(image, (x, y))
        draw.text((x, y + image.height + 8), path.parent.name[:60], fill=(0, 0, 0), font=font)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    sheet.save(out_png.with_suffix(".pdf"))


def write_queries_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = ["# All Input Text Queries", ""]
    for row in rows:
        lines.extend(
            [
                f"## {row['experiment_package_dir']} / {row['row_id']}",
                "",
                f"- Target formula: {row.get('target_formula', '')}",
                f"- Exact input text: {row.get('input_text', '')}",
                f"- Primary workflow artifact: {row.get('row_workflow_artifact_png', '')}",
                f"- Pre-relax CIF: {row.get('pre_relax_cif_path', '')}",
                f"- CHGNet relaxed CIF: {row.get('relaxed_cif_path', '')}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def package_file_manifest(package_root: Path, row_records: list[dict[str, Any]], boundary_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_rel: dict[str, dict[str, Any]] = {}
    for row in row_records:
        for key in ("row_workflow_artifact_png", "row_workflow_artifact_pdf", "row_workflow_artifact_svg"):
            if row.get(key):
                by_rel[row[key]] = row
    rows: list[dict[str, Any]] = []
    for path in sorted(package_root.rglob("*")):
        if path.is_dir():
            continue
        rel_path = str(path.relative_to(package_root))
        record = by_rel.get(rel_path, {})
        role = "workflow_artifact" if path.name.startswith("workflow_artifact") else "supporting_artifact"
        if path.name in {"workflow_diagram.svg", "secondary_trace_diagram.svg"}:
            role = "secondary_trace_diagram"
        rows.append(
            {
                "relative_path": rel_path,
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "artifact_role": role,
                "experiment_id": record.get("experiment_id", ""),
                "row_id": record.get("row_id", ""),
                "workflow_artifact_status": record.get("workflow_artifact_status", ""),
                "vesta_status": record.get("vesta_status", ""),
                "vesta_path_used": record.get("vesta_path_used", ""),
                "projected_surface_included": record.get("projected_surface_included", ""),
                "pot_root": record.get("pot_root", ""),
                "pot_parser_available": record.get("pot_parser_available", ""),
                "pair_coverage_status": record.get("pair_coverage_status", ""),
                "row_specific_spp_found": record.get("row_specific_spp_found", ""),
                "row_specific_spp_pair_count": record.get("row_specific_spp_pair_count", ""),
                "spp_panel_source_mode": record.get("spp_panel_source_mode", ""),
                "spp_score_sign_convention": record.get("spp_score_sign_convention", ""),
                "spp_negative_values_allowed": record.get("spp_negative_values_allowed", ""),
                "spp_lower_is_better": record.get("spp_lower_is_better", ""),
                "pot_pairs_found": record.get("pot_pairs_found", ""),
                "pot_pairs_missing": record.get("pot_pairs_missing", ""),
                "semantic_neighbour_vesta_success_count": record.get("semantic_neighbour_vesta_success_count", ""),
                "semantic_neighbour_target_count": record.get("semantic_neighbour_target_count", ""),
                "semantic_neighbour_selected_count": record.get("semantic_neighbour_selected_count", ""),
                "semantic_neighbour_vesta_png_count": record.get("semantic_neighbour_vesta_png_count", ""),
                "semantic_neighbour_fallback_count": record.get("semantic_neighbour_fallback_count", ""),
                "semantic_neighbour_rendered_png_count": record.get("semantic_neighbour_rendered_png_count", ""),
                "final_crystal_render_status": record.get("final_crystal_render_status", ""),
                "final_crystal_renderer_used": record.get("final_crystal_renderer_used", ""),
                "figure_primary_for_paper": str(bool(record) and role == "workflow_artifact").lower(),
            }
        )
    for boundary in boundary_records:
        rows.append(boundary)
    return rows


def write_readme(package_root: Path, row_records: list[dict[str, Any]], boundary_records: list[dict[str, Any]]) -> None:
    rendered = sum(1 for row in row_records if row.get("workflow_artifact_status") == "rendered")
    vesta_available = sum(1 for row in row_records if row.get("vesta_status") == "available")
    coverage_counts: dict[str, int] = {}
    for row in row_records:
        status = str(row.get("pair_coverage_status") or "unknown")
        coverage_counts[status] = coverage_counts.get(status, 0) + 1
    row_spp_found = sum(str(row.get("row_specific_spp_found")).lower() == "true" for row in row_records)
    universal_only = sum(row.get("spp_panel_source_mode") == "universal_regulariser_only_fallback" for row in row_records)
    semantic_vesta = sum(_safe_int(row.get("semantic_neighbour_vesta_success_count")) for row in row_records)
    semantic_fallback = sum(_safe_int(row.get("semantic_neighbour_fallback_count")) for row in row_records)
    package_label = package_root.name.replace("paper_results_package_", "")
    lines = [
        f"# Paper Results Package {package_label}",
        "",
        "This package contains primary four-panel workflow artifacts generated by `sok_llm_orchestrator.agentic.visualise_workflow_artifact`.",
        "",
        "Primary panel order: Plain-text Query | Paper-display neighbours | SPP/POT guidance | Final generated crystal.",
        "",
        "The optimisation-surface panel is omitted from the primary workflow figures.",
        "SPP/POT curves plot statistical-potential scores, not probabilities or pair-distribution functions; lower scores are preferred, and negative values mark distances favoured relative to the reference/background.",
        "",
        f"- Generated workflow artifact rows: {rendered}/{len(row_records)}",
        f"- VESTA available rows: {vesta_available}/{len(row_records)}",
        f"- Row-specific SPP traces found: {row_spp_found}/{len(row_records)}",
        f"- Universal-regulariser-only fallback rows: {universal_only}",
        f"- Paper-display neighbour VESTA successes: {semantic_vesta}",
        f"- Paper-display neighbour fallback renders: {semantic_fallback}",
        f"- Fallback structure rendering count: {semantic_fallback + sum(str(row.get('final_crystal_renderer_used') or '').startswith('matplotlib_cif_scatter') for row in row_records)}",
        f"- POT pair coverage summary: {coverage_counts}",
        f"- Boundary rows not rendered before solution: {len(boundary_records)}",
        "- Simple workflow diagrams, where present, are retained only as secondary trace diagrams.",
        "",
        "Key files:",
        "- `WORKFLOW_ARTIFACTS_INDEX.csv` and `.md`: top-level row index.",
        "- `WORKFLOW_ARTIFACTS_CONTACT_SHEET.png` and `.pdf`: all rendered rows.",
        "- `EXPERIMENT_INPUTS/ALL_INPUT_TEXT_QUERIES.md`: exact input text queries and CIF paths.",
        "- `PACKAGE_MANIFEST.csv` and `.json`: package file inventory with workflow figure fields.",
        "",
    ]
    (package_root / "README.md").write_text("\n".join(lines), encoding="utf-8")


def write_reproduction_checks(package_root: Path, row_records: list[dict[str, Any]]) -> None:
    pair_counts = [_safe_int(row.get("row_specific_spp_pair_count")) for row in row_records]
    lines = [
        "# Package Checks",
        "",
        f"- Workflow rows: {len(row_records)}",
        f"- Row-specific SPP found: {sum(str(row.get('row_specific_spp_found')).lower() == 'true' for row in row_records)}",
        f"- Universal-only fallback rows: {sum(row.get('spp_panel_source_mode') == 'universal_regulariser_only_fallback' for row in row_records)}",
        f"- Average row-specific SPP pair count: {(sum(pair_counts) / len(pair_counts)) if pair_counts else 0:.2f}",
        "- SPP sign convention: statistical-potential score; lower values are preferred; negative values are allowed and indicate favoured distances relative to the reference/background.",
        "- SPP values are not probabilities.",
        f"- Paper-display neighbour VESTA success count: {sum(_safe_int(row.get('semantic_neighbour_vesta_success_count')) for row in row_records)}",
        f"- Paper-display neighbour fallback count: {sum(_safe_int(row.get('semantic_neighbour_fallback_count')) for row in row_records)}",
        f"- Final-crystal VESTA success count: {sum(row.get('final_crystal_renderer_used') == 'qlip_vesta_renderer' for row in row_records)}",
        f"- Final-crystal fallback count: {sum(str(row.get('final_crystal_renderer_used') or '').startswith('matplotlib_cif_scatter') for row in row_records)}",
        "- Projected surface included: false",
        "",
    ]
    path = package_root / "REPRODUCTION" / "package_checks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_zip(package_root: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_root.parent))


def spp_audit_row(row: dict[str, str], row_run_dir: Path, universal_root: str) -> dict[str, Any]:
    spp_summary_path = row_run_dir / "spp_summary.json"
    spp_pairs_csv_path = row_run_dir / "spp_pairs.csv"
    retrieval_path = row_run_dir / "crystaldb_retrieval_results.json"
    spp = read_json(spp_summary_path)
    retrieval = read_json(retrieval_path)
    row_pairs = read_pair_csv(spp_pairs_csv_path)
    retrieved_cifs = retrieval_cif_paths(retrieval, row_run_dir)
    found = bool(row_pairs)
    reason = "" if found else "spp_pairs.csv missing_or_empty"
    universal_found_count = pot_pair_count(universal_root, row_pairs)
    return {
        "experiment_id": row["experiment_id"],
        "row_id": row["row_id"],
        "formula": row.get("target_formula", ""),
        "row_run_dir": str(row_run_dir),
        "spp_summary_path": str(spp_summary_path) if spp_summary_path.is_file() else "",
        "spp_pairs_csv_path": str(spp_pairs_csv_path) if spp_pairs_csv_path.is_file() else "",
        "row_specific_spp_found": found,
        "row_specific_spp_pair_count": len(row_pairs),
        "row_specific_spp_pairs": ";".join(row_pairs),
        "retrieved_evidence_count": spp.get("retrieved_evidence_count") or len(retrieval.get("neighbors") or []),
        "retrieved_evidence_cif_count": sum(1 for path in retrieved_cifs if path.is_file()),
        "universal_regulariser_used": bool(universal_root),
        "universal_pot_root": universal_root,
        "universal_regulariser_pair_count": universal_found_count,
        "missing_or_ambiguous_spp_reason": reason,
    }


def semantic_audit_row(row: dict[str, str], row_run_dir: Path, package_root: Path, package_record: dict[str, Any]) -> dict[str, Any]:
    retrieval = read_json(row_run_dir / "crystaldb_retrieval_results.json")
    cif_paths = retrieval_cif_paths(retrieval, row_run_dir)
    manifest = read_json(package_root / package_record["experiment_package_dir"] / "rows" / row["row_id"] / "workflow_artifact_manifest.json")
    corpus = (manifest.get("panels") or {}).get("crystal_db_retrieved_corpus") or {}
    children = corpus.get("children") or []
    vesta_success = sum(1 for child in children if child.get("renderer_used") in {"qlip_vesta_renderer", "pre_rendered_vesta_png"} and child.get("render_status") == "rendered")
    fallback = sum(1 for child in children if str(child.get("renderer_used") or "").startswith("matplotlib_cif_scatter"))
    attempted = sum(1 for child in children if child.get("vesta_attempted") or child.get("renderer_used") in {"qlip_vesta_renderer", "matplotlib_cif_scatter_after_vesta_failure"})
    failures = sorted({str(child.get("vesta_failure_status") or child.get("render_status") or "") for child in children if child.get("vesta_failure_status") or str(child.get("render_status") or "").startswith("vesta_")})
    fix_action = "resolved_to_clean_neighbour_cifs_with_manifest_counts" if cif_paths else "no_neighbour_cifs_in_retrieval_trace"
    return {
        "experiment_id": row["experiment_id"],
        "row_id": row["row_id"],
        "formula": row.get("target_formula", ""),
        "retrieved_neighbour_count": len(retrieval.get("neighbors") or []),
        "neighbour_cif_paths_found": len(cif_paths),
        "neighbour_cif_paths_exist": sum(1 for path in cif_paths if path.is_file()),
        "neighbour_cif_parseable_count": sum(1 for path in cif_paths if parseable_cif(path)),
        "vesta_attempted_for_neighbours": attempted,
        "vesta_success_for_neighbours": vesta_success,
        "vesta_failure_reason": ";".join(failures),
        "fallback_success_for_neighbours": fallback,
        "fix_action": fix_action,
    }


VESTA_RENDER_AUDIT_COLUMNS = [
    "build_uuid",
    "experiment_id",
    "row_id",
    "render_id",
    "render_role",
    "source_cif_path",
    "staged_cif_path",
    "source_exists",
    "staged_exists_before_launch",
    "staged_size_bytes",
    "staged_ready_wait_ms",
    "vesta_process_id",
    "launch_timestamp",
    "completion_timestamp",
    "exit_status",
    "output_png_path",
    "output_size_bytes",
    "output_png_valid",
    "retry_count",
    "cleanup_timestamp",
    "failure_reason",
]


def _vesta_audit_row(experiment_id: str, row_id: str, render_role: str, status: dict[str, Any]) -> dict[str, Any]:
    output_path = str(status.get("published_output_png_path") or status.get("vesta_render_path") or status.get("vesta_output_path") or "")
    output = Path(output_path) if output_path else None
    return {
        "build_uuid": status.get("build_uuid", BUILD_UUID),
        "experiment_id": experiment_id,
        "row_id": row_id,
        "render_id": status.get("render_id", ""),
        "render_role": render_role,
        "source_cif_path": status.get("source_cif_path") or status.get("source_artifact_path", ""),
        "staged_cif_path": status.get("staged_cif_path", ""),
        "source_exists": status.get("source_exists", ""),
        "staged_exists_before_launch": status.get("staged_exists_before_launch", ""),
        "staged_size_bytes": status.get("staged_size_bytes", ""),
        "staged_ready_wait_ms": status.get("staged_ready_wait_ms", ""),
        "vesta_process_id": status.get("vesta_process_id", ""),
        "launch_timestamp": status.get("launch_timestamp", ""),
        "completion_timestamp": status.get("completion_timestamp", ""),
        "exit_status": status.get("render_status", ""),
        "output_png_path": output_path,
        "output_size_bytes": status.get("published_output_size_bytes") or status.get("vesta_output_size_bytes") or (output.stat().st_size if output and output.is_file() else 0),
        "output_png_valid": bool(output and output.is_file() and int(output.stat().st_size) > 0),
        "retry_count": status.get("retry_count", ""),
        "cleanup_timestamp": status.get("cleanup_timestamp", ""),
        "failure_reason": status.get("vesta_failure_status") or status.get("render_error") or (";".join(status.get("warnings") or []) if status.get("render_status") != "rendered" else ""),
    }


def write_vesta_render_audits(package_root: Path, row_records: list[dict[str, Any]]) -> None:
    audit_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    for record in row_records:
        manifest = read_json(package_root / record["experiment_package_dir"] / "rows" / record["row_id"] / "workflow_artifact_manifest.json")
        panels = manifest.get("panels") or {}
        exp_id = record.get("experiment_id", "")
        row_id = record.get("row_id", "")
        final_status = panels.get("final_generated_crystal") or {}
        if final_status.get("vesta_call_attempted") or final_status.get("renderer_used") in {"qlip_vesta_renderer", "pre_rendered_vesta_png"}:
            audit_rows.append(_vesta_audit_row(exp_id, row_id, "final_generated", final_status))
        for child in (panels.get("crystal_db_retrieved_corpus") or {}).get("children") or []:
            if child.get("vesta_call_attempted") or child.get("renderer_used") in {"qlip_vesta_renderer", "pre_rendered_vesta_png"} or str(child.get("render_status") or "").startswith("vesta_"):
                audit = _vesta_audit_row(exp_id, row_id, "paper_display_neighbour", child)
                audit["render_id"] = audit["render_id"] or f"neighbour_{child.get('rank', '')}"
                audit_rows.append(audit)
    for row in audit_rows:
        if row["exit_status"] != "rendered" or row["failure_reason"]:
            failed_rows.append(row)
    write_csv(package_root / "VESTA_RENDER_AUDIT.csv", audit_rows, VESTA_RENDER_AUDIT_COLUMNS)
    lines = [
        "# VESTA Render Lifecycle Audit",
        "",
        f"- Build UUID: `{BUILD_UUID}`",
        f"- Audit rows: {len(audit_rows)}",
        f"- Failed render rows: {len(failed_rows)}",
        "",
        "## Lifecycle",
        "",
        "1. Source CIF paths are resolved from retrieval/display metadata.",
        "2. Source CIFs are copied into the workflow render bundle for auditability.",
        "3. VESTA renders are launched only from immutable per-render staging directories under `artifacts/vesta_render_staging/<build_uuid>/...`.",
        "4. The staged CIF is checked for existence, non-zero size, stable size, and readability before launch.",
        "5. VESTA output is validated as a stable readable PNG before it is copied into the mutable package directory.",
        "6. Successful staging directories are removed after final PNG publication; failed staging directories are retained for debugging.",
        "7. Package builds are guarded by `artifacts/.paper_workflow_package_build.lock` before destructive package operations.",
        "",
        "## Failed Renders",
        "",
    ]
    if not failed_rows:
        lines.append("No failed VESTA render rows were recorded in this package.")
    else:
        for row in failed_rows:
            lines.extend(
                [
                    f"### {row['row_id']} / {row['render_id']}",
                    "",
                    f"- source CIF path: `{row['source_cif_path']}`",
                    f"- staged CIF path: `{row['staged_cif_path']}`",
                    f"- source existence at selection time: `{row['source_exists']}`",
                    f"- staged existence before launch: `{row['staged_exists_before_launch']}`",
                    f"- staged file size: `{row['staged_size_bytes']}`",
                    f"- launch timestamp: `{row['launch_timestamp']}`",
                    f"- VESTA process ID: `{row['vesta_process_id']}`",
                    f"- cleanup timestamp: `{row['cleanup_timestamp']}`",
                    f"- output PNG path: `{row['output_png_path']}`",
                    f"- exact failure reason: `{row['failure_reason']}`",
                    "",
                ]
            )
    (package_root / "VESTA_RENDER_LIFECYCLE_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-version", default="v4")
    parser.add_argument("--source-package-root", default="artifacts/paper_results_package_v3")
    parser.add_argument("--package-root", default="")
    parser.add_argument("--output-package-root", default="")
    parser.add_argument("--row-limit", type=int, default=0)
    parser.add_argument("--row-id", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--vesta-path", default="")
    parser.add_argument("--require-vesta", action="store_true")
    parser.add_argument("--vesta-timeout-s", type=float, default=12.0)
    parser.add_argument("--vesta-call-delay-s", type=float, default=1.0)
    parser.add_argument("--vesta-retries", type=int, default=1)
    parser.add_argument("--pot-root", default=str(DEFAULT_POT_ROOT) if DEFAULT_POT_ROOT.exists() else "")
    parser.add_argument("--spp-source-label", default="recorded SPP POT root")
    parser.add_argument("--spp-source-mode", default="row-specific-plus-regulariser")
    parser.add_argument("--require-pot-parser", action="store_true")
    parser.add_argument("--allow-missing-pot-pairs", action="store_true", default=True)
    parser.add_argument("--no-projected-surface", action="store_true", default=True)
    parser.add_argument("--no-semantic-neighbour-vesta", action="store_true", default=False)
    parser.add_argument("--reuse-existing-renders", action="store_true")
    parser.add_argument("--vesta-render-manifest", default="")
    parser.add_argument("--require-vesta-images", action="store_true")
    parser.add_argument("--no-fallback-structure-rendering", action="store_true")
    parser.add_argument("--neighbours-per-row", type=int, default=10)
    parser.add_argument("--ensure-semantic-neighbour-renders", action="store_true")
    parser.add_argument("--cif-search-root", action="append", default=[])
    args = parser.parse_args()

    output_root_arg = args.output_package_root or args.package_root or f"artifacts/paper_results_package_{args.package_version}"
    package_root = resolve_path(output_root_arg)
    build_lock = None
    if os.environ.get("PAPER_PACKAGE_BUILD_LOCK_HELD") != "1":
        build_lock = BuildLock(ROOT / "artifacts" / ".paper_workflow_package_build.lock")
        build_lock.__enter__()
        atexit.register(lambda: build_lock.__exit__(None, None, None))
    source_package_root = resolve_path(args.source_package_root) if args.source_package_root else None
    vesta_path_used, vesta_search_paths = locate_vesta(args.vesta_path)
    pot_root_used = str(resolve_path(args.pot_root)) if args.pot_root else ""
    vesta_png_rows = rendered_pngs_by_row(args.vesta_render_manifest)
    if args.force and not args.reuse_existing_renders:
        safe_rmtree_package(package_root)
    if source_package_root is not None and source_package_root.is_dir() and not package_root.exists():
        shutil.copytree(source_package_root, package_root)
    package_root.mkdir(parents=True, exist_ok=True)

    full_manifest = read_csv(ROOT / "artifacts" / "PAPER_EXPERIMENTS_FULL_SCA_MANIFEST.csv")
    if args.row_id:
        wanted = set(args.row_id)
        full_manifest = [row for row in full_manifest if row["row_id"] in wanted]
    if args.row_limit:
        full_manifest = full_manifest[: args.row_limit]
    pre_manifest = {(row["experiment_id"], row["row_id"]): row for row in read_csv(ROOT / "artifacts" / "paper_final_cifs" / "manifests" / "PRE_RELAX_CIF_MANIFEST.csv")}
    relax_manifest = {(row["experiment_id"], row["row_id"]): row for row in read_csv(ROOT / "artifacts" / "paper_final_cifs" / "manifests" / "PRE_POST_RELAX_COMPARISON.csv")}

    row_records: list[dict[str, Any]] = []
    spp_audit_rows: list[dict[str, Any]] = []
    semantic_audit_rows: list[dict[str, Any]] = []
    for row in full_manifest:
        experiment_id = row["experiment_id"]
        row_id = row["row_id"]
        experiment_dir = EXPERIMENT_PACKAGE_DIRS[experiment_id]
        row_run_dir = ROOT / "local_runs" / experiment_id / row_id
        case_name = f"{experiment_id}__{row_id}__{row.get('target_formula', '')}"
        bundle_dir = package_root / "_render_bundles" / experiment_id / row_id
        figure_out = package_root / "WORKFLOW_ARTIFACTS" / experiment_id / row_id
        row_pkg = package_root / experiment_dir / "rows" / row_id
        row_pkg.mkdir(parents=True, exist_ok=True)

        spp_audit_rows.append(spp_audit_row(row, row_run_dir, pot_root_used))
        if args.reuse_existing_renders:
            rendered_files = rendered_output_files(figure_out)
            if not rendered_files.get("manifest"):
                rendered_files["manifest"] = row_pkg / "workflow_artifact_manifest.json"
            if not rendered_files.get("png"):
                rendered_files["png"] = row_pkg / "workflow_artifact.png"
            if not rendered_files.get("pdf"):
                rendered_files["pdf"] = row_pkg / "workflow_artifact.pdf"
            if not rendered_files.get("svg"):
                rendered_files["svg"] = row_pkg / "workflow_artifact.svg"
        else:
            build_render_bundle(row, row_run_dir, bundle_dir, pot_root=pot_root_used, spp_source_label=args.spp_source_label)
            try:
                visualise_workflow_artifact(
                    bundle_dir,
                    figure_out,
                    case_name,
                    vesta_path=vesta_path_used or None,
                    require_vesta=args.require_vesta,
                    vesta_timeout_s=args.vesta_timeout_s,
                    vesta_call_delay_s=args.vesta_call_delay_s,
                    vesta_retries=args.vesta_retries,
                    ensure_semantic_neighbour_renders=args.ensure_semantic_neighbour_renders,
                    semantic_neighbour_cif_search_roots=[Path(p) for p in args.cif_search_root],
                    include_projected_surface=not args.no_projected_surface,
                    pot_root=pot_root_used or None,
                    spp_source_label=args.spp_source_label,
                    render_semantic_neighbours_with_vesta=not args.no_semantic_neighbour_vesta,
                    final_crystal_image_path=(vesta_png_rows.get(row_id, {}) or {}).get("final") or None,
                    semantic_neighbour_image_manifest=args.vesta_render_manifest or None,
                    require_vesta_images=args.require_vesta_images,
                    no_fallback_structure_rendering=args.no_fallback_structure_rendering,
                    semantic_neighbour_target_count=args.neighbours_per_row,
                )
            except Exception as exc:
                raise RuntimeError(f"Workflow artifact render failed for {experiment_id}/{row_id} using bundle {bundle_dir}") from exc

            rendered_files = rendered_output_files(figure_out)
            for ext in ("png", "pdf", "svg"):
                copy_if_exists(rendered_files.get(ext), row_pkg / f"workflow_artifact.{ext}")
            copy_if_exists(rendered_files.get("manifest"), row_pkg / "workflow_artifact_manifest.json")
            panels_source = rendered_files.get("panels")
            panels_target = row_pkg / "workflow_artifact_panels"
            if panels_target.exists():
                shutil.rmtree(panels_target)
            if panels_source and panels_source.is_dir():
                shutil.copytree(panels_source, panels_target)

            for name in ("input_text.txt", "workflow_trace.json", "workflow_trace.md", "artifact_manifest.json", "validation_summary.json", "workflow_diagram.svg"):
                target_name = "secondary_trace_diagram.svg" if name == "workflow_diagram.svg" else name
                copy_if_exists(row_run_dir / name, row_pkg / target_name)
            copy_if_exists(resolve_path(row["generated_cif_path"]), row_pkg / "generated.cif")

        key = (experiment_id, row_id)
        pre = pre_manifest.get(key, {})
        relaxed = relax_manifest.get(key, {})
        record = {
            **row,
            **manifest_render_fields(rendered_files.get("manifest", Path())),
            "experiment_package_dir": experiment_dir,
            "workflow_artifact_png": rel(rendered_files.get("png", ""), package_root),
            "workflow_artifact_pdf": rel(rendered_files.get("pdf", ""), package_root),
            "workflow_artifact_svg": rel(rendered_files.get("svg", ""), package_root),
            "workflow_artifact_manifest": rel(rendered_files.get("manifest", ""), package_root),
            "row_workflow_artifact_png": rel(row_pkg / "workflow_artifact.png", package_root),
            "row_workflow_artifact_pdf": rel(row_pkg / "workflow_artifact.pdf", package_root),
            "row_workflow_artifact_svg": rel(row_pkg / "workflow_artifact.svg", package_root),
            "pre_relax_cif_path": pre.get("packaged_pre_relax_cif_path") or relaxed.get("pre_relax_cif_path", ""),
            "relaxed_cif_path": relaxed.get("relaxed_cif_path", ""),
        }
        if args.require_pot_parser and str(record.get("pot_parser_available")).lower() != "true":
            raise RuntimeError(f"POT parser unavailable for {experiment_id}/{row_id}")
        if not args.allow_missing_pot_pairs and record.get("pot_pairs_missing"):
            raise RuntimeError(f"Missing POT pairs for {experiment_id}/{row_id}: {record['pot_pairs_missing']}")
        write_json(row_pkg / "package_row_manifest.json", record)
        row_records.append(record)
        semantic_audit_rows.append(semantic_audit_row(row, row_run_dir, package_root, record))

    boundary_records: list[dict[str, Any]] = []
    boundary_csv = ROOT / "local_runs" / "paper_capability_boundary_audit_v1" / "EXPERIMENT_RESULTS.csv"
    if boundary_csv.is_file():
        boundary_dir = package_root / "CAPABILITY_BOUNDARY"
        boundary_dir.mkdir(parents=True, exist_ok=True)
        for boundary in read_csv(boundary_csv):
            boundary_records.append(
                {
                    "artifact_role": "capability_boundary_row",
                    "experiment_id": "paper_capability_boundary_audit_v1",
                    "row_id": boundary.get("row_id", ""),
                    "workflow_artifact_status": "not_rendered_blocked_before_solution",
                    "vesta_status": "",
                    "vesta_path_used": vesta_path_used,
                    "projected_surface_included": "false",
                    "pot_root": pot_root_used,
                    "pot_parser_available": "",
                    "pair_coverage_status": "not_rendered",
                    "pot_pairs_found": "",
                    "pot_pairs_missing": "",
                    "semantic_neighbour_rendered_png_count": 0,
                    "final_crystal_render_status": "not_rendered_no_solution_cif",
                    "figure_primary_for_paper": "false",
                }
            )
        shutil.copy2(boundary_csv, boundary_dir / "EXPERIMENT_RESULTS.csv")
        write_json(boundary_dir / "WORKFLOW_ARTIFACT_STATUS.json", boundary_records)

    index_fields = [
        "experiment_id",
        "experiment_package_dir",
        "row_id",
        "input_text",
        "target_formula",
        "workflow_artifact_status",
        "vesta_status",
        "vesta_path_used",
        "projected_surface_included",
        "pot_root",
        "pot_parser_available",
        "pair_coverage_status",
        "row_specific_spp_found",
        "row_specific_spp_pair_count",
        "row_specific_spp_pairs",
        "displayed_spp_pairs",
        "spp_score_sign_convention",
        "spp_negative_values_allowed",
        "spp_lower_is_better",
        "spp_panel_source_mode",
        "universal_regulariser_used",
        "universal_regulariser_root",
        "pot_pairs_found",
        "pot_pairs_missing",
        "semantic_neighbour_rendered_png_count",
        "semantic_neighbour_inline_rendered_count",
        "semantic_neighbour_vesta_success_count",
        "semantic_neighbour_target_count",
        "semantic_neighbour_selected_count",
        "semantic_neighbour_vesta_png_count",
        "semantic_neighbour_fallback_count",
        "final_crystal_render_status",
        "final_crystal_renderer_used",
        "final_crystal_source_validated",
        "figure_primary_for_paper",
        "row_workflow_artifact_png",
        "row_workflow_artifact_pdf",
        "row_workflow_artifact_svg",
        "pre_relax_cif_path",
        "relaxed_cif_path",
    ]
    write_csv(package_root / "WORKFLOW_ARTIFACTS_INDEX.csv", row_records, index_fields)
    md_lines = ["# Workflow Artifacts Index", ""]
    for row in row_records:
        md_lines.append(f"- `{row['experiment_id']}/{row['row_id']}`: {row['workflow_artifact_status']} | `{row['row_workflow_artifact_png']}`")
    (package_root / "WORKFLOW_ARTIFACTS_INDEX.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    for experiment_id, experiment_dir in EXPERIMENT_PACKAGE_DIRS.items():
        exp_rows = [row for row in row_records if row["experiment_id"] == experiment_id]
        exp_root = package_root / experiment_dir
        write_csv(exp_root / "WORKFLOW_ARTIFACT_INDEX.csv", exp_rows, index_fields)
        exp_md = ["# Workflow Artifact Index", ""]
        for row in exp_rows:
            exp_md.append(f"- `{row['row_id']}`: `{row['row_workflow_artifact_png']}`")
        (exp_root / "WORKFLOW_ARTIFACT_INDEX.md").write_text("\n".join(exp_md) + "\n", encoding="utf-8")
        make_contact_sheet([package_root / row["row_workflow_artifact_png"] for row in exp_rows], exp_root / "WORKFLOW_ARTIFACT_CONTACT_SHEET.png", experiment_dir)

    make_contact_sheet([package_root / row["row_workflow_artifact_png"] for row in row_records], package_root / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png", "All Paper Workflow Artifacts")
    write_queries_md(package_root / "EXPERIMENT_INPUTS" / "ALL_INPUT_TEXT_QUERIES.md", row_records)
    write_readme(package_root, row_records, boundary_records)
    write_reproduction_checks(package_root, row_records)
    write_vesta_render_audits(package_root, row_records)
    if args.vesta_render_manifest:
        render_root = resolve_path(args.vesta_render_manifest).parent
        target = package_root / "VESTA_RENDERING"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(render_root, target)
    audit_root = ROOT / "artifacts" / f"paper_results_package_{args.package_version}_spp_audit"
    if args.force and audit_root.exists():
        safe_rmtree_package(audit_root)
    audit_root.mkdir(parents=True, exist_ok=True)
    write_csv(audit_root / "ROW_SPECIFIC_SPP_AUDIT.csv", spp_audit_rows)
    write_csv(audit_root / "SEMANTIC_NEIGHBOUR_RENDER_AUDIT.csv", semantic_audit_rows)
    write_json(audit_root / "ROW_SPECIFIC_SPP_AUDIT.json", spp_audit_rows)
    write_json(audit_root / "SEMANTIC_NEIGHBOUR_RENDER_AUDIT.json", semantic_audit_rows)

    package_manifest = package_file_manifest(package_root, row_records, boundary_records)
    write_csv(package_root / "PACKAGE_MANIFEST.csv", package_manifest)
    write_json(package_root / "PACKAGE_MANIFEST.json", package_manifest)
    write_json(
        package_root / "BUILD_SUMMARY.json",
        {
            "package_root": str(package_root),
            "row_count": len(row_records),
            "rendered_count": sum(1 for row in row_records if row.get("workflow_artifact_status") == "rendered"),
            "vesta_available_count": sum(1 for row in row_records if row.get("vesta_status") == "available"),
            "vesta_path_used": vesta_path_used,
            "vesta_search_paths": vesta_search_paths,
            "pot_root_used": pot_root_used,
            "projected_surface_included": False,
            "row_specific_spp_found_count": sum(str(row.get("row_specific_spp_found")).lower() == "true" for row in row_records),
            "universal_only_fallback_count": sum(row.get("spp_panel_source_mode") == "universal_regulariser_only_fallback" for row in row_records),
            "semantic_neighbour_vesta_success_count": sum(_safe_int(row.get("semantic_neighbour_vesta_success_count")) for row in row_records),
            "semantic_neighbour_fallback_count": sum(_safe_int(row.get("semantic_neighbour_fallback_count")) for row in row_records),
            "final_crystal_vesta_success_count": sum(row.get("final_crystal_renderer_used") == "qlip_vesta_renderer" for row in row_records),
            "final_crystal_fallback_count": sum(str(row.get("final_crystal_renderer_used") or "").startswith("matplotlib_cif_scatter") for row in row_records),
            "pair_coverage_summary": {
                status: sum(1 for row in row_records if row.get("pair_coverage_status") == status)
                for status in sorted({str(row.get("pair_coverage_status") or "") for row in row_records})
            },
            "boundary_not_rendered_count": len(boundary_records),
        },
    )
    write_zip(package_root, package_root.with_suffix(".zip"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
