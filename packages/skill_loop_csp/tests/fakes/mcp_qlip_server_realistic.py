from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sok_llm_orchestrator.contracts.qlip_schema import QLIPValidationError, validate_solve_request  # noqa: E402
from sok_llm_orchestrator.structures.parseable_cif import write_parseable_cif  # noqa: E402
from sok_llm_orchestrator.structures.prototype_scaffold import write_prototype_scaffold_cif  # noqa: E402

TOOLS = [
    "qlip.shapes",
    "qlip.list_constraints",
    "qlip.list_guidance",
    "qlip.validate_request",
    "qlip.solve",
]


def _ok(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "tool": tool,
        "trace_id": f"{tool}-trace",
        "payload_sha256": "realistic",
        "duration_ms": 1,
        "warnings": [],
        "result": result,
    }


def _err(tool: str, code: str, message: str, pointer: str | None = None) -> dict[str, Any]:
    item = {"code": code, "message": message}
    if pointer:
        item["pointer"] = pointer
    return {
        "ok": False,
        "tool": tool,
        "trace_id": f"{tool}-trace",
        "payload_sha256": "realistic",
        "duration_ms": 1,
        "warnings": [],
        "errors": [item],
        "primary_error": item,
        "meta": {"category": "SCHEMA", "retryable": False},
    }


def _extract_request(arguments: Any) -> dict[str, Any] | None:
    if isinstance(arguments, dict) and isinstance(arguments.get("request"), dict):
        return dict(arguments["request"])
    return None


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _package_variant_from_path(path_text: str) -> str:
    lowered = str(path_text or "").replace("\\", "/").lower()
    if "focus" in lowered:
        return "focus"
    if "broad" in lowered:
        return "broad"
    return "default"


def _request_profiles(request: dict[str, Any]) -> dict[str, str]:
    problem = request.get("problem", {})
    design_space = problem.get("design_space", {}) if isinstance(problem, dict) else {}
    template = design_space.get("template", {}) if isinstance(design_space, dict) else {}
    seeding = design_space.get("seeding", {}) if isinstance(design_space, dict) else {}
    sites = design_space.get("sites", {}) if isinstance(design_space, dict) else {}
    ordering_priors = sites.get("ordering_priors", {}) if isinstance(sites, dict) else {}

    def _profile(source: Any, key: str, default: str) -> str:
        if isinstance(source, dict) and isinstance(source.get(key), str):
            text = str(source.get(key)).strip().lower()
            return text or default
        return default

    return {
        "template_seed_profile": _profile(template, "seed_profile", "canonical"),
        "structure_perturbation_profile": _profile(template, "perturbation_profile", "minimal"),
        "lattice_candidate_profile": _profile(seeding, "lattice_candidate_profile", "narrow"),
        "symmetry_relaxation_profile": _profile(seeding, "symmetry_relaxation_profile", "strict"),
        "ordering_perturbation_profile": _profile(ordering_priors, "profile", "none"),
    }


def _structure_signal(profiles: dict[str, str]) -> float:
    template_seed = {
        "canonical": 0.0,
        "polymorph_mix": 0.04,
        "framework_bias": 0.09,
        "ordering_bias": 0.07,
    }
    perturbation = {
        "minimal": 0.0,
        "moderate": 0.05,
        "aggressive": 0.11,
        "template_shuffle": 0.08,
    }
    lattice = {
        "narrow": 0.0,
        "expanded": 0.04,
        "multibasin": 0.10,
    }
    symmetry = {
        "strict": 0.0,
        "soft": 0.02,
        "relaxed": 0.05,
    }
    ordering = {
        "none": 0.0,
        "site_shuffle": 0.03,
        "cation_swap_bias": 0.08,
    }
    return round(
        float(template_seed.get(profiles.get("template_seed_profile"), 0.0))
        + float(perturbation.get(profiles.get("structure_perturbation_profile"), 0.0))
        + float(lattice.get(profiles.get("lattice_candidate_profile"), 0.0))
        + float(symmetry.get(profiles.get("symmetry_relaxation_profile"), 0.0))
        + float(ordering.get(profiles.get("ordering_perturbation_profile"), 0.0)),
        6,
    )


