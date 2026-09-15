from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic import AgenticRuntime, run_placeholder_agentic_cycle
from sok_llm_orchestrator.agentic.schemas import RUN_MANAGER_LOG_SCHEMA_VERSION
from sok_llm_orchestrator.agentic.tools import TOOL_VALIDATION_SCHEMA_VERSION
import sok_llm_orchestrator.agentic.runtime as runtime_module


class _UnknownToolRunManager:
    name = "run_manager"
    role = "Produces an intentionally invalid tool proposal for testing."

    def run(self, input_payload):  # type: ignore[no-untyped-def]
        return {
            "schema_version": RUN_MANAGER_LOG_SCHEMA_VERSION,
            "run_id": "run-invalid",
            "tool_calls_attempted": [
                {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "step": "test invalid tool",
                    "tool_name": "unknown.tool",
                    "arguments": {},
                    "expected_result": "none",
                    "why": "exercise validation failure path",
                    "condition": None,
                }
            ],
            "failures_handled": [],
            "manager_notes": "invalid tool test",
            "artifacts_created": [],
        }


class _NoProposalRunManager:
    name = "run_manager"
    role = "Produces no tool proposals for testing."

    def run(self, input_payload):  # type: ignore[no-untyped-def]
        return {
            "schema_version": RUN_MANAGER_LOG_SCHEMA_VERSION,
            "run_id": "run-no-proposals",
            "tool_calls_attempted": [],
            "failures_handled": [],
            "manager_notes": "no proposals test",
            "artifacts_created": [],
        }


class _MultipleInvalidToolRunManager:
    name = "run_manager"
    role = "Produces multiple invalid tool proposals for testing."

    def run(self, input_payload):  # type: ignore[no-untyped-def]
        return {
            "schema_version": RUN_MANAGER_LOG_SCHEMA_VERSION,
            "run_id": "run-multi-invalid",
            "tool_calls_attempted": [
                {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "step": "test invalid tool one",
                    "tool_name": "unknown.tool",
                    "arguments": {},
                    "expected_result": "none",
                    "why": "exercise multi-invalid path",
                    "condition": None,
                },
                {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "step": "test invalid tool two",
                    "tool_name": "another.unknown",
                    "arguments": {},
                    "expected_result": "none",
                    "why": "exercise multi-invalid path",
                    "condition": None,
                },
            ],
            "failures_handled": [],
            "manager_notes": "multiple invalid tools test",
            "artifacts_created": [],
        }


class _TwoProposalRunManager:
    name = "run_manager"
    role = "Produces two proposals for warning fan-out testing."

    def run(self, input_payload):  # type: ignore[no-untyped-def]
        return {
            "schema_version": RUN_MANAGER_LOG_SCHEMA_VERSION,
            "run_id": "run-two-proposals",
            "tool_calls_attempted": [
                {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "step": "test warning tool one",
                    "tool_name": "crystal.csp_pack",
                    "arguments": {"case_id": "run-two-proposals"},
                    "expected_result": "none",
                    "why": "exercise multi-warning path",
                    "condition": None,
                },
                {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "step": "test warning tool two",
                    "tool_name": "spp.run_pipeline",
                    "arguments": {"pack_path": "placeholder-pack.json"},
                    "expected_result": "none",
                    "why": "exercise multi-warning path",
                    "condition": None,
                },
            ],
            "failures_handled": [],
            "manager_notes": "multiple warning tools test",
            "artifacts_created": [],
        }


class _WarningOnlyRegistry:
    def validate_tool_call_proposal(self, proposal):  # type: ignore[no-untyped-def]
        return {
            "schema_version": TOOL_VALIDATION_SCHEMA_VERSION,
            "valid": True,
            "tool_name": str(proposal.get("tool_name", "")),
            "errors": [],
            "warnings": ["Review recommended before future execution."],
        }


def test_runtime_includes_tool_validation_results_with_valid_defaults() -> None:
    payload = {
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
        "run_id": "run_001",
    }
    result = run_placeholder_agentic_cycle(payload)

    assert isinstance(result["tool_validation_results"], list)
    assert result["tool_validation_results"]
    assert result["tool_validation_results"][0]["schema_version"] == TOOL_VALIDATION_SCHEMA_VERSION
    assert all(item["valid"] is True for item in result["tool_validation_results"])
    assert result["tool_validation_summary"] == {
        "proposal_count": 1,
        "valid_count": 1,
        "invalid_count": 0,
        "warning_count": 0,
        "valid_tool_names": ["crystal.csp_pack"],
        "invalid_tool_names": [],
    }
    assert result["proposal_readiness"] == {
        "schema_version": runtime_module.PROPOSAL_READINESS_SCHEMA_VERSION,
        "status": "all_valid",
        "reason": "All validated tool proposals are ready for a future execution layer.",
        "can_execute_later": True,
    }
    assert result["run_manager_output"]["tool_calls_attempted"][0]["tool_name"] == "crystal.csp_pack"
    assert result["orchestrator_output"]["decision"] == "continue"
    assert result["orchestrator_output"]["next_run_goal"] == "retrieve candidates"
    assert "allowed by current tool validation" in result["orchestrator_output"]["reason"]
    assert "proposals=1" in result["orchestrator_output"]["reason"]
    assert "valid=1" in result["orchestrator_output"]["reason"]
    assert "invalid=0" in result["orchestrator_output"]["reason"]
    assert "warnings=0" in result["orchestrator_output"]["reason"]
    assert "tool_validation_summary" in result["orchestrator_output"]["evidence_used"]


