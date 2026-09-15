from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.crystaldb import apply_crystal_policy_defaults
from sok_llm_orchestrator.contracts.qlip_builders_v2 import build_solve_request_v2
from sok_llm_orchestrator.contracts.qlip_schema import QLIPValidationError, validate_solve_request
from sok_llm_orchestrator.contracts.spp_regularisation import (
    apply_regularised_partial_spp_guidance,
    find_spp_pot_root,
    formula_pairs,
    regularised_partial_spp_config,
)
from sok_llm_orchestrator.external_predictors.adapters import (
    normalize_external_predictor_requests,
    run_external_predictors,
)
from sok_llm_orchestrator.contracts.spp_normalize import normalize_spp_arguments
from sok_llm_orchestrator.mcp.stdio_client import StdioMCPClient
from sok_llm_orchestrator.orchestrator.cell_selection import default_cell_candidates, select_cell_candidates
from sok_llm_orchestrator.orchestrator.logging import RunLogger, canonical_json, sha256_text
from sok_llm_orchestrator.orchestrator.stages.intake import run_intake_stage
from sok_llm_orchestrator.orchestrator.stages.retrieval import run_retrieval_stage
from sok_llm_orchestrator.orchestrator.stages.verification import run_verification_stage
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_payload, task_spec_from_query
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle
from sok_llm_orchestrator.safety.caps import Caps, enforce_requested_caps, enforce_result_caps
from sok_llm_orchestrator.safety.path_sandbox import validate_paths_in_args
from sok_llm_orchestrator.spp.artifact_schema import SPPArtifactManifest
from sok_llm_orchestrator.spp.calibration_harness import run_calibration_harness
from sok_llm_orchestrator.spp.corpus_policy import (
    choose_export_ready_corpus_candidate,
    select_corpus_manifest,
    stage_export_ready_cifs,
)
from sok_llm_orchestrator.structures.prototype_scaffold import (
    orbit_solution_payload,
    prototype_orbit_candidates_payload_from_request,
    prototype_orbit_solution_from_request,
    prototype_scaffold_from_request,
    scaffold_matches_final_cif,
)

_PLAN_OVERRIDE_KEYS = {
    "retrieval_mode",
    "use_spp",
    "corpus_strategy",
    "guidance_mode",
    "verification_preset",
    "rerun_permissions",
}
_KNOWN_EXECUTION_OVERRIDE_KEYS = _PLAN_OVERRIDE_KEYS | {
    "cell_selection_policy",
    "spp_calibration_mode",
    "retrieval_candidate_k",
    "corpus_top_k",
    "corpus_strategy_candidates",
    "corpus_top_k_candidates",
    "spp_package_variant",
    "spp_package_alternatives",
    "spp_package_target",
    "spp_payload_profile",
    "runtime_spp_guidance_weight",
    "spp_guidance_weight",
    "spp_top_k_breakdown",
    "spp_pairs_policy",
    "spp_oob_policy",
    "spp_missing_pair_policy",
    "allow_partial_spp_guidance",
    "allow_qlip_without_spp",
    "spp_regularisation_dir",
    "spp_regularisation_weight",
    "spp_regularization_dir",
    "spp_regularization_weight",
    "weighting_profile",
    "structure_perturbation_profile",
    "template_seed_profile",
    "lattice_candidate_profile",
    "symmetry_relaxation_profile",
    "ordering_perturbation_profile",
    "active_symmetry_mode",
    "qlip_objective",
    "external_predictors",
}
_OVERRIDE_TO_BUILDER_FIELDS: dict[str, list[str]] = {
    "retrieval_mode": ["plan.retrieval_mode", "retrieval_bundle"],
    "corpus_strategy": ["plan.corpus_strategy", "spp_corpus_manifest"],
    "guidance_mode": ["plan.guidance_mode", "qlip_request.guidance"],
    "verification_preset": ["plan.verification_preset"],
    "cell_selection_policy": ["cell_selection.policy", "qlip_request.problem.design_space.template"],
    "spp_calibration_mode": ["spp_payload.defaults", "qlip_request.guidance.params"],
    "retrieval_candidate_k": ["crystal.csp_pack.export_top", "retrieval_bundle"],
    "corpus_top_k": ["spp_corpus_manifest.selected_ids"],
    "corpus_strategy_candidates": ["spp_corpus_candidates"],
    "corpus_top_k_candidates": ["spp_corpus_candidates"],
    "spp_package_variant": ["spp_package_candidates", "spp_artifact_manifest.metadata.package_variant"],
    "spp_package_alternatives": ["spp_package_candidates"],
    "spp_package_target": ["spp.run_pipeline.target", "spp_artifact_manifest.calibration_summary"],
    "spp_payload_profile": ["qlip_request.guidance.params"],
    "runtime_spp_guidance_weight": ["qlip_request.guidance.params.lambda_override"],
    "spp_guidance_weight": ["qlip_request.guidance.params.lambda_override"],
    "spp_top_k_breakdown": ["qlip_request.guidance.params.top_k_breakdown"],
    "spp_pairs_policy": ["qlip_request.guidance.params.pairs_policy"],
    "spp_oob_policy": ["qlip_request.guidance.params.oob_policy"],
    "spp_missing_pair_policy": ["qlip_request.guidance.params.missing_pair_policy"],
    "allow_partial_spp_guidance": ["qlip_request.guidance.params.mode"],
    "allow_qlip_without_spp": ["qlip_request.guidance.params.regularisation_spp_dir"],
    "spp_regularisation_dir": ["qlip_request.guidance.params.regularisation_spp_dir"],
    "spp_regularisation_weight": ["qlip_request.guidance.params.regularisation_weight"],
    "spp_regularization_dir": ["qlip_request.guidance.params.regularisation_spp_dir"],
    "spp_regularization_weight": ["qlip_request.guidance.params.regularisation_weight"],
    "weighting_profile": ["qlip_request.guidance.params.weighting_profile", "qlip_request.guidance.params.lambda_override"],
    "structure_perturbation_profile": ["qlip_request.problem.design_space.template", "qlip_request.problem.design_space.sites"],
    "template_seed_profile": ["qlip_request.problem.design_space.template", "qlip_request.problem.design_space.seeding"],
    "lattice_candidate_profile": ["qlip_request.problem.design_space.template_candidates"],
    "symmetry_relaxation_profile": ["qlip_request.constraints", "qlip_request.problem.design_space"],
    "ordering_perturbation_profile": ["qlip_request.constraints", "qlip_request.problem.design_space.site_priors"],
    "active_symmetry_mode": ["qlip_request.problem.design_space.sites.mode"],
    "qlip_objective": ["qlip_request.objective"],
    "external_predictors": ["external_predictions"],
    "use_spp": ["plan.use_spp", "spp_artifact_presence"],
    "rerun_permissions": [],
}


class PipelineError(RuntimeError):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _safe_artifact_slug(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return "item"
    safe_chars: list[str] = []
    for char in text:
        if char.isalnum() or char in {"-", "_", "."}:
            safe_chars.append(char)
        else:
            safe_chars.append("_")
    slug = "".join(safe_chars).strip("._")
    if not slug:
        slug = "item"
    digest = sha256_text(text)[:8]
    return f"{slug}__{digest}"


def _stub_command(script_name: str) -> list[str]:
    return [sys.executable, "-u", str(_repo_root() / "tests" / "fakes" / script_name)]


def _canonical_inputs(
    query: str | None,
    with_spp: bool,
    mode: str,
    policy_mode: str,
    execution_overrides: dict[str, Any] | None,
    strict_phase1_benchmark_mode: bool,
    task_spec_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "execution_overrides": execution_overrides or {},
        "mode": mode,
        "policy_mode": policy_mode,
        "query": str(query or ""),
        "strict_phase1_benchmark_mode": bool(strict_phase1_benchmark_mode),
        "task_spec_payload": task_spec_payload or None,
        "with_spp": with_spp,
    }


def stable_run_id(inputs: dict[str, Any]) -> str:
    canon = canonical_json(inputs)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, canon))


def _safe_rmtree(path: Path, retries: int = 6, delay_s: float = 0.05) -> None:
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(delay_s)
    if last_error is not None:
        raise last_error


def _semantic_spp_package_ref(spp_artifact: SPPArtifactManifest | None) -> str:
    if spp_artifact is None:
        return "spp://artifact/unknown"
    variant = (
        str(spp_artifact.metadata.get("package_variant"))
        if isinstance(spp_artifact.metadata.get("package_variant"), str)
        else "unknown"
    )
    return f"spp://artifact/{spp_artifact.artifact_id}?variant={variant}&corpus_hash={spp_artifact.corpus_hash}"


def _semantic_qlip_request(
    request: dict[str, Any],
    *,
    spp_artifact: SPPArtifactManifest | None,
) -> dict[str, Any]:
    payload = json.loads(json.dumps(request))
    guidance = payload.get("guidance")
    if not isinstance(guidance, list):
        return payload
    for item in guidance:
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "")).strip() != "objective.energy_spp":
            continue
        params = item.get("params")
        if not isinstance(params, dict):
            continue
        if isinstance(params.get("spp_package_path"), str) and params.get("spp_package_path"):
            params["spp_package_path"] = _semantic_spp_package_ref(spp_artifact)
        if isinstance(params.get("regularisation_spp_dir"), str) and params.get("regularisation_spp_dir"):
            params["regularisation_spp_dir"] = "spp://regularisation/local"
        if isinstance(params.get("regularization_spp_dir"), str) and params.get("regularization_spp_dir"):
            params["regularization_spp_dir"] = "spp://regularisation/local"
    return payload


