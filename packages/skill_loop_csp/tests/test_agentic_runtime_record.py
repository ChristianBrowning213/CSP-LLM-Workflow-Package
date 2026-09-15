from __future__ import annotations

import ast
import builtins
import inspect
import json
from copy import deepcopy

from sok_llm_orchestrator.agentic import (
    AgenticRunRecord,
    build_run_record,
    run_placeholder_agentic_cycle,
    run_placeholder_agentic_cycle_record,
)
from sok_llm_orchestrator.agentic.runtime import (
    RUNTIME_CYCLE_SCHEMA_VERSION,
)
from sok_llm_orchestrator.agentic.schemas import RUN_RECORD_SCHEMA_VERSION, to_json_dict
import sok_llm_orchestrator.agentic.runtime as runtime_module


def test_agentic_run_record_constructs_and_serializes() -> None:
    record = AgenticRunRecord(
        run_id="run_001",
        overall_goal="Improve benchmark performance.",
        run_goal="Prepare archive-ready placeholder outputs.",
        stage="wide_exploration",
        runtime_schema_version=RUNTIME_CYCLE_SCHEMA_VERSION,
        agent_order=["planner", "run_manager", "evaluator", "orchestrator"],
        planner_output={"schema_version": "agentic_csp.run_plan.v1"},
        run_manager_output={"schema_version": "agentic_csp.run_manager_log.v1"},
        evaluator_output={"schema_version": "agentic_csp.run_evaluation.v1"},
        orchestrator_output={"schema_version": "agentic_csp.orchestrator_decision.v1"},
        tool_validation_results=[
            {
                "schema_version": "agentic_csp.tool_validation.v1",
                "valid": True,
                "tool_name": "crystal.csp_pack",
                "errors": [],
                "warnings": [],
            }
        ],
        tool_validation_summary={
            "proposal_count": 1,
            "valid_count": 1,
            "invalid_count": 0,
            "warning_count": 0,
            "valid_tool_names": ["crystal.csp_pack"],
            "invalid_tool_names": [],
        },
        proposal_readiness={
            "schema_version": "agentic_csp.proposal_readiness.v1",
            "status": "all_valid",
            "reason": "All validated tool proposals are ready for a future execution layer.",
            "can_execute_later": True,
        },
        artifact_refs=[{"path": "artifacts/run_001/summary.json", "kind": "json"}],
        warnings=[],
    )
    data = to_json_dict(record)
    assert data["schema_version"] == RUN_RECORD_SCHEMA_VERSION
    assert json.loads(json.dumps(data))["runtime_schema_version"] == RUNTIME_CYCLE_SCHEMA_VERSION
    assert data["tool_validation_results"][0]["valid"] is True
    assert data["tool_validation_summary"]["proposal_count"] == 1
    assert data["proposal_readiness"]["status"] == "all_valid"


def test_build_run_record_preserves_outputs_and_does_not_mutate_inputs() -> None:
    input_payload = {
        "overall_goal": "Improve band gap search quality.",
        "run_goal": "Prepare placeholder cycle outputs.",
        "stage": "wide_exploration",
        "run_id": "run_002",
        "artifact_refs": [
            {"path": "artifacts/run_002/input.json", "kind": "json"},
        ],
    }
    runtime_cycle = run_placeholder_agentic_cycle(input_payload)
    input_before = deepcopy(input_payload)
    cycle_before = deepcopy(runtime_cycle)

    record = build_run_record(input_payload, runtime_cycle)

    assert record["schema_version"] == RUN_RECORD_SCHEMA_VERSION
    assert record["runtime_schema_version"] == RUNTIME_CYCLE_SCHEMA_VERSION
    assert record["run_id"] == "run_002"
    assert record["overall_goal"] == input_payload["overall_goal"]
    assert record["run_goal"] == input_payload["run_goal"]
    assert record["stage"] == input_payload["stage"]
    assert record["planner_output"] == runtime_cycle["planner_output"]
    assert record["run_manager_output"] == runtime_cycle["run_manager_output"]
    assert record["evaluator_output"] == runtime_cycle["evaluator_output"]
    assert record["orchestrator_output"] == runtime_cycle["orchestrator_output"]
    assert record["tool_validation_results"] == runtime_cycle["tool_validation_results"]
    assert record["tool_validation_summary"] == runtime_cycle["tool_validation_summary"]
    assert record["proposal_readiness"] == runtime_cycle["proposal_readiness"]
    assert record["tool_validation_results"][0]["valid"] is True
    assert record["artifact_refs"] == input_payload["artifact_refs"]
    assert record["warnings"] == []
    json.loads(json.dumps(record))
    assert input_payload == input_before
    assert runtime_cycle == cycle_before


