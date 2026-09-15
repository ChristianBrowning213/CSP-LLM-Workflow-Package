from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.optimization.action_compile import compiled_config_signature
from sok_llm_orchestrator.orchestrator.logging import canonical_json, sha256_text

DIMENSION_KEY_MAP = {
    "retrieval_policy": "retrieval_mode",
    "spp_corpus_strategy": "corpus_strategy",
    "spp_weighting_calibration": "spp_calibration_mode",
    "qlip_guidance": "guidance_mode",
    "cell_selection": "cell_selection_policy",
    "weighting_profile": "weighting_profile",
    "structure_perturbation": "structure_perturbation_profile",
    "template_seed": "template_seed_profile",
    "lattice_candidate": "lattice_candidate_profile",
    "symmetry_relaxation": "symmetry_relaxation_profile",
    "ordering_perturbation": "ordering_perturbation_profile",
}
_METADATA_ONLY_COMPILED_KEYS = {"action_id", "action_family", "compiled_id"}
_DEMOTED_METADATA_ONLY_DIMENSIONS = {"spp_weighting_calibration"}


def _safe_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_terms(raw_terms: object) -> list[dict[str, Any]]:
    if not isinstance(raw_terms, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw_terms:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term", "")).strip()
        if not term:
            continue
        value = item.get("value")
        norm_value = float(value) if isinstance(value, (int, float)) else None
        out.append({"term": term, "value": norm_value})
    return out


def _terms_signature(terms: list[dict[str, Any]]) -> str:
    return sha256_text(canonical_json(terms))


def _normalize_list_items(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        norm = {"id": str(item.get("id", "")), "params": item.get("params", {}) if isinstance(item.get("params"), dict) else {}}
        items.append(norm)
    items.sort(key=lambda it: (it.get("id", ""), canonical_json(it.get("params", {}))))
    return items


def normalize_qlip_request_structure(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "top_level_keys": [],
            "guidance_entries": [],
            "constraint_entries": [],
            "objective_structure": {"guidance_ids": [], "constraint_ids": []},
            "solver": {},
            "problem": {},
        }
    guidance_entries = _normalize_list_items(payload.get("guidance"))
    constraint_entries = _normalize_list_items(payload.get("constraints"))
    objective = payload.get("objective")
    objective_payload = objective if isinstance(objective, dict) else None
    problem = payload.get("problem", {})
    solver = payload.get("solver", {})
    if not isinstance(problem, dict):
        problem = {}
    if not isinstance(solver, dict):
        solver = {}
    chemistry = problem.get("chemistry", {})
    design_space = problem.get("design_space", {})
    template = design_space.get("template", {}) if isinstance(design_space, dict) else {}
    lattice = template.get("lattice", {}) if isinstance(template, dict) else {}
    if not isinstance(chemistry, dict):
        chemistry = {}
    if not isinstance(lattice, dict):
        lattice = {}
    return {
        "top_level_keys": sorted(payload.keys()),
        "version": payload.get("version"),
        "problem": {
            "formula": chemistry.get("formula"),
            "template_lattice": {str(k): lattice[k] for k in sorted(lattice)} if lattice else {},
        },
        "solver": {"name": solver.get("name")},
        "guidance_entries": guidance_entries,
        "constraint_entries": constraint_entries,
        "objective_structure": {
            "guidance_ids": [str(item.get("id")) for item in guidance_entries if item.get("id")],
            "constraint_ids": [str(item.get("id")) for item in constraint_entries if item.get("id")],
            "objective": objective_payload,
            "objective_type": (
                str(objective_payload.get("type"))
                if isinstance(objective_payload, dict) and isinstance(objective_payload.get("type"), str)
                else None
            ),
        },
    }


def extract_objective_audit_from_solve_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result", payload)
    nested = result.get("result", result) if isinstance(result, dict) else {}
    summary = nested.get("summary", {}) if isinstance(nested, dict) else {}
    outputs = nested.get("outputs", {}) if isinstance(nested, dict) else {}
    objective_total = summary.get("objective_value")
    objective_total_value = float(objective_total) if isinstance(objective_total, (int, float)) else None
    terms = _normalize_terms(outputs.get("objective_terms"))
    term_map = {str(item["term"]).strip().lower(): item.get("value") for item in terms}
    guidance_terms = [item for item in terms if str(item.get("term", "")).strip().lower() not in {"baseline", "spp"}]
    return {
        "objective_total": objective_total_value,
        "objective_terms": terms,
        "objective_terms_signature": _terms_signature(terms),
        "baseline_term": term_map.get("baseline"),
        "spp_term": term_map.get("spp"),
        "guidance_terms": guidance_terms,
        "solver_summary": summary if isinstance(summary, dict) else {},
    }


def objective_audit_from_run_dir(run_dir: Path) -> dict[str, Any] | None:
    solve_path = run_dir / "artifacts" / "qlip_solve.json"
    payload = _read_json(solve_path)
    if payload is None:
        return None
    return extract_objective_audit_from_solve_payload(payload)


def request_trace_from_run_dir(run_dir: Path) -> dict[str, Any]:
    req_payload = _read_json(run_dir / "artifacts" / "qlip_request.json")
    val_payload = _read_json(run_dir / "artifacts" / "qlip_validate.json")
    solve_payload = _read_json(run_dir / "artifacts" / "qlip_solve.json")
    meta_payload = _read_json(run_dir / "artifacts" / "qlip_builder_meta.json")
    overrides_payload = _read_json(run_dir / "artifacts" / "execution_overrides.json")
    request_signature = sha256_text(canonical_json(req_payload)) if isinstance(req_payload, dict) else None
    validate_signature = sha256_text(canonical_json(val_payload)) if isinstance(val_payload, dict) else None
    solve_signature = sha256_text(canonical_json(solve_payload)) if isinstance(solve_payload, dict) else None
    builder_meta_signature = sha256_text(canonical_json(meta_payload)) if isinstance(meta_payload, dict) else None
    overrides_signature = sha256_text(canonical_json(overrides_payload)) if isinstance(overrides_payload, dict) else None
    request_guidance_ids: list[str] = []
    request_constraint_ids: list[str] = []
    request_objective_type: str | None = None
    request_normalized = normalize_qlip_request_structure(req_payload if isinstance(req_payload, dict) else None)
    request_structure_sig = sha256_text(canonical_json(request_normalized))
    guidance_sig = sha256_text(canonical_json(request_normalized.get("guidance_entries", [])))
    constraint_sig = sha256_text(canonical_json(request_normalized.get("constraint_entries", [])))
    objective_struct_sig = sha256_text(canonical_json(request_normalized.get("objective_structure", {})))
    builder_trace: dict[str, Any] = {}
    if isinstance(meta_payload, dict) and isinstance(meta_payload.get("builder_input_trace"), dict):
        builder_trace = dict(meta_payload.get("builder_input_trace", {}))
    lambda_resolution = {}
    if isinstance(meta_payload, dict) and isinstance(meta_payload.get("spp_lambda_resolution"), dict):
        lambda_resolution = dict(meta_payload.get("spp_lambda_resolution", {}))
    if isinstance(req_payload, dict):
        guidance = req_payload.get("guidance")
        if isinstance(guidance, list):
            request_guidance_ids = [str(item.get("id")) for item in guidance if isinstance(item, dict) and item.get("id")]
        constraints = req_payload.get("constraints")
        if isinstance(constraints, list):
            request_constraint_ids = [str(item.get("id")) for item in constraints if isinstance(item, dict) and item.get("id")]
        objective = req_payload.get("objective")
        if isinstance(objective, dict) and isinstance(objective.get("type"), str):
            request_objective_type = str(objective.get("type"))
    return {
        "run_dir": str(run_dir),
        "qlip_request_signature": request_signature,
        "qlip_validate_signature": validate_signature,
        "qlip_solve_signature": solve_signature,
        "qlip_builder_meta_signature": builder_meta_signature,
        "execution_overrides_signature": overrides_signature,
        "effective_overrides": overrides_payload if isinstance(overrides_payload, dict) else {},
        "builder_input_trace": builder_trace,
        "builder_input_trace_signature": sha256_text(canonical_json(builder_trace)) if builder_trace else None,
        "spp_lambda_resolution": lambda_resolution,
        "request_structure": request_normalized,
        "request_structure_signature": request_structure_sig,
        "guidance_structure_signature": guidance_sig,
        "constraint_structure_signature": constraint_sig,
        "objective_structure_signature": objective_struct_sig,
        "request_top_level_keys": list(request_normalized.get("top_level_keys", [])),
        "request_guidance_entries": list(request_normalized.get("guidance_entries", [])),
        "request_constraint_entries": list(request_normalized.get("constraint_entries", [])),
        "request_guidance_ids": request_guidance_ids,
        "request_constraint_ids": request_constraint_ids,
        "request_objective_type": request_objective_type,
    }


def action_dimensions_from_compiled(compiled: dict[str, Any]) -> dict[str, Any]:
    guided = compiled.get("guided_overrides", {})
    if not isinstance(guided, dict):
        guided = {}
    return {label: guided.get(source_key) for label, source_key in DIMENSION_KEY_MAP.items()}


def build_sensitivity_trace_matrix(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    prev_dims = previous.get("action_dimensions", {}) if isinstance(previous, dict) else {}
    curr_dims = current.get("action_dimensions", {}) if isinstance(current, dict) else {}
    prev_trace = previous.get("request_trace", {}) if isinstance(previous, dict) else {}
    curr_trace = current.get("request_trace", {}) if isinstance(current, dict) else {}
    prev_overrides = prev_trace.get("effective_overrides", {}) if isinstance(prev_trace, dict) else {}
    curr_overrides = curr_trace.get("effective_overrides", {}) if isinstance(curr_trace, dict) else {}
    prev_obj = previous.get("objective_audit", {}) if isinstance(previous, dict) else {}
    curr_obj = current.get("objective_audit", {}) if isinstance(current, dict) else {}
    prev_total = prev_obj.get("objective_total") if isinstance(prev_obj, dict) else None
    curr_total = curr_obj.get("objective_total") if isinstance(curr_obj, dict) else None
    prev_term_sig = prev_obj.get("objective_terms_signature") if isinstance(prev_obj, dict) else None
    curr_term_sig = curr_obj.get("objective_terms_signature") if isinstance(curr_obj, dict) else None
    matrix: dict[str, dict[str, Any]] = {}
    for dim, override_key in DIMENSION_KEY_MAP.items():
        action_changed = prev_dims.get(dim) != curr_dims.get(dim) if previous is not None else True
        request_changed = (
            prev_overrides.get(override_key) != curr_overrides.get(override_key) if previous is not None else True
        )
        objective_changed = False
        if previous is not None:
            if isinstance(prev_total, (int, float)) and isinstance(curr_total, (int, float)):
                objective_changed = abs(float(curr_total) - float(prev_total)) > 1e-12
            elif isinstance(prev_term_sig, str) and isinstance(curr_term_sig, str):
                objective_changed = curr_term_sig != prev_term_sig
        matrix[dim] = {
            "action_changed": bool(action_changed),
            "compiled_changed": bool(action_changed),
            "request_changed": bool(request_changed),
            "objective_changed": bool(objective_changed),
            "previous_value": prev_dims.get(dim),
            "current_value": curr_dims.get(dim),
        }
    return matrix


def classify_backend_sensitivity(
    *,
    unique_action_ids: int,
    unique_compiled_signatures: int,
    unique_executable_signatures: int,
    unique_objective_totals: int,
    unique_objective_term_signatures: int,
) -> str:
    if unique_action_ids <= 1:
        return "repeated_same_action"
    if unique_executable_signatures <= 1:
        return "different_action_same_effective_request"
    if unique_compiled_signatures > 1 and unique_objective_totals > 1:
        return "different_action_different_config_different_objective"
    if unique_compiled_signatures > 1 and unique_objective_totals <= 1:
        if unique_objective_term_signatures > 1:
            return "different_action_same_total_different_objective_terms"
        return "different_action_different_config_same_objective"
    return "insufficient_evidence"


def summarize_dimension_sensitivity(iteration_trace: list[dict[str, Any]]) -> dict[str, str]:
    dims = list(DIMENSION_KEY_MAP.keys())
    out: dict[str, str] = {}
    for dim in dims:
        action_changed = False
        request_changed = False
        objective_changed = False
        for item in iteration_trace:
            matrix = item.get("sensitivity_trace_matrix", {})
            row = matrix.get(dim) if isinstance(matrix, dict) else None
            if not isinstance(row, dict):
                continue
            action_changed = action_changed or bool(row.get("action_changed", False))
            request_changed = request_changed or bool(row.get("request_changed", False))
            objective_changed = objective_changed or bool(row.get("objective_changed", False))
        if objective_changed:
            out[dim] = "affects_backend_objective"
        elif action_changed and request_changed:
            out[dim] = "changes_request_but_not_objective"
        elif action_changed:
            out[dim] = "changes_metadata_only"
        else:
            out[dim] = "unclear_insufficient_evidence"
    return out


def _changed_keys(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    return sorted(key for key in set(left.keys()) | set(right.keys()) if left.get(key) != right.get(key))


def build_request_objective_diff_summary(
    baseline: dict[str, Any],
    variant: dict[str, Any],
) -> dict[str, Any]:
    base_compiled = baseline.get("compiled_action", {})
    var_compiled = variant.get("compiled_action", {})
    if not isinstance(base_compiled, dict):
        base_compiled = {}
    if not isinstance(var_compiled, dict):
        var_compiled = {}

    base_guided = base_compiled.get("guided_overrides", {})
    var_guided = var_compiled.get("guided_overrides", {})
    if not isinstance(base_guided, dict):
        base_guided = {}
    if not isinstance(var_guided, dict):
        var_guided = {}
    base_baseline = base_compiled.get("baseline_overrides", {})
    var_baseline = var_compiled.get("baseline_overrides", {})
    if not isinstance(base_baseline, dict):
        base_baseline = {}
    if not isinstance(var_baseline, dict):
        var_baseline = {}

    changed_top = _changed_keys(base_compiled, var_compiled)
    changed_guided = _changed_keys(base_guided, var_guided)
    changed_baseline = _changed_keys(base_baseline, var_baseline)
    metadata_only_compiled_change = (
        bool(changed_top)
        and not changed_guided
        and not changed_baseline
        and all(key in _METADATA_ONLY_COMPILED_KEYS for key in changed_top)
    )

    base_trace = baseline.get("request_trace", {})
    var_trace = variant.get("request_trace", {})
    if not isinstance(base_trace, dict):
        base_trace = {}
    if not isinstance(var_trace, dict):
        var_trace = {}
    base_overrides = base_trace.get("effective_overrides", {})
    var_overrides = var_trace.get("effective_overrides", {})
    if not isinstance(base_overrides, dict):
        base_overrides = {}
    if not isinstance(var_overrides, dict):
        var_overrides = {}
    changed_request_override_keys = _changed_keys(base_overrides, var_overrides)
    base_req_sig = base_trace.get("qlip_request_signature")
    var_req_sig = var_trace.get("qlip_request_signature")
    base_req_struct_sig = base_trace.get("request_structure_signature")
    var_req_struct_sig = var_trace.get("request_structure_signature")
    base_guidance_sig = base_trace.get("guidance_structure_signature")
    var_guidance_sig = var_trace.get("guidance_structure_signature")
    base_constraint_sig = base_trace.get("constraint_structure_signature")
    var_constraint_sig = var_trace.get("constraint_structure_signature")
    base_objective_struct_sig = base_trace.get("objective_structure_signature")
    var_objective_struct_sig = var_trace.get("objective_structure_signature")
    base_guidance_ids = (
        list(base_trace.get("request_guidance_ids", [])) if isinstance(base_trace.get("request_guidance_ids"), list) else []
    )
    var_guidance_ids = (
        list(var_trace.get("request_guidance_ids", [])) if isinstance(var_trace.get("request_guidance_ids"), list) else []
    )
    base_constraint_ids = (
        list(base_trace.get("request_constraint_ids", []))
        if isinstance(base_trace.get("request_constraint_ids"), list)
        else []
    )
    var_constraint_ids = (
        list(var_trace.get("request_constraint_ids", []))
        if isinstance(var_trace.get("request_constraint_ids"), list)
        else []
    )
    request_structure_changed = (
        isinstance(base_req_struct_sig, str) and isinstance(var_req_struct_sig, str) and base_req_struct_sig != var_req_struct_sig
    )
    guidance_structure_changed = (
        isinstance(base_guidance_sig, str) and isinstance(var_guidance_sig, str) and base_guidance_sig != var_guidance_sig
    ) or base_guidance_ids != var_guidance_ids
    constraint_structure_changed = (
        isinstance(base_constraint_sig, str) and isinstance(var_constraint_sig, str) and base_constraint_sig != var_constraint_sig
    ) or base_constraint_ids != var_constraint_ids
    objective_structure_changed = (
        isinstance(base_objective_struct_sig, str)
        and isinstance(var_objective_struct_sig, str)
        and base_objective_struct_sig != var_objective_struct_sig
    )

    base_builder_trace = base_trace.get("builder_input_trace", {})
    var_builder_trace = var_trace.get("builder_input_trace", {})
    if not isinstance(base_builder_trace, dict):
        base_builder_trace = {}
    if not isinstance(var_builder_trace, dict):
        var_builder_trace = {}
    base_projection = base_builder_trace.get("override_key_projection", {})
    var_projection = var_builder_trace.get("override_key_projection", {})
    if not isinstance(base_projection, dict):
        base_projection = {}
    if not isinstance(var_projection, dict):
        var_projection = {}
    changed_builder_projection_keys = _changed_keys(base_projection, var_projection)
    dropped_keys_base = (
        list(base_builder_trace.get("dropped_override_keys", []))
        if isinstance(base_builder_trace.get("dropped_override_keys"), list)
        else []
    )
    dropped_keys_variant = (
        list(var_builder_trace.get("dropped_override_keys", []))
        if isinstance(var_builder_trace.get("dropped_override_keys"), list)
        else []
    )
    builder_input_changed = canonical_json(base_builder_trace) != canonical_json(var_builder_trace)

    request_changed = (
        bool(changed_request_override_keys)
        or (isinstance(base_req_sig, str) and isinstance(var_req_sig, str) and base_req_sig != var_req_sig)
        or canonical_json(base_trace) != canonical_json(var_trace)
    )

    base_obj = baseline.get("objective_audit", {})
    var_obj = variant.get("objective_audit", {})
    if not isinstance(base_obj, dict):
        base_obj = {}
    if not isinstance(var_obj, dict):
        var_obj = {}
    base_total = _safe_float(base_obj.get("objective_total"))
    var_total = _safe_float(var_obj.get("objective_total"))
    objective_total_delta = (
        float(var_total) - float(base_total) if base_total is not None and var_total is not None else None
    )
    objective_total_changed = (
        abs(float(objective_total_delta)) > 1e-12 if objective_total_delta is not None else False
    )
    base_term_sig = base_obj.get("objective_terms_signature")
    var_term_sig = var_obj.get("objective_terms_signature")
    objective_terms_changed = (
        isinstance(base_term_sig, str) and isinstance(var_term_sig, str) and base_term_sig != var_term_sig
    )
    base_summary = base_obj.get("solver_summary", {})
    var_summary = var_obj.get("solver_summary", {})
    if not isinstance(base_summary, dict):
        base_summary = {}
    if not isinstance(var_summary, dict):
        var_summary = {}
    solver_summary_changed = canonical_json(base_summary) != canonical_json(var_summary)
    objective_changed = objective_total_changed or objective_terms_changed or solver_summary_changed

    base_reference = baseline.get("run_reference", {})
    var_reference = variant.get("run_reference", {})
    if not isinstance(base_reference, dict):
        base_reference = {}
    if not isinstance(var_reference, dict):
        var_reference = {}
    base_artifact = base_reference.get("structure_artifact_path")
    var_artifact = var_reference.get("structure_artifact_path")
    artifact_path_changed = (
        isinstance(base_artifact, str) and isinstance(var_artifact, str) and base_artifact != var_artifact
    )

    return {
        "compiled_config_diff": {
            "changed": canonical_json(base_compiled) != canonical_json(var_compiled),
            "changed_top_level_keys": changed_top,
            "changed_guided_override_keys": changed_guided,
            "changed_baseline_override_keys": changed_baseline,
            "metadata_only_compiled_change": metadata_only_compiled_change,
        },
        "builder_input_diff": {
            "changed": bool(builder_input_changed),
            "changed_projection_keys": changed_builder_projection_keys,
            "baseline_projection": base_projection,
            "variant_projection": var_projection,
            "baseline_dropped_override_keys": dropped_keys_base,
            "variant_dropped_override_keys": dropped_keys_variant,
        },
        "executable_request_diff": {
            "changed": bool(request_changed),
            "changed_effective_override_keys": changed_request_override_keys,
            "baseline_request_signature": base_req_sig if isinstance(base_req_sig, str) else None,
            "variant_request_signature": var_req_sig if isinstance(var_req_sig, str) else None,
            "request_structure_changed": bool(request_structure_changed),
            "guidance_structure_changed": bool(guidance_structure_changed),
            "constraint_structure_changed": bool(constraint_structure_changed),
            "objective_structure_changed": bool(objective_structure_changed),
            "baseline_request_structure_signature": base_req_struct_sig if isinstance(base_req_struct_sig, str) else None,
            "variant_request_structure_signature": var_req_struct_sig if isinstance(var_req_struct_sig, str) else None,
            "baseline_guidance_ids": base_guidance_ids,
            "variant_guidance_ids": var_guidance_ids,
            "baseline_constraint_ids": base_constraint_ids,
            "variant_constraint_ids": var_constraint_ids,
        },
        "objective_diff": {
            "objective_total_baseline": base_total,
            "objective_total_variant": var_total,
            "objective_total_delta": objective_total_delta,
            "objective_total_changed": objective_total_changed,
            "objective_terms_changed": objective_terms_changed,
            "objective_terms_signature_baseline": base_term_sig if isinstance(base_term_sig, str) else None,
            "objective_terms_signature_variant": var_term_sig if isinstance(var_term_sig, str) else None,
            "solver_summary_changed": solver_summary_changed,
            "changed": bool(objective_changed),
        },
        "artifact_diff": {
            "structure_artifact_path_baseline": base_artifact if isinstance(base_artifact, str) else None,
            "structure_artifact_path_variant": var_artifact if isinstance(var_artifact, str) else None,
            "changed": bool(artifact_path_changed),
        },
    }


def classify_override_key_effect(diff_summary: dict[str, Any]) -> str:
    compiled = diff_summary.get("compiled_config_diff", {})
    request = diff_summary.get("executable_request_diff", {})
    objective = diff_summary.get("objective_diff", {})
    if not isinstance(compiled, dict):
        compiled = {}
    if not isinstance(request, dict):
        request = {}
    if not isinstance(objective, dict):
        objective = {}
    metadata_only = bool(compiled.get("metadata_only_compiled_change", False))
    compiled_changed = bool(compiled.get("changed", False))
    request_changed = bool(request.get("changed", False))
    objective_changed = bool(objective.get("changed", False))
    if metadata_only and not request_changed and not objective_changed:
        return "metadata_only"
    if compiled_changed and not request_changed:
        return "same_effective_request"
    if request_changed and objective_changed:
        return "objective_coupled"
    if request_changed and not objective_changed:
        return "request_changes_no_objective_effect"
    return "unclear"


def classify_override_propagation(diff_summary: dict[str, Any], *, override_key: str | None = None) -> str:
    compiled = diff_summary.get("compiled_config_diff", {})
    builder = diff_summary.get("builder_input_diff", {})
    request = diff_summary.get("executable_request_diff", {})
    objective = diff_summary.get("objective_diff", {})
    if not isinstance(compiled, dict):
        compiled = {}
    if not isinstance(builder, dict):
        builder = {}
    if not isinstance(request, dict):
        request = {}
    if not isinstance(objective, dict):
        objective = {}
    if not bool(compiled.get("changed", False)):
        return "unclear"
    builder_changed = bool(builder.get("changed", False))
    request_structure_changed = bool(request.get("request_structure_changed", False))
    guidance_structure_changed = bool(request.get("guidance_structure_changed", False))
    constraint_structure_changed = bool(request.get("constraint_structure_changed", False))
    objective_structure_changed = bool(request.get("objective_structure_changed", False))
    objective_changed = bool(objective.get("changed", False))
    dropped_variant = builder.get("variant_dropped_override_keys", [])
    if not isinstance(dropped_variant, list):
        dropped_variant = []
    if override_key and override_key in [str(key) for key in dropped_variant]:
        return "dropped_before_request"
    if not builder_changed:
        return "dropped_before_request"
    if not (request_structure_changed or guidance_structure_changed or constraint_structure_changed or objective_structure_changed):
        return "changes_request_metadata_only"
    if objective_changed:
        return "propagates_to_request_structure"
    return "propagates_but_no_backend_effect"


def summarize_override_propagation(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    by_dimension: dict[str, str] = {}
    buckets = {
        "propagates_to_request_structure": [],
        "dropped_before_request": [],
        "changes_request_metadata_only": [],
        "propagates_but_no_backend_effect": [],
        "unclear": [],
    }
    for row in comparisons:
        dim = row.get("dimension")
        cls = row.get("propagation_classification")
        if not isinstance(dim, str) or not isinstance(cls, str):
            continue
        by_dimension[dim] = cls
        if cls not in buckets:
            buckets["unclear"].append(dim)
        else:
            buckets[cls].append(dim)
    recommendations: list[str] = []
    if buckets["dropped_before_request"]:
        recommendations.append("Fix compile-to-builder mapping for dropped keys first.")
    if buckets["changes_request_metadata_only"]:
        recommendations.append("Promote metadata-only builder fields into material request structure where intended.")
    if buckets["propagates_but_no_backend_effect"]:
        recommendations.append("Request structure is changing; inspect backend objective coupling/term materialization.")
    if buckets["propagates_to_request_structure"]:
        recommendations.append("Retain propagated keys and prioritize them in optimizer action space.")
    if not recommendations:
        recommendations.append("Insufficient propagation evidence; run a bounded key-ablation with broader variants.")
    return {
        "by_dimension": by_dimension,
        "counts": {key: len(value) for key, value in buckets.items()},
        "groups": buckets,
        "recommendations": recommendations,
    }


def classify_dimension_roles(comparisons: list[dict[str, Any]]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for row in comparisons:
        dim = row.get("dimension")
        if not isinstance(dim, str):
            continue
        if dim in _DEMOTED_METADATA_ONLY_DIMENSIONS:
            roles[dim] = "metadata_only_demoted"
            continue
        propagation = row.get("propagation_classification")
        if not isinstance(propagation, str):
            propagation = "unclear"
        if propagation in {"propagates_to_request_structure", "propagates_but_no_backend_effect"}:
            roles[dim] = "backend_structural"
        elif propagation in {"dropped_before_request", "changes_request_metadata_only"}:
            roles[dim] = "orchestration_metadata_only"
        else:
            roles[dim] = "unresolved"
    return roles


def summarize_action_library_relevance(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    by_dimension: dict[str, set[str]] = {}
    for row in comparisons:
        dimension = row.get("dimension")
        if not isinstance(dimension, str):
            continue
        cls = row.get("classification")
        if not isinstance(cls, str):
            continue
        by_dimension.setdefault(dimension, set()).add(cls)

    useful: list[str] = []
    inert: list[str] = []
    needs_coupling: list[str] = []
    uncertain: list[str] = []
    demoted: list[str] = []
    per_dimension: dict[str, str] = {}
    for dim in sorted(by_dimension):
        if dim in _DEMOTED_METADATA_ONLY_DIMENSIONS:
            label = "metadata_only_demoted"
            demoted.append(dim)
            per_dimension[dim] = label
            continue
        classes = by_dimension[dim]
        if "objective_coupled" in classes:
            label = "likely_useful_for_objective_optimization"
            useful.append(dim)
        elif "same_effective_request" in classes:
            label = "needs_stronger_compile_coupling"
            needs_coupling.append(dim)
        elif classes and classes.issubset({"request_changes_no_objective_effect", "metadata_only"}):
            label = "likely_inert_under_current_backend"
            inert.append(dim)
        else:
            label = "uncertain"
            uncertain.append(dim)
        per_dimension[dim] = label
    return {
        "likely_useful_for_objective_optimization": useful,
        "likely_inert_under_current_backend": inert,
        "needs_stronger_compile_coupling": needs_coupling,
        "uncertain": uncertain,
        "metadata_only_demoted": demoted,
        "per_dimension_relevance": per_dimension,
    }


def execution_signature_from_compiled(query: str, mode: str, compiled: dict[str, Any]) -> str:
    payload = {
        "mode": mode,
        "query": query,
        "query_suffix": compiled.get("query_suffix"),
        "guided_with_spp": compiled.get("guided_with_spp"),
        "baseline_overrides": compiled.get("baseline_overrides"),
        "guided_overrides": compiled.get("guided_overrides"),
    }
    return sha256_text(canonical_json(payload))


def objective_audit_from_execution(execution: dict[str, Any]) -> dict[str, Any]:
    if isinstance(execution.get("objective_audit"), dict):
        payload = dict(execution["objective_audit"])
        terms = _normalize_terms(payload.get("objective_terms"))
        payload["objective_terms"] = terms
        payload["objective_terms_signature"] = _terms_signature(terms)
        return payload
    objective_total = execution.get("objective_total")
    if not isinstance(objective_total, (int, float)):
        objective_total = execution.get("primary_objective")
    value = float(objective_total) if isinstance(objective_total, (int, float)) else None
    terms = _normalize_terms(execution.get("objective_terms"))
    if not terms and value is not None:
        terms = [{"term": "objective_total", "value": value}]
    return {
        "objective_total": value,
        "objective_terms": terms,
        "objective_terms_signature": _terms_signature(terms),
        "baseline_term": None,
        "spp_term": None,
        "guidance_terms": [],
        "solver_summary": dict(execution.get("solver_summary", {}))
        if isinstance(execution.get("solver_summary"), dict)
        else {},
    }


def attach_compiled_signature(compiled: dict[str, Any]) -> dict[str, Any]:
    out = dict(compiled)
    out["compiled_config_signature"] = compiled_config_signature(compiled, include_action_identity=False)
    return out
