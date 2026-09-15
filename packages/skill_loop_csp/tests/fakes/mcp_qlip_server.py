from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from mcp_fake_lib import serve

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sok_llm_orchestrator.contracts.qlip_schema import (  # noqa: E402
    QLIPValidationError,
    SPP_GUIDANCE_PARAMS_SCHEMA,
    validate_solve_request,
)
from sok_llm_orchestrator.structures.parseable_cif import write_parseable_cif  # noqa: E402
from sok_llm_orchestrator.structures.prototype_scaffold import write_prototype_scaffold_cif  # noqa: E402

TOOLS = [
    "qlip.shapes",
    "qlip.list_constraints",
    "qlip.list_guidance",
    "qlip.validate_request",
    "qlip.solve",
]


def _ok(tool: str, result: dict[str, Any], warnings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "tool": tool,
        "trace_id": f"{tool}-trace",
        "payload_sha256": "stub",
        "duration_ms": 1,
        "warnings": warnings or [],
        "result": result,
    }


def _err(tool: str, code: str, message: str, pointer: str | None = None, category: str = "SCHEMA") -> dict[str, Any]:
    item = {"code": code, "message": message}
    if pointer:
        item["pointer"] = pointer
    return {
        "ok": False,
        "tool": tool,
        "trace_id": f"{tool}-trace",
        "payload_sha256": "stub",
        "duration_ms": 1,
        "warnings": [],
        "errors": [item],
        "primary_error": item,
        "meta": {"category": category, "retryable": False},
    }