def _handle_tool_call(name: str, arguments: Any) -> dict[str, Any]:
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
                    {"id": "objective.energy_spp", "kind": "guidance"},
                    {"id": "objective.density_packing", "kind": "objective"},
                    {"id": "objective.linear_property", "kind": "objective"},
                ]
            },
        )
    if name in {"qlip.validate_request", "qlip.solve"}:
        request = _extract_request(arguments)
        if not isinstance(request, dict):
            return _err(name, "validation_error", "request must be object", pointer="/request")
        try:
            validate_solve_request(request)
        except QLIPValidationError as exc:
            pointer, message = str(exc).split(": ", 1) if ": " in str(exc) else ("/", str(exc))
            return _err(name, "validation_error", message, pointer=pointer)
        if name == "qlip.validate_request":
            return _ok(name, {"valid": True, "normalized_request": request, "warnings": [], "errors": []})
        run_dir = Path(os.environ.get("SOKLLM_RUN_DIR", str(ROOT / ".sokllm_workspace" / "runs" / "realistic"))).resolve()
        out_dir = run_dir / "artifacts" / "qlip"
        out_dir.mkdir(parents=True, exist_ok=True)
        formula = "UNKNOWN"
        if isinstance(request.get("problem"), dict):
            chemistry = request["problem"].get("chemistry")
            if isinstance(chemistry, dict) and isinstance(chemistry.get("formula"), str):
                formula = chemistry["formula"]
        guidance = request.get("guidance")
        spp_guidance: dict[str, Any] | None = None
        if isinstance(guidance, list):
            for item in guidance:
                if isinstance(item, dict) and item.get("id") == "objective.energy_spp":
                    spp_guidance = item
                    break
        has_spp = spp_guidance is not None
        guidance_params = (
            dict(spp_guidance.get("params", {}))
            if isinstance(spp_guidance, dict) and isinstance(spp_guidance.get("params"), dict)
            else {}
        )
        profiles = _request_profiles(request)
        structure_signal = _structure_signal(profiles)
        weighting_profile = str(guidance_params.get("weighting_profile", "balanced")).strip().lower() or "balanced"
        package_variant = _package_variant_from_path(str(guidance_params.get("spp_package_path", "")))
        lambda_override = _as_float(guidance_params.get("lambda_override"), 0.7)
        top_k_breakdown = max(0, _as_int(guidance_params.get("top_k_breakdown"), 10))
        base_weight_scale = _as_float(guidance_params.get("base_weight_scale"), 1.0)
        guidance_weight_scale = _as_float(guidance_params.get("guidance_weight_scale"), 1.0)
        variant_offset = {"default": 0.0, "focus": 0.08, "broad": -0.04}.get(package_variant, 0.0)
        lambda_signal = max(0.0, lambda_override - 0.7)
        top_k_signal = min(0.06, 0.002 * float(max(0, top_k_breakdown - 10)))
        guidance_balance_signal = max(0.0, guidance_weight_scale - base_weight_scale)
        problem = request.get("problem") if isinstance(request.get("problem"), dict) else {}
        objective = problem.get("objective")
        objective_type = (
            str(objective.get("type"))
            if isinstance(objective, dict) and isinstance(objective.get("type"), str)
            else None
        )
        cif_path = out_dir / "solution.cif"
        lattice_a = round(
            4.1234
            + (0.08 if has_spp else 0.0)
            + structure_signal
            + variant_offset
            + top_k_signal
            + (0.03 * lambda_signal)
            + (0.02 * guidance_balance_signal),
            6,
        )
        scaffold_trace = write_prototype_scaffold_cif(cif_path, request)
        if not scaffold_trace.get("scaffold_used_for_final_cif"):
            write_parseable_cif(cif_path, formula=formula, lattice_a=lattice_a)
        property_x = round(
            0.61
            + (0.11 if has_spp else 0.0)
            + (0.18 * structure_signal)
            + (0.03 * lambda_signal)
            + (0.015 * guidance_balance_signal)
            + variant_offset
            + top_k_signal,
            6,
        )
        objective_value = round(
            -1.43
            + (0.20 if has_spp else 0.0)
            + (0.45 * structure_signal)
            + (0.08 * lambda_signal)
            + (0.04 * guidance_balance_signal)
            + variant_offset
            + (0.5 * top_k_signal),
            6,
        )
        objective_terms = [{"term": "baseline", "value": 2.0}]
        if has_spp:
            spp_term = round(
                -3.2
                + (0.40 * structure_signal)
                + (0.12 * lambda_signal)
                + (0.05 * guidance_balance_signal)
                + variant_offset
                + (0.5 * top_k_signal),
                6,
            )
            objective_terms.append({"term": "SPP", "value": spp_term})
        structure_profile = "|".join(
            [
                profiles["template_seed_profile"],
                profiles["structure_perturbation_profile"],
                profiles["lattice_candidate_profile"],
                profiles["symmetry_relaxation_profile"],
                profiles["ordering_perturbation_profile"],
            ]
        )
        guidance_profile = "|".join(
            [
                package_variant,
                weighting_profile,
                f"lambda={lambda_override:.2f}",
                f"topk={top_k_breakdown}",
            ]
        )
        return _ok(
            name,
            {
                "run_id": "qlip-realistic-run",
                "result": {
                    "status": "OPTIMAL",
                    "summary": {
                        "solver": "gurobi",
                        "objective_value": objective_value,
                        "property_x": property_x,
                        "structure_profile": structure_profile,
                        "guidance_profile": guidance_profile,
                    },
                    "outputs": {
                        "cif": str(cif_path),
                        "objective_terms": objective_terms
                        + (
                            [{"term": "density_packing:pair_distance_packing", "value": 0.42}]
                            if objective_type == "density_packing"
                            else []
                        )
                        + (
                            [{"term": "linear_property:occupancy_linear", "value": 0.31}]
                            if objective_type == "linear_property"
                            else []
                        )
                        + (
                            [{"term": "threshold_tradeoff:hard_bound", "value": 1.0}]
                            if objective_type == "threshold_tradeoff"
                            else []
                        ),
                        "property_estimates": {"property_x": property_x},
                        "qlip_objective_family": objective_type,
                        "scaffold_trace": scaffold_trace,
                    },
                    "errors": [],
                    "logs": [],
                },
            },
        )
    return _err(name, "unknown_tool", name)


