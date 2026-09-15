"""Run the 100-query challenge suite and build paper evidence pack v2.

The runner is intentionally descriptive. It records workflow evidence produced by
the existing agentic CSP demo/smoke-suite path and does not invent missing CIFs,
POT roots, QLIP success, or final-crystal renderings.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


REQUIRED_COLUMNS = [
    "case_id",
    "short_name",
    "target_formula",
    "query",
    "chemistry_family",
    "challenge_type",
    "expected_motifs_or_priors",
    "difficulty_notes",
    "intent_specificity",
    "benchmark_split",
]

MANIFEST_COLUMNS = [
    "case_id",
    "short_name",
    "target_formula",
    "query",
    "chemistry_family",
    "challenge_type",
    "intent_specificity",
    "benchmark_split",
    "case_dir",
    "status",
    "failure_category",
    "failure_message",
    "semantic_neighbour_count",
    "exported_cif_count",
    "spp_exported_subset_count",
    "selected_pot_root",
    "selected_pot_root_kind",
    "fresh_spp_quality",
    "used_fallback_pots",
    "qlip_request_path",
    "qlip_validation_status",
    "qlip_solve_status",
    "qlip_objective",
    "solution_cif_path",
    "solution_cif_produced",
    "workflow_png_path",
    "workflow_svg_path",
    "workflow_pdf_path",
    "visualisation_manifest_path",
    "final_doc_images_count",
    "runtime_seconds",
    "support_classification",
    "missing_pairs",
    "exportable_pair_support_counts",
    "exact_formula_count",
    "same_chemsys_count",
    "recommendation",
    "qlip_request_attempted",
    "qlip_request_blocked_stage",
    "qlip_request_blocked_reason",
    "upstream_failure_category",
    "upstream_failure_subcategory",
    "crystal_db_retrieval_query",
    "query_style",
    "query_skill_version",
    "generated_cif_robocrys_available",
    "generated_cif_robocrys_description_path",
    "generated_cif_robocrys_metadata_path",
    "generated_cif_robocrys_condensed_path",
    "generated_cif_robocrys_error",
    "generated_cif_robocrys_warning_count",
    "robocrys_intent_validation_available",
    "robocrys_intent_alignment_score",
    "robocrys_intent_judgement",
    "robocrys_intent_validation_path",
    "robocrys_intent_skip_reason",
    "spp_objective_audit_path",
    "spp_objective_audit_available",
    "spp_objective_audit_error",
]

FINAL_DOC_IMAGE_COLUMNS = [
    "image_id",
    "case_id",
    "short_name",
    "image_type",
    "source_path",
    "copied_path",
    "exists",
    "file_size_bytes",
    "notes",
]

ROBOCRYS_SIDECAR_COLUMNS = [
    "case_id",
    "short_name",
    "target_formula",
    "solution_cif_path",
    "robocrys_available",
    "description_path",
    "metadata_path",
    "condensed_path",
    "error",
    "warning_count",
]

ROBOCRYS_INTENT_VALIDATION_COLUMNS = [
    "case_id",
    "short_name",
    "target_formula",
    "available",
    "alignment_score",
    "judgement",
    "skip_reason",
    "validation_path",
    "validation_markdown_path",
]

ROBOCRYS_INTENT_EXAMPLE_COLUMNS = [
    "case_id",
    "short_name",
    "target_formula",
    "chemistry_family",
    "challenge_type",
    "original_query",
    "crystal_db_retrieval_query",
    "compact_retrieval_query",
    "pair_evidence_query",
    "final_cif_path",
    "generated_cif_robocrys_description_path",
    "generated_cif_robocrys_description",
    "generated_cif_robocrys_condensed_path",
    "qlip_guidance_mode",
    "status",
    "notes",
]

SPP_OBJECTIVE_AUDIT_COLUMNS = [
    "case_id",
    "short_name",
    "target_formula",
    "status",
    "failure_category",
    "available",
    "audit_path",
    "error",
    "qlip_objective",
    "guidance_weight",
    "cutoff",
    "missing_pair_policy",
    "regularisation_spp_dir",
    "regularisation_weight",
    "regularisation_enabled",
    "regularisation_pairs_loaded",
    "regularisation_contribution_count",
    "total_spp_score",
    "weighted_total_score",
    "shortest_contact",
    "explicit_spp_contribution_count",
    "missing_pair_fallback_contribution_count",
    "no_contribution_count",
    "supported_pair_type_count",
    "missing_pair_type_count",
]

FAILURE_CATEGORIES = {
    "success",
    "input_validation_failed",
    "workflow_command_failed",
    "retrieval_failed",
    "insufficient_semantic_neighbours",
    "insufficient_exportable_cifs",
    "spp_generation_failed",
    "spp_quality_diagnostic_only",
    "spp_fallback_selected",
    "qlip_request_missing",
    "qlip_request_blocked_by_corpus_selection",
    "qlip_request_blocked_by_spp_generation",
    "qlip_request_blocked_by_missing_required_guidance",
    "qlip_request_blocked_by_unsupported_formula",
    "qlip_request_builder_error",
    "qlip_request_not_attempted_due_previous_stage",
    "qlip_request_blocked_by_backend_requires_pots",
    "qlip_validation_failed",
    "qlip_solve_failed",
    "gurobi_license_error",
    "final_cif_missing",
    "visualisation_failed",
    "unknown_failure",
    "robocrys_unavailable",
    "robocrys_intent_validation_unavailable",
}


def _load_build_workflow_case_figure() -> Any:
    module_path = REPO_ROOT / "scripts" / "build_workflow_case_figure.py"
    spec = importlib.util.spec_from_file_location("paper_pack_build_workflow_case_figure", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load workflow case figure helper from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_workflow_case_figure


def _load_visualise_workflow_artifact() -> Any:
    from sok_llm_orchestrator.agentic.visualise_workflow_artifact import visualise_workflow_artifact

    return visualise_workflow_artifact


def _load_run_paper_smoke_suite() -> Any:
    from sok_llm_orchestrator.agentic.paper_smoke_suite import run_paper_smoke_suite

    return run_paper_smoke_suite


def _rel(path: str | Path | None) -> str:
    if not path:
        return ""
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(REPO_ROOT.resolve()))
    except (OSError, ValueError):
        return str(candidate)


def _case_dir_manifest_value(case_dir: Path, out_root: Path | None = None) -> str:
    if out_root is not None:
        try:
            return str(case_dir.resolve().relative_to(out_root.resolve()))
        except (OSError, ValueError):
            pass
    return _rel(case_dir)


def _read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.exists():
        return {}
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _qlip_audit_module() -> Any | None:
    qlip_root = REPO_ROOT.parent / "qlip"
    audit_path = qlip_root / "tools" / "audit_spp_objective.py"
    if not audit_path.exists():
        return None
    if str(qlip_root) not in sys.path:
        sys.path.insert(0, str(qlip_root))
    if str(qlip_root / "src") not in sys.path:
        sys.path.insert(0, str(qlip_root / "src"))
    spec = importlib.util.spec_from_file_location("qlip_audit_spp_objective", audit_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spp_guidance_from_request(request: Mapping[str, Any]) -> tuple[dict[str, Any], float]:
    guidance = request.get("guidance") if isinstance(request.get("guidance"), list) else []
    for item in guidance:
        if not isinstance(item, Mapping):
            continue
        if item.get("id") == "objective.energy_spp" and item.get("enabled", True):
            params = item.get("params") if isinstance(item.get("params"), Mapping) else {}
            try:
                weight = float(item.get("weight", 1.0))
            except (TypeError, ValueError):
                weight = 1.0
            return dict(params), weight
    return {}, 1.0


def _write_spp_objective_audit_sidecar(
    case_dir: Path,
    *,
    qlip_request_path: str,
    solution_cif_path: str,
    qlip_objective: Any,
) -> dict[str, Any]:
    out_dir = case_dir / "qlip"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "qlip_spp_objective_audit.json"
    out_md = out_dir / "qlip_spp_objective_audit.md"
    request = _read_json(qlip_request_path)
    params, weight = _spp_guidance_from_request(request)
    context = request.get("context") if isinstance(request.get("context"), Mapping) else {}
    pot_root = str(params.get("pot_root") or context.get("pot_root") or "")
    cutoff = params.get("cutoff", params.get("spp_cutoff", 11.0))
    try:
        cutoff = float(cutoff)
    except (TypeError, ValueError):
        cutoff = 11.0
    missing_pair_policy = str(params.get("missing_pair_policy") or "block")
    regularisation_spp_dir = str(
        params.get("regularisation_spp_dir")
        or params.get("regularization_spp_dir")
        or ""
    )
    try:
        regularisation_weight = float(
            params.get("regularisation_weight", params.get("regularization_weight", 0.0)) or 0.0
        )
    except (TypeError, ValueError):
        regularisation_weight = 0.0
    base_payload = {
        "available": False,
        "qlip_request_path": _rel(qlip_request_path),
        "solution_cif_path": _rel(solution_cif_path),
        "qlip_objective": qlip_objective,
        "guidance_params_sent": params,
        "guidance_weight": weight,
        "pot_root": pot_root,
        "cutoff": cutoff,
        "missing_pair_policy": missing_pair_policy,
        "regularisation_spp_dir": regularisation_spp_dir,
        "regularisation_weight": regularisation_weight,
        "error": "",
        "note": "SPP objective audit is diagnostic only and is not physical validation.",
    }
    if not qlip_request_path or not solution_cif_path:
        base_payload["error"] = "missing_request_or_solution_cif"
        _write_json(out_json, base_payload)
        out_md.write_text("# SPP Objective Audit\n\nUnavailable: missing request or solution CIF.\n", encoding="utf-8")
        return {
            "spp_objective_audit_path": _rel(out_json),
            "spp_objective_audit_available": False,
            "spp_objective_audit_error": base_payload["error"],
        }
    if not pot_root:
        base_payload["error"] = "pot_root_missing"
        _write_json(out_json, base_payload)
        out_md.write_text("# SPP Objective Audit\n\nUnavailable: no POT root was sent in QLIP guidance/context.\n", encoding="utf-8")
        return {
            "spp_objective_audit_path": _rel(out_json),
            "spp_objective_audit_available": False,
            "spp_objective_audit_error": base_payload["error"],
        }
    try:
        module = _qlip_audit_module()
        if module is None:
            raise RuntimeError("qlip audit_spp_objective.py not found")
        payload = module.audit(
            Path(solution_cif_path),
            Path(pot_root),
            cutoff=cutoff,
            missing_pair_policy=missing_pair_policy,
            guidance_weight=weight,
            regularisation_spp_dir=Path(regularisation_spp_dir) if regularisation_spp_dir else None,
            regularisation_weight=regularisation_weight,
            top_k=10,
        )
        payload["summary"]["qlip_objective"] = qlip_objective
        payload["summary"]["guidance_params_sent"] = params
        module.write_outputs(payload, out_json, out_dir / "qlip_spp_objective_audit.csv", out_md)
        return {
            "spp_objective_audit_path": _rel(out_json),
            "spp_objective_audit_available": True,
            "spp_objective_audit_error": "",
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic sidecar should not change workflow status
        base_payload["error"] = f"{type(exc).__name__}: {exc}"
        _write_json(out_json, base_payload)
        out_md.write_text(
            "# SPP Objective Audit\n\n"
            f"Unavailable: `{base_payload['error']}`\n\n"
            "The workflow result was not changed by this diagnostic failure.\n",
            encoding="utf-8",
        )
        return {
            "spp_objective_audit_path": _rel(out_json),
            "spp_objective_audit_available": False,
            "spp_objective_audit_error": base_payload["error"],
        }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column, "")) for column in columns})


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _safe_slug(value: str) -> str:
    slug = "".join(ch.lower() for ch in value if ch.isalnum() or ch in {"_", "-"})
    return slug or "case"


def _case_run_id(row: Mapping[str, Any]) -> str:
    return f"{_safe_slug(str(row.get('case_id', 'case')))}_{_safe_slug(str(row.get('short_name', 'run')))}"


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _mapping_list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _step(execution: Mapping[str, Any], tool_name: str) -> dict[str, Any]:
    for item in _mapping_list(execution, "step_results"):
        if item.get("tool_name") == tool_name:
            return item
    return {}


def _artifact_ref(step: Mapping[str, Any], ref_name: str) -> str:
    for item in _mapping_list(step, "artifact_refs"):
        if item.get("ref_name") == ref_name:
            return str(item.get("value") or "")
    return ""


def _nested(payload: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return default if current is None else current


def _resolve_path(path_text: str, suite_dir: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    direct = REPO_ROOT / path
    if direct.exists():
        return direct
    return suite_dir / path


def _load_csv(csv_path: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[str]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing_columns = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        rows = [{column: (row.get(column) or "").strip() for column in fieldnames} for row in reader]
    failures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        missing_values = [column for column in REQUIRED_COLUMNS if not row.get(column)]
        case_id = row.get("case_id") or f"row_{index}"
        if case_id in seen:
            missing_values.append("case_id_unique")
        seen.add(case_id)
        if missing_columns or missing_values:
            failures.append(
                {
                    "row_number": index,
                    "case_id": case_id,
                    "short_name": row.get("short_name", ""),
                    "target_formula": row.get("target_formula", ""),
                    "query": row.get("query", ""),
                    "chemistry_family": row.get("chemistry_family", ""),
                    "challenge_type": row.get("challenge_type", ""),
                    "missing_columns": missing_columns,
                    "missing_or_invalid_values": missing_values,
                    "message": "Input row failed challenge CSV validation.",
                }
            )
    return rows, failures, missing_columns


def _select_rows(rows: list[dict[str, str]], *, offset: int, limit: int | None, case_id: str | None) -> list[dict[str, str]]:
    if case_id:
        return [row for row in rows if row.get("case_id") == case_id]
    selected = rows[max(offset, 0) :]
    if limit is not None:
        selected = selected[: max(limit, 0)]
    return selected


def _prepare_out_root(out_root: Path, *, overwrite: bool, resume: bool, skip_existing: bool) -> None:
    v1 = REPO_ROOT / "test_workdir" / "paper_evidence_pack_v1"
    if out_root.resolve() == v1.resolve():
        raise ValueError("Refusing to write v2 output into paper_evidence_pack_v1.")
    if out_root.exists() and not (overwrite or resume or skip_existing):
        raise FileExistsError(f"{out_root} already exists; use --resume, --skip-existing, or --overwrite-v2.")
    if overwrite and out_root.exists():
        shutil.rmtree(out_root)
    for name in ["raw_runs", "figures", "final_doc_images", "manifests", "reports", "logs"]:
        (out_root / name).mkdir(parents=True, exist_ok=True)


def _query_metadata_for_row(row: Mapping[str, Any]) -> dict[str, Any]:
    from sok_llm_orchestrator.agentic.skills.robocrys_query_skill import build_robocrys_style_crystal_db_query

    return build_robocrys_style_crystal_db_query(
        original_query=str(row.get("query", "")),
        target_formula=str(row.get("target_formula", "")),
        chemistry_family=str(row.get("chemistry_family", "")),
        challenge_type=str(row.get("challenge_type", "")),
        expected_motifs_or_priors=str(row.get("expected_motifs_or_priors", "")),
    )


def _write_crystal_db_query_sidecar(case_dir: Path, row: Mapping[str, Any], query_metadata: Mapping[str, Any] | None) -> None:
    if not query_metadata:
        return
    _write_json(
        case_dir / "crystal_db_query.json",
        {
            "original_user_query": row.get("query", ""),
            "crystal_db_retrieval_query": query_metadata.get("crystal_db_retrieval_query", ""),
            "compact_retrieval_query": query_metadata.get("compact_retrieval_query", ""),
            "pair_evidence_query": query_metadata.get("pair_evidence_query", ""),
            "query_style": query_metadata.get("query_style", "robocrys_descriptive"),
            "skill_version": query_metadata.get("skill_version", ""),
            "terms_added": query_metadata.get("terms_added", []),
            "motif_terms_from_input": query_metadata.get("motif_terms_from_input", []),
            "material_system": query_metadata.get("material_system", []),
            "pair_evidence_targets": query_metadata.get("pair_evidence_targets", []),
            "validator_requirements": query_metadata.get("validator_requirements", []),
            "requirement_aliases": query_metadata.get("requirement_aliases", {}),
            "explicit_text_aliases": query_metadata.get("explicit_text_aliases", {}),
            "implicit_condensed_rules": query_metadata.get("implicit_condensed_rules", {}),
            "requirement_source": query_metadata.get("requirement_source", ""),
            "query_rewrite_reason": "align semantic query with robocrys text_docs retrieval surface",
            "warnings": query_metadata.get("warnings", []),
        },
    )


def _suite_payload(
    selected_rows: list[dict[str, str]],
    query_metadata_by_case: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    query_metadata_by_case = query_metadata_by_case or {}
    return {
        "schema_version": "skill_loop.challenge_suite.v2",
        "suite_name": "paper_evidence_pack_v2_challenge_suite",
        "runs": [
            {
                "id": _case_run_id(row),
                "material_system": row["target_formula"],
                "goal": str(
                    (query_metadata_by_case.get(str(row.get("case_id"))) or {}).get("crystal_db_retrieval_query")
                    or row["query"]
                ),
                "expected_outcome": "blocked_or_partial",
                "expected_failure_family": "",
                "challenge_case": {
                    **row,
                    "original_query": row["query"],
                    "query_skill": dict(query_metadata_by_case.get(str(row.get("case_id"))) or {}),
                },
            }
            for row in selected_rows
        ],
    }


FORMULA_RE = re.compile(r"([A-Z][a-z]?)([0-9.]*)")


def _formula_elements(formula: str) -> list[str]:
    elements = [match.group(1) for match in FORMULA_RE.finditer(str(formula or ""))]
    return sorted(dict.fromkeys(elements), key=str.lower)


def _required_pairs(elements: list[str]) -> list[str]:
    ordered = sorted(dict.fromkeys(elements), key=str.lower)
    return [f"{a}-{b}" for a, b in combinations_with_replacement(ordered, 2)]


def _pair_key(pair: str) -> tuple[str, str]:
    left, right = str(pair).split("-", 1)
    ordered = sorted([left, right], key=str.lower)
    return ordered[0], ordered[1]


def _default_crystal_db_path() -> Path:
    candidates = [
        REPO_ROOT.parent / "Crystal-DB" / "data" / "phase6_mp_10k.db",
        REPO_ROOT / "data" / "phase6_mp_10k.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_crystal_db_records(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT
              s.structure_id,
              s.reduced_formula,
              s.cif_text,
              s.license_restricted,
              m.formula,
              m.elements_csv,
              p.allow_export,
              p.allow_cif_return,
              p.license_notes
            FROM structures s
            LEFT JOIN metadata m ON m.structure_id = s.structure_id
            LEFT JOIN provenance p ON p.structure_id = s.structure_id
            """
        ).fetchall()
    finally:
        con.close()
    records = []
    for row in rows:
        elements = [
            item.strip()
            for item in str(row["elements_csv"] or "").split(",")
            if item.strip()
        ]
        if not elements:
            elements = _formula_elements(str(row["formula"] or row["reduced_formula"] or ""))
        exportable = bool(row["cif_text"]) and bool(row["allow_export"] in (1, True, None)) and not bool(row["license_restricted"])
        records.append(
            {
                "structure_id": row["structure_id"],
                "formula": row["formula"] or row["reduced_formula"] or "",
                "elements": sorted(dict.fromkeys(elements), key=str.lower),
                "chemsys": "-".join(sorted(dict.fromkeys(elements), key=str.lower)),
                "exportable": exportable,
                "has_cif_text": bool(row["cif_text"]),
                "blocked_by_policy": bool(row["allow_export"] == 0 or row["license_restricted"]),
                "license_notes": row["license_notes"] or "",
            }
        )
    return records


