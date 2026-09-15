from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.contracts.qlip_schema import (
    QLIPValidationError,
    SPP_GUIDANCE_PARAMS_SCHEMA,
    validate_solve_request,
)
from sok_llm_orchestrator.mcp.fake_lib import serve
from sok_llm_orchestrator.structures.parseable_cif import write_parseable_cif
from sok_llm_orchestrator.structures.prototype_scaffold import write_prototype_scaffold_cif

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
        "payload_sha256": "shim",
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
        "payload_sha256": "shim",
        "duration_ms": 1,
        "warnings": [],
        "errors": [item],
        "primary_error": item,
        "meta": {"category": category, "retryable": False},
    }


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
            return _ok(name, {"valid": True, "normalized_request": request, "warnings": [], "errors": []})

        run_dir = Path(os.environ.get("SOKLLM_RUN_DIR", str(Path.cwd() / ".sokllm_workspace" / "runs" / "shim"))).resolve()
        output_dir = run_dir / "artifacts" / "qlip"
        output_dir.mkdir(parents=True, exist_ok=True)
        cif_path = output_dir / "solution.cif"
        formula = (
            str(request.get("problem", {}).get("chemistry", {}).get("formula"))
            if isinstance(request.get("problem"), dict)
            and isinstance(request.get("problem", {}).get("chemistry"), dict)
            and isinstance(request.get("problem", {}).get("chemistry", {}).get("formula"), str)
            else "Si"
        )
        scaffold_trace = write_prototype_scaffold_cif(cif_path, request)
        if not scaffold_trace.get("scaffold_used_for_final_cif"):
            write_parseable_cif(cif_path, formula=formula, lattice_a=4.2)
        terms = [{"term": "baseline", "value": 2.83}]
        has_spp = any(item.get("id") == "objective.energy_spp" for item in request.get("guidance", []))
        objective = request.get("objective")
        objective_type = (
            str(objective.get("type"))
            if isinstance(objective, dict) and isinstance(objective.get("type"), str)
            else None
        )
        property_x = 0.61
        if has_spp:
            terms.append({"term": "SPP", "value": -4.36})
            property_x = 0.78
        if objective_type == "density_packing":
            terms.append({"term": "density_packing:pair_distance_packing", "value": 0.42})
        elif objective_type == "linear_property":
            terms.append({"term": "linear_property:occupancy_linear", "value": 0.31})
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
                    },
                    "outputs": {
                        "cif": str(cif_path),
                        "decoder_debug": None,
                        "artifacts": [],
                        "objective_terms": terms,
                        "property_estimates": {"property_x": property_x},
                        "spp_summary": "shim spp summary" if has_spp else None,
                        "spp_breakdown": "shim spp breakdown" if has_spp else None,
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
