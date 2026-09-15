from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from .execution_handoff import build_execution_handoff
from .execution_intent import build_execution_intent
from .executor_preflight import build_executor_preflight
from .failure_handling import handle_inspection_failures
from .manager_logging import (
    build_manager_notes,
    build_tool_call_log_rows,
    write_manager_replay_artifacts,
)
from .noop_executor import build_noop_execution_report
from .partial_success import build_partial_success_evaluation, build_continuation_summary
from .result_inspection import inspect_step_results
from .schemas import assert_json_serializable, to_json_dict
from .step_execution import build_step_execution_plan, run_noop_step_execution

CHAIN_FIXTURE_SCHEMA_VERSION = "agentic_csp.chain_fixture.v1"
C_LAYER_REPLAY_SCHEMA_VERSION = "agentic_csp.c_layer_replay.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def assert_chain_fixture_ready_for_c_layer(chain_result: Mapping[str, Any]) -> None:
    if not isinstance(chain_result, Mapping):
        msg = "chain_result must be a mapping"
        raise TypeError(msg)

    required = {
        "planner_result": chain_result.get("planner_result"),
        "run_manager_log": chain_result.get("run_manager_log"),
        "run_evaluation": chain_result.get("run_evaluation"),
        "orchestrator_decision": chain_result.get("orchestrator_decision"),
    }
    missing = [key for key, value in required.items() if not isinstance(value, Mapping)]
    if missing:
        msg = "Missing required A/B chain mappings: " + ", ".join(missing)
        raise ValueError(msg)

    planner_result = required["planner_result"]
    run_plan = planner_result.get("run_plan") if isinstance(planner_result, Mapping) else None
    compile_result = (
        planner_result.get("compile_result") if isinstance(planner_result, Mapping) else None
    )
    if not isinstance(run_plan, Mapping):
        msg = "planner_result.run_plan must be present for C-layer fixture replay"
        raise ValueError(msg)
    if not isinstance(compile_result, Mapping):
        msg = "planner_result.compile_result must be present for C-layer fixture replay"
        raise ValueError(msg)