def test_runtime_unknown_tool_proposal_fails_truthfully_without_execution() -> None:
    runtime = AgenticRuntime(run_manager=_UnknownToolRunManager())
    result = runtime.run_cycle(
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "run_id": "run_002",
        }
    )

    assert result["tool_validation_results"][0]["schema_version"] == TOOL_VALIDATION_SCHEMA_VERSION
    assert result["tool_validation_results"][0]["valid"] is False
    assert result["tool_validation_results"][0]["tool_name"] == "unknown.tool"
    assert result["tool_validation_summary"] == {
        "proposal_count": 1,
        "valid_count": 0,
        "invalid_count": 1,
        "warning_count": 0,
        "valid_tool_names": [],
        "invalid_tool_names": ["unknown.tool"],
    }
    assert result["proposal_readiness"] == {
        "schema_version": runtime_module.PROPOSAL_READINESS_SCHEMA_VERSION,
        "status": "has_invalid",
        "reason": "One or more validated tool proposals are invalid.",
        "can_execute_later": False,
    }
    assert result["run_manager_output"]["tool_calls_attempted"][0]["tool_name"] == "unknown.tool"
    assert result["orchestrator_output"]["decision"] != "continue"
    assert result["orchestrator_output"]["next_run_goal"] == (
        "repair invalid unknown.tool proposal before execution"
    )
    assert "First error for unknown.tool" in result["orchestrator_output"]["reason"]
    assert "Unknown tool" in result["orchestrator_output"]["reason"]
    assert "unknown.tool" in result["orchestrator_output"]["reason"]
    assert "block future execution" in result["orchestrator_output"]["reason"]
    assert "invalid=1" in result["orchestrator_output"]["reason"]


def test_runtime_no_proposals_blocks_orchestrator_continue_decision() -> None:
    runtime = AgenticRuntime(run_manager=_NoProposalRunManager())
    result = runtime.run_cycle(
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "run_id": "run_004",
        }
    )

    assert result["tool_validation_results"] == []
    assert result["tool_validation_summary"] == {
        "proposal_count": 0,
        "valid_count": 0,
        "invalid_count": 0,
        "warning_count": 0,
        "valid_tool_names": [],
        "invalid_tool_names": [],
    }
    assert result["proposal_readiness"] == {
        "schema_version": runtime_module.PROPOSAL_READINESS_SCHEMA_VERSION,
        "status": "no_proposals",
        "reason": "No tool proposals were validated.",
        "can_execute_later": False,
    }
    assert result["orchestrator_output"]["decision"] != "continue"
    assert "generate executable tool proposals" in result["orchestrator_output"]["next_run_goal"]
    assert "no executable proposals" in result["orchestrator_output"]["reason"]
    assert "proposals=0" in result["orchestrator_output"]["reason"]


def test_runtime_warning_only_validation_keeps_continue_with_warning_reason() -> None:
    runtime = AgenticRuntime(tool_registry=_WarningOnlyRegistry())
    result = runtime.run_cycle(
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "run_id": "run_005",
        }
    )

    assert result["tool_validation_results"][0]["valid"] is True
    assert result["tool_validation_results"][0]["warnings"] == [
        "Review recommended before future execution."
    ]
    assert result["tool_validation_summary"] == {
        "proposal_count": 1,
        "valid_count": 1,
        "invalid_count": 0,
        "warning_count": 1,
        "valid_tool_names": ["crystal.csp_pack"],
        "invalid_tool_names": [],
    }
    assert result["proposal_readiness"] == {
        "schema_version": runtime_module.PROPOSAL_READINESS_SCHEMA_VERSION,
        "status": "has_warnings",
        "reason": "All validated tool proposals are usable, but warnings remain.",
        "can_execute_later": True,
    }
    assert result["orchestrator_output"]["decision"] == "continue"
    assert result["orchestrator_output"]["next_run_goal"] == (
        "review warnings on crystal.csp_pack proposal before execution"
    )
    assert (
        "First warning for crystal.csp_pack: Review recommended before future execution."
        in result["orchestrator_output"]["reason"]
    )
    assert "allowed with warnings" in result["orchestrator_output"]["reason"]
    assert "warnings=1" in result["orchestrator_output"]["reason"]


