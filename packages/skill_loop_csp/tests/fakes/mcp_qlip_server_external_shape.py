from __future__ import annotations

import json
import os
from typing import Any

from mcp_fake_lib import serve

TOOLS = [
    "qlip.shapes",
    "qlip.list_constraints",
    "qlip.list_guidance",
    "qlip.validate_request",
    "qlip.solve",
]


def _wrap(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(envelope, indent=2, sort_keys=True)}],
        "structuredContent": envelope,
        "isError": bool(not envelope.get("ok", False)),
    }


def _success(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    return _wrap(
        {
            "ok": True,
            "tool": tool,
            "trace_id": f"{tool}-external-shape",
            "result": result,
            "errors": [],
            "warnings": [],
            "meta": {"payload_sha256": "external-shape", "category": "RUNTIME", "retryable": False},
        }
    )


def _error(tool: str, code: str, message: str) -> dict[str, Any]:
    error_item = {"code": code, "message": message, "meta": {"category": "RUNTIME", "retryable": False}}
    return _wrap(
        {
            "ok": False,
            "tool": tool,
            "trace_id": f"{tool}-external-shape",
            "result": None,
            "errors": [error_item],
            "primary_error": error_item,
            "warnings": [],
            "meta": {"payload_sha256": "external-shape", "category": "RUNTIME", "retryable": False},
        }
    )


def _extract_formula(arguments: dict[str, Any]) -> str:
    request = arguments.get("request")
    if not isinstance(request, dict):
        return "UNKNOWN"
    problem = request.get("problem")
    if not isinstance(problem, dict):
        return "UNKNOWN"
    chemistry = problem.get("chemistry")
    if not isinstance(chemistry, dict):
        return "UNKNOWN"
    formula = chemistry.get("formula")
    return str(formula) if isinstance(formula, str) and formula.strip() else "UNKNOWN"


def on_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    mode = os.environ.get("FAKE_QLIP_EXT_SHAPE_MODE", "valid").strip().lower()
    if name == "qlip.shapes":
        return _success(
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
        return _success(name, {"items": []})
    if name == "qlip.list_guidance":
        return _success(name, {"items": []})
    if name == "qlip.validate_request":
        request = args.get("request")
        if not isinstance(request, dict):
            return _error(name, "SCHEMA_VALIDATION_ERROR", "request must be object")
        if mode == "unexpected_contract":
            return {"content": [{"type": "text", "text": "unexpected"}]}
        return _success(name, {"valid": True, "errors": [], "warnings": [], "normalized_request": request})
    if name == "qlip.solve":
        request = args.get("request")
        if not isinstance(request, dict):
            return _error(name, "SCHEMA_VALIDATION_ERROR", "request must be object")
        if mode == "unexpected_contract":
            return {"content": [{"type": "text", "text": "unexpected"}]}
        formula = _extract_formula(args)
        if mode == "non_solution":
            return _success(
                name,
                {
                    "run_id": "external-shape-run",
                    "result": {
                        "status": "INFEASIBLE",
                        "summary": {"solver": "gurobi", "termination": "infeasible"},
                        "outputs": {"decoder_debug": None, "artifacts": []},
                        "errors": [{"code": "INFEASIBLE", "message": "no feasible solution"}],
                        "logs": [],
                    },
                },
            )
        outputs: dict[str, Any] = {"decoder_debug": None, "artifacts": []}
        if mode != "missing_artifact":
            outputs["cif"] = (
                "\n".join(
                    [
                        "data_solution",
                        f"_chemical_formula_sum '{formula}'",
                        "_cell_length_a 4.6000",
                        "_cell_length_b 4.6000",
                        "_cell_length_c 3.0000",
                    ]
                )
                + "\n"
            )
        return _success(
            name,
            {
                "run_id": "external-shape-run",
                "result": {
                    "status": "OPTIMAL",
                    "summary": {"solver": "gurobi", "termination": "optimal"},
                    "outputs": outputs,
                    "errors": [],
                    "logs": [],
                },
            },
        )
    return _error(name, "UNKNOWN_TOOL", name)


if __name__ == "__main__":
    serve(TOOLS, on_call)

