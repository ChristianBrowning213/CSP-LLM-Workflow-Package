from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from .archive import write_agentic_llm_trace_markdown
from .execution_handoff import build_execution_handoff
from .execution_intent import build_execution_intent
from .executor_preflight import build_executor_preflight
from .evaluator_runtime import run_live_evaluator
from .noop_executor import build_noop_execution_report
from .orchestrator_runtime import run_live_orchestrator
from .planner_runtime import run_live_planner_and_compile
from .run_manager_runtime import run_live_run_manager
from .schemas import assert_json_serializable, to_json_dict

PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION = "agentic_csp.proposal_review_chain.v1"
FULL_LIVE_AGENT_CHAIN_ROUTE_MODE = "full_live_agent_chain"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def _trace_paths_for_agent(root: Path, agent_name: str) -> dict[str, str]:
    trace_json_path = root / f"agentic_llm_trace_{agent_name}.json"
    if not trace_json_path.exists():
        return {}

    trace_json = json.loads(trace_json_path.read_text(encoding="utf-8"))
    markdown_write = write_agentic_llm_trace_markdown(trace_json, root, agent_name)
    markdown_path = str(markdown_write["markdown_path"])
    return {
        "json": str(trace_json_path),
        "markdown": markdown_path,
    }


def _compact_run_plan_for_evaluator(run_plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": _safe_string(run_plan, "schema_version"),
        "overall_goal": _safe_string(run_plan, "overall_goal"),
        "run_goal": _safe_string(run_plan, "run_goal"),
        "stage": _safe_string(run_plan, "stage"),
        "plan_as_text": _safe_string(run_plan, "plan_as_text"),
        "success_criteria": run_plan.get("success_criteria"),
        "stop_conditions_for_this_run": run_plan.get("stop_conditions_for_this_run"),
        "what_we_tried_previously_that_is_related": run_plan.get(
            "what_we_tried_previously_that_is_related"
        ),
    }


def _compact_compile_result_for_evaluator(compile_result: Mapping[str, Any]) -> dict[str, Any]:
    compact_proposals: list[dict[str, Any]] = []
    proposals = compile_result.get("proposals")
    if isinstance(proposals, list):
        for proposal in proposals:
            if not isinstance(proposal, Mapping):
                continue
            compact_proposals.append(
                {
                    "schema_version": _safe_string(proposal, "schema_version"),
                    "tool_name": _safe_string(proposal, "tool_name"),
                    "arguments": to_json_dict(proposal.get("arguments", {}))
                    if isinstance(proposal.get("arguments"), Mapping)
                    else {},
                    "expected_result": _safe_string(proposal, "expected_result"),
                }
            )

    compact_validation_results: list[dict[str, Any]] = []
    validation_results = compile_result.get("validation_results")
    if isinstance(validation_results, list):
        for item in validation_results:
            if not isinstance(item, Mapping):
                continue
            compact_validation_results.append(
                {
                    "schema_version": _safe_string(item, "schema_version"),
                    "tool_name": _safe_string(item, "tool_name"),
                    "valid": item.get("valid") is True,
                    "errors": list(item.get("errors", []))
                    if isinstance(item.get("errors"), list)
                    else [],
                    "warnings": list(item.get("warnings", []))
                    if isinstance(item.get("warnings"), list)
                    else [],
                }
            )

    return {
        "schema_version": _safe_string(compile_result, "schema_version"),
        "proposals": compact_proposals,
        "validation_results": compact_validation_results,
        "warnings": list(compile_result.get("warnings", []))
        if isinstance(compile_result.get("warnings"), list)
        else [],
    }


def _compact_run_manager_log_for_evaluator(run_manager_log: Mapping[str, Any]) -> dict[str, Any]:
    compact_tool_calls: list[dict[str, Any]] = []
    tool_calls_attempted = run_manager_log.get("tool_calls_attempted")
    if isinstance(tool_calls_attempted, list):
        for item in tool_calls_attempted:
            if not isinstance(item, Mapping):
                continue
            compact_tool_calls.append(
                {
                    "tool_name": _safe_string(item, "tool_name"),
                    "executed": item.get("executed") is True,
                    "remarks": _safe_string(item, "remarks"),
                }
            )

    return {
        "schema_version": _safe_string(run_manager_log, "schema_version"),
        "run_id": _safe_string(run_manager_log, "run_id"),
        "manager_notes": _safe_string(run_manager_log, "manager_notes"),
        "tool_calls_attempted": compact_tool_calls,
        "failures_handled": list(run_manager_log.get("failures_handled", []))
        if isinstance(run_manager_log.get("failures_handled"), list)
        else [],
        "artifacts_created": list(run_manager_log.get("artifacts_created", []))
        if isinstance(run_manager_log.get("artifacts_created"), list)
        else [],
    }


