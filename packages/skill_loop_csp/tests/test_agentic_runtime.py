from __future__ import annotations

import ast
import builtins
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic import run_placeholder_agentic_cycle
from sok_llm_orchestrator.agentic.runtime import RUNTIME_CYCLE_SCHEMA_VERSION
from sok_llm_orchestrator.agentic.schemas import (
    ORCHESTRATOR_DECISION_SCHEMA_VERSION,
    RUN_EVALUATION_SCHEMA_VERSION,
    RUN_MANAGER_LOG_SCHEMA_VERSION,
    RUN_PLAN_SCHEMA_VERSION,
)
import sok_llm_orchestrator.agentic.runtime as runtime_module


def test_runtime_returns_expected_cycle_shape() -> None:
    result = run_placeholder_agentic_cycle(
        {
            "overall_goal": "Improve band gap search quality.",
            "run_goal": "Prepare a deterministic placeholder cycle.",
            "stage": "wide_exploration",
            "run_id": "run_001",
        }
    )

    assert result["schema_version"] == RUNTIME_CYCLE_SCHEMA_VERSION
    assert result["run_id"] == "run_001"
    assert result["agent_order"] == ["planner", "run_manager", "evaluator", "orchestrator"]
    assert result["planner_output"]["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert result["run_manager_output"]["schema_version"] == RUN_MANAGER_LOG_SCHEMA_VERSION
    assert result["evaluator_output"]["schema_version"] == RUN_EVALUATION_SCHEMA_VERSION
    assert (
        result["orchestrator_output"]["schema_version"]
        == ORCHESTRATOR_DECISION_SCHEMA_VERSION
    )


def test_runtime_output_is_json_serializable_and_deterministic() -> None:
    payload = {
        "overall_goal": "Advance the benchmark objective.",
        "run_goal": "Prepare a deterministic cycle output.",
        "stage": "wide_exploration",
        "run_id": "run_det",
        "nested": {"alpha": 1},
    }
    payload_before = deepcopy(payload)

    first = run_placeholder_agentic_cycle(payload)
    second = run_placeholder_agentic_cycle(payload)

    assert first == second
    json.loads(json.dumps(first))
    assert payload == payload_before


def test_runtime_needs_no_filesystem_writes(monkeypatch) -> None:
    def fail_open(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Filesystem access is not expected in the placeholder runtime.")

    monkeypatch.setattr(builtins, "open", fail_open)

    result = run_placeholder_agentic_cycle(
        {
            "overall_goal": "Test no file access.",
            "run_goal": "Stay fully in memory.",
            "stage": "wide_exploration",
            "run_id": "run_mem",
        }
    )

    assert result["schema_version"] == RUNTIME_CYCLE_SCHEMA_VERSION


def test_runtime_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = run_placeholder_agentic_cycle({"overall_goal": "test", "run_goal": "test"})
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules


def test_runtime_has_no_sqlite_or_pipeline_dependency() -> None:
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
