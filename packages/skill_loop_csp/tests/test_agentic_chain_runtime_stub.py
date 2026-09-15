from __future__ import annotations

import ast
from contextlib import contextmanager
import inspect
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from time import sleep
from uuid import uuid4

from sok_llm_orchestrator.agentic.chain_runtime import (
    FULL_LIVE_AGENT_CHAIN_ROUTE_MODE,
    PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION,
    run_live_proposal_review_chain,
)
from sok_llm_orchestrator.agentic.chain_fixtures import (
    load_chain_fixture,
    replay_c_layer_from_fixture,
    write_chain_fixture,
)
from sok_llm_orchestrator.agentic.schemas import (
    ORCHESTRATOR_DECISION_SCHEMA_VERSION,
    RUN_EVALUATION_SCHEMA_VERSION,
    RUN_MANAGER_LOG_SCHEMA_VERSION,
    RUN_PLAN_SCHEMA_VERSION,
)
import sok_llm_orchestrator.agentic.chain_runtime as chain_runtime_module


@contextmanager
def _repo_local_tempdir() -> Path:
    parent = Path.cwd() / "test_workdir" / "agentic_chain_runtime_tmp"
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"case_{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def _planner_result() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.planner_compile_run.v1",
        "run_plan": {
            "schema_version": RUN_PLAN_SCHEMA_VERSION,
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "detailed_description": "Plan retrieval.",
            "hoping_to_find": "Promising candidates.",
            "plan_as_text": "tool_hint: crystal.csp_pack",
            "what_we_tried_previously_that_is_related": "No prior failures.",
            "success_criteria": ["Prepare valid proposals."],
            "stop_conditions_for_this_run": ["Missing inputs."],
        },
        "compile_result": {
            "schema_version": "agentic_csp.plan_compile.v1",
            "proposals": [
                {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "step": "Retrieve candidate structures.",
                    "tool_name": "crystal.csp_pack",
                    "arguments": {"query": "retrieve candidates"},
                    "expected_result": "Ranked candidate set with exportability metadata.",
                    "why": "Retrieval-focused planning.",
                    "condition": "Review only.",
                }
            ],
            "validation_results": [
                {
                    "schema_version": "agentic_csp.tool_validation.v1",
                    "tool_name": "crystal.csp_pack",
                    "valid": True,
                    "errors": [],
                    "warnings": [],
                }
            ],
            "warnings": [],
        },
        "proposal_count": 1,
        "valid_proposal_count": 1,
        "invalid_proposal_count": 0,
        "warnings": [],
    }


def _run_manager_log() -> dict[str, object]:
    return {
        "schema_version": RUN_MANAGER_LOG_SCHEMA_VERSION,
        "run_id": "run_001",
        "tool_calls_attempted": [],
        "failures_handled": [],
        "manager_notes": "Reviewed proposal readiness only; no execution occurred.",
        "artifacts_created": [],
    }


def _run_evaluation() -> dict[str, object]:
    return {
        "schema_version": RUN_EVALUATION_SCHEMA_VERSION,
        "run_id": "run_001",
        "run_goal": "retrieve candidates",
        "run_goal_success": True,
        "overall_goal_progress": "Proposal review advanced the overall goal without execution.",
        "summary": "The proposal-review run produced a valid future crystal.csp_pack proposal.",
        "what_worked": ["The planner emitted a compilable tool hint."],
        "what_failed_or_was_weak": ["No execution occurred in this ticket."],
        "scientific_findings": ["Proposal readiness improved."],
        "best_artifacts": [],
        "scores": {"proposal_readiness": "good"},
        "comparison_to_previous_best": "Comparable to prior review-only runs.",
        "recommended_next_run": "Continue the proposal-review chain.",
        "should_stop": False,
        "stop_reason": "",
        "needs_user_clarification": False,
        "clarification_question": "",
    }