def _infer_family(row: Mapping[str, Any]) -> str:
    text = " ".join(str(row.get(key, "")) for key in ("chemistry_family", "challenge_type", "query", "short_name")).lower()
    for family in [
        "perovskite",
        "spinel",
        "rocksalt",
        "fluorite",
        "pyrochlore",
        "garnet",
        "layered oxide",
        "layered chalcogenide",
        "phosphate framework",
        "sulfide",
        "thiophosphate",
        "nitride",
        "carbide",
        "boride",
        "halide",
    ]:
        if family in text:
            return family
    return "unknown"


def _support_for_row(row: Mapping[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    elements = _formula_elements(str(row.get("target_formula") or ""))
    required = _required_pairs(elements)
    exportable = [record for record in records if record["exportable"]]
    row_formula = str(row.get("target_formula") or "")
    target_chemsys = "-".join(elements)
    exact_formula_count = sum(1 for record in exportable if str(record["formula"]) == row_formula)
    same_chemsys_count = sum(1 for record in exportable if record["chemsys"] == target_chemsys)
    element_counts = Counter(element for record in exportable for element in record["elements"])
    pair_counts: dict[str, int] = {}
    for pair in required:
        left, right = _pair_key(pair)
        pair_counts[pair] = sum(1 for record in exportable if left in record["elements"] and right in record["elements"])
    covered = [pair for pair, count in pair_counts.items() if count > 0]
    missing = [pair for pair, count in pair_counts.items() if count == 0]
    if required and not missing and same_chemsys_count > 0:
        support = "fully_supported"
        risk = "low"
        recommendation = "run_full_workflow"
    elif required and not missing:
        support = "pair_supported"
        risk = "medium"
        recommendation = "run_full_workflow"
    elif covered:
        support = "partially_supported"
        risk = "medium"
        recommendation = "run_without_fresh_spp"
    elif elements and all(element_counts.get(element, 0) > 0 for element in elements):
        support = "element_only_supported"
        risk = "high"
        recommendation = "run_retrieval_only"
    else:
        support = "unsupported"
        risk = "unsupported"
        recommendation = "needs_corpus_expansion"
    return {
        "case_id": row.get("case_id", ""),
        "short_name": row.get("short_name", ""),
        "target_formula": row_formula,
        "required_elements": elements,
        "required_pairs": required,
        "exact_formula_exists": exact_formula_count > 0,
        "exact_formula_count": exact_formula_count,
        "same_chemsys_count": same_chemsys_count,
        "exportable_pair_support_counts": pair_counts,
        "missing_pairs": missing,
        "support_classification": support,
        "likely_workflow_risk": risk,
        "recommendation": recommendation,
        "inferred_family": _infer_family(row),
    }


def build_crystal_db_capability_audit(csv_rows: list[dict[str, str]], *, db_path: Path) -> dict[str, Any]:
    records = _load_crystal_db_records(db_path)
    exportable = [record for record in records if record["exportable"]]
    element_counts = Counter(element for record in records for element in record["elements"])
    exportable_element_counts = Counter(element for record in exportable for element in record["elements"])
    chemsys_counts = Counter(record["chemsys"] for record in records if record["chemsys"])
    exportable_chemsys_counts = Counter(record["chemsys"] for record in exportable if record["chemsys"])
    pair_records: dict[str, list[dict[str, Any]]] = {}
    for record in exportable:
        for pair in _required_pairs(record["elements"]):
            pair_records.setdefault(pair, []).append(record)
    pair_coverage = [
        {
            "pair": pair,
            "structure_count": len(items),
            "pair_distance_observation_count": "",
            "structures_with_nonzero_pair_distances_within_cutoff": "",
            "min_distance": "",
            "median_distance": "",
            "max_distance": "",
            "example_structure_ids": [item["structure_id"] for item in items[:5]],
            "example_cif_paths": [],
        }
        for pair, items in sorted(pair_records.items())
    ]
    challenge_support = [_support_for_row(row, records) for row in csv_rows]
    family_counts = Counter(item["inferred_family"] for item in challenge_support)
    return {
        "schema_version": "crystal_db_capability_audit.v1",
        "db_path": _rel(db_path),
        "corpus_counts": {
            "total_structures": len(records),
            "exportable_cif_structures": len(exportable),
            "non_exportable_structures": len(records) - len(exportable),
            "structures_with_missing_source_paths": 0,
            "structures_blocked_by_policy_or_redaction": sum(1 for record in records if record["blocked_by_policy"]),
        },
        "element_coverage": [
            {"element": element, "count": element_counts[element], "exportable_count": exportable_element_counts[element]}
            for element in sorted(element_counts)
        ],
        "chemsys_coverage": [
            {"chemsys": chemsys, "count": chemsys_counts[chemsys], "exportable_count": exportable_chemsys_counts[chemsys]}
            for chemsys in sorted(chemsys_counts)
        ],
        "top_chemsys_by_exportable_count": exportable_chemsys_counts.most_common(50),
        "pair_evidence_coverage": pair_coverage,
        "family_coverage": [{"family": family, "count": count, "label_source": "inferred"} for family, count in sorted(family_counts.items())],
        "challenge_support": challenge_support,
    }


def _write_capability_audit(out_root: Path, rows: list[dict[str, str]], *, db_path: Path) -> dict[str, Any]:
    audit = build_crystal_db_capability_audit(rows, db_path=db_path)
    reports = out_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write_json(reports / "CRYSTAL_DB_CAPABILITY_AUDIT.json", audit)
    support_rows = audit["challenge_support"]
    support_columns = [
        "case_id",
        "short_name",
        "target_formula",
        "required_elements",
        "required_pairs",
        "exact_formula_exists",
        "exact_formula_count",
        "same_chemsys_count",
        "exportable_pair_support_counts",
        "missing_pairs",
        "support_classification",
        "likely_workflow_risk",
        "recommendation",
        "inferred_family",
    ]
    _write_csv(reports / "CRYSTAL_DB_CAPABILITY_AUDIT.csv", support_rows, support_columns)
    counts = Counter(item["support_classification"] for item in support_rows)
    md = [
        "# Crystal-DB Capability Audit",
        "",
        f"- DB path: {_rel(db_path)}",
        f"- Total structures: {audit['corpus_counts']['total_structures']}",
        f"- Exportable CIF structures: {audit['corpus_counts']['exportable_cif_structures']}",
        f"- Non-exportable structures: {audit['corpus_counts']['non_exportable_structures']}",
        f"- Policy/redaction blocked structures: {audit['corpus_counts']['structures_blocked_by_policy_or_redaction']}",
        "",
        "## Challenge Support Classification",
        *[f"- {key}: {value}" for key, value in sorted(counts.items())],
        "",
        "## Notes",
        "- Pair evidence counts are element co-occurrence support in exportable CIF structures.",
        "- Distance observations are left blank unless a cheap local geometry pass is added.",
        "- Partial support is evidence for diagnostics, not proof that fresh SPP guidance is solver-compatible.",
    ]
    (reports / "CRYSTAL_DB_CAPABILITY_AUDIT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return audit


def _empty_manifest_row(
    row: Mapping[str, Any],
    case_dir: Path,
    *,
    status: str,
    category: str,
    message: str,
    runtime: float = 0.0,
    out_root: Path | None = None,
) -> dict[str, Any]:
    return {
        "case_id": row.get("case_id", ""),
        "short_name": row.get("short_name", ""),
        "target_formula": row.get("target_formula", ""),
        "query": row.get("query", ""),
        "chemistry_family": row.get("chemistry_family", ""),
        "challenge_type": row.get("challenge_type", ""),
        "intent_specificity": row.get("intent_specificity", "medium") or "medium",
        "benchmark_split": row.get("benchmark_split", "mixed_specificity") or "mixed_specificity",
        "case_dir": _case_dir_manifest_value(case_dir, out_root),
        "status": status,
        "failure_category": category if category in FAILURE_CATEGORIES else "unknown_failure",
        "failure_message": message,
        "semantic_neighbour_count": 0,
        "exported_cif_count": 0,
        "spp_exported_subset_count": 0,
        "selected_pot_root": "",
        "selected_pot_root_kind": "missing",
        "fresh_spp_quality": "unknown",
        "used_fallback_pots": False,
        "qlip_request_path": "",
        "qlip_validation_status": "",
        "qlip_solve_status": "",
        "qlip_objective": "",
        "solution_cif_path": "",
        "solution_cif_produced": False,
        "workflow_png_path": "",
        "workflow_svg_path": "",
        "workflow_pdf_path": "",
        "visualisation_manifest_path": "",
        "final_doc_images_count": 0,
        "runtime_seconds": round(runtime, 3),
        "support_classification": "",
        "missing_pairs": [],
        "exportable_pair_support_counts": {},
        "exact_formula_count": 0,
        "same_chemsys_count": 0,
        "recommendation": "",
        "qlip_request_attempted": False,
        "qlip_request_blocked_stage": "",
        "qlip_request_blocked_reason": "",
        "upstream_failure_category": "",
        "upstream_failure_subcategory": "",
        "crystal_db_retrieval_query": "",
        "query_style": "",
        "query_skill_version": "",
        "generated_cif_robocrys_available": False,
        "generated_cif_robocrys_description_path": "",
        "generated_cif_robocrys_metadata_path": "",
        "generated_cif_robocrys_condensed_path": "",
        "generated_cif_robocrys_error": "",
        "generated_cif_robocrys_warning_count": 0,
        "robocrys_intent_validation_available": False,
        "robocrys_intent_alignment_score": "",
        "robocrys_intent_judgement": "",
        "robocrys_intent_validation_path": "",
        "robocrys_intent_skip_reason": "",
        "spp_objective_audit_path": "",
        "spp_objective_audit_available": False,
        "spp_objective_audit_error": "",
    }


def _write_case_sidecars(case_dir: Path, row: Mapping[str, Any], *, command: Mapping[str, Any], status: Mapping[str, Any]) -> None:
    _write_json(case_dir / "input_query.json", dict(row))
    _write_json(case_dir / "run_command.json", dict(command))
    _write_json(case_dir / "workflow_stdout.json", {"runner": "in_process", "stdout": []})
    (case_dir / "workflow_stderr.txt").write_text("", encoding="utf-8")
    _write_json(case_dir / "workflow_status.json", dict(status))


def _write_failure_summary(case_dir: Path, manifest_row: Mapping[str, Any]) -> None:
    _write_json(
        case_dir / "failure_summary.json",
        {
            "status": manifest_row.get("status", ""),
            "failure_category": manifest_row.get("failure_category", ""),
            "failure_message": manifest_row.get("failure_message", ""),
            "solution_cif_produced": manifest_row.get("solution_cif_produced", False),
            "workflow_figure_produced": bool(manifest_row.get("workflow_png_path") or manifest_row.get("workflow_svg_path") or manifest_row.get("workflow_pdf_path")),
        },
    )


def _robocrys_empty_fields(error: str = "") -> dict[str, Any]:
    return {
        "generated_cif_robocrys_available": False,
        "generated_cif_robocrys_description_path": "",
        "generated_cif_robocrys_metadata_path": "",
        "generated_cif_robocrys_condensed_path": "",
        "generated_cif_robocrys_error": error,
        "generated_cif_robocrys_warning_count": 0,
    }


def _write_generated_cif_robocrys_sidecars(
    case_dir: Path,
    solution_cif: str,
    *,
    strict: bool,
    robocrys_python: str | None = None,
) -> dict[str, Any]:
    if not solution_cif:
        return _robocrys_empty_fields("no_solution_cif")
    sidecar_dir = case_dir / "robocrys"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    try:
        from sok_llm_orchestrator.agentic.robocrys_adapter import describe_cif_with_robocrys

        result = describe_cif_with_robocrys(Path(solution_cif), strict=strict, robocrys_python=robocrys_python)
    except Exception as exc:  # noqa: BLE001 - optional unless strict requested by caller.
        if strict:
            raise
        result = {
            "robocrys_available": False,
            "description": None,
            "condensed_structure": None,
            "engine": "robocrys",
            "text_view": "robocrys",
            "robocrys_version": None,
            "cif_path": solution_cif,
            "warnings": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    description_path = ""
    condensed_path = ""
    if result.get("description"):
        description_file = sidecar_dir / "generated_cif_robocrys_description.txt"
        description_file.write_text(str(result["description"]), encoding="utf-8")
        description_path = _rel(description_file)
    if isinstance(result.get("condensed_structure"), Mapping):
        condensed_file = sidecar_dir / "generated_cif_robocrys_condensed.json"
        _write_json(condensed_file, result["condensed_structure"])
        condensed_path = _rel(condensed_file)
    metadata = {key: value for key, value in result.items() if key != "condensed_structure"}
    metadata["description_path"] = description_path
    metadata["condensed_path"] = condensed_path
    metadata_file = sidecar_dir / "generated_cif_robocrys_metadata.json"
    _write_json(metadata_file, metadata)
    return {
        "generated_cif_robocrys_available": bool(result.get("robocrys_available")),
        "generated_cif_robocrys_description_path": description_path,
        "generated_cif_robocrys_metadata_path": _rel(metadata_file),
        "generated_cif_robocrys_condensed_path": condensed_path,
        "generated_cif_robocrys_error": str(result.get("error") or ""),
        "generated_cif_robocrys_warning_count": len(result.get("warnings") if isinstance(result.get("warnings"), list) else []),
    }


def _intent_empty_fields(skip_reason: str = "") -> dict[str, Any]:
    return {
        "robocrys_intent_validation_available": False,
        "robocrys_intent_alignment_score": "",
        "robocrys_intent_judgement": "not_scored" if skip_reason else "",
        "robocrys_intent_validation_path": "",
        "robocrys_intent_skip_reason": skip_reason,
    }


def _render_intent_validation_markdown(payload: Mapping[str, Any]) -> str:
    rule = payload.get("rule_based") if isinstance(payload.get("rule_based"), Mapping) else payload
    llm = payload.get("llm_judge") if isinstance(payload.get("llm_judge"), Mapping) else {}
    final = payload.get("final_decision") if isinstance(payload.get("final_decision"), Mapping) else {}
    scores = rule.get("scores") if isinstance(rule.get("scores"), Mapping) else {}
    missing = rule.get("missing_terms") if isinstance(rule.get("missing_terms"), Mapping) else {}
    matched = rule.get("matched_terms") if isinstance(rule.get("matched_terms"), Mapping) else {}
    lines = [
        "# Robocrys Intent Alignment",
        "",
        f"- final judgement: {final.get('judgement', payload.get('judgement', ''))}",
        f"- final score: {final.get('score', scores.get('overall_intent_alignment', 0.0))}",
        f"- decision source: {final.get('decision_source', 'rule_based')}",
        f"- available: {payload.get('available', False)}",
        f"- rule_based skip_reason: {rule.get('skip_reason') or ''}",
        f"- llm_judge judgement: {llm.get('judgement', '')}",
        f"- llm_judge skip_reason: {llm.get('skip_reason') or ''}",
        "",
        "## Rule-Based Scores",
        *[f"- {key}: {value}" for key, value in scores.items()],
        "",
        "## LLM Judge",
        f"- available: {llm.get('available', False)}",
        f"- score: {llm.get('score')}",
        f"- correct: {llm.get('correct')}",
        f"- explanation: {llm.get('explanation', '')}",
        "",
        "## Matched Terms",
        *[f"- {key}: {', '.join(str(item) for item in value) if isinstance(value, list) else value}" for key, value in matched.items()],
        "",
        "## Missing Terms",
        *[f"- {key}: {', '.join(str(item) for item in value) if isinstance(value, list) else value}" for key, value in missing.items()],
        "",
        "## Explanation",
        str(payload.get("explanation", "")),
        "",
        "This is semantic/motif alignment evidence only. It is not experimental validation or proof of thermodynamic stability.",
    ]
    return "\n".join(lines) + "\n"


def _write_robocrys_intent_validation_sidecars(
    case_dir: Path,
    row: Mapping[str, Any],
    query_metadata: Mapping[str, Any] | None,
    robocrys_fields: Mapping[str, Any],
    *,
    llm_judge_enabled: bool = False,
    llm_model_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from sok_llm_orchestrator.agentic.robocrys_intent_validator import (
        combine_rule_based_and_llm_validation,
        judge_robocrys_intent_alignment_with_llm,
        validate_generated_cif_against_query,
    )

    description = None
    description_path = str(robocrys_fields.get("generated_cif_robocrys_description_path") or "")
    if description_path:
        path = REPO_ROOT / description_path
        if path.is_file():
            description = path.read_text(encoding="utf-8", errors="ignore")
    condensed: Mapping[str, Any] | None = None
    condensed_path = str(robocrys_fields.get("generated_cif_robocrys_condensed_path") or "")
    if condensed_path:
        payload = _read_json(REPO_ROOT / condensed_path)
        if isinstance(payload, Mapping):
            condensed = payload
    retrieval_query = str((query_metadata or {}).get("crystal_db_retrieval_query") or row.get("query", ""))
    validator_requirements = (query_metadata or {}).get("validator_requirements")
    if not isinstance(validator_requirements, list):
        validator_requirements = []
    requirement_aliases = (query_metadata or {}).get("requirement_aliases")
    if not isinstance(requirement_aliases, Mapping):
        requirement_aliases = {}
    rule_based = validate_generated_cif_against_query(
        original_query=str(row.get("query", "")),
        crystal_db_retrieval_query=retrieval_query,
        generated_cif_robocrys_description=description,
        target_formula=str(row.get("target_formula", "")),
        chemistry_family=str(row.get("chemistry_family", "")),
        expected_motifs_or_priors=row.get("expected_motifs_or_priors", ""),
        intent_specificity=str(row.get("intent_specificity", "medium") or "medium"),
        generated_cif_condensed_structure=condensed,
        validator_requirements=validator_requirements,
        requirement_aliases=requirement_aliases,
    )
    llm_payload = None
    if llm_judge_enabled and description:
        llm_payload = judge_robocrys_intent_alignment_with_llm(
            original_query=str(row.get("query", "")),
            crystal_db_retrieval_query=retrieval_query,
            generated_cif_robocrys_description=description,
            target_formula=str(row.get("target_formula", "")),
            chemistry_family=str(row.get("chemistry_family", "")),
            expected_motifs_or_priors=row.get("expected_motifs_or_priors", ""),
            intent_specificity=str(row.get("intent_specificity", "medium") or "medium"),
            model_config=dict(llm_model_config or {}),
            validator_requirements=validator_requirements,
            requirement_evidence=rule_based.get("requirement_evidence") if isinstance(rule_based.get("requirement_evidence"), Mapping) else {},
            generated_cif_condensed_structure=condensed,
        )
    elif llm_judge_enabled:
        llm_payload = {
            "validator_version": "v1_llm_robocrys_intent_judge",
            "available": False,
            "skip_reason": "robocrys_output_unavailable",
            "score": None,
            "correct": None,
            "judgement": "not_scored",
            "matched_requirements": [],
            "missing_requirements": [],
            "contradictions": [],
            "concerns": [],
            "explanation": "LLM judge was not attempted because Robocrys output is unavailable.",
            "not_physical_validation_notice": True,
            "prompt": "",
            "raw_response": "",
        }
    payload = {
        "case_id": row.get("case_id", ""),
        "target_formula": row.get("target_formula", ""),
        **combine_rule_based_and_llm_validation(rule_based, llm_payload),
    }
    sidecar_dir = case_dir / "robocrys"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    json_path = sidecar_dir / "robocrys_intent_validation.json"
    md_path = sidecar_dir / "robocrys_intent_validation.md"
    _write_json(json_path, payload)
    md_path.write_text(_render_intent_validation_markdown(payload), encoding="utf-8")
    llm = payload.get("llm_judge") if isinstance(payload.get("llm_judge"), Mapping) else {}
    if llm.get("prompt"):
        (sidecar_dir / "robocrys_intent_judge_prompt.txt").write_text(str(llm.get("prompt") or ""), encoding="utf-8")
    if llm.get("raw_response"):
        (sidecar_dir / "robocrys_intent_judge_raw_response.txt").write_text(str(llm.get("raw_response") or ""), encoding="utf-8")
    _write_json(sidecar_dir / "robocrys_intent_judge.json", llm)
    final = payload.get("final_decision") if isinstance(payload.get("final_decision"), Mapping) else {}
    return {
        "robocrys_intent_validation_available": bool(payload.get("available")),
        "robocrys_intent_alignment_score": final.get("score", ""),
        "robocrys_intent_judgement": final.get("judgement", ""),
        "robocrys_intent_validation_path": _rel(json_path),
        "robocrys_intent_skip_reason": _combined_skip_reason(payload),
    }


def _combined_skip_reason(payload: Mapping[str, Any]) -> str:
    if payload.get("available"):
        return ""
    rule = payload.get("rule_based") if isinstance(payload.get("rule_based"), Mapping) else {}
    llm = payload.get("llm_judge") if isinstance(payload.get("llm_judge"), Mapping) else {}
    return str(rule.get("skip_reason") or llm.get("skip_reason") or "not_scored")


def _summarise_case(
    row: Mapping[str, Any],
    summary_run: Mapping[str, Any],
    suite_dir: Path,
    out_root: Path,
    *,
    runtime: float,
    stop_on_visualisation_error: bool = False,
    describe_generated_cifs_with_robocrys: bool = False,
    require_robocrys: bool = False,
    robocrys_python: str | None = None,
    validate_robocrys_intent_alignment: bool = False,
    require_robocrys_intent_validation: bool = False,
    llm_judge_enabled: bool = False,
    llm_model_config: Mapping[str, Any] | None = None,
    query_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    case_dir = suite_dir / _case_run_id(row)
    artifacts = summary_run.get("artifact_paths") if isinstance(summary_run.get("artifact_paths"), Mapping) else {}
    evaluation_path = _resolve_path(str(artifacts.get("workflow_evaluation_json") or ""), suite_dir) if artifacts else Path()
    execution_path = _resolve_path(str(artifacts.get("execution_run_json") or ""), suite_dir) if artifacts else Path()
    evaluation = _read_json(evaluation_path)
    execution = _read_json(execution_path)
    retrieval_step = _step(execution, "crystal.csp_pack")
    spp_step = _step(execution, "spp.run_pipeline")
    validation_step = _step(execution, "qlip.validate_request")
    solve_step = _step(execution, "qlip.solve")
    retrieval_summary = retrieval_step.get("output_summary") if isinstance(retrieval_step.get("output_summary"), Mapping) else {}
    spp_summary = spp_step.get("output_summary") if isinstance(spp_step.get("output_summary"), Mapping) else {}
    validation_summary = validation_step.get("output_summary") if isinstance(validation_step.get("output_summary"), Mapping) else {}
    solve_summary = solve_step.get("output_summary") if isinstance(solve_step.get("output_summary"), Mapping) else {}
    retrieval_observed = _nested(evaluation, "evidence_checks", "retrieval", "observed", default={}) or {}
    spp_observed = _nested(evaluation, "evidence_checks", "spp_guidance", "observed", default={}) or {}
    solve_observed = _nested(evaluation, "execution_checks", "solve", "observed", default={}) or {}

    semantic_count = _as_int(
        retrieval_summary.get("neighbor_count")
        or retrieval_summary.get("semantic_neighbour_count")
        or retrieval_observed.get("neighbor_count")
        or retrieval_observed.get("semantic_neighbour_count")
    )
    exported_cifs = _as_int(
        _nested(retrieval_summary, "corpus_selection", "selected_cif_count", default=0)
        or retrieval_summary.get("exported_cif_count")
        or retrieval_observed.get("exported_cif_count")
    )
    spp_subset = _as_int(spp_summary.get("exported_subset_count") or spp_summary.get("spp_exported_subset_count"))
    selected_pot_root = str(spp_summary.get("selected_pot_root") or spp_summary.get("pot_root") or spp_observed.get("pot_root") or "")
    pot_kind = str(spp_summary.get("pot_root_source") or spp_summary.get("selected_pot_root_kind") or ("missing" if not selected_pot_root else "unknown"))
    corpus_quality = str(
        spp_summary.get("corpus_quality_status")
        or _nested(spp_summary, "fresh_generation", "corpus_quality", "corpus_quality_status", default="")
        or "unknown"
    )
    used_fallback = pot_kind.lower() in {"fallback", "fallback_precompiled", "precompiled_fallback"} or "fallback" in pot_kind.lower()
    qlip_request = (
        str(spp_summary.get("qlip_request_path") or spp_summary.get("request_ref") or _artifact_ref(spp_step, "qlip_request_path") or _artifact_ref(spp_step, "request_ref") or "")
    )
    qlip_validation_status = str(validation_summary.get("package_validation_status") or validation_summary.get("status") or validation_step.get("status") or "")
    qlip_solve_status = str(summary_run.get("qlip_status") or solve_summary.get("status") or solve_summary.get("qlip_status") or solve_observed.get("qlip_status") or "")
    qlip_objective = solve_summary.get("objective_value", solve_observed.get("objective_value", ""))
    solution_cif = str(summary_run.get("solution_cif_path") or solve_summary.get("solution_cif_path") or solve_observed.get("solution_cif_path") or "")
    solution_produced = bool(solution_cif and Path(solution_cif).is_file())
    robocrys_fields = _robocrys_empty_fields("skipped")
    if describe_generated_cifs_with_robocrys:
        if solution_produced:
            robocrys_fields = _write_generated_cif_robocrys_sidecars(
                case_dir,
                solution_cif,
                strict=require_robocrys,
                robocrys_python=robocrys_python,
            )
        else:
            robocrys_fields = _robocrys_empty_fields("no_solution_cif")
    intent_fields = _intent_empty_fields("skipped")
    if validate_robocrys_intent_alignment:
        intent_fields = _write_robocrys_intent_validation_sidecars(
            case_dir,
            row,
            query_metadata,
            robocrys_fields,
            llm_judge_enabled=llm_judge_enabled,
            llm_model_config=llm_model_config,
        )

    _write_json(case_dir / "retrieval_summary.json", {"step": retrieval_step, "observed": retrieval_observed})
    _write_json(case_dir / "spp_summary.json", {"step": spp_step, "observed": spp_observed})
    _write_json(case_dir / "qlip_validation.json", {"step": validation_step})
    _write_json(case_dir / "qlip_solve_summary.json", {"step": solve_step, "observed": solve_observed})

    workflow_png = workflow_svg = workflow_pdf = visual_manifest = ""
    vis_error = ""
    if case_dir.exists():
        try:
            visualise_workflow_artifact = _load_visualise_workflow_artifact()
            vis = visualise_workflow_artifact(case_dir, out_root / "figures", str(row.get("target_formula") or row.get("short_name") or row.get("case_id")))
            workflow_png = _rel(vis.get("png_path"))
            workflow_svg = _rel(vis.get("svg_path"))
            workflow_pdf = _rel(vis.get("pdf_path"))
            visual_manifest = _rel(vis.get("manifest_path"))
            _write_json(case_dir / "visualisation_manifest.json", vis.get("manifest", {}))
        except Exception as exc:  # noqa: BLE001 - visualisation must be recorded honestly.
            vis_error = f"{type(exc).__name__}: {exc}"
            if stop_on_visualisation_error:
                raise
            try:
                build_workflow_case_figure = _load_build_workflow_case_figure()
                fallback = build_workflow_case_figure(suite_dir, str(row.get("target_formula") or row.get("case_id")), out_root)
                workflow_png = _rel(fallback.get("png_path"))
                workflow_svg = _rel(fallback.get("svg_path"))
                workflow_pdf = ""
                visual_manifest = _rel(out_root / "figure_manifest.json")
                _write_json(case_dir / "visualisation_manifest.json", {"fallback_case_figure": fallback, "visualise_error": vis_error})
            except Exception as fallback_exc:  # noqa: BLE001
                vis_error += f"; fallback={type(fallback_exc).__name__}: {fallback_exc}"

    qlip_request_context = _qlip_request_context(
        retrieval_step=retrieval_step,
        spp_step=spp_step,
        qlip_request=qlip_request,
        failure_code=str(summary_run.get("actual_failure_code") or summary_run.get("failure_code") or ""),
    )
    failure_category, failure_message = _classify_failure(
        summary_run=summary_run,
        retrieval_step=retrieval_step,
        spp_step=spp_step,
        validation_step=validation_step,
        solve_step=solve_step,
        semantic_count=semantic_count,
        exported_cifs=exported_cifs,
        qlip_request=qlip_request,
        qlip_validation_status=qlip_validation_status,
        qlip_solve_status=qlip_solve_status,
        solution_produced=solution_produced,
        used_fallback=used_fallback,
        corpus_quality=corpus_quality,
        vis_error=vis_error,
        qlip_request_blocked_stage=qlip_request_context["qlip_request_blocked_stage"],
        qlip_request_blocked_reason=qlip_request_context["qlip_request_blocked_reason"],
    )
    if require_robocrys and solution_produced and not robocrys_fields.get("generated_cif_robocrys_available"):
        failure_category = "robocrys_unavailable"
        failure_message = robocrys_fields.get("generated_cif_robocrys_error") or "Robocrys sidecar generation was required but unavailable."
    if require_robocrys_intent_validation and solution_produced and not intent_fields.get("robocrys_intent_validation_available"):
        failure_category = "robocrys_intent_validation_unavailable"
        failure_message = intent_fields.get("robocrys_intent_skip_reason") or "Robocrys intent validation was required but unavailable."
    status = "success" if failure_category == "success" else str(summary_run.get("final_status") or "failed")
    manifest_row = _empty_manifest_row(
        row,
        case_dir,
        status=status,
        category=failure_category,
        message=failure_message,
        runtime=runtime,
        out_root=out_root,
    )
    manifest_row.update(
        {
            "semantic_neighbour_count": semantic_count,
            "exported_cif_count": exported_cifs,
            "spp_exported_subset_count": spp_subset,
            "selected_pot_root": _rel(selected_pot_root),
            "selected_pot_root_kind": pot_kind,
            "fresh_spp_quality": corpus_quality,
            "used_fallback_pots": used_fallback,
            "qlip_request_path": _rel(qlip_request),
            "qlip_validation_status": qlip_validation_status,
            "qlip_solve_status": qlip_solve_status,
            "qlip_objective": qlip_objective,
            "solution_cif_path": _rel(solution_cif),
            "solution_cif_produced": solution_produced,
            "workflow_png_path": workflow_png,
            "workflow_svg_path": workflow_svg,
            "workflow_pdf_path": workflow_pdf,
            "visualisation_manifest_path": visual_manifest,
            "crystal_db_retrieval_query": (query_metadata or {}).get("crystal_db_retrieval_query", ""),
            "query_style": (query_metadata or {}).get("query_style", ""),
            "query_skill_version": (query_metadata or {}).get("skill_version", ""),
            **robocrys_fields,
            **intent_fields,
            **qlip_request_context,
        }
    )
    manifest_row.update(
        _write_spp_objective_audit_sidecar(
            case_dir,
            qlip_request_path=qlip_request,
            solution_cif_path=solution_cif,
            qlip_objective=qlip_objective,
        )
    )
    _write_failure_summary(case_dir, manifest_row)
    return manifest_row


def _qlip_request_context(
    *,
    retrieval_step: Mapping[str, Any],
    spp_step: Mapping[str, Any],
    qlip_request: str,
    failure_code: str,
) -> dict[str, Any]:
    if qlip_request:
        return {
            "qlip_request_attempted": True,
            "qlip_request_blocked_stage": "",
            "qlip_request_blocked_reason": "",
            "upstream_failure_category": "",
            "upstream_failure_subcategory": "",
        }
    retrieval_summary = retrieval_step.get("output_summary") if isinstance(retrieval_step.get("output_summary"), Mapping) else {}
    spp_summary = spp_step.get("output_summary") if isinstance(spp_step.get("output_summary"), Mapping) else {}
    retrieval_error = retrieval_step.get("error") if isinstance(retrieval_step.get("error"), Mapping) else {}
    spp_error = spp_step.get("error") if isinstance(spp_step.get("error"), Mapping) else {}
    corpus_selection = retrieval_summary.get("corpus_selection") if isinstance(retrieval_summary.get("corpus_selection"), Mapping) else {}
    corpus_status = str(retrieval_summary.get("corpus_selection_status") or corpus_selection.get("corpus_selection_status") or "")
    if retrieval_step and retrieval_step.get("status") in {"blocked", "failed"}:
        stage = "corpus_selection" if corpus_status or retrieval_error.get("code") else "retrieval"
        reason = str(retrieval_error.get("code") or corpus_status or failure_code or "retrieval_blocked")
        return {
            "qlip_request_attempted": False,
            "qlip_request_blocked_stage": stage,
            "qlip_request_blocked_reason": reason,
            "upstream_failure_category": "retrieval_failed" if stage == "retrieval" else "qlip_request_blocked_by_corpus_selection",
            "upstream_failure_subcategory": reason,
        }
    if not spp_step:
        return {
            "qlip_request_attempted": False,
            "qlip_request_blocked_stage": "spp_generation",
            "qlip_request_blocked_reason": failure_code or "spp_not_run",
            "upstream_failure_category": "spp_generation_failed",
            "upstream_failure_subcategory": failure_code or "spp_not_run",
        }
    blocked_stage = str(spp_summary.get("qlip_request_blocked_stage") or "")
    blocked_reason = str(spp_summary.get("qlip_request_blocked_reason") or "")
    if blocked_stage or blocked_reason:
        return {
            "qlip_request_attempted": bool(spp_summary.get("qlip_request_attempted")),
            "qlip_request_blocked_stage": blocked_stage,
            "qlip_request_blocked_reason": blocked_reason,
            "upstream_failure_category": f"qlip_request_blocked_by_{blocked_stage}" if blocked_stage else "qlip_request_not_attempted_due_previous_stage",
            "upstream_failure_subcategory": blocked_reason,
        }
    if spp_step.get("status") in {"blocked", "failed"}:
        reason = str(spp_error.get("code") or failure_code or "spp_generation_failed")
        return {
            "qlip_request_attempted": False,
            "qlip_request_blocked_stage": "spp_generation",
            "qlip_request_blocked_reason": reason,
            "upstream_failure_category": "qlip_request_blocked_by_spp_generation",
            "upstream_failure_subcategory": reason,
        }
    if str(spp_summary.get("qlip_solve_compatible")).lower() == "false":
        return {
            "qlip_request_attempted": False,
            "qlip_request_blocked_stage": "missing_required_guidance",
            "qlip_request_blocked_reason": "qlip_package_not_solver_compatible",
            "upstream_failure_category": "qlip_request_blocked_by_missing_required_guidance",
            "upstream_failure_subcategory": "qlip_package_not_solver_compatible",
        }
    return {
        "qlip_request_attempted": False,
        "qlip_request_blocked_stage": "unknown",
        "qlip_request_blocked_reason": failure_code or "qlip_request_missing",
        "upstream_failure_category": "qlip_request_not_attempted_due_previous_stage",
        "upstream_failure_subcategory": failure_code or "qlip_request_missing",
    }


def _classify_failure(
    *,
    summary_run: Mapping[str, Any],
    retrieval_step: Mapping[str, Any],
    spp_step: Mapping[str, Any],
    validation_step: Mapping[str, Any],
    solve_step: Mapping[str, Any],
    semantic_count: int,
    exported_cifs: int,
    qlip_request: str,
    qlip_validation_status: str,
    qlip_solve_status: str,
    solution_produced: bool,
    used_fallback: bool,
    corpus_quality: str,
    vis_error: str,
    qlip_request_blocked_stage: str,
    qlip_request_blocked_reason: str,
) -> tuple[str, str]:
    if vis_error:
        return "visualisation_failed", vis_error
    if solution_produced and qlip_solve_status.upper() in {"OPTIMAL", "SUCCESS", "SUCCEEDED"}:
        return "success", ""
    failed_tool = str(summary_run.get("actual_failed_tool") or summary_run.get("failed_tool") or "")
    failure_code = str(summary_run.get("actual_failure_code") or summary_run.get("failure_code") or "")
    text = f"{failed_tool} {failure_code} {qlip_solve_status}".lower()
    if "gurobi" in text and "license" in text:
        return "gurobi_license_error", failure_code or "Gurobi license error reported."
    if not retrieval_step:
        return "retrieval_failed", failure_code or "Crystal-DB retrieval did not run."
    if semantic_count == 0 and exported_cifs == 0:
        return "insufficient_exportable_cifs", failure_code or "No semantic-neighbour CIFs were exported."
    if semantic_count == 0:
        return "insufficient_semantic_neighbours", failure_code or "No semantic neighbours were recorded."
    if not spp_step:
        return "spp_generation_failed", failure_code or "SPP/POT generation did not run."
    if used_fallback:
        return "spp_fallback_selected", "Fallback/precompiled POT package was selected."
    if "diagnostic" in corpus_quality.lower() or "unusable" in corpus_quality.lower():
        return "spp_quality_diagnostic_only", f"Fresh SPP quality is {corpus_quality}."
    if not qlip_request:
        blocked_map = {
            "corpus_selection": "qlip_request_blocked_by_corpus_selection",
            "spp_generation": "qlip_request_blocked_by_spp_generation",
            "missing_required_guidance": "qlip_request_blocked_by_missing_required_guidance",
            "unsupported_formula": "qlip_request_blocked_by_unsupported_formula",
            "builder_error": "qlip_request_builder_error",
            "backend_requires_pots": "qlip_request_blocked_by_backend_requires_pots",
        }
        category = blocked_map.get(qlip_request_blocked_stage, "qlip_request_not_attempted_due_previous_stage")
        return category, qlip_request_blocked_reason or failure_code or "No QLIP request path was recorded."
    if not validation_step or qlip_validation_status.lower() in {"failed", "blocked", "invalid"}:
        return "qlip_validation_failed", failure_code or f"QLIP validation status: {qlip_validation_status or 'missing'}."
    if solve_step and qlip_solve_status and qlip_solve_status.upper() not in {"OPTIMAL", "SUCCESS", "SUCCEEDED"}:
        return "qlip_solve_failed", failure_code or f"QLIP solve status: {qlip_solve_status}."
    if not solution_produced:
        return "final_cif_missing", failure_code or "No real solution CIF was produced."
    return "unknown_failure", failure_code or "Workflow did not produce classifiable success evidence."


def _copy_images_for_final_doc(out_root: Path, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    final_dir = out_root / "final_doc_images"
    final_dir.mkdir(parents=True, exist_ok=True)
    image_rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()

    def add(row: Mapping[str, Any], image_type: str, source_text: str, notes: str = "") -> None:
        if not source_text:
            return
        case_id = str(row.get("case_id") or "")
        short_name = str(row.get("short_name") or "")
        source = REPO_ROOT / source_text if not Path(source_text).is_absolute() else Path(source_text)
        counters[f"{case_id}_{image_type}"] += 1
        suffix = source.suffix or ".artifact"
        copied = final_dir / f"{_safe_slug(case_id)}_{_safe_slug(short_name)}_{image_type}_{counters[f'{case_id}_{image_type}']:02d}{suffix}"
        exists = source.exists()
        size = source.stat().st_size if exists else 0
        if exists:
            shutil.copy2(source, copied)
        image_rows.append(
            {
                "image_id": f"{_safe_slug(case_id)}_{image_type}_{counters[f'{case_id}_{image_type}']:02d}",
                "case_id": case_id,
                "short_name": short_name,
                "image_type": image_type,
                "source_path": _rel(source),
                "copied_path": _rel(copied) if exists else "",
                "exists": exists,
                "file_size_bytes": size,
                "notes": notes,
            }
        )

    for row in rows:
        add(row, "workflow_artifact_png", str(row.get("workflow_png_path") or ""))
        add(row, "workflow_artifact_svg", str(row.get("workflow_svg_path") or ""))
        add(row, "workflow_artifact_pdf", str(row.get("workflow_pdf_path") or ""))
        if row.get("solution_cif_produced"):
            manifest_path = row.get("visualisation_manifest_path")
            manifest = _read_json(REPO_ROOT / str(manifest_path)) if manifest_path else {}
            final_panel = _nested(manifest, "panels", "final_generated_crystal", default={}) or {}
            for key in ["image_path", "rendered_png_path", "final_crystal_png_path"]:
                add(row, "final_generated_crystal", str(final_panel.get(key) or ""), "Only copied when solution_cif_produced is true.")
        manifest_path = row.get("visualisation_manifest_path")
        manifest = _read_json(REPO_ROOT / str(manifest_path)) if manifest_path else {}
        sidecars = manifest.get("semantic_neighbours_sidecars") if isinstance(manifest.get("semantic_neighbours_sidecars"), Mapping) else {}
        for key in ["json_path", "csv_path"]:
            path_text = str(sidecars.get(key) or "")
            if path_text:
                add(row, f"semantic_neighbour_{key.replace('_path', '')}", _rel(path_text), "Semantic neighbour sidecar, not a rendered crystal image.")
    _write_json(final_dir / "final_doc_images_manifest.json", image_rows)
    _write_csv(final_dir / "final_doc_images_manifest.csv", image_rows, FINAL_DOC_IMAGE_COLUMNS)
    for row in rows:
        row["final_doc_images_count"] = sum(1 for image in image_rows if image["case_id"] == row.get("case_id") and image["exists"])
    return image_rows, {"missing": sum(1 for row in image_rows if not row["exists"]), "count": len(image_rows)}


def _write_robocrys_sidecar_manifests(out_root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sidecar_rows: list[dict[str, Any]] = []
    for row in rows:
        sidecar_rows.append(
            {
                "case_id": row.get("case_id", ""),
                "short_name": row.get("short_name", ""),
                "target_formula": row.get("target_formula", ""),
                "solution_cif_path": row.get("solution_cif_path", ""),
                "robocrys_available": row.get("generated_cif_robocrys_available", False),
                "description_path": row.get("generated_cif_robocrys_description_path", ""),
                "metadata_path": row.get("generated_cif_robocrys_metadata_path", ""),
                "condensed_path": row.get("generated_cif_robocrys_condensed_path", ""),
                "error": row.get("generated_cif_robocrys_error", ""),
                "warning_count": row.get("generated_cif_robocrys_warning_count", 0),
            }
        )
    manifests = out_root / "manifests"
    _write_json(manifests / "robocrys_sidecars_manifest.json", sidecar_rows)
    _write_csv(manifests / "robocrys_sidecars_manifest.csv", sidecar_rows, ROBOCRYS_SIDECAR_COLUMNS)
    return sidecar_rows


def _write_intent_validation_manifests(out_root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest_rows: list[dict[str, Any]] = []
    for row in rows:
        manifest_rows.append(
            {
                "case_id": row.get("case_id", ""),
                "short_name": row.get("short_name", ""),
                "target_formula": row.get("target_formula", ""),
                "available": row.get("robocrys_intent_validation_available", False),
                "alignment_score": row.get("robocrys_intent_alignment_score", ""),
                "judgement": row.get("robocrys_intent_judgement", ""),
                "skip_reason": row.get("robocrys_intent_skip_reason", ""),
                "validation_path": row.get("robocrys_intent_validation_path", ""),
                "validation_markdown_path": str(row.get("robocrys_intent_validation_path", "")).replace(".json", ".md")
                if row.get("robocrys_intent_validation_path")
                else "",
            }
        )
    manifests = out_root / "manifests"
    _write_json(manifests / "robocrys_intent_validation_manifest.json", manifest_rows)
    _write_csv(manifests / "robocrys_intent_validation_manifest.csv", manifest_rows, ROBOCRYS_INTENT_VALIDATION_COLUMNS)
    return manifest_rows


def _write_intent_alignment_summary(
    out_root: Path,
    validation_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]] | None = None,
) -> None:
    from sok_llm_orchestrator.agentic.robocrys_intent_validator import summarize_intent_validation_results

    manifest_rows = manifest_rows or []
    payloads: list[dict[str, Any]] = []
    for row in validation_rows:
        path_text = str(row.get("validation_path") or "")
        if not path_text:
            continue
        path = REPO_ROOT / path_text
        if path.is_file():
            payload = _read_json(path)
            payload["case_id"] = row.get("case_id", "")
            payload["short_name"] = row.get("short_name", "")
            payload["target_formula"] = row.get("target_formula", "")
            matching_manifest = next((item for item in manifest_rows if item.get("case_id") == row.get("case_id")), {})
            payload["intent_specificity"] = matching_manifest.get("intent_specificity", payload.get("intent_specificity", "medium"))
            payload["benchmark_split"] = matching_manifest.get("benchmark_split", payload.get("benchmark_split", "mixed_specificity"))
            payloads.append(payload)
    summary = summarize_intent_validation_results(payloads)
    solved_cases = sum(1 for row in manifest_rows if row.get("solution_cif_produced"))
    robocrys_descriptions = sum(1 for row in manifest_rows if row.get("generated_cif_robocrys_description_path"))
    source_counts = summary.get("decision_source_counts", {}) if isinstance(summary.get("decision_source_counts"), Mapping) else {}
    if summary.get("llm_judged_count", 0) and source_counts.get("rule_based"):
        score_basis = "mixed"
    elif summary.get("llm_judged_count", 0):
        score_basis = "llm_judge"
    elif summary.get("rule_based_scored_count", 0):
        score_basis = "rule_based_fallback"
    else:
        score_basis = "not_scored"
    summary.update(
        {
            "total_cases": len(manifest_rows) if manifest_rows else len(validation_rows),
            "solved_cases": solved_cases,
            "robocrys_descriptions_produced": robocrys_descriptions,
            "score_basis": score_basis,
        }
    )
    summary["warning"] = "Robocrys intent alignment is semantic/motif alignment only. It is not physical validation, experimental validation, or proof of thermodynamic stability."
    reports = out_root / "reports"
    _write_json(reports / "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.json", summary)
    skip_counts = summary.get("llm_skip_reasons") or summary.get("skip_reason_counts", {})
    lines = [
        "# Robocrys Intent Alignment Summary",
        "",
        f"- total cases: {summary.get('total_cases', 0)}",
        f"- solved cases: {summary.get('solved_cases', 0)}",
        f"- Robocrys descriptions produced: {summary.get('robocrys_descriptions_produced', 0)}",
        f"- scored count: {summary.get('scored_count', 0)}",
        f"- rule-based scored count: {summary.get('rule_based_scored_count', 0)}",
        f"- LLM judged count: {summary.get('llm_judged_count', 0)}",
        f"- correct count: {summary.get('correct_count', 0)}",
        f"- partially correct count: {summary.get('partially_correct_count', 0)}",
        f"- incorrect count: {summary.get('incorrect_count', 0)}",
        f"- not scored count: {summary.get('not_scored_count', 0)}",
        f"- score basis: {summary.get('score_basis', 'not_scored')}",
        f"- mean alignment score: {summary.get('mean_alignment_score', 0.0)}",
        f"- median alignment score: {summary.get('median_alignment_score', 0.0)}",
        f"- mean LLM score: {summary.get('mean_llm_score') if summary.get('mean_llm_score') is not None else 'N/A'}",
        f"- median LLM score: {summary.get('median_llm_score') if summary.get('median_llm_score') is not None else 'N/A'}",
        f"- mean rule-based score: {summary.get('mean_rule_based_score', 0.0)}",
        f"- explicit text match count: {summary.get('explicit_text_match_count', 0)}",
        f"- alias text match count: {summary.get('alias_text_match_count', 0)}",
        f"- implicit condensed match count: {summary.get('implicit_condensed_match_count', 0)}",
        f"- LLM skip reasons: {json.dumps(skip_counts, sort_keys=True)}",
        *([] if summary.get("llm_judged_count", 0) else ["- No live LLM judgements were produced."]),
        "",
        "## Performance By Intent Specificity",
        *[
            f"- {key}: {json.dumps(value, sort_keys=True)}"
            for key, value in sorted((summary.get("intent_specificity_counts") or {}).items())
        ],
        "",
        "## Performance By Benchmark Split",
        *[
            f"- {key}: {json.dumps(value, sort_keys=True)}"
            for key, value in sorted((summary.get("benchmark_split_counts") or {}).items())
        ],
        "",
        "## Common Missing Terms",
        *[f"- {term}: {count}" for term, count in summary.get("common_missing_terms", [])],
        "",
        "## Common Matched Terms",
        *[f"- {term}: {count}" for term, count in summary.get("common_matched_terms", [])],
        "",
        "## Important Limitation",
        "- This is semantic/motif alignment evidence only. It is not experimental validation, thermodynamic stability evidence, or proof of a new stable material.",
    ]
    (reports / "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (reports / "ROB0CRYS_INTENT_ALIGNMENT_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_json(reports / "ROB0CRYS_INTENT_ALIGNMENT_SUMMARY.json", summary)


def _backup_existing_robocrys_intent_reports(out_root: Path) -> list[str]:
    reports = out_root / "reports"
    suffix = time.strftime("%Y%m%d_%H%M%S")
    backed_up: list[str] = []
    for name in [
        "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.json",
        "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.md",
        "ROB0CRYS_INTENT_ALIGNMENT_SUMMARY.json",
        "ROB0CRYS_INTENT_ALIGNMENT_SUMMARY.md",
    ]:
        path = reports / name
        if not path.exists():
            continue
        backup = reports / f"{path.stem}.before_rescore_{suffix}{path.suffix}"
        shutil.copy2(path, backup)
        backed_up.append(_rel(backup))
    return backed_up


def _case_dir_from_manifest_row(out_root: Path, row: Mapping[str, Any]) -> Path:
    value = str(row.get("case_dir") or "")
    if value:
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate
        out_relative = out_root / candidate
        if out_relative.exists() or str(value).startswith("raw_runs"):
            return out_relative
        repo_relative = REPO_ROOT / candidate
        if repo_relative.exists():
            return repo_relative
    return out_root / "raw_runs" / _case_run_id(row)


def _robocrys_fields_from_manifest_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "generated_cif_robocrys_available": row.get("generated_cif_robocrys_available", False),
        "generated_cif_robocrys_description_path": row.get("generated_cif_robocrys_description_path", ""),
        "generated_cif_robocrys_metadata_path": row.get("generated_cif_robocrys_metadata_path", ""),
        "generated_cif_robocrys_condensed_path": row.get("generated_cif_robocrys_condensed_path", ""),
        "generated_cif_robocrys_error": row.get("generated_cif_robocrys_error", ""),
        "generated_cif_robocrys_warning_count": row.get("generated_cif_robocrys_warning_count", 0),
    }


def _rescore_existing_robocrys_intent(out_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    if not out_root.exists():
        raise FileNotFoundError(f"Existing output root not found for Robocrys intent rescore: {out_root}")
    print("NO_SOLVE_RESCORE_MODE: QLIP solve disabled")
    manifest_rows = _load_manifest_rows(out_root)
    if not manifest_rows:
        raise FileNotFoundError(f"No manifest rows found under {out_root}")
    if args.require_llm_intent_judge and not args.llm_robocrys_intent_judge:
        raise ValueError("--require-llm-intent-judge requires --llm-robocrys-intent-judge.")
    llm_model_config = _llm_intent_judge_config(args)
    if args.require_llm_intent_judge and not llm_model_config.get("client"):
        raise RuntimeError(str(llm_model_config.get("skip_reason") or "llm_judge_unavailable"))
    backups = _backup_existing_robocrys_intent_reports(out_root)
    rescored_rows: list[dict[str, Any]] = []
    for row in manifest_rows:
        updated = dict(row)
        case_dir = _case_dir_from_manifest_row(out_root, updated)
        query_metadata = _read_json(case_dir / "crystal_db_query.json")
        robocrys_fields = _robocrys_fields_from_manifest_row(updated)
        if (
            not robocrys_fields.get("generated_cif_robocrys_description_path")
            and args.describe_generated_cifs_with_robocrys
            and updated.get("solution_cif_path")
        ):
            robocrys_fields = _write_generated_cif_robocrys_sidecars(
                case_dir,
                str(updated.get("solution_cif_path") or ""),
                strict=bool(args.require_robocrys),
                robocrys_python=args.robocrys_python,
            )
            updated.update(robocrys_fields)
        intent_fields = _write_robocrys_intent_validation_sidecars(
            case_dir,
            updated,
            query_metadata,
            robocrys_fields,
            llm_judge_enabled=bool(args.llm_robocrys_intent_judge),
            llm_model_config=llm_model_config,
        )
        updated.update(intent_fields)
        rescored_rows.append(updated)
    intent_validation_rows = _write_intent_validation_manifests(out_root, rescored_rows)
    _write_intent_alignment_summary(out_root, intent_validation_rows, rescored_rows)
    _write_robocrys_intent_examples(out_root, rescored_rows)
    _write_master_manifests(out_root, rescored_rows)
    _write_json(
        out_root / "logs" / "robocrys_intent_rescore.json",
        {
            "mode": "NO_SOLVE_RESCORE_MODE",
            "qlip_solve_disabled": True,
            "llm_judge_enabled": bool(args.llm_robocrys_intent_judge),
            "llm_backend": args.llm_intent_judge_backend,
            "llm_model": args.llm_intent_judge_model,
            "backups": backups,
            "rescored_rows": len(rescored_rows),
        },
    )
    summary = _read_json(out_root / "reports" / "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.json")
    return {
        "out_root": _rel(out_root),
        "mode": "NO_SOLVE_RESCORE_MODE",
        "qlip_solve_disabled": True,
        "rescored_rows": len(rescored_rows),
        "backups": backups,
        "llm_judged_count": summary.get("llm_judged_count", 0),
        "mean_llm_score": summary.get("mean_llm_score"),
        "judgement_counts": summary.get("judgement_counts", {}),
        "summary_json": _rel(out_root / "reports" / "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.json"),
        "summary_md": _rel(out_root / "reports" / "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.md"),
    }


def _write_spp_objective_audit_summary(out_root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit_rows: list[dict[str, Any]] = []
    for row in rows:
        audit_path = row.get("spp_objective_audit_path", "")
        payload = _read_json(REPO_ROOT / audit_path) if audit_path else {}
        summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else payload
        if not isinstance(summary, Mapping):
            summary = {}
        supported = summary.get("pair_types_supported_by_spp", [])
        missing = summary.get("missing_pair_types", [])
        audit_rows.append(
            {
                "case_id": row.get("case_id", ""),
                "short_name": row.get("short_name", ""),
                "target_formula": row.get("target_formula", ""),
                "status": row.get("status", ""),
                "failure_category": row.get("failure_category", ""),
                "available": bool(row.get("spp_objective_audit_available")),
                "audit_path": audit_path,
                "error": row.get("spp_objective_audit_error", "") or summary.get("error", ""),
                "qlip_objective": summary.get("qlip_objective", row.get("qlip_objective", "")),
                "guidance_weight": summary.get("guidance_weight", ""),
                "cutoff": summary.get("cutoff", ""),
                "missing_pair_policy": summary.get("missing_pair_policy", ""),
                "regularisation_spp_dir": summary.get("regularisation_spp_dir", ""),
                "regularisation_weight": summary.get("regularisation_weight", ""),
                "regularisation_enabled": summary.get("regularisation_enabled", ""),
                "regularisation_pairs_loaded": summary.get("regularisation_pairs_loaded", ""),
                "regularisation_contribution_count": summary.get("regularisation_contribution_count", ""),
                "total_spp_score": summary.get("total_spp_score", ""),
                "weighted_total_score": summary.get("weighted_total_score", ""),
                "shortest_contact": summary.get("shortest_contact", ""),
                "explicit_spp_contribution_count": summary.get("explicit_spp_contribution_count", ""),
                "missing_pair_fallback_contribution_count": summary.get("missing_pair_fallback_contribution_count", ""),
                "no_contribution_count": summary.get("no_contribution_count", ""),
                "supported_pair_type_count": len(supported) if isinstance(supported, list) else "",
                "missing_pair_type_count": len(missing) if isinstance(missing, list) else "",
            }
        )
    _write_csv(out_root / "manifests" / "spp_objective_audit.csv", audit_rows, SPP_OBJECTIVE_AUDIT_COLUMNS)
    _write_json(out_root / "reports" / "SPP_OBJECTIVE_AUDIT_SUMMARY.json", {"rows": audit_rows})
    available = [row for row in audit_rows if row["available"]]
    missing_sources = Counter(
        "fallback"
        if int(row.get("missing_pair_fallback_contribution_count") or 0)
        else "none"
        if int(row.get("no_contribution_count") or 0)
        else "explicit_only"
        for row in available
    )
    lines = [
        "# SPP Objective Audit Summary",
        "",
        "This report diagnoses SPP objective visibility, missing-pair handling, and guidance weighting. It is not physical validation.",
        "",
        f"- Total rows: {len(audit_rows)}",
        f"- Audit sidecars available: {len(available)}",
        f"- Audit sidecars unavailable: {len(audit_rows) - len(available)}",
        "",
        "## Missing-Pair Contribution Modes",
        *[f"- {key}: {value}" for key, value in sorted(missing_sources.items())],
        "",
        "## Shortest Contacts",
        "",
        "| case_id | formula | policy | weight | reg_weight | reg_pairs | shortest_contact | explicit_terms | regularisation_terms | missing_fallback_terms | no_contribution_terms |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in sorted(available, key=lambda r: float(r["shortest_contact"] or 9999))[:20]:
        lines.append(
            f"| {item['case_id']} | {item['target_formula']} | {item['missing_pair_policy']} | "
            f"{item['guidance_weight']} | {item['regularisation_weight']} | {item['regularisation_pairs_loaded']} | "
            f"{item['shortest_contact']} | {item['explicit_spp_contribution_count']} | "
            f"{item['regularisation_contribution_count']} | {item['missing_pair_fallback_contribution_count']} | {item['no_contribution_count']} |"
        )
    (out_root / "reports" / "SPP_OBJECTIVE_AUDIT_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return audit_rows


def _write_robocrys_intent_examples(out_root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for row in rows:
        description_path = str(row.get("generated_cif_robocrys_description_path") or "")
        description = ""
        if description_path:
            path = REPO_ROOT / description_path
            if path.is_file():
                description = path.read_text(encoding="utf-8", errors="ignore")
        query_sidecar = _read_json(out_root / str(row.get("case_dir", "")) / "crystal_db_query.json") if row.get("case_dir") else {}
        qlip_guidance_mode = ""
        qlip_request = _read_json(REPO_ROOT / str(row.get("qlip_request_path", ""))) if row.get("qlip_request_path") else {}
        guidance = qlip_request.get("guidance") if isinstance(qlip_request.get("guidance"), list) else []
        for item in guidance:
            if isinstance(item, Mapping):
                params = item.get("params") if isinstance(item.get("params"), Mapping) else {}
                mode = str(params.get("mode") or "")
                if mode == "partial":
                    qlip_guidance_mode = "partial_spp"
                    break
                if mode in {"complete", "strict"}:
                    qlip_guidance_mode = "complete_spp"
        if not qlip_guidance_mode:
            qlip_guidance_mode = "no_spp" if row.get("qlip_request_path") else ""
        examples.append(
            {
                "case_id": row.get("case_id", ""),
                "short_name": row.get("short_name", ""),
                "target_formula": row.get("target_formula", ""),
                "chemistry_family": row.get("chemistry_family", ""),
                "challenge_type": row.get("challenge_type", ""),
                "original_query": row.get("query", ""),
                "crystal_db_retrieval_query": query_sidecar.get("crystal_db_retrieval_query", row.get("crystal_db_retrieval_query", "")),
                "compact_retrieval_query": query_sidecar.get("compact_retrieval_query", ""),
                "pair_evidence_query": query_sidecar.get("pair_evidence_query", ""),
                "final_cif_path": row.get("solution_cif_path", ""),
                "generated_cif_robocrys_description_path": description_path,
                "generated_cif_robocrys_description": description,
                "generated_cif_robocrys_condensed_path": row.get("generated_cif_robocrys_condensed_path", ""),
                "qlip_guidance_mode": qlip_guidance_mode,
                "status": row.get("status", ""),
                "notes": row.get("generated_cif_robocrys_error", ""),
            }
        )
    manifests = out_root / "manifests"
    jsonl_path = manifests / "robocrys_intent_examples.jsonl"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in examples) + ("\n" if examples else ""), encoding="utf-8")
    _write_csv(manifests / "robocrys_intent_examples.csv", examples, ROBOCRYS_INTENT_EXAMPLE_COLUMNS)
    return examples


class _OllamaIntentJudgeClient:
    def __init__(self, base_url: str, model: str, timeout_s: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = float(timeout_s)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
        }
        options: dict[str, Any] = {}
        if isinstance(temperature, (int, float)):
            options["temperature"] = float(temperature)
        if isinstance(max_tokens, int) and max_tokens > 0:
            options["num_predict"] = int(max_tokens)
        if options:
            payload["options"] = options
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            response = json.loads(resp.read().decode("utf-8"))
        content = ""
        if isinstance(response, Mapping):
            message = response.get("message") if isinstance(response.get("message"), Mapping) else {}
            content = str(message.get("content") or response.get("response") or "")
        return {"choices": [{"message": {"content": content}}], "ollama_response": response}


def _normalise_openai_base_url(url: str) -> str:
    value = str(url or "").rstrip("/")
    suffix = "/chat/completions"
    if value.endswith(suffix):
        value = value[: -len(suffix)]
    if value.endswith("/v1"):
        return value
    if value.endswith("/v1/"):
        return value.rstrip("/")
    return value


def _default_llm_url_for_backend(backend: str, settings_url: str) -> str:
    if backend == "ollama":
        return "http://localhost:11434"
    if backend in {"lmstudio", "openai_compatible"}:
        return settings_url or "http://localhost:1234/v1"
    return settings_url or "http://localhost:1234/v1"


def _ollama_model_names(url: str, timeout_s: float) -> tuple[list[str], str]:
    try:
        req = urllib.request.Request(f"{str(url).rstrip('/')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        models = payload.get("models") if isinstance(payload, Mapping) else []
        names = [
            str(item.get("name") or item.get("model"))
            for item in models
            if isinstance(item, Mapping) and (item.get("name") or item.get("model"))
        ]
        return sorted(set(names)), ""
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"


def _llm_intent_judge_config(args: argparse.Namespace, *, force: bool = False) -> dict[str, Any]:
    if not force and not args.llm_robocrys_intent_judge:
        return {}
    try:
        from sok_llm_orchestrator.config import Settings
        from sok_llm_orchestrator.llm.client import LLMClient

        settings = Settings.from_sources()
        backend = str(args.llm_intent_judge_backend or "ollama").lower()
        url = args.llm_intent_judge_url or _default_llm_url_for_backend(backend, settings.llm_base_url)
        model = args.llm_intent_judge_model or settings.llm_model
        timeout_s = float(args.llm_intent_judge_timeout_s or settings.llm_timeout_s)
        if backend == "ollama":
            models, tags_error = _ollama_model_names(url, timeout_s)
            if model and model not in models and models:
                return {
                    "client": None,
                    "skip_reason": "llm_judge_unavailable:model_not_found",
                    "backend": backend,
                    "url": url,
                    "model": model,
                    "models_available": models,
                    "model_found": False,
                    "tags_error": tags_error,
                }
            if not model:
                if len(models) == 1:
                    model = models[0]
                else:
                    return {
                        "client": None,
                        "skip_reason": "llm_judge_unavailable:model_not_configured",
                        "backend": backend,
                        "url": url,
                        "model": "",
                        "models_available": models,
                        "model_found": False,
                        "tags_error": tags_error,
                    }
            client = _OllamaIntentJudgeClient(url, model, timeout_s)
            return {
                "client": client,
                "backend": backend,
                "url": url,
                "model": model,
                "timeout_s": timeout_s,
                "models_available": models,
                "model_found": model in models if models else False,
                "tags_error": tags_error,
            }
        if backend in {"existing", "lmstudio", "openai_compatible"}:
            if not model:
                return {"client": None, "skip_reason": "llm_judge_unavailable:model_missing", "backend": backend, "url": url, "model": ""}
            base_url = _normalise_openai_base_url(url)
            api_key = settings.llm_api_key or ("local" if "localhost" in base_url or "127.0.0.1" in base_url else None)
            if not api_key:
                return {"client": None, "skip_reason": "llm_judge_unavailable:api_key_missing", "backend": backend, "url": base_url, "model": model}
            client = LLMClient(base_url=base_url, api_key=api_key, model=model, timeout_s=int(timeout_s), max_retries=1)
            return {"client": client, "backend": backend, "url": base_url, "model": model, "timeout_s": timeout_s}
        return {"client": None, "skip_reason": f"llm_judge_unavailable:unsupported_backend:{backend}", "backend": backend, "url": url, "model": model}
    except Exception as exc:  # noqa: BLE001
        if args.require_llm_intent_judge:
            raise
        return {"client": None, "skip_reason": f"llm_judge_unavailable:{type(exc).__name__}: {exc}"}


def _write_llm_intent_judge_preflight(out_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    from sok_llm_orchestrator.agentic.robocrys_intent_validator import judge_robocrys_intent_alignment_with_llm

    config = _llm_intent_judge_config(args, force=True)
    client = config.get("client")
    backend = str(config.get("backend") or args.llm_intent_judge_backend or "ollama")
    url = str(config.get("url") or args.llm_intent_judge_url or "")
    model = str(config.get("model") or args.llm_intent_judge_model or "")
    result: dict[str, Any] = {
        "backend_configured": bool(client),
        "backend_type": backend,
        "endpoint_url": url,
        "model": model,
        "reachable": False,
        "models_available": config.get("models_available", []),
        "model_found": bool(config.get("model_found")),
        "test_prompt_succeeded": False,
        "json_parse_succeeded": False,
        "latency_seconds": 0.0,
        "available": False,
        "error": config.get("skip_reason", ""),
        "note": "Ollama is preferred for LLM text judging. LM Studio/OpenAI-compatible judging remains available when explicitly selected.",
    }
    if client:
        started = time.monotonic()
        judgement = judge_robocrys_intent_alignment_with_llm(
            original_query="Generate BaTiO3 perovskite with TiO6 octahedra.",
            crystal_db_retrieval_query="BaTiO3 perovskite structured oxide with TiO6 octahedra and corner-sharing octahedra.",
            generated_cif_robocrys_description="BaTiO3 is Perovskite structured. Ti is bonded to six O atoms to form TiO6 octahedra.",
            target_formula="BaTiO3",
            chemistry_family="oxide_perovskite",
            expected_motifs_or_priors="TiO6 octahedra; perovskite",
            model_config=config,
        )
        result["latency_seconds"] = round(time.monotonic() - started, 3)
        result["reachable"] = judgement.get("skip_reason") not in {"llm_judge_unavailable"}
        result["test_prompt_succeeded"] = bool(judgement.get("raw_response")) or bool(judgement.get("available"))
        result["json_parse_succeeded"] = bool(judgement.get("available"))
        result["available"] = bool(judgement.get("available"))
        result["error"] = "" if judgement.get("available") else str(judgement.get("skip_reason") or judgement.get("explanation") or "")
        result["preflight_judgement"] = {key: value for key, value in judgement.items() if key not in {"prompt", "raw_response"}}
    reports = out_root / "reports"
    _write_json(reports / "LLM_INTENT_JUDGE_PREFLIGHT.json", result)
    lines = [
        "# LLM Intent Judge Preflight",
        "",
        f"- backend configured: {result['backend_configured']}",
        f"- backend type: {result['backend_type']}",
        f"- endpoint/url: {result['endpoint_url']}",
        f"- model: {result['model']}",
        f"- reachable: {result['reachable']}",
        f"- models available: {json.dumps(result['models_available'])}",
        f"- model found: {result['model_found']}",
        f"- test prompt succeeded: {result['test_prompt_succeeded']}",
        f"- JSON parse succeeded: {result['json_parse_succeeded']}",
        f"- latency seconds: {result['latency_seconds']}",
        f"- available: {result['available']}",
        f"- error: {result['error']}",
        "",
        "Ollama is preferred for LLM text judging. LM Studio/OpenAI-compatible judging is still supported when explicitly selected.",
    ]
    (reports / "LLM_INTENT_JUDGE_PREFLIGHT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def _missing_manifest_path_count(rows: list[dict[str, Any]]) -> int:
    path_fields = [
        "qlip_request_path",
        "solution_cif_path",
        "workflow_png_path",
        "workflow_svg_path",
        "workflow_pdf_path",
        "visualisation_manifest_path",
        "spp_objective_audit_path",
    ]
    missing = 0
    for row in rows:
        for field in path_fields:
            value = str(row.get(field) or "")
            if value and not (REPO_ROOT / value).exists() and not Path(value).exists():
                missing += 1
    return missing


def _write_master_manifests(out_root: Path, rows: list[dict[str, Any]]) -> None:
    _write_json(
        out_root / "manifests" / "paper_evidence_pack_v2_manifest.json",
        {"schema_version": "paper_evidence_pack.v2", "rows": rows, "failure_categories": sorted(FAILURE_CATEGORIES)},
    )
    _write_csv(out_root / "manifests" / "paper_evidence_pack_v2_manifest.csv", rows, MANIFEST_COLUMNS)


def _write_summary_report(
    out_root: Path,
    *,
    total_csv_rows: int,
    requested_cases: int,
    rows: list[dict[str, Any]],
    final_doc_count: int,
    missing_path_count: int,
) -> None:
    categories = Counter(str(row.get("failure_category") or "unknown_failure") for row in rows)
    families = Counter(str(row.get("chemistry_family") or "unknown") for row in rows)
    challenge_types = Counter(str(row.get("challenge_type") or "unknown") for row in rows)
    qlip_statuses = Counter(str(row.get("qlip_solve_status") or "missing") for row in rows)
    fresh = sum(1 for row in rows if "fresh" in str(row.get("selected_pot_root_kind", "")).lower())
    fallback = sum(1 for row in rows if row.get("used_fallback_pots") is True)
    diagnostic = sum(1 for row in rows if row.get("failure_category") == "spp_quality_diagnostic_only")
    pot_missing = sum(1 for row in rows if not row.get("selected_pot_root"))
    png_count = sum(1 for row in rows if row.get("workflow_png_path"))
    svg_count = sum(1 for row in rows if row.get("workflow_svg_path"))
    pdf_count = sum(1 for row in rows if row.get("workflow_pdf_path"))
    successes = [row for row in rows if row.get("failure_category") == "success"]
    failures = [row for row in rows if row.get("failure_category") != "success"]

    def lines_for(counter: Counter[str]) -> list[str]:
        return [f"- {key}: {value}" for key, value in sorted(counter.items())]

    report = [
        "# Paper Evidence Pack V2 Summary",
        "",
        "This challenge suite is evidence generation and workflow stress-testing. It is not experimental validation or proof of new stable materials.",
        "",
        f"- Total CSV rows: {total_csv_rows}",
        f"- Total requested cases: {requested_cases}",
        f"- Total attempted cases: {len(rows)}",
        f"- Total successes: {len(successes)}",
        f"- Total failed/diagnostic cases: {len(failures)}",
        "",
        "## Failure category counts",
        *lines_for(categories),
        "",
        "## Chemistry family counts",
        *lines_for(families),
        "",
        "## Challenge type counts",
        *lines_for(challenge_types),
        "",
        "## QLIP status counts",
        *lines_for(qlip_statuses),
        "",
        "## SPP selected package summary",
        f"- fresh selected: {fresh}",
        f"- fallback selected: {fallback}",
        f"- diagnostic-only: {diagnostic}",
        f"- missing: {pot_missing}",
        "",
        "## Artifact counts",
        f"- workflow PNG files produced: {png_count}",
        f"- workflow SVG files produced: {svg_count}",
        f"- workflow PDF files produced: {pdf_count}",
        f"- final_doc_images files: {final_doc_count}",
        f"- missing file count from manifest paths: {missing_path_count}",
        "",
        "## Top successful cases",
        *[f"- {row['case_id']} {row['short_name']}: QLIP={row['qlip_solve_status']} CIF={row['solution_cif_path']}" for row in successes[:10]],
        *([] if successes else ["- none"]),
        "",
        "## Representative failed cases",
        *[f"- {row['case_id']} {row['short_name']}: {row['failure_category']} - {row['failure_message']}" for row in failures[:10]],
        *([] if failures else ["- none"]),
        "",
        "## Safe claims",
        "- The CSV-driven runner records natural-language inputs, retrieval/SPP/QLIP evidence, generated figures, and failure categories.",
        "- Successful cases can be described as solver-backed only when `solution_cif_produced` is true and QLIP reports a successful solve status.",
        "",
        "## Claims not safe",
        "- Do not claim experimental validation, DFT validation, thermodynamic stability, or discovery of new stable materials from this evidence pack alone.",
        "- Do not count fallback or diagnostic-only SPP/POT cases as fresh calibrated predictor success.",
    ]
    (out_root / "reports").mkdir(parents=True, exist_ok=True)
    (out_root / "reports" / "PAPER_EVIDENCE_PACK_V2_SUMMARY.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def _write_failure_analysis(out_root: Path, rows: list[dict[str, Any]]) -> Path:
    reports = out_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    categories = Counter(str(row.get("failure_category") or "unknown_failure") for row in rows)
    blocked = Counter(
        str(row.get("qlip_request_blocked_stage") or "not_blocked")
        for row in rows
        if not row.get("qlip_request_path")
    )
    def cases_for(category: str) -> list[str]:
        return [
            f"- {row.get('case_id')} {row.get('short_name')}: {row.get('upstream_failure_subcategory') or row.get('failure_message')}"
            for row in rows
            if row.get("failure_category") == category
        ][:30] or ["- none"]

    fallback_cases = [
        f"- {row.get('case_id')} {row.get('short_name')}: {row.get('selected_pot_root_kind')}"
        for row in rows
        if row.get("used_fallback_pots") is True
    ][:50] or ["- none"]
    diagnostic_cases = [
        f"- {row.get('case_id')} {row.get('short_name')}: {row.get('fresh_spp_quality')}"
        for row in rows
        if row.get("failure_category") == "spp_quality_diagnostic_only"
    ][:50] or ["- none"]
    report = [
        "# Paper Evidence Pack V2 Failure Analysis",
        "",
        "This report separates scientific/data-coverage failures from implementation failures. Missing pair evidence, diagnostic-only SPP packages, and blocked QLIP requests are not QLIP solve failures.",
        "",
        "## Top Failure Categories",
        *[f"- {key}: {value}" for key, value in sorted(categories.items())],
        "",
        "## QLIP Request Blocked Stages",
        *[f"- {key}: {value}" for key, value in sorted(blocked.items())],
        "",
        "## spp_generation_failed Cases",
        *cases_for("spp_generation_failed"),
        "",
        "## qlip_validation_failed Cases",
        *cases_for("qlip_validation_failed"),
        "",
        "## qlip_solve_failed Cases",
        *cases_for("qlip_solve_failed"),
        "",
        "## final_cif_missing Cases",
        *cases_for("final_cif_missing"),
        "",
        "## Fallback POT Cases",
        *fallback_cases,
        "",
        "## Diagnostic-only SPP/POT Cases",
        *diagnostic_cases,
        "",
        "## Interpretation Notes",
        "- Expected data-coverage failures include unsupported chemistries, missing required pairs, no exportable CIFs, and diagnostic-only partial SPP packages.",
        "- Implementation bugs are indicated by workflow_command_failed, qlip_request_builder_error, uncontrolled exceptions, or missing manifest paths without an explicit reason.",
        "- qlip_request_missing is decomposed by qlip_request_blocked_stage and qlip_request_blocked_reason for new/updated rows.",
    ]
    path = reports / "PAPER_EVIDENCE_PACK_V2_FAILURE_ANALYSIS.md"
    path.write_text("\n".join(report) + "\n", encoding="utf-8")
    return path


def _load_manifest_rows(out_root: Path) -> list[dict[str, Any]]:
    manifest_path = out_root / "manifests" / "paper_evidence_pack_v2_manifest.json"
    payload = _read_json(manifest_path)
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _support_manifest_fields(support: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "support_classification": support.get("support_classification", ""),
        "missing_pairs": support.get("missing_pairs", []),
        "exportable_pair_support_counts": support.get("exportable_pair_support_counts", {}),
        "exact_formula_count": support.get("exact_formula_count", 0),
        "same_chemsys_count": support.get("same_chemsys_count", 0),
        "recommendation": support.get("recommendation", ""),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    csv_path = (REPO_ROOT / args.csv).resolve() if not Path(args.csv).is_absolute() else Path(args.csv)
    out_root = (REPO_ROOT / args.out_root).resolve() if not Path(args.out_root).is_absolute() else Path(args.out_root)
    if args.rescore_existing_robocrys_intent:
        return _rescore_existing_robocrys_intent(out_root, args)
    _prepare_out_root(out_root, overwrite=args.overwrite_v2, resume=args.resume, skip_existing=args.skip_existing)
    rows, validation_failures, missing_columns = _load_csv(csv_path)
    selected = _select_rows(rows, offset=args.offset, limit=args.limit, case_id=args.case_id)
    db_path = Path(args.crystal_db_path) if args.crystal_db_path else _default_crystal_db_path()
    if not db_path.is_absolute():
        db_path = (REPO_ROOT / db_path).resolve()
    if args.failure_audit_only:
        manifest_rows = _load_manifest_rows(out_root)
        path = _write_failure_analysis(out_root, manifest_rows)
        return {"out_root": _rel(out_root), "failure_analysis_path": _rel(path), "rows": len(manifest_rows)}
    if args.skip_robocrys and args.require_robocrys:
        raise ValueError("--skip-robocrys and --require-robocrys cannot be used together.")
    if args.require_robocrys_intent_validation and not args.validate_robocrys_intent_alignment:
        raise ValueError("--require-robocrys-intent-validation requires --validate-robocrys-intent-alignment.")
    if args.require_llm_intent_judge and not args.llm_robocrys_intent_judge:
        raise ValueError("--require-llm-intent-judge requires --llm-robocrys-intent-judge.")
    if args.llm_intent_judge_preflight_only:
        preflight = _write_llm_intent_judge_preflight(out_root, args)
        return {
            "out_root": _rel(out_root),
            "llm_intent_judge_preflight": preflight,
            "preflight_json": _rel(out_root / "reports" / "LLM_INTENT_JUDGE_PREFLIGHT.json"),
            "preflight_md": _rel(out_root / "reports" / "LLM_INTENT_JUDGE_PREFLIGHT.md"),
        }
    llm_model_config = _llm_intent_judge_config(args)
    if args.require_llm_intent_judge and not llm_model_config.get("client"):
        raise RuntimeError(str(llm_model_config.get("skip_reason") or "llm_judge_unavailable"))
    support_by_case: dict[str, dict[str, Any]] = {}
    if args.capability_audit_only or args.preflight_support_only:
        audit = _write_capability_audit(out_root, rows, db_path=db_path)
        if args.capability_audit_only or args.preflight_support_only:
            return {
                "out_root": _rel(out_root),
                "capability_audit_json": _rel(out_root / "reports" / "CRYSTAL_DB_CAPABILITY_AUDIT.json"),
                "support_classification": dict(Counter(item["support_classification"] for item in audit["challenge_support"])),
            }
    if args.allow_partial_pair_evidence or args.allow_qlip_without_spp:
        audit = build_crystal_db_capability_audit(rows, db_path=db_path)
        support_by_case = {str(item["case_id"]): item for item in audit["challenge_support"]}
    query_metadata_by_case: dict[str, dict[str, Any]] = {}
    if args.use_robocrys_query_skill:
        for row in selected:
            query_metadata_by_case[str(row.get("case_id", ""))] = _query_metadata_for_row(row)
    command = vars(args).copy()
    command["csv"] = _rel(csv_path)
    command["out_root"] = _rel(out_root)

    manifest_rows: list[dict[str, Any]] = []
    for failure in validation_failures:
        case_dir = out_root / "raw_runs" / _case_run_id(failure)
        case_dir.mkdir(parents=True, exist_ok=True)
        _write_case_sidecars(case_dir, failure, command=command, status={"status": "input_validation_failed"})
        row = _empty_manifest_row(
            failure,
            case_dir,
            status="failed",
            category="input_validation_failed",
            message=failure["message"],
            out_root=out_root,
        )
        _write_failure_summary(case_dir, row)
        manifest_rows.append(row)

    valid_selected = [row for row in selected if row.get("case_id") not in {failure["case_id"] for failure in validation_failures} and not missing_columns]
    if args.dry_run:
        for row in valid_selected:
            case_dir = out_root / "raw_runs" / _case_run_id(row)
            case_dir.mkdir(parents=True, exist_ok=True)
            _write_case_sidecars(case_dir, row, command=command, status={"status": "dry_run", "workflow_executed": False})
            query_metadata = query_metadata_by_case.get(str(row.get("case_id", "")))
            _write_crystal_db_query_sidecar(case_dir, row, query_metadata)
            dry_row = _empty_manifest_row(
                row,
                case_dir,
                status="dry_run",
                category="unknown_failure",
                message="Dry run: workflow not executed.",
                out_root=out_root,
            )
            if args.validate_robocrys_intent_alignment:
                intent_fields = _write_robocrys_intent_validation_sidecars(
                    case_dir,
                    row,
                    query_metadata,
                    _robocrys_empty_fields("no_solution_cif"),
                    llm_judge_enabled=bool(args.llm_robocrys_intent_judge),
                    llm_model_config=llm_model_config,
                )
                dry_row.update(intent_fields)
            if query_metadata:
                dry_row.update(
                    {
                        "crystal_db_retrieval_query": query_metadata.get("crystal_db_retrieval_query", ""),
                        "query_style": query_metadata.get("query_style", ""),
                        "query_skill_version": query_metadata.get("skill_version", ""),
                    }
                )
            if row.get("case_id") in support_by_case:
                dry_row.update(_support_manifest_fields(support_by_case[row["case_id"]]))
            _write_failure_summary(case_dir, dry_row)
            manifest_rows.append(dry_row)
    elif valid_selected:
        suite_path = out_root / "manifests" / "paper_evidence_pack_v2_suite.json"
        _write_json(suite_path, _suite_payload(valid_selected, query_metadata_by_case))
        started = time.monotonic()
        run_paper_smoke_suite = _load_run_paper_smoke_suite()
        old_env = {
            key: os.environ.get(key)
            for key in [
                "SKILL_LOOP_ALLOW_QLIP_WITHOUT_SPP",
                "SKILL_LOOP_ALLOW_PARTIAL_SPP_GUIDANCE",
                "SKILL_LOOP_SPP_MISSING_PAIR_POLICY",
                "SKILL_LOOP_SPP_GUIDANCE_WEIGHT",
                "SKILL_LOOP_SPP_WEIGHTING_PROFILE",
                "SKILL_LOOP_SPP_REGULARISATION_DIR",
                "SKILL_LOOP_SPP_REGULARIZATION_DIR",
                "SKILL_LOOP_SPP_REGULARISATION_WEIGHT",
                "SKILL_LOOP_SPP_REGULARIZATION_WEIGHT",
                "SKILL_LOOP_FORCE_CUBIC_LATTICE_TEMPLATE",
                "SKILL_LOOP_CUBIC_LATTICE_A",
            ]
        }
        if args.allow_qlip_without_spp:
            os.environ["SKILL_LOOP_ALLOW_QLIP_WITHOUT_SPP"] = "1"
        if args.allow_partial_spp_guidance:
            os.environ["SKILL_LOOP_ALLOW_PARTIAL_SPP_GUIDANCE"] = "1"
            os.environ["SKILL_LOOP_SPP_MISSING_PAIR_POLICY"] = args.spp_missing_pair_policy
        spp_weight = float(args.spp_guidance_weight) * float(args.spp_guidance_weight_scale)
        if args.spp_weighting_profile != "custom":
            profile_weights = {"default": 1.0, "moderate": 3.0, "strong": 10.0, "very_strong": 30.0}
            spp_weight = profile_weights.get(args.spp_weighting_profile, spp_weight)
        os.environ["SKILL_LOOP_SPP_GUIDANCE_WEIGHT"] = str(spp_weight)
        os.environ["SKILL_LOOP_SPP_WEIGHTING_PROFILE"] = str(args.spp_weighting_profile)
        if args.spp_regularisation_dir:
            os.environ["SKILL_LOOP_SPP_REGULARISATION_DIR"] = str(args.spp_regularisation_dir)
            os.environ["SKILL_LOOP_SPP_REGULARIZATION_DIR"] = str(args.spp_regularisation_dir)
        os.environ["SKILL_LOOP_SPP_REGULARISATION_WEIGHT"] = str(args.spp_regularisation_weight)
        os.environ["SKILL_LOOP_SPP_REGULARIZATION_WEIGHT"] = str(args.spp_regularisation_weight)
        if args.force_cubic_lattice_template:
            os.environ["SKILL_LOOP_FORCE_CUBIC_LATTICE_TEMPLATE"] = "1"
            os.environ["SKILL_LOOP_CUBIC_LATTICE_A"] = str(args.cubic_lattice_a)
        try:
            result = run_paper_smoke_suite(suite_json=suite_path, out_dir=out_root / "raw_runs", mcp_backend="configured")
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else _read_json(out_root / "raw_runs" / "suite_summary.json")
        run_by_id = {str(item.get("run_id")): item for item in summary.get("runs", []) if isinstance(item, Mapping)}
        for row in valid_selected:
            case_dir = out_root / "raw_runs" / _case_run_id(row)
            _write_case_sidecars(case_dir, row, command=command, status={"status": "attempted", "workflow_executed": True})
            query_metadata = query_metadata_by_case.get(str(row.get("case_id", "")))
            _write_crystal_db_query_sidecar(case_dir, row, query_metadata)
            if args.skip_existing and (case_dir / "failure_summary.json").exists():
                continue
            case_started = time.monotonic()
            try:
                case_row = _summarise_case(
                        row,
                        run_by_id.get(_case_run_id(row), {}),
                        out_root / "raw_runs",
                        out_root,
                        runtime=time.monotonic() - case_started,
                        describe_generated_cifs_with_robocrys=bool(args.describe_generated_cifs_with_robocrys and not args.skip_robocrys),
                        require_robocrys=bool(args.require_robocrys),
                        robocrys_python=args.robocrys_python,
                        validate_robocrys_intent_alignment=bool(args.validate_robocrys_intent_alignment),
                        require_robocrys_intent_validation=bool(args.require_robocrys_intent_validation),
                        llm_judge_enabled=bool(args.llm_robocrys_intent_judge),
                        llm_model_config=llm_model_config,
                        query_metadata=query_metadata,
                    )
                if row.get("case_id") in support_by_case:
                    case_row.update(_support_manifest_fields(support_by_case[row["case_id"]]))
                manifest_rows.append(case_row)
            except Exception as exc:  # noqa: BLE001
                failure_row = _empty_manifest_row(
                    row,
                    case_dir,
                    status="failed",
                    category="workflow_command_failed",
                    message=f"{type(exc).__name__}: {exc}",
                    runtime=time.monotonic() - case_started,
                    out_root=out_root,
                )
                _write_failure_summary(case_dir, failure_row)
                manifest_rows.append(failure_row)
                if args.stop_on_first_failure:
                    break
        _write_json(out_root / "logs" / "runner_timing.json", {"runtime_seconds": round(time.monotonic() - started, 3)})

    image_rows, image_stats = _copy_images_for_final_doc(out_root, manifest_rows)
    robocrys_sidecar_rows = _write_robocrys_sidecar_manifests(out_root, manifest_rows)
    intent_validation_rows = _write_intent_validation_manifests(out_root, manifest_rows)
    intent_examples = _write_robocrys_intent_examples(out_root, manifest_rows)
    _write_intent_alignment_summary(out_root, intent_validation_rows, manifest_rows)
    _write_spp_objective_audit_summary(out_root, manifest_rows)
    missing_path_count = _missing_manifest_path_count(manifest_rows) + image_stats["missing"]
    _write_master_manifests(out_root, manifest_rows)
    _write_summary_report(
        out_root,
        total_csv_rows=len(rows),
        requested_cases=len(selected),
        rows=manifest_rows,
        final_doc_count=sum(1 for row in image_rows if row["exists"]),
        missing_path_count=missing_path_count,
    )
    _write_failure_analysis(out_root, manifest_rows)
    return {
        "out_root": _rel(out_root),
        "total_csv_rows": len(rows),
        "requested_cases": len(selected),
        "attempted_cases": len(manifest_rows),
        "successes": sum(1 for row in manifest_rows if row["failure_category"] == "success"),
        "final_cifs": sum(1 for row in manifest_rows if row["solution_cif_produced"]),
        "workflow_png": sum(1 for row in manifest_rows if row["workflow_png_path"]),
        "workflow_svg": sum(1 for row in manifest_rows if row["workflow_svg_path"]),
        "workflow_pdf": sum(1 for row in manifest_rows if row["workflow_pdf_path"]),
        "query_metadata_sidecars": sum(1 for row in manifest_rows if (out_root / row["case_dir"] / "crystal_db_query.json").exists() if row.get("case_dir")),
        "generated_cif_robocrys_sidecars": sum(1 for row in robocrys_sidecar_rows if row.get("metadata_path")),
        "generated_cif_robocrys_descriptions": sum(1 for row in robocrys_sidecar_rows if row.get("description_path")),
        "robocrys_intent_examples": len(intent_examples),
        "robocrys_intent_validation_sidecars": sum(1 for row in intent_validation_rows if row.get("validation_path")),
        "robocrys_intent_scored": sum(1 for row in intent_validation_rows if row.get("available")),
        "missing_path_count": missing_path_count,
        "failure_categories": Counter(row["failure_category"] for row in manifest_rows),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="challenge_queries_100.csv")
    parser.add_argument("--out-root", default=str(Path("test_workdir") / "paper_evidence_pack_v2"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--overwrite-v2", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-on-first-failure", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--crystal-db-path", default=None)
    parser.add_argument("--capability-audit-only", action="store_true")
    parser.add_argument("--preflight-support-only", action="store_true")
    parser.add_argument("--failure-audit-only", action="store_true")
    parser.add_argument("--rescore-existing-robocrys-intent", action="store_true")
    parser.add_argument("--allow-qlip-without-spp", action="store_true")
    parser.add_argument("--allow-partial-pair-evidence", action="store_true")
    parser.add_argument("--allow-diagnostic-spp", action="store_true")
    parser.add_argument("--allow-partial-spp-guidance", action="store_true", default=True)
    parser.add_argument("--spp-missing-pair-policy", choices=["neutral", "zero", "soft_repulsive", "fallback", "block"], default="neutral")
    parser.add_argument("--spp-guidance-weight", type=float, default=1.0)
    parser.add_argument("--spp-guidance-weight-scale", type=float, default=1.0)
    parser.add_argument("--spp-weighting-profile", choices=["custom", "default", "moderate", "strong", "very_strong"], default="custom")
    parser.add_argument("--spp-regularisation-dir", "--spp-regularization-dir", dest="spp_regularisation_dir", default="")
    parser.add_argument("--spp-regularisation-weight", "--spp-regularization-weight", dest="spp_regularisation_weight", type=float, default=0.0)
    parser.add_argument("--allow-fallback-pots", action="store_true")
    parser.add_argument("--family-aware-fallback-only", action="store_true")
    parser.add_argument("--force-cubic-lattice-template", action="store_true")
    parser.add_argument("--cubic-lattice-a", type=float, default=4.6)
    parser.add_argument("--describe-generated-cifs-with-robocrys", action="store_true")
    parser.add_argument("--require-robocrys", action="store_true")
    parser.add_argument("--skip-robocrys", action="store_true")
    parser.add_argument("--robocrys-python", default=None)
    parser.add_argument("--use-robocrys-query-skill", action="store_true")
    parser.add_argument("--no-robocrys-query-skill", dest="use_robocrys_query_skill", action="store_false")
    parser.add_argument("--validate-robocrys-intent-alignment", action="store_true")
    parser.add_argument("--require-robocrys-intent-validation", action="store_true")
    parser.add_argument("--llm-robocrys-intent-judge", "--use-llm-robocrys-intent-judge", dest="llm_robocrys_intent_judge", action="store_true")
    parser.add_argument("--require-llm-intent-judge", action="store_true")
    parser.add_argument("--llm-intent-judge-preflight-only", action="store_true")
    parser.add_argument("--llm-intent-judge-model", "--llm-judge-model", dest="llm_intent_judge_model", default=None)
    parser.add_argument("--llm-intent-judge-backend", "--llm-judge-backend", dest="llm_intent_judge_backend", choices=["ollama", "lmstudio", "openai_compatible", "existing"], default="ollama")
    parser.add_argument("--llm-intent-judge-url", "--llm-judge-url", dest="llm_intent_judge_url", default=None)
    parser.add_argument("--llm-intent-judge-timeout-s", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run(args)
    print(json.dumps(result, indent=2, sort_keys=True, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