def _build_symmetry_trace(
    *,
    task_spec_obj: Any,
    qlip_request: dict[str, Any],
    qlip_request_meta: dict[str, Any],
    cif_path: str | None = None,
) -> dict[str, Any]:
    problem = qlip_request.get("problem") if isinstance(qlip_request, dict) else {}
    symmetry = problem.get("symmetry") if isinstance(problem, dict) else {}
    prototype = problem.get("prototype") if isinstance(problem, dict) else {}
    design_space = problem.get("design_space") if isinstance(problem, dict) else {}
    sites = design_space.get("sites") if isinstance(design_space, dict) else {}
    constraints = qlip_request.get("constraints") if isinstance(qlip_request, dict) else []
    active_constraints = [
        str(item.get("id"))
        for item in constraints
        if isinstance(item, dict) and str(item.get("id", "")).startswith("constraint.")
    ] if isinstance(constraints, list) else []
    requested_space_group = getattr(getattr(task_spec_obj, "symmetry_request", None), "space_group", None) or getattr(
        task_spec_obj, "target_space_group", None
    )
    requested_crystal_system = getattr(task_spec_obj, "target_crystal_system", None)
    requested_family = getattr(task_spec_obj, "target_structure_family", None) or getattr(task_spec_obj, "prototype", None)
    trace = {
        "schema_version": "symmetry_trace.v1",
        "requested_space_group": requested_space_group,
        "requested_space_group_number": getattr(task_spec_obj, "target_space_group_number", None),
        "requested_crystal_system": requested_crystal_system,
        "requested_family": requested_family,
        "requested_prototype": getattr(task_spec_obj, "prototype", None),
        "source": "structured_task_spec" if requested_space_group or requested_crystal_system or requested_family else "none",
        "qlip_request_fields_written": {
            "problem.symmetry": isinstance(symmetry, dict) and bool(symmetry),
            "problem.prototype": isinstance(prototype, dict) and bool(prototype),
            "problem.design_space.sites.mode": sites.get("mode") if isinstance(sites, dict) else None,
            "problem.design_space.sites.site_mode": sites.get("site_mode") if isinstance(sites, dict) else None,
            "constraints": active_constraints,
        },
        "active_symmetry_mode": qlip_request_meta.get("active_symmetry_mode", "none"),
        "active_symmetry_constraints": active_constraints,
        "candidate_site_source": sites.get("candidate_site_source") if isinstance(sites, dict) else None,
        "scaffold_used_for_final_cif": False,
        "final_cif_source": "generic_fallback",
        "scaffold_family": None,
        "scaffold_space_group": None,
        "scaffold_space_group_number": None,
        "scaffold_crystal_system": None,
        "scaffold_site_count": None,
        "scaffold_formula": None,
        "scaffold_lattice_parameters": None,
        "scaffold_fractional_coordinates": None,
        "scaffold_orbits": None,
        "orbit_count": None,
        "orbit_level_selection": False,
        "variable_orbit_selection": False,
        "selected_orbits": [],
        "selected_sites": [],
        "selected_species_by_orbit": {},
        "selected_candidate_id": None,
        "objective_value": None,
        "symmetry_closed": None,
        "spp_scoring_status": None,
        "spp_source": None,
        "spp_source_type": None,
        "spp_pot_dir": None,
        "spp_preflight_path": sites.get("spp_preflight_path") if isinstance(sites, dict) else None,
        "spp_preflight_final_status": sites.get("spp_preflight_final_status") if isinstance(sites, dict) else None,
        "required_pairs": sites.get("required_pairs") if isinstance(sites, dict) else None,
        "loaded_pair_count": sites.get("loaded_pair_count") if isinstance(sites, dict) else None,
        "missing_pairs": sites.get("missing_pairs") if isinstance(sites, dict) else None,
        "selected_pair_score_breakdown": None,
        "spp_fallback_reason": None,
        "orbit_assignment_solver": None,
        "scaffold_source_note": None,
        "fallback_reason": None,
    }
    _, scaffold_trace = prototype_scaffold_from_request(qlip_request)
    trace.update(
        {
            "scaffold_used_for_final_cif": False,
            "final_cif_source": scaffold_trace.get("final_cif_source"),
            "scaffold_family": scaffold_trace.get("scaffold_family"),
            "scaffold_space_group": scaffold_trace.get("scaffold_space_group"),
            "scaffold_space_group_number": scaffold_trace.get("scaffold_space_group_number"),
            "scaffold_crystal_system": scaffold_trace.get("scaffold_crystal_system"),
            "scaffold_site_count": scaffold_trace.get("scaffold_site_count"),
            "scaffold_formula": scaffold_trace.get("scaffold_formula"),
            "scaffold_lattice_parameters": scaffold_trace.get("scaffold_lattice_parameters"),
            "scaffold_fractional_coordinates": scaffold_trace.get("scaffold_fractional_coordinates"),
            "scaffold_orbits": scaffold_trace.get("scaffold_orbits"),
            "orbit_count": scaffold_trace.get("orbit_count"),
            "orbit_level_selection": bool(scaffold_trace.get("orbit_level_selection")),
            "variable_orbit_selection": bool(scaffold_trace.get("variable_orbit_selection")),
            "selected_orbits": scaffold_trace.get("selected_orbits") or [],
            "selected_sites": scaffold_trace.get("selected_sites") or [],
            "selected_species_by_orbit": scaffold_trace.get("selected_species_by_orbit") or {},
            "selected_candidate_id": scaffold_trace.get("selected_candidate_id"),
            "objective_value": scaffold_trace.get("objective_value"),
            "symmetry_closed": scaffold_trace.get("symmetry_closed"),
            "spp_scoring_status": scaffold_trace.get("spp_scoring_status"),
            "spp_source": scaffold_trace.get("spp_source"),
            "spp_source_type": scaffold_trace.get("spp_source_type"),
            "spp_pot_dir": scaffold_trace.get("spp_pot_dir"),
            "spp_preflight_path": scaffold_trace.get("spp_preflight_path") or (sites.get("spp_preflight_path") if isinstance(sites, dict) else None),
            "spp_preflight_final_status": sites.get("spp_preflight_final_status") if isinstance(sites, dict) else None,
            "required_pairs": sites.get("required_pairs") if isinstance(sites, dict) else None,
            "loaded_pair_count": sites.get("loaded_pair_count") if isinstance(sites, dict) else None,
            "missing_pairs": sites.get("missing_pairs") if isinstance(sites, dict) else None,
            "selected_pair_score_breakdown": scaffold_trace.get("selected_pair_score_breakdown"),
            "spp_fallback_reason": scaffold_trace.get("spp_fallback_reason"),
            "orbit_assignment_solver": scaffold_trace.get("orbit_assignment_solver"),
            "scaffold_source_note": scaffold_trace.get("scaffold_source_note"),
            "fallback_reason": scaffold_trace.get("fallback_reason"),
        }
    )
    if trace["active_symmetry_mode"] in {"none", "request_only"}:
        trace["fallback_reason"] = "unsupported_family" if requested_family else "no_symmetry_requested"
    if cif_path:
        final_scaffold_trace = scaffold_matches_final_cif(cif_path, qlip_request)
        trace.update(
            {
                "scaffold_used_for_final_cif": bool(final_scaffold_trace.get("scaffold_used_for_final_cif")),
                "final_cif_source": final_scaffold_trace.get("final_cif_source"),
                "scaffold_family": final_scaffold_trace.get("scaffold_family"),
                "scaffold_space_group": final_scaffold_trace.get("scaffold_space_group"),
                "scaffold_space_group_number": final_scaffold_trace.get("scaffold_space_group_number"),
                "scaffold_crystal_system": final_scaffold_trace.get("scaffold_crystal_system"),
                "scaffold_site_count": final_scaffold_trace.get("scaffold_site_count"),
                "scaffold_formula": final_scaffold_trace.get("scaffold_formula"),
                "scaffold_lattice_parameters": final_scaffold_trace.get("scaffold_lattice_parameters"),
                "scaffold_fractional_coordinates": final_scaffold_trace.get("scaffold_fractional_coordinates"),
                "scaffold_orbits": final_scaffold_trace.get("scaffold_orbits"),
                "orbit_count": final_scaffold_trace.get("orbit_count"),
                "orbit_level_selection": bool(final_scaffold_trace.get("orbit_level_selection")),
                "variable_orbit_selection": bool(final_scaffold_trace.get("variable_orbit_selection")),
                "selected_orbits": final_scaffold_trace.get("selected_orbits") or [],
                "selected_sites": final_scaffold_trace.get("selected_sites") or [],
                "selected_species_by_orbit": final_scaffold_trace.get("selected_species_by_orbit") or {},
                "selected_candidate_id": final_scaffold_trace.get("selected_candidate_id"),
                "objective_value": final_scaffold_trace.get("objective_value"),
                "symmetry_closed": final_scaffold_trace.get("symmetry_closed"),
                "spp_scoring_status": final_scaffold_trace.get("spp_scoring_status"),
                "spp_source": final_scaffold_trace.get("spp_source"),
                "spp_source_type": final_scaffold_trace.get("spp_source_type"),
                "spp_pot_dir": final_scaffold_trace.get("spp_pot_dir"),
                "spp_preflight_path": final_scaffold_trace.get("spp_preflight_path") or (sites.get("spp_preflight_path") if isinstance(sites, dict) else None),
                "spp_preflight_final_status": sites.get("spp_preflight_final_status") if isinstance(sites, dict) else None,
                "required_pairs": sites.get("required_pairs") if isinstance(sites, dict) else None,
                "loaded_pair_count": sites.get("loaded_pair_count") if isinstance(sites, dict) else None,
                "missing_pairs": sites.get("missing_pairs") if isinstance(sites, dict) else None,
                "selected_pair_score_breakdown": final_scaffold_trace.get("selected_pair_score_breakdown"),
                "spp_fallback_reason": final_scaffold_trace.get("spp_fallback_reason"),
                "orbit_assignment_solver": final_scaffold_trace.get("orbit_assignment_solver"),
                "scaffold_source_note": final_scaffold_trace.get("scaffold_source_note"),
                "fallback_reason": final_scaffold_trace.get("fallback_reason"),
            }
        )
        if trace["active_symmetry_mode"] in {"none", "request_only"}:
            trace["fallback_reason"] = "unsupported_family" if requested_family else "no_symmetry_requested"
        trace["post_solve_validation"] = _analyze_output_symmetry(
            cif_path,
            requested_space_group=requested_space_group,
            requested_crystal_system=requested_crystal_system,
        )
    return trace


