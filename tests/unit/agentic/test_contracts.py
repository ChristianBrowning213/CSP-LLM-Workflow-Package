from __future__ import annotations

import pytest

from llm_csp.agentic.contracts import (
    ApprovalPolicy,
    InspectRunInput,
    RunCSPInput,
    TOOL_CONTRACTS,
    UnknownToolError,
    WriteScopePolicy,
    get_tool_contract,
    validate_tool_input,
    validate_tool_output,
)
from llm_csp.agentic.models import SupportedToolName


DESIGN_SPACE = {
    "template": {"name": "cubic", "lattice": {"a": 3.9}},
    "sites": {"mode": "uniform_grid"},
}


def test_registry_contains_exactly_four_tools() -> None:
    assert set(TOOL_CONTRACTS) == set(SupportedToolName)
    assert len(TOOL_CONTRACTS) == 4
    with pytest.raises(UnknownToolError):
        get_tool_contract("run_shell")


def test_search_input_accepts_valid_request_and_rejects_unknown_field() -> None:
    result = validate_tool_input("search_crystal_db", {"query": "perovskite", "k": 5})
    assert result.k == 5
    with pytest.raises(TypeError, match="unexpected"):
        validate_tool_input("search_crystal_db", {"query": "x", "shell": "whoami"})
    with pytest.raises(ValueError, match="1 through 50"):
        validate_tool_input("search_crystal_db", {"query": "x", "k": 51})


def test_run_csp_reuses_existing_workflow_request() -> None:
    payload = {
        "request": {"query": "cubic strontium titanate", "formula": "SrTiO3", "design_space": DESIGN_SPACE},
        "config_ref": "workflow_config_1", "parent_decision_id": "decision_1",
    }
    value = validate_tool_input("run_csp", payload)
    assert isinstance(value, RunCSPInput)
    assert value.request.formula == "SrTiO3"


def test_validate_candidate_requires_registered_candidate_reference() -> None:
    with pytest.raises(TypeError, match="missing"):
        validate_tool_input("validate_candidate", {})
    with pytest.raises(ValueError, match="candidate or CIF"):
        validate_tool_input("validate_candidate", {
            "candidate_ref": {"artifact_id": "a", "kind": "log", "path": "log.json", "producing_run_id": "run"}
        })


def test_inspect_run_is_read_only_and_sections_are_closed() -> None:
    contract = get_tool_contract("inspect_run")
    assert contract.read_only
    assert contract.approval_policy is ApprovalPolicy.READ_ONLY
    assert contract.side_effects == ()
    assert contract.allowed_write_scope is WriteScopePolicy.NONE
    assert isinstance(validate_tool_input("inspect_run", {"workflow_run_id": "run_1"}), InspectRunInput)
    with pytest.raises(ValueError, match="unsupported inspection"):
        validate_tool_input("inspect_run", {"workflow_run_id": "run_1", "include": ["source"]})


@pytest.mark.parametrize("status", [
    "missing_db", "embedding_incompatible", "SPP incomplete", "OPTIMAL", "FEASIBLE",
    "FEASIBLE_TIME_LIMIT", "INFEASIBLE", "gurobi_unavailable", "backend_unavailable",
])
def test_tool_output_preserves_subsystem_status(status) -> None:
    result = validate_tool_output("run_csp", {
        "tool_call_id": "call_1", "tool_name": "run_csp", "status": status, "data": {"subsystem_status": status}
    })
    assert result.status == status
    assert result.data["subsystem_status"] == status


def test_tool_output_must_match_contract_and_is_strict() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_tool_output("run_csp", {"tool_call_id": "call", "tool_name": "inspect_run", "status": "OPTIMAL"})
    with pytest.raises(TypeError, match="unexpected"):
        validate_tool_output("run_csp", {"tool_call_id": "call", "tool_name": "run_csp", "status": "OPTIMAL", "prose": "done"})