def test_run_placeholder_agentic_cycle_record_is_json_serializable() -> None:
    record = run_placeholder_agentic_cycle_record(
        {
            "overall_goal": "test",
            "run_goal": "test",
            "stage": "wide_exploration",
            "run_id": "run_003",
        }
    )
    assert record["schema_version"] == RUN_RECORD_SCHEMA_VERSION
    assert record["runtime_schema_version"] == RUNTIME_CYCLE_SCHEMA_VERSION
    assert record["tool_validation_results"]
    assert record["tool_validation_results"][0]["valid"] is True
    assert record["tool_validation_summary"]["proposal_count"] == 1
    assert record["proposal_readiness"]["status"] == "all_valid"
    json.loads(json.dumps(record))


def test_build_run_record_defaults_missing_tool_validation_results_to_empty_list() -> None:
    input_payload = {
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
        "run_id": "run_003b",
    }
    runtime_cycle = run_placeholder_agentic_cycle(input_payload)
    runtime_cycle_without_validation = deepcopy(runtime_cycle)
    runtime_cycle_without_validation.pop("tool_validation_results", None)
    runtime_cycle_without_validation.pop("tool_validation_summary", None)

    record = build_run_record(input_payload, runtime_cycle_without_validation)

    assert record["tool_validation_results"] == []
    assert record["tool_validation_summary"] == {
        "proposal_count": 0,
        "valid_count": 0,
        "invalid_count": 0,
        "warning_count": 0,
        "valid_tool_names": [],
        "invalid_tool_names": [],
    }
    assert record["proposal_readiness"] == {
        "schema_version": "agentic_csp.proposal_readiness.v1",
        "status": "no_proposals",
        "reason": "No tool proposals were validated.",
        "can_execute_later": False,
    }
    assert runtime_cycle_without_validation == {
        key: value
        for key, value in runtime_cycle.items()
        if key not in {"tool_validation_results", "tool_validation_summary"}
    }


def test_build_run_record_computes_summary_if_missing_but_validation_results_exist() -> None:
    input_payload = {
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
        "run_id": "run_003c",
    }
    runtime_cycle = run_placeholder_agentic_cycle(input_payload)
    runtime_cycle_without_summary = deepcopy(runtime_cycle)
    runtime_cycle_without_summary.pop("tool_validation_summary", None)

    record = build_run_record(input_payload, runtime_cycle_without_summary)

    assert record["tool_validation_results"] == runtime_cycle["tool_validation_results"]
    assert record["tool_validation_summary"] == {
        "proposal_count": 1,
        "valid_count": 1,
        "invalid_count": 0,
        "warning_count": 0,
        "valid_tool_names": ["crystal.csp_pack"],
        "invalid_tool_names": [],
    }
    assert record["proposal_readiness"] == {
        "schema_version": "agentic_csp.proposal_readiness.v1",
        "status": "all_valid",
        "reason": "All validated tool proposals are ready for a future execution layer.",
        "can_execute_later": True,
    }


def test_runtime_record_keeps_artifact_refs_plain_and_needs_no_filesystem_writes(monkeypatch) -> None:
    def fail_open(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Filesystem access is not expected in the run-record builder.")

    monkeypatch.setattr(builtins, "open", fail_open)

    record = run_placeholder_agentic_cycle_record(
        {
            "overall_goal": "Archive safety test",
            "run_goal": "Stay fully in memory",
            "stage": "wide_exploration",
            "run_id": "run_004",
            "artifact_refs": [{"path": "artifacts/run_004/input.json", "kind": "json"}],
            "warnings": ["input warning"],
        }
    )

    assert isinstance(record["artifact_refs"], list)
    assert isinstance(record["artifact_refs"][0], dict)
    assert record["warnings"] == ["input warning"]


def test_runtime_record_has_no_sqlite_or_pipeline_dependency() -> None:
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
