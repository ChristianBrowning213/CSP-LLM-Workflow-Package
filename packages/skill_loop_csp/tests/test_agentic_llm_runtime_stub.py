from __future__ import annotations

import ast
import inspect
import json
import sys

from sok_llm_orchestrator.agentic.archive import write_agentic_llm_trace
from sok_llm_orchestrator.agentic.llm_runtime import AgentLLMRuntime
from sok_llm_orchestrator.agentic.schemas import RUN_PLAN_SCHEMA_VERSION
import sok_llm_orchestrator.agentic.llm_runtime as llm_runtime_module


class _FakeLLMClient:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls: list[list[dict[str, object]]] = []

    def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(list(messages))
        if not self._outputs:
            raise AssertionError("No more fake LLM outputs configured")
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": self._outputs.pop(0),
                    }
                }
            ]
        }


def _valid_run_plan_output() -> dict[str, object]:
    return {
        "schema_version": RUN_PLAN_SCHEMA_VERSION,
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
        "detailed_description": "Plan a retrieval-focused run.",
        "hoping_to_find": "Promising TiO2 candidate structures.",
        "plan_as_text": "tool_hint: crystal.csp_pack",
        "what_we_tried_previously_that_is_related": "No prior failed strategies.",
        "success_criteria": ["Return a valid strategy-only plan."],
        "stop_conditions_for_this_run": ["Missing inputs."],
    }


def test_llm_runtime_accepts_valid_json_response(workdir) -> None:  # type: ignore[no-untyped-def]
    client = _FakeLLMClient(
        [
            json.dumps(_valid_run_plan_output())
        ]
    )
    runtime = AgentLLMRuntime(client=client)

    before = list(workdir.iterdir())
    result = runtime.run_agent(
        "planner",
        {"overall_goal": "TiO2", "run_goal": "retrieve candidates", "stage": "wide_exploration"},
        "run_plan",
    )

    assert result["parsed_output"] is not None
    assert result["parsed_output"]["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert result["agent_name"] == "planner"
    assert result["runtime_context"]["model"] == ""
    assert "api_key" not in result["runtime_context"]
    assert "Return exactly one JSON object." in json.dumps(result["user_payload"])
    assert isinstance(result["system_prompt"], str) and result["system_prompt"].strip()
    assert result["raw_output"]
    assert len(result["attempts"]) == 1
    assert result["validation_errors"] == []
    assert before == list(workdir.iterdir())


def test_llm_runtime_retries_malformed_json_then_succeeds() -> None:
    client = _FakeLLMClient(
        [
            "{not valid json",
            json.dumps(_valid_run_plan_output()),
        ]
    )
    runtime = AgentLLMRuntime(client=client)

    result = runtime.run_agent(
        "planner",
        {"overall_goal": "TiO2", "run_goal": "retrieve candidates", "stage": "wide_exploration"},
        "run_plan",
    )

    assert result["parsed_output"] is not None
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["validation_errors"]
    assert "Malformed JSON object" in result["validation_errors"][0]


def test_llm_runtime_retries_missing_top_level_fields_then_succeeds() -> None:
    client = _FakeLLMClient(
        [
            json.dumps(
                {
                    "schema_version": RUN_PLAN_SCHEMA_VERSION,
                    "metadata": {
                        "overall_goal": "TiO2",
                        "run_goal": "retrieve candidates",
                        "stage": "wide_exploration",
                    },
                    "plan_as_text": "tool_hint: crystal.csp_pack",
                }
            ),
            json.dumps(_valid_run_plan_output()),
        ]
    )
    runtime = AgentLLMRuntime(client=client)

    result = runtime.run_agent(
        "planner",
        {"overall_goal": "TiO2", "run_goal": "retrieve candidates", "stage": "wide_exploration"},
        "run_plan",
    )

    assert result["parsed_output"] is not None
    assert len(result["attempts"]) == 2
    assert "Missing required top-level fields" in result["validation_errors"][0]


def test_llm_runtime_wrong_schema_version_fails_truthfully() -> None:
    client = _FakeLLMClient(
        [
            json.dumps(
                {
                    "schema_version": "agentic_csp.run_manager_log.v1",
                    "overall_goal": "TiO2",
                    "run_goal": "retrieve candidates",
                    "stage": "wide_exploration",
                    "detailed_description": "Plan a retrieval-focused run.",
                    "hoping_to_find": "Promising TiO2 candidate structures.",
                    "plan_as_text": "tool_hint: crystal.csp_pack",
                    "what_we_tried_previously_that_is_related": "No prior failed strategies.",
                    "success_criteria": ["Return a valid strategy-only plan."],
                    "stop_conditions_for_this_run": ["Missing inputs."],
                }
            )
        ]
    )
    runtime = AgentLLMRuntime(client=client, max_attempts=1)

    result = runtime.run_agent(
        "planner",
        {"overall_goal": "TiO2", "run_goal": "retrieve candidates", "stage": "wide_exploration"},
        "run_plan",
    )

    assert result["parsed_output"] is None
    assert len(result["attempts"]) == 1
    assert "schema_version must be" in result["validation_errors"][0]
    assert result["raw_output"]


def test_llm_runtime_preserves_attempt_records_and_is_json_serializable() -> None:
    client = _FakeLLMClient(
        [
            "{broken",
            json.dumps(_valid_run_plan_output()),
        ]
    )
    runtime = AgentLLMRuntime(client=client)

    result = runtime.run_agent(
        "planner",
        {"overall_goal": "TiO2", "run_goal": "retrieve candidates", "stage": "wide_exploration"},
        "run_plan",
    )

    assert result["attempts"][0]["raw_output"] == "{broken"
    assert result["attempts"][1]["raw_output"]
    assert json.loads(json.dumps(result))["attempts"][0]["attempt_number"] == 1


def test_llm_runtime_trace_can_be_written_as_archive_ready_json(workdir) -> None:  # type: ignore[no-untyped-def]
    client = _FakeLLMClient(
        [
            json.dumps(_valid_run_plan_output())
        ]
    )
    runtime = AgentLLMRuntime(client=client)

    result = runtime.run_agent(
        "planner",
        {"overall_goal": "TiO2", "run_goal": "retrieve candidates", "stage": "wide_exploration"},
        "run_plan",
    )
    out = write_agentic_llm_trace(result, workdir, "planner")
    round_tripped = json.loads(
        (workdir / "agentic_llm_trace_planner.json").read_text(encoding="utf-8")
    )

    assert round_tripped == result
    assert out["agent_name"] == "planner"


def test_llm_runtime_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(llm_runtime_module)
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


def test_llm_runtime_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    client = _FakeLLMClient(
        [
            json.dumps(_valid_run_plan_output())
        ]
    )
    runtime = AgentLLMRuntime(client=client)
    _ = runtime.run_agent(
        "planner",
        {"overall_goal": "TiO2", "run_goal": "retrieve candidates", "stage": "wide_exploration"},
        "run_plan",
    )
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