def _proposal_review_chain_summary(result: Mapping[str, Any]) -> str:
    planner_result = result.get("planner_result")
    run_manager_log = result.get("run_manager_log")
    run_evaluation = result.get("run_evaluation")
    orchestrator_decision = result.get("orchestrator_decision")
    execution_intent = result.get("execution_intent")
    execution_handoff = result.get("execution_handoff")
    executor_preflight = result.get("executor_preflight")
    noop_execution_report = result.get("noop_execution_report")
    stage_timings = result.get("stage_timings")
    trace_paths = result.get("trace_paths")

    run_plan = planner_result.get("run_plan") if isinstance(planner_result, Mapping) else {}
    compile_result = (
        planner_result.get("compile_result") if isinstance(planner_result, Mapping) else {}
    )

    lines = [
        "# Agentic Proposal Review Chain Summary",
        "",
        f"- Run ID: {_safe_string(result, 'run_id')}",
        f"- Overall Goal: {_safe_string(run_plan, 'overall_goal')}",
        f"- Run Goal: {_safe_string(run_plan, 'run_goal')}",
        f"- Stage: {_safe_string(run_plan, 'stage')}",
        f"- Planner Schema: {_safe_string(run_plan, 'schema_version')}",
        f"- Compile Schema: {_safe_string(compile_result, 'schema_version')}",
        f"- Run Manager Schema: {_safe_string(run_manager_log, 'schema_version') if isinstance(run_manager_log, Mapping) else ''}",
        f"- Evaluator Schema: {_safe_string(run_evaluation, 'schema_version') if isinstance(run_evaluation, Mapping) else ''}",
        f"- Orchestrator Schema: {_safe_string(orchestrator_decision, 'schema_version') if isinstance(orchestrator_decision, Mapping) else ''}",
        "",
        "## Route Diagnostics",
        "",
        f"- route mode: {_safe_string(result, 'route_mode')}",
        f"- source run id: {_safe_string(result, 'run_id')}",
        f"- route type: {'fixture replay' if _safe_string(result, 'route_mode') == 'fixture_replay_c_layer' else 'full live'}",
        "",
        "## Proposal Counts",
        "",
        f"- proposals: {planner_result.get('proposal_count', 0) if isinstance(planner_result, Mapping) else 0}",
        f"- valid: {planner_result.get('valid_proposal_count', 0) if isinstance(planner_result, Mapping) else 0}",
        f"- invalid: {planner_result.get('invalid_proposal_count', 0) if isinstance(planner_result, Mapping) else 0}",
        "",
        "## Run Manager",
        "",
        f"- manager_notes: {_safe_string(run_manager_log, 'manager_notes') if isinstance(run_manager_log, Mapping) else ''}",
        "",
        "## Evaluator",
        "",
        f"- summary: {_safe_string(run_evaluation, 'summary') if isinstance(run_evaluation, Mapping) else ''}",
        "",
        "## Orchestrator",
        "",
        f"- decision: {_safe_string(orchestrator_decision, 'decision') if isinstance(orchestrator_decision, Mapping) else ''}",
        f"- reason: {_safe_string(orchestrator_decision, 'reason') if isinstance(orchestrator_decision, Mapping) else ''}",
        f"- next_run_goal: {_safe_string(orchestrator_decision, 'next_run_goal') if isinstance(orchestrator_decision, Mapping) else ''}",
        "",
        "## Execution Intent",
        "",
        f"- status: {_safe_string(execution_intent, 'status') if isinstance(execution_intent, Mapping) else ''}",
        f"- execution allowed: {str(bool(execution_intent.get('execution_allowed', False))).lower() if isinstance(execution_intent, Mapping) else 'false'}",
        f"- selected proposal count: {len(execution_intent.get('selected_proposals', [])) if isinstance(execution_intent, Mapping) and isinstance(execution_intent.get('selected_proposals'), list) else 0}",
        "",
    ]

    if isinstance(execution_intent, Mapping):
        blocked_reasons = execution_intent.get("blocked_reasons")
        if isinstance(blocked_reasons, list) and blocked_reasons:
            lines.append("- blocked reasons:")
            for reason in blocked_reasons:
                lines.append(f"  - {reason}")
        else:
            lines.append("- blocked reasons: none")
    else:
        lines.append("- blocked reasons: none")

    lines.extend(
        [
            "",
            "## Execution Handoff",
            "",
            f"- status: {_safe_string(execution_handoff, 'status') if isinstance(execution_handoff, Mapping) else ''}",
            f"- execution allowed: {str(bool(execution_handoff.get('execution_allowed', False))).lower() if isinstance(execution_handoff, Mapping) else 'false'}",
            f"- selected tool sequence: {', '.join(str(item) for item in execution_handoff.get('selected_tool_sequence', [])) if isinstance(execution_handoff, Mapping) and isinstance(execution_handoff.get('selected_tool_sequence'), list) else ''}",
            f"- preflight requirements: {', '.join(str(item) for item in execution_handoff.get('preflight_requirements', [])) if isinstance(execution_handoff, Mapping) and isinstance(execution_handoff.get('preflight_requirements'), list) else ''}",
        f"- blocked reasons: {' | '.join(str(item) for item in execution_handoff.get('blocked_reasons', [])) if isinstance(execution_handoff, Mapping) and isinstance(execution_handoff.get('blocked_reasons'), list) and execution_handoff.get('blocked_reasons') else 'none'}",
        "",
        "## Trace Files",
        "",
    ]
    )
    lines[-3:-3] = [
        "## Executor Preflight",
        "",
        f"- status: {_safe_string(executor_preflight, 'status') if isinstance(executor_preflight, Mapping) else ''}",
        f"- execution allowed: {str(bool(executor_preflight.get('execution_allowed', False))).lower() if isinstance(executor_preflight, Mapping) else 'false'}",
        f"- dry run only: {str(bool(executor_preflight.get('dry_run_only', False))).lower() if isinstance(executor_preflight, Mapping) else 'true'}",
        f"- missing requirements: {', '.join(str(item) for item in executor_preflight.get('missing_requirements', [])) if isinstance(executor_preflight, Mapping) and isinstance(executor_preflight.get('missing_requirements'), list) and executor_preflight.get('missing_requirements') else 'none'}",
        f"- blocked reasons: {' | '.join(str(item) for item in executor_preflight.get('blocked_reasons', [])) if isinstance(executor_preflight, Mapping) and isinstance(executor_preflight.get('blocked_reasons'), list) and executor_preflight.get('blocked_reasons') else 'none'}",
        "",
        "## Noop Execution Report",
        "",
        f"- mode: {_safe_string(noop_execution_report, 'mode') if isinstance(noop_execution_report, Mapping) else ''}",
        f"- status: {_safe_string(noop_execution_report, 'status') if isinstance(noop_execution_report, Mapping) else ''}",
        f"- execution performed: {str(bool(noop_execution_report.get('execution_performed', False))).lower() if isinstance(noop_execution_report, Mapping) else 'false'}",
        f"- would call tools: {', '.join(str(item) for item in noop_execution_report.get('would_call_tools', [])) if isinstance(noop_execution_report, Mapping) and isinstance(noop_execution_report.get('would_call_tools'), list) and noop_execution_report.get('would_call_tools') else 'none'}",
        f"- blocked reasons: {' | '.join(str(item) for item in noop_execution_report.get('blocked_reasons', [])) if isinstance(noop_execution_report, Mapping) and isinstance(noop_execution_report.get('blocked_reasons'), list) and noop_execution_report.get('blocked_reasons') else 'none'}",
        "",
        "## Stage Timings",
        "",
    ]

    if isinstance(stage_timings, Mapping) and stage_timings:
        for key in (
            "planner_compile",
            "run_manager",
            "evaluator",
            "orchestrator",
            "execution_intent",
            "execution_handoff",
            "executor_preflight",
            "noop_execution_report",
            "bundle_write",
            "archive_write_total",
            "total",
        ):
            value = stage_timings.get(key)
            if isinstance(value, int | float):
                lines.append(f"- {key}: {value:.6f}")
    else:
        lines.append("- not_collected")

    lines.extend(
        [
            "",
            "## Trace Files",
            "",
        ]
    )

    if isinstance(trace_paths, Mapping) and trace_paths:
        for agent_name in ("planner", "run_manager", "evaluator", "orchestrator"):
            agent_paths = trace_paths.get(agent_name)
            if not isinstance(agent_paths, Mapping):
                continue
            lines.append(f"- {agent_name} JSON: {_safe_string(agent_paths, 'json')}")
            lines.append(f"- {agent_name} Markdown: {_safe_string(agent_paths, 'markdown')}")
    else:
        lines.append("- No trace files were archived.")

    return "\n".join(lines) + "\n"