def _analyze_output_symmetry(
    cif_path: str,
    *,
    requested_space_group: str | None,
    requested_crystal_system: str | None,
) -> dict[str, Any]:
    try:
        from pymatgen.core import Structure
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        structure = Structure.from_file(cif_path)
        analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5)
        analyzed_space_group = analyzer.get_space_group_symbol()
        analyzed_number = analyzer.get_space_group_number()
        analyzed_system = analyzer.get_crystal_system()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "cif_path": cif_path,
            "error": f"{type(exc).__name__}: {exc}",
        }
    requested_sg_norm = str(requested_space_group or "").replace(" ", "").lower()
    analyzed_sg_norm = str(analyzed_space_group or "").replace(" ", "").lower()
    requested_system_norm = str(requested_crystal_system or "").strip().lower()
    return {
        "ok": True,
        "cif_path": cif_path,
        "analyzed_space_group": analyzed_space_group,
        "analyzed_space_group_number": analyzed_number,
        "analyzed_crystal_system": analyzed_system,
        "space_group_exact_match": bool(requested_sg_norm and requested_sg_norm == analyzed_sg_norm),
        "crystal_system_match": bool(requested_system_norm and requested_system_norm == str(analyzed_system).lower()),
        "claim_enforced": False,
        "note": "Diagnostic only; generation is not claimed symmetry-enforced unless analyzer checks pass.",
    }