def write_chain_fixture(chain_result: Mapping[str, Any], out_dir) -> dict[str, Any]:
    assert_chain_fixture_ready_for_c_layer(chain_result)

    chain_dict = to_json_dict(chain_result)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    fixture_json_path = root / "agentic_proposal_review_chain_fixture.json"

    fixture_payload = {
        "schema_version": CHAIN_FIXTURE_SCHEMA_VERSION,
        "route_mode": "fixture_source_ab_chain",
        "source_chain_schema_version": _safe_string(chain_dict, "schema_version"),
        "source_run_id": _safe_string(chain_dict, "run_id"),
        "chain_result": chain_dict,
    }
    assert_json_serializable(fixture_payload)
    fixture_json_path.write_text(
        json.dumps(fixture_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "schema_version": CHAIN_FIXTURE_SCHEMA_VERSION,
        "fixture_json_path": str(fixture_json_path),
        "artifact_paths": [str(fixture_json_path)],
    }


def load_chain_fixture(path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        msg = "Fixture payload must be a JSON object"
        raise ValueError(msg)

    chain_result = payload.get("chain_result")
    if not isinstance(chain_result, Mapping):
        msg = "Fixture payload is missing chain_result"
        raise ValueError(msg)

    assert_chain_fixture_ready_for_c_layer(chain_result)
    return to_json_dict(chain_result)


def replay_c_layer_from_fixture(
    chain_result: Mapping[str, Any],
    include_noop: bool = True,
    include_step_execution: bool = True,
    write_manager_artifacts_dir=None,
) -> dict[str, Any]:
    assert_chain_fixture_ready_for_c_layer(chain_result)

    chain_dict = deepcopy(to_json_dict(chain_result))
    planner_result = to_json_dict(chain_dict["planner_result"])
    run_manager_log = to_json_dict(chain_dict["run_manager_log"])
    run_evaluation = to_json_dict(chain_dict["run_evaluation"])
    orchestrator_decision = to_json_dict(chain_dict["orchestrator_decision"])

    execution_intent = build_execution_intent(planner_result, run_manager_log)
    execution_handoff = build_execution_handoff(
        {
            "schema_version": _safe_string(chain_dict, "schema_version"),
            "run_id": _safe_string(chain_dict, "run_id"),
            "planner_result": planner_result,
            "compile_result": planner_result.get("compile_result", {}),
            "run_manager_log": run_manager_log,
            "run_evaluation": run_evaluation,
            "orchestrator_decision": orchestrator_decision,
            "execution_intent": execution_intent,
        }
    )
    executor_preflight = build_executor_preflight(execution_handoff)

    replay_steps = [
        "execution_intent",
        "execution_handoff",
        "executor_preflight",
    ]
    result = {
        "schema_version": C_LAYER_REPLAY_SCHEMA_VERSION,
        "route_mode": "fixture_replay_c_layer",
        "source_chain_schema_version": _safe_string(chain_dict, "schema_version"),
        "source_run_id": _safe_string(chain_dict, "run_id"),
        "execution_intent": execution_intent,
        "execution_handoff": execution_handoff,
        "executor_preflight": executor_preflight,
        "replay_steps": replay_steps,
        "warnings": [],
    }
    if include_step_execution:
        step_execution_plan = build_step_execution_plan(execution_handoff)
        noop_step_execution = run_noop_step_execution(step_execution_plan)
        result_inspection = inspect_step_results(noop_step_execution)
        failure_handling = handle_inspection_failures(result_inspection)
        result["step_execution_plan"] = step_execution_plan
        result["noop_step_execution"] = noop_step_execution
        result["result_inspection"] = result_inspection
        result["failure_handling"] = failure_handling
        replay_steps.extend(
            [
                "step_execution_plan",
                "noop_step_execution",
                "result_inspection",
                "failure_handling",
            ]
        )
    if include_noop:
        result["noop_execution_report"] = build_noop_execution_report(executor_preflight)
        replay_steps.append("noop_execution_report")
    if write_manager_artifacts_dir is not None:
        result["manager_notes"] = build_manager_notes(result)
        result["tool_call_log_rows"] = build_tool_call_log_rows(result)
        result["manager_replay_artifacts"] = write_manager_replay_artifacts(
            result,
            write_manager_artifacts_dir,
        )
        replay_steps.extend(
            [
                "manager_notes",
                "tool_call_log_rows",
                "manager_replay_artifacts",
            ]
        )

    # Add partial success evaluation and continuation summary
    result["partial_success"] = build_partial_success_evaluation(result)
    result["continuation_summary"] = build_continuation_summary(result["partial_success"])
    replay_steps.extend([
        "partial_success",
        "continuation_summary",
    ])

    result["c_layer_replay_report"] = build_c_layer_replay_report(result)
    assert_json_serializable(result)
    return result


def build_c_layer_replay_report(replay_result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(replay_result, Mapping):
        msg = "replay_result must be a mapping"
        raise TypeError(msg)

    replay_dict = to_json_dict(replay_result)
    c_steps: list[dict[str, str]] = []
    ordered_names = [
        "execution_intent",
        "execution_handoff",
        "executor_preflight",
        "step_execution_plan",
        "noop_step_execution",
        "result_inspection",
        "failure_handling",
    ]
    optional_names = [
        "manager_notes",
        "tool_call_log_rows",
        "manager_replay_artifacts",
    ]
    final_names = [
        "partial_success",
        "continuation_summary",
    ]

    for name in ordered_names + [item for item in optional_names if item in replay_dict] + final_names:
        value = replay_dict.get(name)
        if isinstance(value, Mapping):
            status = _safe_string(value, "status")
            if name == "continuation_summary":
                status = _safe_string(value, "final_status")
            elif name == "manager_notes" and not status:
                status = "recorded"
            elif name == "manager_replay_artifacts" and not status:
                status = "written"
            c_steps.append(
                {
                    "name": name,
                    "status": status,
                }
            )
        elif name == "tool_call_log_rows" and isinstance(value, list):
            c_steps.append({"name": name, "status": "recorded"})

    continuation_summary = replay_dict.get("continuation_summary")
    final_status = (
        _safe_string(continuation_summary, "final_status")
        if isinstance(continuation_summary, Mapping)
        else _safe_string(
            replay_dict.get("failure_handling", {})
            if isinstance(replay_dict.get("failure_handling"), Mapping)
            else {},
            "status",
            "unknown",
        )
    )
    summary = f"C-layer replay finished with {final_status}."
    result = {
        "schema_version": "agentic_csp.c_layer_replay_report.v1",
        "route_mode": replay_dict.get("route_mode", "fixture_replay_c_layer"),
        "c_steps": c_steps,
        "final_status": final_status,
        "summary": summary,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "CHAIN_FIXTURE_SCHEMA_VERSION",
    "C_LAYER_REPLAY_SCHEMA_VERSION",
    "assert_chain_fixture_ready_for_c_layer",
    "build_c_layer_replay_report",
    "load_chain_fixture",
    "replay_c_layer_from_fixture",
    "write_chain_fixture",
]