def _write_json_line(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _response_id(req_id: Any) -> Any:
    if os.environ.get("FAKE_MCP_RESPONSE_ID_STRING") == "1":
        return str(req_id)
    return req_id


def main() -> None:
    initialized = False
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})
        if method == "initialize":
            _write_json_line(
                {
                    "jsonrpc": "2.0",
                    "id": _response_id(req_id),
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "qlip-realistic", "version": "1.0.0"},
                        "capabilities": {},
                    },
                }
            )
            continue
        if method == "notifications/initialized":
            initialized = True
            continue
        _write_json_line(
            {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"server": "qlip-realistic", "phase": "pre_response"},
            }
        )
        if not initialized:
            _write_json_line(
                {
                    "jsonrpc": "2.0",
                    "id": _response_id(req_id),
                    "error": {"code": -32602, "message": "Invalid request parameters", "data": ""},
                }
            )
            continue
        if method == "tools/list":
            result = {"tools": [{"name": name} for name in TOOLS]}
            _write_json_line({"jsonrpc": "2.0", "id": _response_id(req_id), "result": result})
            continue
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments")
            if not isinstance(name, str):
                _write_json_line(
                    {"jsonrpc": "2.0", "id": _response_id(req_id), "error": {"code": -32602, "message": "missing name"}}
                )
                continue
            result = _handle_tool_call(name, arguments)
            _write_json_line({"jsonrpc": "2.0", "id": _response_id(req_id), "result": result})
            continue
        _write_json_line(
            {"jsonrpc": "2.0", "id": _response_id(req_id), "error": {"code": -32601, "message": "Method not found"}}
        )


if __name__ == "__main__":
    main()