def _call_tool(
    client: StdioMCPClient,
    logger: RunLogger,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    response = client.call_tool(tool_name, arguments)
    logger.log_tool_call(tool_name, arguments, response)
    payload = _unwrap_mcp_payload(response)
    if tool_name == "crystal.csp_pack":
        payload = _normalize_crystal_csp_pack_payload(payload)
    return payload


def _unwrap_mcp_payload(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    result = response.get("result", response)
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return dict(structured)
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, Mapping):
                    continue
                if item.get("type") == "json" and isinstance(item.get("json"), Mapping):
                    return dict(item["json"])
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    text = str(item["text"]).strip()
                    if text.startswith("{") and text.endswith("}"):
                        try:
                            parsed = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(parsed, dict):
                            return parsed
    structured = response.get("structuredContent")
    if isinstance(structured, dict):
        return dict(structured)
    return response


def _normalize_crystal_csp_pack_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    normalized = dict(payload)
    export = normalized.get("export")
    if isinstance(export, Mapping) and not isinstance(normalized.get("exports"), Mapping):
        normalized["exports"] = {
            "out_dir": export.get("out_dir"),
            "manifest_json": export.get("manifest_json") or export.get("manifest_path"),
            "results_json": export.get("results_json") or export.get("results_path"),
            "cifs_dir": export.get("cifs_dir") or export.get("cif_dir"),
        }
    return normalized


def _strip_live_qlip_design_space_metadata(request: dict[str, Any]) -> dict[str, Any]:
    sanitized = json.loads(json.dumps(request))
    problem = sanitized.get("problem")
    if not isinstance(problem, dict):
        return sanitized
    objective = sanitized.pop("objective", None)
    if isinstance(objective, dict):
        problem["objective"] = objective
    elif not isinstance(problem.get("objective"), dict):
        problem["objective"] = {"type": "none"}
    design_space = problem.get("design_space")
    if not isinstance(design_space, dict):
        return sanitized
    design_space.pop("template_candidates", None)
    design_space.pop("seeding", None)
    template = design_space.get("template")
    if isinstance(template, dict):
        for key in (
            "ordering_perturbation_profile",
            "perturbation_profile",
            "seed_profile",
            "symmetry_relaxation_profile",
        ):
            template.pop(key, None)
    sites = design_space.get("sites")
    if isinstance(sites, dict):
        sites.pop("ordering_priors", None)
    return sanitized




def _unwrap_spp_result(response: dict[str, Any]) -> dict[str, Any]:
    if "result" in response and isinstance(response["result"], dict):
        if not response.get("ok", True):
            raise PipelineError(str(response.get("error", {})))
        return response["result"]
    return response


def _as_int(value: Any, default: int, *, min_value: int = 1, max_value: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(min_value, min(max_value, parsed))


def _as_float(value: Any, default: float, *, min_value: float = 0.0, max_value: float = 10.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return max(min_value, min(max_value, parsed))


def _as_optional_float(value: Any, *, min_value: float = 0.0, max_value: float = 10.0) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(min_value, min(max_value, parsed))


def _as_list_of_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text in out:
            continue
        out.append(text)
    return out


def _as_list_of_int(value: Any, *, min_value: int = 1, max_value: int = 100) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        parsed = max(min_value, min(max_value, parsed))
        if parsed in out:
            continue
        out.append(parsed)
    return out


def _guidance_payload_defaults(calibration_mode: str, payload_profile: str, weighting_profile: str) -> dict[str, Any]:
    # Calibration mode influences the default strength envelope.
    by_mode: dict[str, dict[str, Any]] = {
        "conservative": {
            "lambda_override": 0.3,
            "top_k_breakdown": 6,
            "pairs_policy": "task_pairs",
            "oob_policy": "clamp",
            "missing_pair_policy": "zero",
        },
        "balanced": {
            "lambda_override": 0.7,
            "top_k_breakdown": 12,
            "pairs_policy": "task_pairs",
            "oob_policy": "max",
            "missing_pair_policy": "max_global",
        },
        "aggressive": {
            "lambda_override": 1.2,
            "top_k_breakdown": 22,
            "pairs_policy": "all_available",
            "oob_policy": "max",
            "missing_pair_policy": "max_global",
        },
    }
    by_profile: dict[str, dict[str, Any]] = {
        "weak": {
            "lambda_override": 0.25,
            "top_k_breakdown": 5,
            "pairs_policy": "task_pairs",
            "oob_policy": "clamp",
            "missing_pair_policy": "zero",
        },
        "balanced": {
            "lambda_override": 0.7,
            "top_k_breakdown": 12,
            "pairs_policy": "task_pairs",
            "oob_policy": "max",
            "missing_pair_policy": "max_global",
        },
        "strong": {
            "lambda_override": 1.4,
            "top_k_breakdown": 28,
            "pairs_policy": "all_available",
            "oob_policy": "max",
            "missing_pair_policy": "max_global",
        },
    }
    mode_key = str(calibration_mode or "balanced").strip().lower()
    profile_key = str(payload_profile or "balanced").strip().lower()
    weighting_key = str(weighting_profile or "balanced").strip().lower()
    weighting_adjustments: dict[str, dict[str, Any]] = {
        "base_dominant": {
            "lambda_scale": 0.5,
            "base_weight_scale": 1.2,
            "guidance_weight_scale": 0.7,
        },
        "balanced": {
            "lambda_scale": 1.0,
            "base_weight_scale": 1.0,
            "guidance_weight_scale": 1.0,
        },
        "guidance_dominant": {
            "lambda_scale": 1.35,
            "base_weight_scale": 0.9,
            "guidance_weight_scale": 1.3,
        },
        "property_push_strong": {
            "lambda_scale": 1.7,
            "base_weight_scale": 0.8,
            "guidance_weight_scale": 1.6,
        },
        "experimental_extreme": {
            "lambda_scale": 2.1,
            "base_weight_scale": 0.7,
            "guidance_weight_scale": 1.9,
        },
    }
    payload = dict(by_mode.get(mode_key, by_mode["balanced"]))
    payload.update(by_profile.get(profile_key, by_profile["balanced"]))
    adj = dict(weighting_adjustments.get(weighting_key, weighting_adjustments["balanced"]))
    lambda_raw = _as_float(payload.get("lambda_override"), 0.7, min_value=0.0, max_value=10.0)
    payload["lambda_override"] = _as_float(lambda_raw * float(adj.get("lambda_scale", 1.0)), lambda_raw, min_value=0.0, max_value=10.0)
    payload["base_weight_scale"] = _as_float(adj.get("base_weight_scale"), 1.0, min_value=0.1, max_value=4.0)
    payload["guidance_weight_scale"] = _as_float(adj.get("guidance_weight_scale"), 1.0, min_value=0.1, max_value=4.0)
    payload["weighting_profile"] = weighting_key
    return payload


def _resolve_spp_lambda(
    *,
    default_lambda: float,
    selected_calibration: dict[str, Any] | None,
    execution_overrides: dict[str, Any],
) -> dict[str, Any]:
    runtime_override = _as_optional_float(execution_overrides.get("runtime_spp_guidance_weight"))
    action_override = _as_optional_float(execution_overrides.get("spp_guidance_weight"))
    recommended = None
    if isinstance(selected_calibration, dict):
        recommended = _as_optional_float(selected_calibration.get("recommended_weight"))

    if isinstance(runtime_override, float):
        return {
            "spp_lambda_source": "runtime_override",
            "spp_lambda_value": float(runtime_override),
            "spp_lambda_recommended_available": isinstance(recommended, float),
            "spp_lambda_override_applied": True,
            "spp_lambda_recommended_value": float(recommended) if isinstance(recommended, float) else None,
        }
    if isinstance(action_override, float):
        return {
            "spp_lambda_source": "action_override",
            "spp_lambda_value": float(action_override),
            "spp_lambda_recommended_available": isinstance(recommended, float),
            "spp_lambda_override_applied": True,
            "spp_lambda_recommended_value": float(recommended) if isinstance(recommended, float) else None,
        }
    if isinstance(recommended, float):
        return {
            "spp_lambda_source": "calibration_recommended",
            "spp_lambda_value": float(recommended),
            "spp_lambda_recommended_available": True,
            "spp_lambda_override_applied": True,
            "spp_lambda_recommended_value": float(recommended),
        }
    return {
        "spp_lambda_source": "payload_default",
        "spp_lambda_value": float(default_lambda),
        "spp_lambda_recommended_available": False,
        "spp_lambda_override_applied": False,
        "spp_lambda_recommended_value": None,
    }


def _relevant_env_snapshot() -> dict[str, str]:
    prefixes = ("CRYSTAL", "CRYSTALDB", "SPP", "QLIP", "FAKE_CRYSTAL", "ALLOWED_", "LLM_")
    names = {"QLIP_ALLOWED_PATH_ROOTS", "ALLOWED_READ_ROOTS", "ALLOWED_WRITE_ROOTS"}
    return {
        key: value
        for key, value in sorted(os.environ.items())
        if key in names or any(key.startswith(prefix) for prefix in prefixes)
    }


def _regularisation_pair_file_status(root: Path | None, formula: str | None) -> list[dict[str, Any]]:
    pairs = formula_pairs(formula)
    if root is None or not root.exists():
        return [
            {
                "pair": pair,
                "pair_dir_exists": False,
                "pot_file_exists": False,
                "resolved_pair_dir": None,
                "resolved_pot_file": None,
            }
            for pair in pairs
        ]
    children = {child.name.upper(): child for child in root.iterdir() if child.is_dir()}
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        pair_dir = children.get(pair.upper())
        pot_file = None
        if pair_dir is not None:
            direct = pair_dir / f"{pair}.POT"
            if direct.is_file():
                pot_file = direct
            else:
                expected = f"{pair}.POT".upper()
                pot_file = next((item for item in pair_dir.iterdir() if item.is_file() and item.name.upper() == expected), None)
        rows.append(
            {
                "pair": pair,
                "pair_dir_exists": pair_dir is not None,
                "pot_file_exists": pot_file is not None,
                "resolved_pair_dir": str(pair_dir) if pair_dir is not None else None,
                "resolved_pot_file": str(pot_file) if pot_file is not None else None,
            }
        )
    return rows


def _retrieval_export_diagnostics(retrieval_bundle: RetrievalBundle) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in retrieval_bundle.items:
        if not isinstance(item, dict):
            continue
        artifacts = item.get("artifacts") if isinstance(item.get("artifacts"), dict) else {}
        export_path_raw = str(artifacts.get("cif_export_path") or "").strip()
        export_path = Path(export_path_raw) if export_path_raw else None
        rows.append(
            {
                "structure_id": item.get("structure_id"),
                "why_returned": item.get("why_returned"),
                "cif_export_status": artifacts.get("cif_export_status"),
                "cif_export_error": artifacts.get("cif_export_error"),
                "allow_export": artifacts.get("allow_export"),
                "cif_export_path": export_path_raw or None,
                "cif_export_path_exists": bool(export_path and export_path.exists()),
            }
        )
    return rows


def _build_spp_corpus_unavailable_diagnostics(
    *,
    retrieval_bundle: RetrievalBundle,
    corpus_candidates: list[dict[str, Any]],
    selected_candidate_index: int,
    staged_cifs: dict[str, Any],
    fallback_cfg: dict[str, Any] | None,
    allow_without_spp: bool,
    overrides: dict[str, Any],
    settings: Settings,
    formula: str | None,
    failure_reason: str,
) -> dict[str, Any]:
    export_rows = _retrieval_export_diagnostics(retrieval_bundle)
    fallback_path_raw = None
    if fallback_cfg is not None:
        fallback_path_raw = str(fallback_cfg.get("regularisation_spp_dir") or "").strip()
    if not fallback_path_raw:
        fallback_path_raw = str(
            overrides.get("spp_regularisation_dir")
            or overrides.get("spp_regularization_dir")
            or ""
        ).strip()
    fallback_path = Path(fallback_path_raw).resolve() if fallback_path_raw else None
    export_ready_count = sum(
        1
        for row in export_rows
        if str(row.get("cif_export_status") or "").lower() == "exported" and bool(row.get("cif_export_path_exists"))
    )
    return {
        "schema_version": "spp.corpus_unavailable_diagnostics.v1",
        "failure_reason": failure_reason,
        "retrieval_candidate_count": len(retrieval_bundle.items),
        "export_ready_candidate_count": export_ready_count,
        "retrieval_export_rows": export_rows,
        "corpus_candidate_count": len(corpus_candidates),
        "selected_candidate_index": int(selected_candidate_index),
        "corpus_candidates": corpus_candidates,
        "staged_cifs": staged_cifs,
        "regularisation_fallback": {
            "configured": fallback_cfg is not None,
            "allow_qlip_without_spp": bool(allow_without_spp),
            "resolved_path": str(fallback_path) if fallback_path is not None else None,
            "path_exists": bool(fallback_path and fallback_path.exists()),
            "required_pair_files": _regularisation_pair_file_status(fallback_path, formula),
        },
        "settings": {
            "crystaldb_policy_mode": settings.crystaldb_policy_mode,
            "crystaldb_mcp_cmd": settings.crystaldb_mcp_cmd,
            "crystaldb_mcp_cwd": settings.crystaldb_mcp_cwd,
            "spp_mcp_cmd": settings.spp_mcp_cmd,
            "spp_mcp_cwd": settings.spp_mcp_cwd,
            "qlip_mcp_cmd": settings.qlip_mcp_cmd,
            "qlip_mcp_cwd": settings.qlip_mcp_cwd,
            "workspace_root": str(settings.workspace_root),
            "qlip_allowed_path_roots": [str(Path(root).resolve()) for root in settings.qlip_allowed_path_roots],
        },
        "runtime": {
            "cwd": str(Path.cwd().resolve()),
            "entrypoint_config_path": str(overrides.get("entrypoint_config_path") or ""),
            "entrypoint_cwd": str(overrides.get("entrypoint_cwd") or ""),
            "environment": _relevant_env_snapshot(),
        },
    }


def _build_builder_input_trace(
    *,
    execution_overrides: dict[str, Any] | None,
    plan_payload: dict[str, Any],
    cell_policy: str,
    task_spec_obj: Any,
    retrieval_bundle: RetrievalBundle,
    corpus_manifest: Any,
    corpus_candidates: list[dict[str, Any]],
    spp_artifact_manifest: SPPArtifactManifest | None,
    spp_package_candidates: list[dict[str, Any]],
    guidance_payload: dict[str, Any],
    lambda_resolution: dict[str, Any] | None,
    effective_with_spp: bool,
    qlip_objective: Any,
    external_predictor_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    overrides = dict(execution_overrides or {})
    override_keys = sorted(str(key) for key in overrides.keys())
    consumed_by_plan = sorted(key for key in override_keys if key in _PLAN_OVERRIDE_KEYS)
    consumed_by_cell_selection = ["cell_selection_policy"] if "cell_selection_policy" in override_keys else []
    consumed_by_spp = sorted(
        key
        for key in override_keys
        if key
        in {
            "retrieval_candidate_k",
            "corpus_top_k",
            "corpus_strategy_candidates",
            "corpus_top_k_candidates",
            "spp_package_variant",
            "spp_package_alternatives",
            "spp_package_target",
            "spp_payload_profile",
            "runtime_spp_guidance_weight",
            "spp_guidance_weight",
            "spp_top_k_breakdown",
            "spp_pairs_policy",
            "spp_oob_policy",
            "spp_missing_pair_policy",
            "spp_calibration_mode",
            "weighting_profile",
            "structure_perturbation_profile",
            "template_seed_profile",
            "lattice_candidate_profile",
            "symmetry_relaxation_profile",
            "ordering_perturbation_profile",
            "qlip_objective",
            "external_predictors",
        }
    )
    consumed_keys = sorted(set(consumed_by_plan + consumed_by_cell_selection + consumed_by_spp))
    dropped_keys = sorted(key for key in override_keys if key not in consumed_keys)
    unknown_override_keys = sorted(key for key in override_keys if key not in _KNOWN_EXECUTION_OVERRIDE_KEYS)
    override_projection = {
        "retrieval_mode": plan_payload.get("retrieval_mode"),
        "corpus_strategy": plan_payload.get("corpus_strategy"),
        "guidance_mode": plan_payload.get("guidance_mode"),
        "verification_preset": plan_payload.get("verification_preset"),
        "cell_selection_policy": cell_policy,
        "spp_calibration_mode": overrides.get("spp_calibration_mode"),
        "retrieval_candidate_k": overrides.get("retrieval_candidate_k"),
        "corpus_top_k": overrides.get("corpus_top_k"),
        "corpus_strategy_candidates": overrides.get("corpus_strategy_candidates"),
        "corpus_top_k_candidates": overrides.get("corpus_top_k_candidates"),
        "spp_package_variant": overrides.get("spp_package_variant"),
        "spp_package_alternatives": overrides.get("spp_package_alternatives"),
        "spp_package_target": overrides.get("spp_package_target"),
        "spp_payload_profile": overrides.get("spp_payload_profile"),
        "runtime_spp_guidance_weight": overrides.get("runtime_spp_guidance_weight"),
        "spp_guidance_weight": overrides.get("spp_guidance_weight"),
        "spp_top_k_breakdown": overrides.get("spp_top_k_breakdown"),
        "spp_pairs_policy": overrides.get("spp_pairs_policy"),
        "spp_oob_policy": overrides.get("spp_oob_policy"),
        "spp_missing_pair_policy": overrides.get("spp_missing_pair_policy"),
        "weighting_profile": overrides.get("weighting_profile"),
        "structure_perturbation_profile": overrides.get("structure_perturbation_profile"),
        "template_seed_profile": overrides.get("template_seed_profile"),
        "lattice_candidate_profile": overrides.get("lattice_candidate_profile"),
        "symmetry_relaxation_profile": overrides.get("symmetry_relaxation_profile"),
        "ordering_perturbation_profile": overrides.get("ordering_perturbation_profile"),
        "qlip_objective": overrides.get("qlip_objective"),
        "external_predictors": overrides.get("external_predictors"),
        "use_spp": bool(plan_payload.get("use_spp", True)),
        "rerun_permissions": plan_payload.get("rerun_permissions"),
    }
    return {
        "schema_version": "qlip.builder_input_trace.v1",
        "override_keys_present": override_keys,
        "unknown_override_keys": unknown_override_keys,
        "consumed_override_keys": consumed_keys,
        "dropped_override_keys": dropped_keys,
        "override_to_builder_fields": dict(_OVERRIDE_TO_BUILDER_FIELDS),
        "override_key_projection": override_projection,
        "builder_inputs": {
            "composition_target": task_spec_obj.composition_target,
            "symmetry_space_group": task_spec_obj.symmetry_request.space_group,
            "symmetry_hardness": task_spec_obj.symmetry_request.hardness,
            "plan_retrieval_mode": plan_payload.get("retrieval_mode"),
            "plan_corpus_strategy": plan_payload.get("corpus_strategy"),
            "plan_guidance_mode": plan_payload.get("guidance_mode"),
            "plan_verification_preset": plan_payload.get("verification_preset"),
            "selected_cell_policy": cell_policy,
            "retrieval_id": retrieval_bundle.retrieval_id,
            "retrieval_item_count": len(retrieval_bundle.items),
            "corpus_selected_count": len(corpus_manifest.selected_ids),
            "corpus_candidate_count": len(corpus_candidates),
            "corpus_candidate_ids": [str(item.get("candidate_id")) for item in corpus_candidates],
            "selected_corpus_candidate_id": (
                str(corpus_manifest.metadata.get("selected_candidate_id"))
                if isinstance(corpus_manifest.metadata.get("selected_candidate_id"), str)
                else None
            ),
            "spp_artifact_present": spp_artifact_manifest is not None,
            "spp_artifact_id": spp_artifact_manifest.artifact_id if spp_artifact_manifest else None,
            "spp_package_candidate_count": len(spp_package_candidates),
            "spp_package_candidate_ids": [str(item.get("candidate_id")) for item in spp_package_candidates],
            "selected_spp_package_variant": (
                str(spp_artifact_manifest.metadata.get("package_variant"))
                if spp_artifact_manifest is not None and isinstance(spp_artifact_manifest.metadata.get("package_variant"), str)
                else None
            ),
            "weighting_profile": (
                str(spp_artifact_manifest.metadata.get("weighting_profile"))
                if spp_artifact_manifest is not None and isinstance(spp_artifact_manifest.metadata.get("weighting_profile"), str)
                else None
            ),
            "structure_perturbation_profile": (
                str(spp_artifact_manifest.metadata.get("structure_perturbation_profile"))
                if spp_artifact_manifest is not None and isinstance(spp_artifact_manifest.metadata.get("structure_perturbation_profile"), str)
                else None
            ),
            "template_seed_profile": (
                str(spp_artifact_manifest.metadata.get("template_seed_profile"))
                if spp_artifact_manifest is not None and isinstance(spp_artifact_manifest.metadata.get("template_seed_profile"), str)
                else None
            ),
            "lattice_candidate_profile": (
                str(spp_artifact_manifest.metadata.get("lattice_candidate_profile"))
                if spp_artifact_manifest is not None and isinstance(spp_artifact_manifest.metadata.get("lattice_candidate_profile"), str)
                else None
            ),
            "symmetry_relaxation_profile": (
                str(spp_artifact_manifest.metadata.get("symmetry_relaxation_profile"))
                if spp_artifact_manifest is not None and isinstance(spp_artifact_manifest.metadata.get("symmetry_relaxation_profile"), str)
                else None
            ),
            "ordering_perturbation_profile": (
                str(spp_artifact_manifest.metadata.get("ordering_perturbation_profile"))
                if spp_artifact_manifest is not None and isinstance(spp_artifact_manifest.metadata.get("ordering_perturbation_profile"), str)
                else None
            ),
            "guidance_payload": dict(guidance_payload),
            "spp_lambda_source": (
                lambda_resolution.get("spp_lambda_source")
                if isinstance(lambda_resolution, dict)
                else None
            ),
            "spp_lambda_value": (
                lambda_resolution.get("spp_lambda_value")
                if isinstance(lambda_resolution, dict)
                else None
            ),
            "spp_lambda_recommended_available": (
                lambda_resolution.get("spp_lambda_recommended_available")
                if isinstance(lambda_resolution, dict)
                else None
            ),
            "spp_lambda_override_applied": (
                lambda_resolution.get("spp_lambda_override_applied")
                if isinstance(lambda_resolution, dict)
                else None
            ),
            "effective_with_spp": bool(effective_with_spp),
            "qlip_objective": qlip_objective,
            "qlip_objective_family": (
                str(qlip_objective.get("type"))
                if isinstance(qlip_objective, dict) and isinstance(qlip_objective.get("type"), str)
                else None
            ),
            "external_predictor_targets": list(external_predictor_targets),
            "external_predictor_ids": [
                str(item.get("predictor_id"))
                for item in external_predictor_targets
                if isinstance(item, dict) and isinstance(item.get("predictor_id"), str)
            ],
        },
    }


@dataclass(slots=True)
class PipelineRun:
    run_id: str
    run_dir: Path
    manifest_path: Path
    status: str


def run_csp_pipeline(
    query: str | None,
    with_spp: bool,
    mode: str,
    workspace: Path,
    settings: Settings,
    qlip_request_mutator: Any = None,
    execution_overrides: dict[str, Any] | None = None,
    task_spec_payload: dict[str, Any] | None = None,
    strict_phase1_benchmark_mode: bool = False,
) -> PipelineRun:
    workspace = workspace.resolve()
    (workspace / "runs").mkdir(parents=True, exist_ok=True)
    canonical_inputs = _canonical_inputs(
        query=query,
        with_spp=with_spp,
        mode=mode,
        policy_mode=settings.crystaldb_policy_mode,
        execution_overrides=execution_overrides,
        strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
        task_spec_payload=task_spec_payload,
    )
    run_id = stable_run_id(canonical_inputs)
    run_dir = workspace / "runs" / run_id
    if run_dir.exists():
        _safe_rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(run_dir)
    status = "SUCCEEDED"
    failure_reason: str | None = None
    effective_with_spp = bool(with_spp)
    caps = Caps(
        max_cif_count=settings.max_cif_count,
        max_runtime_seconds=settings.max_runtime_seconds,
        max_output_bytes=settings.max_output_bytes,
    )

    crystal_cmd: str | list[str]
    spp_cmd: str | list[str]
    qlip_cmd: str | list[str]
    if mode == "stub":
        crystal_cmd = _stub_command("mcp_crystaldb_server.py")
        spp_cmd = _stub_command("mcp_spp_server.py")
        qlip_cmd = _stub_command("mcp_qlip_server.py")
    else:
        crystal_cmd = settings.crystaldb_mcp_cmd
        spp_cmd = settings.spp_mcp_cmd
        qlip_cmd = settings.qlip_mcp_cmd

    env = {
        "CRYSTALDB_POLICY_MODE": settings.crystaldb_policy_mode,
        "SOKLLM_RUN_DIR": str(run_dir),
        **os.environ,
    }
    if settings.qlip_allowed_path_roots:
        env["QLIP_ALLOWED_PATH_ROOTS"] = os.pathsep.join(
            str(Path(root).resolve()) for root in settings.qlip_allowed_path_roots
        )
    crystal_cwd = str(Path(settings.crystaldb_mcp_cwd).resolve()) if settings.crystaldb_mcp_cwd else str(_repo_root())
    spp_cwd = str(Path(settings.spp_mcp_cwd).resolve()) if settings.spp_mcp_cwd else str(_repo_root())
    qlip_cwd = str(Path(settings.qlip_mcp_cwd).resolve()) if settings.qlip_mcp_cwd else str(_repo_root())
    plan_overrides = None
    explicit_guidance_override: str | None = None
    explicit_use_spp_override: bool | None = None
    if execution_overrides:
        plan_overrides = {key: execution_overrides[key] for key in _PLAN_OVERRIDE_KEYS if key in execution_overrides}
        if isinstance(execution_overrides.get("guidance_mode"), str):
            explicit_guidance_override = str(execution_overrides["guidance_mode"])
        if isinstance(execution_overrides.get("use_spp"), bool):
            explicit_use_spp_override = bool(execution_overrides["use_spp"])

    if task_spec_payload is not None:
        task_spec_obj = task_spec_from_payload(
            task_spec_payload,
            strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
        )
    else:
        task_spec_obj = task_spec_from_query(
            str(query or ""),
            strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
        )
    task_spec_payload, plan_payload, clarification_payload = run_intake_stage(
        query,
        plan_overrides=plan_overrides,
        task_spec_payload=task_spec_payload,
        strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
    )
    logger.write_artifact("artifacts/task_spec.json", task_spec_payload)
    logger.write_artifact("artifacts/run_plan.json", plan_payload)
    logger.write_artifact("artifacts/clarification_decision.json", clarification_payload)
    if execution_overrides:
        logger.write_artifact("artifacts/execution_overrides.json", execution_overrides)
    overrides = dict(execution_overrides or {})
    with (
        StdioMCPClient(crystal_cmd, env=env, cwd=crystal_cwd) as crystal,
        StdioMCPClient(spp_cmd, env=env, cwd=spp_cwd) as spp,
        StdioMCPClient(qlip_cmd, env=env, cwd=qlip_cwd) as qlip,
    ):
        try:
            crystal_out_dir = run_dir / "artifacts" / "crystal_pack"
            retrieval_candidate_k = _as_int(overrides.get("retrieval_candidate_k"), 3, min_value=1, max_value=30)
            crystal_args = {
                "query": str(task_spec_obj.query_text),
                "out_dir": str(crystal_out_dir),
                "export_top": retrieval_candidate_k,
            }
            crystal_args, crystal_notes = apply_crystal_policy_defaults(
                crystal_args, settings.crystaldb_policy_mode
            )
            if crystal_notes:
                logger.write_artifact("artifacts/crystal_policy_notes.json", {"notes": crystal_notes})
            validate_paths_in_args(
                crystal_args,
                read_keys=[],
                write_keys=["out_dir"],
                allowed_read_roots=settings.allowed_read_roots,
                allowed_write_roots=settings.allowed_write_roots,
            )
            crystal_resp = _call_tool(crystal, logger, "crystal.csp_pack", crystal_args)
            logger.write_artifact("artifacts/crystal_csp_pack.json", crystal_resp)
            retrieval_bundle: RetrievalBundle = run_retrieval_stage(
                crystal_resp,
                mode=plan_payload["retrieval_mode"],
                property_key=task_spec_obj.property_bias,
            )
            logger.write_artifact("artifacts/retrieval_bundle.json", retrieval_bundle.to_dict())
            selected_corpus_strategy = str(plan_payload["corpus_strategy"])
            selected_top_k = _as_int(overrides.get("corpus_top_k"), 3, min_value=1, max_value=30)
            strategy_candidates = _as_list_of_str(overrides.get("corpus_strategy_candidates"))
            allowed_strategies = {"top_k", "composition_tight", "family_biased", "property_biased"}
            strategy_candidates = [item for item in strategy_candidates if item in allowed_strategies]
            if selected_corpus_strategy not in strategy_candidates:
                strategy_candidates.insert(0, selected_corpus_strategy)
            if not strategy_candidates:
                strategy_candidates = [selected_corpus_strategy]
            top_k_candidates = _as_list_of_int(overrides.get("corpus_top_k_candidates"), min_value=1, max_value=30)
            if selected_top_k not in top_k_candidates:
                top_k_candidates.insert(0, selected_top_k)
            if not top_k_candidates:
                top_k_candidates = [selected_top_k]

            corpus_candidates: list[dict[str, Any]] = []
            seen_corpus_hashes: set[str] = set()
            selected_candidate_index: int | None = None
            for strategy in strategy_candidates:
                for top_k in top_k_candidates:
                    try:
                        candidate_manifest = select_corpus_manifest(
                            retrieval=retrieval_bundle,
                            strategy=strategy,
                            top_k=top_k,
                            property_key=task_spec_obj.property_bias,
                        )
                    except ValueError:
                        continue
                    if candidate_manifest.content_hash in seen_corpus_hashes:
                        continue
                    seen_corpus_hashes.add(candidate_manifest.content_hash)
                    candidate_id = f"{strategy}:top{top_k}:{len(corpus_candidates)}"
                    row = {
                        "candidate_id": candidate_id,
                        "strategy": strategy,
                        "top_k": int(top_k),
                        "content_hash": candidate_manifest.content_hash,
                        "manifest": candidate_manifest.to_dict(),
                    }
                    if strategy == selected_corpus_strategy and int(top_k) == int(selected_top_k) and selected_candidate_index is None:
                        selected_candidate_index = len(corpus_candidates)
                    corpus_candidates.append(row)
            if not corpus_candidates:
                raise PipelineError("No valid SPP corpus candidates could be selected from retrieval results.")
            if selected_candidate_index is None:
                selected_candidate_index = 0
            (
                selected_candidate_index,
                corpus_selection_resolution,
                corpus_candidates,
            ) = choose_export_ready_corpus_candidate(
                retrieval_bundle,
                corpus_candidates,
                selected_candidate_index,
            )
            corpus_manifest = select_corpus_manifest(
                retrieval=retrieval_bundle,
                strategy=str(corpus_candidates[selected_candidate_index]["strategy"]),
                top_k=int(corpus_candidates[selected_candidate_index]["top_k"]),
                property_key=task_spec_obj.property_bias,
            )
            corpus_manifest.metadata["selected_candidate_id"] = str(corpus_candidates[selected_candidate_index]["candidate_id"])
            corpus_manifest.metadata["selected_candidate_index"] = int(selected_candidate_index)
            corpus_manifest.metadata["selection_reason"] = str(corpus_selection_resolution["selection_reason"])
            corpus_manifest.metadata["requested_candidate_id"] = str(corpus_selection_resolution["requested_candidate_id"])
            corpus_manifest.metadata["exportability"] = dict(corpus_candidates[selected_candidate_index].get("exportability", {}))
            logger.write_artifact(
                "artifacts/spp_corpus_candidates.json",
                {
                    "schema_version": "spp.corpus_candidates.v1",
                    "requested_candidate_id": str(corpus_selection_resolution["requested_candidate_id"]),
                    "selected_candidate_id": str(corpus_candidates[selected_candidate_index]["candidate_id"]),
                    "selected_candidate_index": int(selected_candidate_index),
                    "selection_reason": str(corpus_selection_resolution["selection_reason"]),
                    "items": corpus_candidates,
                },
            )
            logger.write_artifact("artifacts/spp_corpus_manifest.json", corpus_manifest.to_dict())
            cell_policy = str(overrides.get("cell_selection_policy")) if overrides.get("cell_selection_policy") else ("retrieval_informed" if with_spp else "baseline_default")
            cell_candidates = select_cell_candidates(
                policy=cell_policy,
                retrieval=retrieval_bundle,
                fixed_candidates=default_cell_candidates(),
            )
            logger.write_artifact(
                "artifacts/cell_candidates.json",
                {
                    "schema_version": "cell_candidates.v1",
                    "policy": cell_policy,
                    "items": [
                        {"candidate_id": c.candidate_id, "lattice": c.lattice, "source": c.source}
                        for c in cell_candidates
                    ],
                },
            )

            package_path: str | None = None
            spp_artifact_manifest: SPPArtifactManifest | None = None
            spp_package_candidates: list[dict[str, Any]] = []
            selected_calibration: dict[str, Any] | None = None
            lambda_resolution: dict[str, Any] | None = None
            weighting_profile = str(overrides.get("weighting_profile", "balanced")).strip().lower() or "balanced"
            if weighting_profile not in {
                "base_dominant",
                "balanced",
                "guidance_dominant",
                "property_push_strong",
                "experimental_extreme",
            }:
                weighting_profile = "balanced"
            structure_perturbation_profile = (
                str(overrides.get("structure_perturbation_profile", "minimal")).strip().lower() or "minimal"
            )
            if structure_perturbation_profile not in {"minimal", "moderate", "aggressive", "template_shuffle"}:
                structure_perturbation_profile = "minimal"
            template_seed_profile = str(overrides.get("template_seed_profile", "canonical")).strip().lower() or "canonical"
            if template_seed_profile not in {"canonical", "polymorph_mix", "framework_bias", "ordering_bias"}:
                template_seed_profile = "canonical"
            lattice_candidate_profile = (
                str(overrides.get("lattice_candidate_profile", "narrow")).strip().lower() or "narrow"
            )
            if lattice_candidate_profile not in {"narrow", "expanded", "multibasin"}:
                lattice_candidate_profile = "narrow"
            symmetry_relaxation_profile = (
                str(overrides.get("symmetry_relaxation_profile", "strict")).strip().lower() or "strict"
            )
            if symmetry_relaxation_profile not in {"strict", "soft", "relaxed"}:
                symmetry_relaxation_profile = "strict"
            ordering_perturbation_profile = (
                str(overrides.get("ordering_perturbation_profile", "none")).strip().lower() or "none"
            )
            if ordering_perturbation_profile not in {"none", "site_shuffle", "cation_swap_bias"}:
                ordering_perturbation_profile = "none"
            active_symmetry_mode = str(overrides.get("active_symmetry_mode", "")).strip().lower() or None
            if active_symmetry_mode not in {
                None,
                "prototype_orbit_qlip",
                "prototype_orbit_variable_qlip",
                "prototype_orbit_variable_spp_qlip",
            }:
                active_symmetry_mode = None
            guidance_payload = _guidance_payload_defaults(
                str(overrides.get("spp_calibration_mode", "balanced")),
                str(overrides.get("spp_payload_profile", "balanced")),
                weighting_profile,
            )
            guidance_payload["template_seed_profile"] = template_seed_profile
            guidance_payload["lattice_candidate_profile"] = lattice_candidate_profile
            guidance_payload["symmetry_relaxation_profile"] = symmetry_relaxation_profile
            guidance_payload["ordering_perturbation_profile"] = ordering_perturbation_profile
            if "spp_top_k_breakdown" in overrides:
                guidance_payload["top_k_breakdown"] = _as_int(overrides.get("spp_top_k_breakdown"), int(guidance_payload["top_k_breakdown"]), min_value=0, max_value=100)
            if str(overrides.get("spp_pairs_policy", "")) in {"task_pairs", "all_available"}:
                guidance_payload["pairs_policy"] = str(overrides.get("spp_pairs_policy"))
            if str(overrides.get("spp_oob_policy", "")) in {"zero", "clamp", "max"}:
                guidance_payload["oob_policy"] = str(overrides.get("spp_oob_policy"))
            if str(overrides.get("spp_missing_pair_policy", "")) in {"zero", "max_global", "error", "soft_repulsive"}:
                guidance_payload["missing_pair_policy"] = str(overrides.get("spp_missing_pair_policy"))

            effective_with_spp = bool(with_spp)
            if explicit_guidance_override in {"guidance_only", "budget_constraint"}:
                effective_with_spp = True
            if explicit_use_spp_override is not None:
                effective_with_spp = explicit_use_spp_override
            if plan_payload.get("guidance_mode") == "none":
                effective_with_spp = False
            if plan_payload.get("use_spp") is False:
                effective_with_spp = False
            regularised_partial_cfg = regularised_partial_spp_config(overrides)
            use_regularised_partial_guidance = regularised_partial_cfg is not None
            regularised_pot_root = None
            selected_exportable_count = int(
                corpus_candidates[selected_candidate_index]
                .get("exportability", {})
                .get("exportable_count", 0)
                or 0
            )
            if (
                effective_with_spp
                and use_regularised_partial_guidance
                and bool(overrides.get("allow_qlip_without_spp", False))
                and selected_exportable_count <= 0
            ):
                regularised_pot_root = find_spp_pot_root(
                    tuple(Path(root).resolve() for root in settings.qlip_allowed_path_roots),
                    task_spec_obj.composition_target,
                )
                if regularised_pot_root:
                    overrides["spp_pot_root"] = regularised_pot_root
                logger.write_artifact(
                    "artifacts/spp_regularisation_fallback.json",
                    {
                        "schema_version": "spp.regularisation_fallback.v1",
                        "reason": "no_export_ready_candidate",
                        "local_spp_package_generated": False,
                        "regularisation_spp_dir": regularised_partial_cfg["regularisation_spp_dir"],
                        "regularisation_weight": regularised_partial_cfg["regularisation_weight"],
                        "spp_guidance_weight": regularised_partial_cfg["spp_guidance_weight"],
                        "missing_pair_policy": regularised_partial_cfg["missing_pair_policy"],
                    },
                )
                selected_calibration = {
                    "status": "regularisation_fallback",
                    "reason": "no_export_ready_candidate",
                    "local_spp_package_generated": False,
                }
                effective_with_spp = False

            if effective_with_spp:
                selected_corpus_candidate = corpus_candidates[selected_candidate_index]
                spp_input_dir = (
                    run_dir
                    / "artifacts"
                    / "spp_input"
                    / _safe_artifact_slug(selected_corpus_candidate["candidate_id"])
                )
                staged_cifs = stage_export_ready_cifs(
                    retrieval_bundle,
                    list(corpus_manifest.selected_ids),
                    spp_input_dir,
                )
                logger.write_artifact("artifacts/spp_input_selection.json", staged_cifs)
                if int(staged_cifs.get("staged_count", 0) or 0) <= 0:
                    fallback_cfg = regularised_partial_spp_config(overrides)
                    allow_without_spp = bool(overrides.get("allow_qlip_without_spp", False))
                    if fallback_cfg is None or not allow_without_spp:
                        explicit_corpus_guidance = any(
                            key in overrides
                            for key in {
                                "retrieval_candidate_k",
                                "corpus_strategy",
                                "corpus_top_k",
                                "corpus_strategy_candidates",
                                "corpus_top_k_candidates",
                                "guidance_mode",
                            }
                        )
                        failure_reason = (
                            "spp_corpus_unavailable:no_export_ready_candidate"
                            if explicit_corpus_guidance
                            else "spp_corpus_unavailable:no_export_ready_candidate_and_no_regularisation_fallback"
                        )
                        logger.write_artifact(
                            "artifacts/spp_corpus_unavailable_diagnostics.json",
                            _build_spp_corpus_unavailable_diagnostics(
                                retrieval_bundle=retrieval_bundle,
                                corpus_candidates=corpus_candidates,
                                selected_candidate_index=selected_candidate_index,
                                staged_cifs=staged_cifs,
                                fallback_cfg=fallback_cfg,
                                allow_without_spp=allow_without_spp,
                                overrides=overrides,
                                settings=settings,
                                formula=task_spec_obj.composition_target,
                                failure_reason=failure_reason,
                            ),
                        )
                        raise PipelineError(failure_reason)
                    logger.write_artifact(
                        "artifacts/spp_regularisation_fallback.json",
                        {
                            "schema_version": "spp.regularisation_fallback.v1",
                            "reason": "no_export_ready_candidate",
                            "local_spp_package_generated": False,
                            "regularisation_spp_dir": fallback_cfg["regularisation_spp_dir"],
                            "regularisation_weight": fallback_cfg["regularisation_weight"],
                            "spp_guidance_weight": fallback_cfg["spp_guidance_weight"],
                            "missing_pair_policy": fallback_cfg["missing_pair_policy"],
                        },
                    )
                    regularised_pot_root = find_spp_pot_root(
                        tuple(Path(root).resolve() for root in settings.qlip_allowed_path_roots),
                        task_spec_obj.composition_target,
                    )
                    if regularised_pot_root:
                        overrides["spp_pot_root"] = regularised_pot_root
                    selected_calibration = {
                        "status": "regularisation_fallback",
                        "reason": "no_export_ready_candidate",
                        "local_spp_package_generated": False,
                    }
                    lambda_resolution = _resolve_spp_lambda(
                        default_lambda=float(guidance_payload.get("lambda_override", 0.7)),
                        selected_calibration=selected_calibration,
                        execution_overrides=overrides,
                    )
                    guidance_payload["lambda_override"] = float(lambda_resolution["spp_lambda_value"])
                    logger.write_artifact("artifacts/spp_lambda_resolution.json", dict(lambda_resolution))
                    effective_with_spp = True
                    spp_artifact_manifest = None
                    package_alternatives = []
                    selected_variant = str(overrides.get("spp_package_variant", "default")).strip().lower() or "default"
                    package_path = None
                    # Skip local SPP packaging; QLIP will receive explicit partial regularisation guidance below.
                if int(staged_cifs.get("staged_count", 0) or 0) <= 0:
                    pass
                else:
                    selected_variant = str(overrides.get("spp_package_variant", "default")).strip().lower() or "default"
                package_alternatives = _as_list_of_str(overrides.get("spp_package_alternatives"))
                package_alternatives = [item for item in package_alternatives if item in {"default", "focus", "broad"}]
                if selected_variant not in {"default", "focus", "broad"}:
                    selected_variant = "default"
                if selected_variant not in package_alternatives:
                    package_alternatives.insert(0, selected_variant)
                if not package_alternatives:
                    package_alternatives = [selected_variant]

                base_target = _as_float(overrides.get("spp_package_target"), 0.9, min_value=0.0, max_value=10.0)
                target_by_variant = {
                    "default": base_target,
                    "focus": min(10.0, base_target + 0.15),
                    "broad": max(0.0, base_target - 0.15),
                }
                last_spp_resp: dict[str, Any] | None = None
                last_pkg_resp: dict[str, Any] | None = None
                for idx, variant in enumerate(package_alternatives):
                    run_name = f"spp_run_{variant}_{idx}"
                    target = float(target_by_variant.get(variant, base_target))
                    spp_args_raw = {
                        "cif_dir": str(spp_input_dir),
                        "out_dir": str(run_dir / "artifacts" / "spp" / variant),
                        "name": run_name,
                        "target": target,
                    }
                    spp_args, spp_warnings = normalize_spp_arguments("spp.run_pipeline", spp_args_raw)
                    if spp_warnings:
                        logger.write_artifact(f"artifacts/spp_run_warnings_{variant}.json", spp_warnings)
                    validate_paths_in_args(
                        spp_args,
                        read_keys=["cif_dir"],
                        write_keys=["out_dir"],
                        allowed_read_roots=settings.allowed_read_roots,
                        allowed_write_roots=settings.allowed_write_roots,
                    )
                    enforce_requested_caps(spp_args, caps)
                    spp_resp = _call_tool(spp, logger, "spp.run_pipeline", spp_args)
                    spp_result = _unwrap_spp_result(spp_resp)
                    enforce_result_caps(spp_result, caps)
                    logger.write_artifact(f"artifacts/spp_run_{variant}.json", spp_resp)

                    pkg_args_raw = {
                        "run_root": spp_result["run_root"],
                        "out_dir": str(run_dir / "artifacts" / "spp_package" / variant),
                        "name": f"spp_package_{variant}",
                        "includeRegistrySnapshot": False,
                    }
                    pkg_args, pkg_warnings = normalize_spp_arguments("spp.package_for_qlip", pkg_args_raw)
                    if pkg_warnings:
                        logger.write_artifact(f"artifacts/spp_package_warnings_{variant}.json", pkg_warnings)
                    validate_paths_in_args(
                        pkg_args,
                        read_keys=["run_root", "spp_root", "calibration_json"],
                        write_keys=["out_dir"],
                        allowed_read_roots=settings.allowed_read_roots,
                        allowed_write_roots=settings.allowed_write_roots,
                    )
                    pkg_resp = _call_tool(spp, logger, "spp.package_for_qlip", pkg_args)
                    pkg_result = _unwrap_spp_result(pkg_resp)
                    enforce_result_caps(pkg_result, caps)
                    logger.write_artifact(f"artifacts/spp_package_{variant}.json", pkg_resp)

                    quantile = 0.8
                    if variant == "focus":
                        quantile = 0.9
                    elif variant == "broad":
                        quantile = 0.65
                    calibration = run_calibration_harness(
                        reference_scores=[float(item.get("scores", {}).get("score", 0.0)) for item in retrieval_bundle.items],
                        target_quantile=quantile,
                    )
                    logger.write_artifact(f"artifacts/spp_calibration_report_{variant}.json", calibration)
                    candidate_id = f"{variant}:{idx}"
                    spp_package_candidates.append(
                        {
                            "candidate_id": candidate_id,
                            "variant": variant,
                            "target": target,
                            "run_root": str(spp_result.get("run_root")),
                            "final_bundle_path": str(pkg_result.get("final_bundle_path")),
                            "calibration_summary": calibration,
                        }
                    )
                    if variant == selected_variant and package_path is None:
                        package_path = str(pkg_result.get("final_bundle_path"))
                        last_spp_resp = spp_resp
                        last_pkg_resp = pkg_resp
                        selected_calibration = calibration
                if package_path is None and spp_package_candidates:
                    package_path = str(spp_package_candidates[0]["final_bundle_path"])
                    selected_variant = str(spp_package_candidates[0]["variant"])
                    selected_calibration = dict(spp_package_candidates[0]["calibration_summary"])
                if not spp_package_candidates:
                    raise PipelineError("No SPP package candidates were generated.")
                logger.write_artifact(
                    "artifacts/spp_package_candidates.json",
                    {
                        "schema_version": "spp.package_candidates.v1",
                        "selected_variant": selected_variant,
                        "selected_package_path": package_path,
                        "items": spp_package_candidates,
                    },
                )
                if isinstance(last_spp_resp, dict):
                    logger.write_artifact("artifacts/spp_run.json", last_spp_resp)
                if isinstance(last_pkg_resp, dict):
                    logger.write_artifact("artifacts/spp_package.json", last_pkg_resp)
                logger.write_artifact("artifacts/spp_calibration_report.json", selected_calibration)
                lambda_resolution = _resolve_spp_lambda(
                    default_lambda=float(guidance_payload.get("lambda_override", 0.7)),
                    selected_calibration=selected_calibration,
                    execution_overrides=overrides,
                )
                guidance_payload["lambda_override"] = float(lambda_resolution["spp_lambda_value"])
                logger.write_artifact("artifacts/spp_lambda_resolution.json", dict(lambda_resolution))
                spp_artifact_manifest = SPPArtifactManifest(
                    artifact_id=f"spp-{run_id}-{selected_variant}",
                    corpus_hash=corpus_manifest.content_hash,
                    weighting_policy=f"{str(overrides.get('spp_payload_profile', 'balanced')).strip().lower()}_rank",
                    bin_policy={"bin_width": 0.1},
                    smoothing_params={"sigma": 0.2},
                    calibration_summary=selected_calibration,
                    neighbor_policy="first_shell",
                    cutoff_policy="bandpass",
                    shrink_protection={"enabled": True, "min_distance": 1.2, "max_distance": 6.5},
                    metadata={
                        "spp_package_path": package_path,
                        "pot_root": str(Path(package_path) / "spp_root"),
                        "selected_ids": corpus_manifest.selected_ids,
                        "selected_corpus_candidate_id": str(corpus_candidates[selected_candidate_index]["candidate_id"]),
                        "selected_corpus_strategy": str(corpus_candidates[selected_candidate_index]["strategy"]),
                        "selected_corpus_top_k": int(corpus_candidates[selected_candidate_index]["top_k"]),
                        "requested_corpus_candidate_id": str(corpus_selection_resolution["requested_candidate_id"]),
                        "corpus_selection_reason": str(corpus_selection_resolution["selection_reason"]),
                        "selected_exportable_count": int(
                            corpus_candidates[selected_candidate_index].get("exportability", {}).get("exportable_count", 0) or 0
                        ),
                        "selected_blocked_count": int(
                            corpus_candidates[selected_candidate_index].get("exportability", {}).get("blocked_count", 0) or 0
                        ),
                        "retrieval_candidate_k": retrieval_candidate_k,
                        "package_variant": selected_variant,
                        "weighting_profile": weighting_profile,
                        "structure_perturbation_profile": structure_perturbation_profile,
                        "template_seed_profile": template_seed_profile,
                        "lattice_candidate_profile": lattice_candidate_profile,
                        "symmetry_relaxation_profile": symmetry_relaxation_profile,
                        "ordering_perturbation_profile": ordering_perturbation_profile,
                        "package_candidate_ids": [str(item["candidate_id"]) for item in spp_package_candidates],
                        "guidance_payload": dict(guidance_payload),
                        "spp_input_dir": str(spp_input_dir),
                        "staged_cif_count": int(staged_cifs.get("staged_count", 0) or 0),
                        "spp_lambda_source": lambda_resolution.get("spp_lambda_source") if isinstance(lambda_resolution, dict) else None,
                        "spp_lambda_value": lambda_resolution.get("spp_lambda_value") if isinstance(lambda_resolution, dict) else None,
                        "spp_lambda_recommended_available": (
                            lambda_resolution.get("spp_lambda_recommended_available")
                            if isinstance(lambda_resolution, dict)
                            else None
                        ),
                        "spp_lambda_override_applied": (
                            lambda_resolution.get("spp_lambda_override_applied")
                            if isinstance(lambda_resolution, dict)
                            else None
                        ),
                    },
                )
                logger.write_artifact("artifacts/spp_artifact_manifest.json", spp_artifact_manifest.to_dict())

            if lambda_resolution is None:
                lambda_resolution = _resolve_spp_lambda(
                    default_lambda=float(guidance_payload.get("lambda_override", 0.7)),
                    selected_calibration=selected_calibration,
                    execution_overrides=overrides,
                )
                guidance_payload["lambda_override"] = float(lambda_resolution["spp_lambda_value"])
                logger.write_artifact("artifacts/spp_lambda_resolution.json", dict(lambda_resolution))

            qlip_objective = overrides.get("qlip_objective") if "qlip_objective" in overrides else task_spec_obj.qlip_objective
            external_predictor_targets = normalize_external_predictor_requests(
                overrides.get("external_predictors")
                if "external_predictors" in overrides
                else task_spec_obj.external_predictor_targets
            )
            builder_input_trace = _build_builder_input_trace(
                execution_overrides=execution_overrides,
                plan_payload=plan_payload,
                cell_policy=cell_policy,
                task_spec_obj=task_spec_obj,
                retrieval_bundle=retrieval_bundle,
                corpus_manifest=corpus_manifest,
                corpus_candidates=corpus_candidates,
                spp_artifact_manifest=spp_artifact_manifest,
                spp_package_candidates=spp_package_candidates,
                guidance_payload=guidance_payload,
                lambda_resolution=lambda_resolution,
                effective_with_spp=effective_with_spp,
                qlip_objective=qlip_objective,
                external_predictor_targets=external_predictor_targets,
            )
            qlip_request, qlip_request_meta = build_solve_request_v2(
                task_spec=task_spec_obj,
                cell_candidates=cell_candidates,
                retrieval_bundle=retrieval_bundle,
                spp_artifact=spp_artifact_manifest,
                guidance_mode=str(plan_payload["guidance_mode"]),
                guidance_config=guidance_payload,
                weighting_profile=weighting_profile,
                structure_perturbation_profile=structure_perturbation_profile,
                template_seed_profile=template_seed_profile,
                lattice_candidate_profile=lattice_candidate_profile,
                symmetry_relaxation_profile=symmetry_relaxation_profile,
                ordering_perturbation_profile=ordering_perturbation_profile,
                active_symmetry_mode=active_symmetry_mode,
                qlip_objective=qlip_objective,
            )
            qlip_request_meta = dict(qlip_request_meta)
            qlip_request_meta["builder_input_trace"] = builder_input_trace
            qlip_request_meta["spp_lambda_resolution"] = dict(lambda_resolution or {})
            logger.write_artifact("artifacts/qlip_builder_meta.json", qlip_request_meta)
            if qlip_request_mutator:
                qlip_request = qlip_request_mutator(json.loads(json.dumps(qlip_request)))
            if use_regularised_partial_guidance:
                qlip_request = apply_regularised_partial_spp_guidance(
                    qlip_request,
                    formula=task_spec_obj.composition_target,
                    overrides=overrides,
                )
                qlip_request_meta["regularised_partial_spp_guidance"] = {
                    "enabled": True,
                    "local_spp_package_generated": spp_artifact_manifest is not None,
                    "regularisation_spp_dir": regularised_partial_cfg["regularisation_spp_dir"],
                    "regularisation_weight": regularised_partial_cfg["regularisation_weight"],
                    "spp_guidance_weight": regularised_partial_cfg["spp_guidance_weight"],
                    "missing_pair_policy": regularised_partial_cfg["missing_pair_policy"],
                    "pot_root": regularised_pot_root,
                }
            if mode == "live":
                logger.write_artifact("artifacts/qlip_request.builder.json", qlip_request)
                qlip_request = _strip_live_qlip_design_space_metadata(qlip_request)
            logger.write_artifact("artifacts/qlip_request.json", qlip_request)
            logger.write_artifact(
                "artifacts/qlip_request.semantic.json",
                _semantic_qlip_request(qlip_request, spp_artifact=spp_artifact_manifest),
            )
            logger.write_artifact(
                "artifacts/symmetry_trace.json",
                _build_symmetry_trace(
                    task_spec_obj=task_spec_obj,
                    qlip_request=qlip_request,
                    qlip_request_meta=qlip_request_meta,
                ),
            )
            orbit_solution = prototype_orbit_solution_from_request(qlip_request)
            if qlip_request_meta.get("active_symmetry_mode") in {
                "prototype_orbit_qlip",
                "prototype_orbit_variable_qlip",
                "prototype_orbit_variable_spp_qlip",
            } and orbit_solution is not None:
                logger.write_artifact("artifacts/orbit_solution.json", orbit_solution_payload(orbit_solution))
                orbit_candidates = prototype_orbit_candidates_payload_from_request(qlip_request)
                if orbit_candidates is not None:
                    logger.write_artifact("artifacts/orbit_candidates.json", orbit_candidates)
            validate_solve_request(qlip_request)
            validate_resp = _call_tool(qlip, logger, "qlip.validate_request", {"request": qlip_request})
            logger.write_artifact("artifacts/qlip_validate.json", validate_resp)
            if validate_resp.get("ok") is False:
                raise PipelineError(f"qlip_request_rejected:{validate_resp.get('primary_error') or validate_resp.get('errors')}")
            solve_resp = _call_tool(qlip, logger, "qlip.solve", {"request": qlip_request})
            logger.write_artifact("artifacts/qlip_solve.json", solve_resp)
            verification = run_verification_stage(
                solve_payload=solve_resp,
                guidance_expected=effective_with_spp or use_regularised_partial_guidance,
                preset_name=plan_payload["verification_preset"],
            )
            logger.write_artifact("artifacts/verification_report.json", verification)
            if not verification.get("ok", False):
                raise PipelineError(f"qlip_outputs_invalid:{verification}")

            solve_payload = solve_resp.get("result", solve_resp)
            cif_path = None
            if isinstance(solve_payload, dict):
                # QLIP v5 shape: result.result.outputs.cif
                nested_result = solve_payload.get("result")
                if isinstance(nested_result, dict):
                    outputs = nested_result.get("outputs")
                    if isinstance(outputs, dict):
                        cif = outputs.get("cif")
                        if isinstance(cif, str):
                            cif_path = cif
                # Backward-compatible fallback
                if cif_path is None:
                    cif = solve_payload.get("cif_path")
                    if isinstance(cif, str):
                        cif_path = cif
            if external_predictor_targets:
                external_predictions = run_external_predictors(
                    external_predictor_targets,
                    formula=task_spec_obj.composition_target,
                    cif_path=cif_path,
                )
                logger.write_artifact("artifacts/external_predictions.json", external_predictions)
                if not bool(external_predictions.get("ok", False)):
                    raise PipelineError(f"external_predictions_failed:{external_predictions}")
            if isinstance(cif_path, str) and cif_path:
                logger.write_artifact(
                    "artifacts/symmetry_trace.json",
                    _build_symmetry_trace(
                        task_spec_obj=task_spec_obj,
                        qlip_request=qlip_request,
                        qlip_request_meta=qlip_request_meta,
                        cif_path=cif_path,
                    ),
                )
                novelty_args = {"cif_path": cif_path}
                novelty_args, novelty_notes = apply_crystal_policy_defaults(
                    novelty_args, settings.crystaldb_policy_mode
                )
                if novelty_notes:
                    logger.write_artifact("artifacts/novelty_policy_notes.json", {"notes": novelty_notes})
                validate_paths_in_args(
                    novelty_args,
                    read_keys=["cif_path"],
                    write_keys=[],
                    allowed_read_roots=settings.allowed_read_roots,
                    allowed_write_roots=settings.allowed_write_roots,
                )
                novelty_resp = _call_tool(crystal, logger, "crystal.novelty_check", novelty_args)
                logger.write_artifact("artifacts/novelty_check.json", novelty_resp)

        except QLIPValidationError as exc:
            status = "FAILED_SCHEMA"
            failure_reason = str(exc)
        except Exception as exc:  # noqa: BLE001
            status = "FAILED"
            failure_reason = str(exc)

    manifest = {
        "schema_version": "run_manifest.v1",
        "run_id": run_id,
        "inputs": canonical_inputs,
        "inputs_hash": sha256_text(canonical_json(canonical_inputs)),
        "stage_versions": {
            "task_spec": "task_spec.v1",
            "run_plan": "run_plan.v1",
            "retrieval": "retrieval.result.v2",
            "spp_artifact": "spp.artifact.v1" if effective_with_spp else None,
        },
        "status": status,
        "failure_reason": failure_reason,
        "tool_call_log": str(logger.log_path.relative_to(run_dir)),
    }
    manifest_path = logger.write_manifest(manifest)
    return PipelineRun(run_id=run_id, run_dir=run_dir, manifest_path=manifest_path, status=status)