def _write_solution_cif(
    *,
    cif_path: Path,
    formula: str,
    movement_strength: int,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if os.environ.get("FAKE_QLIP_PLACEHOLDER_SOLUTION") == "1":
        cif_path.write_text("data_solution\n", encoding="utf-8")
        return {"scaffold_used_for_final_cif": False, "final_cif_source": "generic_fallback", "fallback_reason": "placeholder_solution_requested"}
    if os.environ.get("FAKE_QLIP_BAD_CIF") == "1":
        cif_path.write_text("not_a_cif\nthis will not parse\n", encoding="utf-8")
        return {"scaffold_used_for_final_cif": False, "final_cif_source": "generic_fallback", "fallback_reason": "bad_cif_requested"}
    if os.environ.get("FAKE_QLIP_INCOMPLETE_CIF") == "1":
        cif_path.write_text(
            "\n".join(
                [
                    "data_solution",
                    "_symmetry_space_group_name_H-M 'P 1'",
                    "_cell_length_a 4.00000000",
                    "_cell_length_b 4.00000000",
                    "_cell_length_c 4.00000000",
                    "_cell_angle_alpha 90.00000000",
                    "_cell_angle_beta 90.00000000",
                    "_cell_angle_gamma 90.00000000",
                    f"_chemical_formula_sum '{formula}'",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return {"scaffold_used_for_final_cif": False, "final_cif_source": "generic_fallback", "fallback_reason": "incomplete_cif_requested"}
    output_formula = formula
    lattice_a = 4.0 + (0.08 * movement_strength)
    if os.environ.get("FAKE_QLIP_CONSTANT_SOLUTION") == "1":
        output_formula = "Si"
        lattice_a = 4.2
    scaffold_trace = write_prototype_scaffold_cif(cif_path, request or {})
    if not scaffold_trace.get("scaffold_used_for_final_cif"):
        write_parseable_cif(cif_path, formula=output_formula, lattice_a=lattice_a)
    return scaffold_trace


def on_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "qlip.shapes":
        return _ok(
            name,
            {
                "tools": [
                    {
                        "name": "qlip.solve",
                        "strict_schema": True,
                        "canonical_args_example": {"version": "1.0"},
                    }
                ]
            },
        )
    if name == "qlip.list_constraints":
        return _ok(name, {"items": []})
    if name == "qlip.list_guidance":
        return _ok(
            name,
            {
                "items": [
                    {
                        "id": "objective.energy_spp",
                        "kind": "guidance",
                        "title": "SPP objective guidance",
                        "description": "Adds SPP term to objective decomposition.",
                        "params_schema": SPP_GUIDANCE_PARAMS_SCHEMA,
                        "tags": ["spp", "objective"],
                        "capabilities": {},
                        "version": "v1",
                    },
                    {
                        "id": "objective.density_packing",
                        "kind": "objective",
                        "title": "Density packing objective",
                        "description": "Pair-distance packing/contact proxy, not physical mass density.",
                        "tags": ["objective", "density_packing"],
                        "capabilities": {"objective_types": ["density_packing"]},
                        "version": "v1",
                    },
                    {
                        "id": "objective.linear_property",
                        "kind": "objective",
                        "title": "Occupancy-linear property objective",
                        "description": "Native linear property over occupancy terms.",
                        "tags": ["objective", "linear_property"],
                        "capabilities": {"objective_types": ["linear_property", "threshold_tradeoff"]},
                        "version": "v1",
                    }
                ]
            },
        )
    if name in {"qlip.validate_request", "qlip.solve"}:
        request = args.get("request")
        if not isinstance(request, dict):
            return _err(name, "validation_error", "request must be object", pointer="/request")
        try:
            validate_solve_request(request)
        except QLIPValidationError as exc:
            pointer, message = str(exc).split(": ", 1) if ": " in str(exc) else ("/", str(exc))
            return _err(name, "validation_error", message, pointer=pointer)
        if name == "qlip.validate_request":
            normalized_request = dict(request)
            problem = normalized_request.get("problem")
            if isinstance(problem, dict) and "objective" not in problem:
                problem = dict(problem)
                problem["objective"] = {"type": "spp_energy"}
                normalized_request["problem"] = problem
            return _ok(name, {"valid": True, "normalized_request": normalized_request, "warnings": [], "errors": []})

        if os.environ.get("FAKE_QLIP_SOLVE_ERROR_DIAGNOSTICS") == "1":
            return _ok(
                name,
                {
                    "run_id": "qlip-run",
                    "result": {
                        "status": "ERROR",
                        "error": "pot_root_missing",
                        "outputs": {"cif": None},
                        "certificates": {
                            "diagnostics": {
                                "spp_guidance": {
                                    "mode": "partial_regularised",
                                    "missing_pair_policy": "soft_repulsive",
                                    "regularisation_weight": 2.0,
                                },
                                "qlip_error": {
                                    "code": "pot_root_missing",
                                    "message": "context.pot_root is required for SPP potentials",
                                },
                                "solver_status": "ERROR",
                            }
                        },
                        "errors": [
                            {
                                "code": "pot_root_missing",
                                "message": "context.pot_root is required for SPP potentials",
                            }
                        ],
                    },
                },
            )

        run_dir = Path(os.environ.get("SOKLLM_RUN_DIR", str(ROOT / ".sokllm_workspace" / "runs" / "stub"))).resolve()
        output_dir = run_dir / "artifacts" / "qlip"
        output_dir.mkdir(parents=True, exist_ok=True)
        cif_path = output_dir / "solution.cif"
        problem = request.get("problem", {})
        design_space = problem.get("design_space", {}) if isinstance(problem, dict) else {}
        template = design_space.get("template", {}) if isinstance(design_space, dict) else {}
        seeding = design_space.get("seeding", {}) if isinstance(design_space, dict) else {}
        sites = design_space.get("sites", {}) if isinstance(design_space, dict) else {}
        ordering_priors = sites.get("ordering_priors", {}) if isinstance(sites, dict) else {}
        template_candidates = design_space.get("template_candidates", []) if isinstance(design_space, dict) else []
        constraints = request.get("constraints", [])
        guidance = request.get("guidance", [])
        objective = problem.get("objective") if isinstance(problem, dict) else None
        formula = (
            str(problem.get("chemistry", {}).get("formula"))
            if isinstance(problem, dict)
            and isinstance(problem.get("chemistry"), dict)
            and isinstance(problem.get("chemistry", {}).get("formula"), str)
            else "UNKNOWN"
        )
        seed_profile = (
            str(template.get("seed_profile"))
            if isinstance(template, dict) and isinstance(template.get("seed_profile"), str)
            else "canonical"
        )
        perturb_profile = (
            str(template.get("perturbation_profile"))
            if isinstance(template, dict) and isinstance(template.get("perturbation_profile"), str)
            else "minimal"
        )
        lattice_profile = (
            str(seeding.get("lattice_candidate_profile"))
            if isinstance(seeding, dict) and isinstance(seeding.get("lattice_candidate_profile"), str)
            else "narrow"
        )
        symmetry_profile = (
            str(seeding.get("symmetry_relaxation_profile"))
            if isinstance(seeding, dict) and isinstance(seeding.get("symmetry_relaxation_profile"), str)
            else "strict"
        )
        ordering_profile = (
            str(ordering_priors.get("profile"))
            if isinstance(ordering_priors, dict) and isinstance(ordering_priors.get("profile"), str)
            else "none"
        )
        movement_strength = 0
        movement_strength += 1 if seed_profile != "canonical" else 0
        movement_strength += 1 if perturb_profile != "minimal" else 0
        movement_strength += 1 if lattice_profile != "narrow" else 0
        movement_strength += 1 if symmetry_profile != "strict" else 0
        movement_strength += 1 if ordering_profile != "none" else 0
        movement_strength += 1 if isinstance(template_candidates, list) and len(template_candidates) > 1 else 0
        if isinstance(constraints, list):
            if any(isinstance(item, dict) and item.get("id") == "constraint.space_group_soft" for item in constraints):
                movement_strength += 1
            if any(
                isinstance(item, dict) and item.get("id") == "constraint.ordering_perturbation_profile" for item in constraints
            ):
                movement_strength += 1
        structure_tag = f"{seed_profile}|{perturb_profile}|{lattice_profile}|{symmetry_profile}|{ordering_profile}|m{movement_strength}"
        scaffold_trace = _write_solution_cif(
            cif_path=cif_path,
            formula=formula,
            movement_strength=movement_strength,
            request=request,
        )
        terms = [{"term": "baseline", "value": 2.83}]
        has_spp = False
        if isinstance(guidance, list):
            has_spp = any(isinstance(item, dict) and item.get("id") == "objective.energy_spp" for item in guidance)
        property_x = 0.61
        if has_spp:
            terms.append({"term": "SPP", "value": -4.36})
            property_x = 0.78 + (0.01 * min(5, movement_strength))
        if movement_strength > 0:
            terms.append({"term": "structure_shift", "value": -0.02 * float(movement_strength)})
        objective_type = str(objective.get("type")) if isinstance(objective, dict) and isinstance(objective.get("type"), str) else None
        if objective_type == "density_packing":
            terms.append({"term": "density_packing:pair_distance_packing", "value": 0.42 + 0.01 * movement_strength})
        elif objective_type == "linear_property":
            terms.append({"term": "linear_property:occupancy_linear", "value": 0.31 + 0.02 * movement_strength})
        elif objective_type == "threshold_tradeoff":
            terms.append({"term": "threshold_tradeoff:hard_bound", "value": 1.0})
            if isinstance(objective.get("property_weight"), (int, float)):
                terms.append({"term": "threshold_tradeoff:weighted_property", "value": float(objective["property_weight"])})
        return _ok(
            name,
            {
                "run_id": "qlip-run",
                "result": {
                    "status": "OPTIMAL",
                    "summary": {
                        "solver": "gurobi",
                        "timing_ms": 10,
                        "objective_value": -1.53,
                        "property_x": property_x,
                        "best_bound": -1.53,
                        "mip_gap": 0.0,
                        "termination": "optimal",
                        "structure_profile": structure_tag,
                    },
                    "outputs": {
                        "cif": str(cif_path),
                        "decoder_debug": None,
                        "artifacts": [],
                        "objective_terms": terms,
                        "property_estimates": {"property_x": property_x},
                        "spp_summary": "stub spp summary" if has_spp else None,
                        "spp_breakdown": "stub spp breakdown" if has_spp else None,
                        "qlip_objective_family": objective_type,
                        "scaffold_trace": scaffold_trace,
                    },
                    "certificates": {},
                    "errors": [],
                    "logs": [],
                },
            },
        )
    return _err(name, "unknown_tool", name, category="FORMAT")


if __name__ == "__main__":
    serve(TOOLS, on_call)