def run_live_proposal_review_chain(
    llm_runtime: Any,
    input_payload: Mapping[str, Any],
    out_dir,
    archive_traces: bool = True,
    require_proposals: bool = True,
    preflight_available_tools=None,
    preflight_operator_allows_execution: bool = False,
    preflight_workspace_writeable: bool = False,
    collect_stage_timings: bool = False,
) -> dict[str, Any]:
    if not isinstance(input_payload, Mapping):
        msg = "input_payload must be a mapping"
        raise TypeError(msg)

    original_input_payload = to_json_dict(input_payload)
    assert_json_serializable(original_input_payload)
    working_input_payload = deepcopy(original_input_payload)

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    planner_dir = root / "planner"
    run_manager_dir = root / "run_manager"
    evaluator_dir = root / "evaluator"
    orchestrator_dir = root / "orchestrator"
    if archive_traces:
        planner_dir.mkdir(parents=True, exist_ok=True)
        run_manager_dir.mkdir(parents=True, exist_ok=True)
        evaluator_dir.mkdir(parents=True, exist_ok=True)
        orchestrator_dir.mkdir(parents=True, exist_ok=True)

    stage_timings: dict[str, float] = {}
    total_started_at = perf_counter() if collect_stage_timings else 0.0

    stage_started_at = perf_counter() if collect_stage_timings else 0.0
    planner_result = run_live_planner_and_compile(
        llm_runtime,
        working_input_payload,
        out_dir=planner_dir if archive_traces else None,
        archive_trace=archive_traces,
        require_proposals=require_proposals,
    )
    if collect_stage_timings:
        stage_timings["planner_compile"] = perf_counter() - stage_started_at

    stage_started_at = perf_counter() if collect_stage_timings else 0.0
    run_manager_log = run_live_run_manager(
        llm_runtime,
        {
            "run_id": original_input_payload.get("run_id", ""),
            "run_plan": planner_result["run_plan"],
            "compile_result": planner_result["compile_result"],
            "proposal_count": planner_result["proposal_count"],
            "valid_proposal_count": planner_result["valid_proposal_count"],
            "invalid_proposal_count": planner_result["invalid_proposal_count"],
            "warnings": planner_result["warnings"],
        },
        out_dir=run_manager_dir if archive_traces else None,
        archive_trace=archive_traces,
    )
    if collect_stage_timings:
        stage_timings["run_manager"] = perf_counter() - stage_started_at

    evaluator_input_payload = {
        "run_id": original_input_payload.get("run_id", ""),
        "run_plan": _compact_run_plan_for_evaluator(planner_result["run_plan"]),
        "compile_result": _compact_compile_result_for_evaluator(
            planner_result["compile_result"]
        ),
        "run_manager_log": _compact_run_manager_log_for_evaluator(run_manager_log),
        "proposal_count": planner_result["proposal_count"],
        "valid_proposal_count": planner_result["valid_proposal_count"],
        "invalid_proposal_count": planner_result["invalid_proposal_count"],
        "warnings": planner_result["warnings"],
    }
    stage_started_at = perf_counter() if collect_stage_timings else 0.0
    run_evaluation = run_live_evaluator(
        llm_runtime,
        evaluator_input_payload,
        out_dir=evaluator_dir if archive_traces else None,
        archive_trace=archive_traces,
    )
    if collect_stage_timings:
        stage_timings["evaluator"] = perf_counter() - stage_started_at

    stage_started_at = perf_counter() if collect_stage_timings else 0.0
    orchestrator_decision = run_live_orchestrator(
        llm_runtime,
        {
            "run_id": original_input_payload.get("run_id", ""),
            "run_plan": planner_result["run_plan"],
            "compile_result": planner_result["compile_result"],
            "run_manager_log": run_manager_log,
            "run_evaluation": run_evaluation,
            "proposal_count": planner_result["proposal_count"],
            "valid_proposal_count": planner_result["valid_proposal_count"],
            "invalid_proposal_count": planner_result["invalid_proposal_count"],
            "warnings": planner_result["warnings"],
        },
        out_dir=orchestrator_dir if archive_traces else None,
        archive_trace=archive_traces,
    )
    if collect_stage_timings:
        stage_timings["orchestrator"] = perf_counter() - stage_started_at

    stage_started_at = perf_counter() if collect_stage_timings else 0.0
    execution_intent = build_execution_intent(planner_result, run_manager_log)
    if collect_stage_timings:
        stage_timings["execution_intent"] = perf_counter() - stage_started_at

    chain_result_for_handoff = {
        "schema_version": PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION,
        "run_id": _safe_string(run_manager_log, "run_id") or _safe_string(
            original_input_payload, "run_id"
        ),
        "planner_result": planner_result,
        "run_manager_log": run_manager_log,
        "run_evaluation": run_evaluation,
        "orchestrator_decision": orchestrator_decision,
        "execution_intent": execution_intent,
    }
    stage_started_at = perf_counter() if collect_stage_timings else 0.0
    execution_handoff = build_execution_handoff(chain_result_for_handoff)
    if collect_stage_timings:
        stage_timings["execution_handoff"] = perf_counter() - stage_started_at

    stage_started_at = perf_counter() if collect_stage_timings else 0.0
    executor_preflight = build_executor_preflight(
        execution_handoff,
        available_tools=preflight_available_tools,
        operator_allows_execution=preflight_operator_allows_execution,
        workspace_writeable=preflight_workspace_writeable,
    )
    if collect_stage_timings:
        stage_timings["executor_preflight"] = perf_counter() - stage_started_at

    stage_started_at = perf_counter() if collect_stage_timings else 0.0
    noop_execution_report = build_noop_execution_report(executor_preflight)
    if collect_stage_timings:
        stage_timings["noop_execution_report"] = perf_counter() - stage_started_at

    archive_started_at = perf_counter() if collect_stage_timings else 0.0
    trace_paths: dict[str, dict[str, str]] = {}
    if archive_traces:
        for agent_name, agent_dir in (
            ("planner", planner_dir),
            ("run_manager", run_manager_dir),
            ("evaluator", evaluator_dir),
            ("orchestrator", orchestrator_dir),
        ):
            agent_paths = _trace_paths_for_agent(agent_dir, agent_name)
            if agent_paths:
                trace_paths[agent_name] = agent_paths
    if collect_stage_timings:
        stage_timings["archive_write_total"] = perf_counter() - archive_started_at

    run_id = _safe_string(run_manager_log, "run_id") or _safe_string(
        original_input_payload, "run_id"
    )
    result = {
        "schema_version": PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION,
        "run_id": run_id,
        "route_mode": FULL_LIVE_AGENT_CHAIN_ROUTE_MODE,
        "planner_result": planner_result,
        "compile_result": planner_result["compile_result"],
        "run_manager_log": run_manager_log,
        "run_evaluation": run_evaluation,
        "orchestrator_decision": orchestrator_decision,
        "execution_intent": execution_intent,
        "execution_handoff": execution_handoff,
        "executor_preflight": executor_preflight,
        "noop_execution_report": noop_execution_report,
        "artifact_paths": [],
        "trace_paths": trace_paths,
    }
    if collect_stage_timings:
        result["stage_timings"] = stage_timings

    chain_json_path = root / "agentic_proposal_review_chain.json"
    chain_markdown_path = root / "agentic_proposal_review_chain_summary.md"

    artifact_paths = [str(chain_json_path), str(chain_markdown_path)]
    for agent_paths in trace_paths.values():
        artifact_paths.extend(agent_paths.values())
    result["artifact_paths"] = artifact_paths
    assert_json_serializable(result)

    bundle_started_at = perf_counter() if collect_stage_timings else 0.0
    chain_json_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    chain_markdown_path.write_text(
        _proposal_review_chain_summary(result),
        encoding="utf-8",
    )
    if collect_stage_timings:
        stage_timings["bundle_write"] = perf_counter() - bundle_started_at
        stage_timings["total"] = perf_counter() - total_started_at
        assert_json_serializable(result)
        chain_json_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        chain_markdown_path.write_text(
            _proposal_review_chain_summary(result),
            encoding="utf-8",
        )
    return result


__all__ = [
    "FULL_LIVE_AGENT_CHAIN_ROUTE_MODE",
    "PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION",
    "run_live_proposal_review_chain",
]