def _orchestrator_decision() -> dict[str, object]:
    return {
        "schema_version": ORCHESTRATOR_DECISION_SCHEMA_VERSION,
        "decision": "continue",
        "reason": "The evaluator reports a useful proposal-review run with no execution.",
        "next_run_goal": "Continue proposal review for crystal.csp_pack readiness.",
        "current_stage": "wide_exploration",
        "evidence_used": ["run_evaluation", "run_manager_log", "compile_result"],
        "user_message_if_stopping": "",
        "clarification_question_if_needed": "",
    }


def _write_fake_trace(out_dir: Path, agent_name: str, parsed_output: dict[str, object]) -> None:
    trace = {
        "agent_name": agent_name,
        "runtime_context": {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "gpt-oss:20b",
        },
        "system_prompt": "Return JSON only.",
        "user_payload": {"input_payload": {"run_id": "run_001"}},
        "parsed_output": parsed_output,
        "raw_output": json.dumps(parsed_output),
        "attempts": [
            {
                "attempt_number": 1,
                "raw_output": json.dumps(parsed_output),
                "validation_errors": [],
            }
        ],
        "validation_errors": [],
    }
    (out_dir / f"agentic_llm_trace_{agent_name}.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _find_unexpected_execution_artifacts(root: Path) -> list[str]:
    unexpected: list[str] = []
    for path in root.rglob("*"):
        name = path.name.lower()
        if path.is_file() and name.startswith("mcp") and name.endswith(".jsonl"):
            unexpected.append(str(path))
        if path.is_dir() and "tool_execution" in name:
            unexpected.append(str(path))
    return sorted(unexpected)


def test_run_live_proposal_review_chain_writes_json_markdown_and_trace_bundle() -> None:
    original_planner = chain_runtime_module.run_live_planner_and_compile
    original_run_manager = chain_runtime_module.run_live_run_manager
    original_evaluator = chain_runtime_module.run_live_evaluator
    original_orchestrator = chain_runtime_module.run_live_orchestrator

    planner_calls: list[dict[str, object]] = []
    evaluator_calls: list[dict[str, object]] = []

    def _fake_planner(llm_runtime, input_payload, out_dir=None, archive_trace=False, require_proposals=False):  # type: ignore[no-untyped-def]
        sleep(0.01)
        planner_calls.append(
            {
                "input_payload": deepcopy(dict(input_payload)),
                "out_dir": str(out_dir) if out_dir is not None else None,
                "archive_trace": archive_trace,
                "require_proposals": require_proposals,
            }
        )
        result = _planner_result()
        if archive_trace and out_dir is not None:
            _write_fake_trace(Path(out_dir), "planner", result["run_plan"])
        return result

    def _fake_run_manager(llm_runtime, input_payload, out_dir=None, archive_trace=False):  # type: ignore[no-untyped-def]
        sleep(0.01)
        result = _run_manager_log()
        if archive_trace and out_dir is not None:
            _write_fake_trace(Path(out_dir), "run_manager", result)
        return result

    def _fake_evaluator(llm_runtime, input_payload, out_dir=None, archive_trace=False):  # type: ignore[no-untyped-def]
        sleep(0.01)
        evaluator_calls.append(deepcopy(dict(input_payload)))
        result = _run_evaluation()
        if archive_trace and out_dir is not None:
            _write_fake_trace(Path(out_dir), "evaluator", result)
        return result

    def _fake_orchestrator(llm_runtime, input_payload, out_dir=None, archive_trace=False):  # type: ignore[no-untyped-def]
        sleep(0.01)
        result = _orchestrator_decision()
        if archive_trace and out_dir is not None:
            _write_fake_trace(Path(out_dir), "orchestrator", result)
        return result

    chain_runtime_module.run_live_planner_and_compile = _fake_planner
    chain_runtime_module.run_live_run_manager = _fake_run_manager
    chain_runtime_module.run_live_evaluator = _fake_evaluator
    chain_runtime_module.run_live_orchestrator = _fake_orchestrator
    try:
        payload = {
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "nested": {"alpha": 1},
        }
        before = deepcopy(payload)
        with _repo_local_tempdir() as root:
            result = run_live_proposal_review_chain(
                object(),
                payload,
                root,
                archive_traces=True,
                require_proposals=True,
                collect_stage_timings=True,
            )

            chain_json_path = root / "agentic_proposal_review_chain.json"
            chain_markdown_path = root / "agentic_proposal_review_chain_summary.md"
            names = sorted(path.name for path in root.iterdir())
            summary = chain_markdown_path.read_text(encoding="utf-8")
            round_tripped = json.loads(chain_json_path.read_text(encoding="utf-8"))

            assert payload == before
            assert result["schema_version"] == PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION
            assert result["route_mode"] == FULL_LIVE_AGENT_CHAIN_ROUTE_MODE
            assert result["compile_result"]["schema_version"] == "agentic_csp.plan_compile.v1"
            assert planner_calls[0]["require_proposals"] is True
            assert names == [
                "agentic_proposal_review_chain.json",
                "agentic_proposal_review_chain_summary.md",
                "evaluator",
                "orchestrator",
                "planner",
                "run_manager",
            ]
            assert chain_json_path.exists()
            assert chain_markdown_path.exists()
            assert round_tripped["schema_version"] == PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION
            assert round_tripped["route_mode"] == FULL_LIVE_AGENT_CHAIN_ROUTE_MODE
            assert "## Route Diagnostics" in summary
            assert "- route mode: full_live_agent_chain" in summary
            assert "- source run id: run_001" in summary
            assert "- route type: full live" in summary
            assert "## Proposal Counts" in summary
            assert "- proposals: 1" in summary
            assert "## Run Manager" in summary
            assert "Reviewed proposal readiness only; no execution occurred." in summary
            assert "## Evaluator" in summary
            assert "The proposal-review run produced a valid future crystal.csp_pack proposal." in summary
            assert "## Orchestrator" in summary
            assert "Continue proposal review for crystal.csp_pack readiness." in summary
            assert "## Execution Intent" in summary
            assert "- status: ready_for_execution" in summary
            assert "- execution allowed: true" in summary
            assert "- selected proposal count: 1" in summary
            assert "## Execution Handoff" in summary
            assert "- status: ready" in summary
            assert "- selected tool sequence: crystal.csp_pack" in summary
            assert "- preflight requirements: executor_available, tool_registry_compatible, operator_allows_execution, workspace_writeable" in summary
            assert "## Executor Preflight" in summary
            assert "- status: blocked" in summary
            assert "- execution allowed: false" in summary
            assert "- dry run only: true" in summary
            assert "- missing requirements: operator_allows_execution, workspace_writeable" in summary
            assert "## Noop Execution Report" in summary
            assert "- mode: noop_dry_run" in summary
            assert "- status: blocked" in summary
            assert "- execution performed: false" in summary
            assert "- would call tools: none" in summary
            assert "## Stage Timings" in summary
            assert "## Trace Files" in summary
            assert result["execution_intent"]["schema_version"] == "agentic_csp.execution_intent.v1"
            assert result["execution_intent"]["status"] == "ready_for_execution"
            assert result["execution_intent"]["execution_allowed"] is True
            assert result["execution_intent"]["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"
            assert result["execution_handoff"]["schema_version"] == "agentic_csp.execution_handoff.v1"
            assert result["execution_handoff"]["status"] == "ready"
            assert result["execution_handoff"]["execution_allowed"] is True
            assert result["execution_handoff"]["selected_tool_sequence"] == ["crystal.csp_pack"]
            assert result["execution_handoff"]["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"
            assert result["executor_preflight"]["schema_version"] == "agentic_csp.executor_preflight.v1"
            assert result["executor_preflight"]["status"] == "blocked"
            assert result["executor_preflight"]["execution_allowed"] is False
            assert result["executor_preflight"]["dry_run_only"] is True
            assert "operator_allows_execution" in result["executor_preflight"]["missing_requirements"]
            assert "workspace_writeable" in result["executor_preflight"]["missing_requirements"]
            assert result["noop_execution_report"]["schema_version"] == "agentic_csp.noop_execution_report.v1"
            assert result["noop_execution_report"]["mode"] == "noop_dry_run"
            assert result["noop_execution_report"]["status"] == "blocked"
            assert result["noop_execution_report"]["execution_performed"] is False
            assert result["noop_execution_report"]["dry_run_only"] is True
            assert result["noop_execution_report"]["would_call_tools"] == []
            assert isinstance(result["stage_timings"], dict)
            for key in (
                "planner_compile",
                "run_manager",
                "evaluator",
                "orchestrator",
                "execution_intent",
                "execution_handoff",
                "executor_preflight",
                "noop_execution_report",
                "archive_write_total",
                "bundle_write",
                "total",
            ):
                assert key in result["stage_timings"]
                assert isinstance(result["stage_timings"][key], (int, float))
            evaluator_payload = evaluator_calls[0]
            compact_run_plan = evaluator_payload["run_plan"]
            compact_compile_result = evaluator_payload["compile_result"]
            compact_run_manager_log = evaluator_payload["run_manager_log"]
            assert "detailed_description" not in compact_run_plan
            assert "hoping_to_find" not in compact_run_plan
            assert compact_run_plan["plan_as_text"] == "tool_hint: crystal.csp_pack"
            assert list(compact_compile_result["proposals"][0].keys()) == [
                "schema_version",
                "tool_name",
                "arguments",
                "expected_result",
            ]
            assert "step" not in compact_compile_result["proposals"][0]
            assert compact_run_manager_log["tool_calls_attempted"] == []
            assert compact_run_manager_log["manager_notes"] == (
                "Reviewed proposal readiness only; no execution occurred."
            )
            assert result["trace_paths"]["planner"]["json"].endswith("agentic_llm_trace_planner.json")
            assert result["trace_paths"]["planner"]["markdown"].endswith("agentic_llm_trace_planner.md")
            assert result["trace_paths"]["orchestrator"]["json"].endswith("agentic_llm_trace_orchestrator.json")
            assert all(Path(path).exists() for path in result["artifact_paths"])
            assert json.loads(json.dumps(result))["schema_version"] == PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION
            all_names = sorted(
                path.name for path in root.rglob("*") if path.is_file()
            )
            assert all(not name.startswith(".") for name in all_names)
            assert all(not name.endswith(".db") for name in all_names)
            assert all(not name.endswith(".sqlite") for name in all_names)
            assert _find_unexpected_execution_artifacts(root) == []
    finally:
        chain_runtime_module.run_live_planner_and_compile = original_planner
        chain_runtime_module.run_live_run_manager = original_run_manager
        chain_runtime_module.run_live_evaluator = original_evaluator
        chain_runtime_module.run_live_orchestrator = original_orchestrator


def test_run_live_proposal_review_chain_can_pass_executor_preflight_when_explicitly_allowed() -> None:
    original_planner = chain_runtime_module.run_live_planner_and_compile
    original_run_manager = chain_runtime_module.run_live_run_manager
    original_evaluator = chain_runtime_module.run_live_evaluator
    original_orchestrator = chain_runtime_module.run_live_orchestrator

    def _fake_planner(llm_runtime, input_payload, out_dir=None, archive_trace=False, require_proposals=False):  # type: ignore[no-untyped-def]
        return _planner_result()

    def _fake_run_manager(llm_runtime, input_payload, out_dir=None, archive_trace=False):  # type: ignore[no-untyped-def]
        return _run_manager_log()

    def _fake_evaluator(llm_runtime, input_payload, out_dir=None, archive_trace=False):  # type: ignore[no-untyped-def]
        return _run_evaluation()

    def _fake_orchestrator(llm_runtime, input_payload, out_dir=None, archive_trace=False):  # type: ignore[no-untyped-def]
        return _orchestrator_decision()

    chain_runtime_module.run_live_planner_and_compile = _fake_planner
    chain_runtime_module.run_live_run_manager = _fake_run_manager
    chain_runtime_module.run_live_evaluator = _fake_evaluator
    chain_runtime_module.run_live_orchestrator = _fake_orchestrator
    try:
        with _repo_local_tempdir() as root:
            result = run_live_proposal_review_chain(
                object(),
                {
                    "run_id": "run_001",
                    "overall_goal": "TiO2",
                    "run_goal": "retrieve candidates",
                    "stage": "wide_exploration",
                },
                root,
                archive_traces=False,
                require_proposals=True,
                preflight_available_tools=["crystal.csp_pack"],
                preflight_operator_allows_execution=True,
                preflight_workspace_writeable=True,
                collect_stage_timings=True,
            )

            assert result["executor_preflight"]["status"] == "pass"
            assert result["executor_preflight"]["execution_allowed"] is True
            assert result["executor_preflight"]["dry_run_only"] is True
            assert result["executor_preflight"]["selected_tool_sequence"] == [
                "crystal.csp_pack"
            ]
            assert result["noop_execution_report"]["status"] == "would_execute"
            assert result["noop_execution_report"]["execution_performed"] is False
            assert result["noop_execution_report"]["dry_run_only"] is True
            assert result["noop_execution_report"]["would_call_tools"] == [
                "crystal.csp_pack"
            ]
            assert "stage_timings" in result
    finally:
        chain_runtime_module.run_live_planner_and_compile = original_planner
        chain_runtime_module.run_live_run_manager = original_run_manager
        chain_runtime_module.run_live_evaluator = original_evaluator
        chain_runtime_module.run_live_orchestrator = original_orchestrator


def test_chain_runtime_fixture_route_round_trips_and_replays_c_layer() -> None:
    original_planner = chain_runtime_module.run_live_planner_and_compile
    original_run_manager = chain_runtime_module.run_live_run_manager
    original_evaluator = chain_runtime_module.run_live_evaluator
    original_orchestrator = chain_runtime_module.run_live_orchestrator

    def _fake_planner(llm_runtime, input_payload, out_dir=None, archive_trace=False, require_proposals=False):  # type: ignore[no-untyped-def]
        return _planner_result()

    def _fake_run_manager(llm_runtime, input_payload, out_dir=None, archive_trace=False):  # type: ignore[no-untyped-def]
        return _run_manager_log()

    def _fake_evaluator(llm_runtime, input_payload, out_dir=None, archive_trace=False):  # type: ignore[no-untyped-def]
        return _run_evaluation()

    def _fake_orchestrator(llm_runtime, input_payload, out_dir=None, archive_trace=False):  # type: ignore[no-untyped-def]
        return _orchestrator_decision()

    chain_runtime_module.run_live_planner_and_compile = _fake_planner
    chain_runtime_module.run_live_run_manager = _fake_run_manager
    chain_runtime_module.run_live_evaluator = _fake_evaluator
    chain_runtime_module.run_live_orchestrator = _fake_orchestrator
    try:
        with _repo_local_tempdir() as root:
            result = run_live_proposal_review_chain(
                object(),
                {
                    "run_id": "run_001",
                    "overall_goal": "TiO2",
                    "run_goal": "retrieve candidates",
                    "stage": "wide_exploration",
                },
                root,
                archive_traces=False,
                require_proposals=True,
            )
            fixture_dir = root / "fixture"
            fixture_write = write_chain_fixture(result, fixture_dir)
            loaded = load_chain_fixture(fixture_write["fixture_json_path"])
            replay = replay_c_layer_from_fixture(loaded)

            assert loaded["run_id"] == result["run_id"]
            assert replay["route_mode"] == "fixture_replay_c_layer"
            assert replay["execution_intent"]["status"] == result["execution_intent"]["status"]
            assert replay["execution_handoff"]["status"] == result["execution_handoff"]["status"]
            assert replay["executor_preflight"]["status"] == result["executor_preflight"]["status"]
            assert replay["noop_execution_report"]["status"] == result["noop_execution_report"]["status"]
            assert replay["noop_execution_report"]["execution_performed"] is False
    finally:
        chain_runtime_module.run_live_planner_and_compile = original_planner
        chain_runtime_module.run_live_run_manager = original_run_manager
        chain_runtime_module.run_live_evaluator = original_evaluator
        chain_runtime_module.run_live_orchestrator = original_orchestrator


def test_chain_runtime_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(chain_runtime_module)
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


def test_chain_runtime_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    assert "sok_llm_orchestrator.pipeline" not in sys.modules
