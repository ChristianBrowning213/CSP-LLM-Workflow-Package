"""Small reusable structured responses for deterministic planner tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DESIGN_SPACE = {
    "template": {"name": "cubic", "lattice": {"a": 3.9}},
    "sites": {"mode": "uniform_grid"},
}


def normal_csp_plan(*, formula: str = "SrTiO3") -> dict[str, Any]:
    """A normal run relies on workflow-internal retrieval and validation."""
    return {
        "status": "PLAN",
        "goal": f"Generate a candidate for {formula}",
        "steps": [{
            "step_ref": "run",
            "tool_name": "run_csp",
            "purpose": "Run the packaged retrieval-guided CSP workflow",
            "inputs": {
                "request": {
                    "query": formula, "formula": formula, "design_space": deepcopy(DESIGN_SPACE),
                    "constraints": [], "topology_family": None, "target_space_group": None,
                    "scaffold_id": None,
                },
                "config_ref": "workflow",
                "parent_decision_id": "planner_decision",
            },
            "dependencies": [],
        }],
        "hard_constraints": [],
        "soft_preferences": [],
        "success_criteria": [],
        "clarification": None,
    }


def retrieval_only_plan(*, formula: str = "SrTiO3") -> dict[str, Any]:
    return {
        "status": "PLAN",
        "goal": f"Find crystal evidence for {formula}",
        "steps": [{
            "step_ref": "search",
            "tool_name": "search_crystal_db",
            "purpose": "Retrieve attributable evidence before deciding whether to generate",
            "inputs": {"query": formula, "formula": formula, "k": 10},
            "dependencies": [],
        }],
        "hard_constraints": [], "soft_preferences": [], "success_criteria": [], "clarification": None,
    }


def user_input_required(field: str = "target_formula") -> dict[str, Any]:
    return {
        "status": "USER_INPUT_REQUIRED", "goal": "Clarify the request", "steps": [],
        "hard_constraints": [], "soft_preferences": [], "success_criteria": [],
        "clarification": {
            "question": "What target composition should be used?",
            "missing_field": field,
            "why_required": "The deterministic CSP request requires a target formula.",
        },
    }


def unknown_tool_plan() -> dict[str, Any]:
    value = normal_csp_plan()
    value["steps"][0]["tool_name"] = "run_dft"
    return value


def missing_hard_constraint_plan() -> dict[str, Any]:
    value = normal_csp_plan()
    value["hard_constraints"] = []
    return value


def malformed_response() -> str:
    return "this is not a structured planner response"


def malformed_then_valid() -> list[Any]:
    return [malformed_response(), normal_csp_plan()]


def permanently_malformed() -> list[Any]:
    return [malformed_response(), malformed_response(), malformed_response()]


def cyclic_plan() -> dict[str, Any]:
    value = retrieval_only_plan()
    value["steps"].append({
        "step_ref": "inspect", "tool_name": "inspect_run", "purpose": "inspect",
        "inputs": {"workflow_run_id": "future"}, "dependencies": ["search"],
    })
    value["steps"][0]["dependencies"] = ["inspect"]
    return value


__all__ = [
    "DESIGN_SPACE", "cyclic_plan", "malformed_response", "malformed_then_valid",
    "missing_hard_constraint_plan", "normal_csp_plan", "permanently_malformed",
    "retrieval_only_plan", "unknown_tool_plan", "user_input_required",
]