def test_runtime_multiple_invalid_tools_fall_back_to_generic_repair_goal() -> None:
    runtime = AgenticRuntime(run_manager=_MultipleInvalidToolRunManager())
    result = runtime.run_cycle(
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "run_id": "run_006",
        }
    )

    assert result["proposal_readiness"]["status"] == "has_invalid"
    assert result["tool_validation_summary"]["invalid_tool_names"] == [
        "unknown.tool",
        "another.unknown",
    ]
    assert result["orchestrator_output"]["next_run_goal"] == (
        "repair invalid tool proposals before execution"
    )
    assert "First error for" not in result["orchestrator_output"]["reason"]
    assert "invalid=2" in result["orchestrator_output"]["reason"]


def test_runtime_multiple_warning_tools_fall_back_to_generic_review_goal() -> None:
    runtime = AgenticRuntime(
        run_manager=_TwoProposalRunManager(),
        tool_registry=_WarningOnlyRegistry(),
    )
    result = runtime.run_cycle(
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "run_id": "run_007",
        }
    )

    assert result["proposal_readiness"]["status"] == "has_warnings"
    assert result["tool_validation_summary"]["warning_count"] == 2
    assert result["orchestrator_output"]["next_run_goal"] == (
        "review warning-bearing tool proposals before execution"
    )
    assert "First warning for" not in result["orchestrator_output"]["reason"]
    assert "warnings=2" in result["orchestrator_output"]["reason"]


def test_summarize_tool_validation_results_counts_valid_invalid_and_warnings() -> None:
    summary = runtime_module.summarize_tool_validation_results(
        [
            {
                "schema_version": TOOL_VALIDATION_SCHEMA_VERSION,
                "valid": True,
                "tool_name": "crystal.csp_pack",
                "errors": [],
                "warnings": [],
            },
            {
                "schema_version": TOOL_VALIDATION_SCHEMA_VERSION,
                "valid": False,
                "tool_name": "unknown.tool",
                "errors": ["Missing required argument: case_id"],
                "warnings": ["Unexpected argument: foo"],
            },
        ]
    )

    assert summary == {
        "proposal_count": 2,
        "valid_count": 1,
        "invalid_count": 1,
        "warning_count": 1,
        "valid_tool_names": ["crystal.csp_pack"],
        "invalid_tool_names": ["unknown.tool"],
    }


def test_classify_proposal_readiness_handles_all_required_states() -> None:
    assert runtime_module.classify_proposal_readiness(
        {
            "proposal_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "warning_count": 0,
            "valid_tool_names": [],
            "invalid_tool_names": [],
        }
    ) == {
        "schema_version": runtime_module.PROPOSAL_READINESS_SCHEMA_VERSION,
        "status": "no_proposals",
        "reason": "No tool proposals were validated.",
        "can_execute_later": False,
    }
    assert runtime_module.classify_proposal_readiness(
        {
            "proposal_count": 2,
            "valid_count": 2,
            "invalid_count": 0,
            "warning_count": 0,
            "valid_tool_names": ["a", "b"],
            "invalid_tool_names": [],
        }
    )["status"] == "all_valid"
    assert runtime_module.classify_proposal_readiness(
        {
            "proposal_count": 2,
            "valid_count": 1,
            "invalid_count": 1,
            "warning_count": 0,
            "valid_tool_names": ["a"],
            "invalid_tool_names": ["b"],
        }
    )["status"] == "has_invalid"
    assert runtime_module.classify_proposal_readiness(
        {
            "proposal_count": 1,
            "valid_count": 1,
            "invalid_count": 0,
            "warning_count": 2,
            "valid_tool_names": ["a"],
            "invalid_tool_names": [],
        }
    )["status"] == "has_warnings"
    assert runtime_module.classify_proposal_readiness(
        {
            "proposal_count": 3,
            "valid_count": 1,
            "invalid_count": 0,
            "warning_count": 0,
            "valid_tool_names": ["a"],
            "invalid_tool_names": [],
        }
    ) == {
        "schema_version": runtime_module.PROPOSAL_READINESS_SCHEMA_VERSION,
        "status": "has_invalid",
        "reason": "Proposal validation state is inconsistent, so execution is blocked.",
        "can_execute_later": False,
    }


def test_runtime_tool_validation_output_is_json_serializable_and_input_is_not_mutated() -> None:
    payload = {
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
        "run_id": "run_003",
        "nested": {"alpha": 1},
    }
    payload_before = deepcopy(payload)

    result = run_placeholder_agentic_cycle(payload)

    json.loads(json.dumps(result))
    assert payload == payload_before


def test_runtime_tool_validation_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = run_placeholder_agentic_cycle({"overall_goal": "TiO2", "run_goal": "retrieve"})
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules


def test_runtime_tool_validation_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(runtime_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module.split(".")[0])

    assert "sqlite3" not in imported_modules
    assert "sqlalchemy" not in imported_modules
    assert "pipeline" not in imported_modules
