from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

MANAGER_NOTES_SCHEMA_VERSION = "agentic_csp.manager_notes.v1"
TOOL_CALL_LOG_ROW_SCHEMA_VERSION = "agentic_csp.tool_call_log_row.v1"
MANAGER_REPLAY_ARTIFACTS_SCHEMA_VERSION = "agentic_csp.manager_replay_artifacts.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def _decision_from_action(action_type: str) -> str:
    if action_type == "block_next_stage":
        return "block"
    if action_type in {"fallback_retrieval", "recompile_request"}:
        return "recover"
    if action_type == "skip_optional_stage":
        return "skip"
    return "continue"


def _step_contexts(replay_result: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(replay_result, Mapping):
        msg = "replay_result must be a mapping"
        raise TypeError(msg)

    replay_dict = to_json_dict(replay_result)
    step_execution_plan = replay_dict.get("step_execution_plan")
    noop_step_execution = replay_dict.get("noop_step_execution")
    result_inspection = replay_dict.get("result_inspection")
    failure_handling = replay_dict.get("failure_handling")

    plan_steps = (
        [
            to_json_dict(item)
            for item in step_execution_plan.get("steps", [])
            if isinstance(item, Mapping)
        ]
        if isinstance(step_execution_plan, Mapping)
        else []
    )
    step_results = (
        [
            to_json_dict(item)
            for item in noop_step_execution.get("step_results", [])
            if isinstance(item, Mapping)
        ]
        if isinstance(noop_step_execution, Mapping)
        else []
    )
    inspected_steps = (
        [
            to_json_dict(item)
            for item in result_inspection.get("inspected_steps", [])
            if isinstance(item, Mapping)
        ]
        if isinstance(result_inspection, Mapping)
        else []
    )
    actions = (
        [
            to_json_dict(item)
            for item in failure_handling.get("actions", [])
            if isinstance(item, Mapping)
        ]
        if isinstance(failure_handling, Mapping)
        else []
    )

    result_by_step = {
        int(item.get("step_index", index)): item for index, item in enumerate(step_results)
    }
    inspection_by_step = {
        int(item.get("step_index", index)): item for index, item in enumerate(inspected_steps)
    }
    action_by_step = {
        int(item.get("source_step_index", -1)): item
        for item in actions
        if isinstance(item.get("source_step_index"), int)
    }

    contexts: list[dict[str, Any]] = []
    for index, step in enumerate(plan_steps):
        step_index = int(step.get("step_index", index))
        proposal = (
            to_json_dict(step["proposal"])
            if isinstance(step.get("proposal"), Mapping)
            else {}
        )
        result_row = result_by_step.get(step_index, {})
        inspection_row = inspection_by_step.get(step_index, {})
        action_row = action_by_step.get(step_index, {})
        failure_action = _safe_string(action_row, "action_type", "continue")

        contexts.append(
            {
                "step_index": step_index,
                "tool_name": _safe_string(step, "tool_name"),
                "proposal": proposal,
                "step": step,
                "result": result_row,
                "inspection": inspection_row,
                "action": action_row,
                "failure_action": failure_action,
                "decision": _decision_from_action(failure_action),
            }
        )

    return replay_dict, contexts


def build_manager_notes(replay_result: Mapping[str, Any]) -> dict[str, Any]:
    replay_dict, contexts = _step_contexts(replay_result)
    failure_handling = (
        to_json_dict(replay_dict["failure_handling"])
        if isinstance(replay_dict.get("failure_handling"), Mapping)
        else {}
    )

    step_notes = [
        {
            "step_index": context["step_index"],
            "tool_name": context["tool_name"],
            "step_input_summary": {
                "proposed_arguments": context["proposal"].get("arguments", {}),
                "expected_mode": _safe_string(context["step"], "expected_mode"),
                "step_status": _safe_string(context["step"], "status"),
            },
            "step_output_summary": {
                "step_status": _safe_string(context["result"], "status"),
                "result_summary": _safe_string(context["result"], "result_summary"),
            },
            "inspection_status": _safe_string(context["inspection"], "inspection_status"),
            "failure_action": context["failure_action"],
            "decision": context["decision"],
        }
        for context in contexts
    ]

    final_status = _safe_string(failure_handling, "status", "unknown")
    summary = f"Replay-side manager notes recorded {len(step_notes)} step(s) with {final_status}."
    result = {
        "schema_version": MANAGER_NOTES_SCHEMA_VERSION,
        "route_mode": _safe_string(replay_dict, "route_mode"),
        "source_run_id": _safe_string(replay_dict, "source_run_id"),
        "summary": summary,
        "step_notes": step_notes,
        "blocked_reasons": [
            str(item)
            for item in failure_handling.get("blocked_reasons", [])
            if str(item).strip()
        ]
        if isinstance(failure_handling.get("blocked_reasons"), list)
        else [],
        "recovery_actions": [
            str(item)
            for item in failure_handling.get("recovery_actions", [])
            if str(item).strip()
        ]
        if isinstance(failure_handling.get("recovery_actions"), list)
        else [],
        "warnings": [
            str(item)
            for item in replay_dict.get("warnings", [])
            if str(item).strip()
        ]
        if isinstance(replay_dict.get("warnings"), list)
        else [],
    }
    assert_json_serializable(result)
    return result


def build_tool_call_log_rows(replay_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    replay_dict, contexts = _step_contexts(replay_result)
    rows = [
        {
            "schema_version": TOOL_CALL_LOG_ROW_SCHEMA_VERSION,
            "route_mode": _safe_string(replay_dict, "route_mode"),
            "source_run_id": _safe_string(replay_dict, "source_run_id"),
            "step_index": context["step_index"],
            "tool_name": context["tool_name"],
            "proposed_arguments": context["proposal"].get("arguments", {}),
            "execution_mode": "noop_dry_run",
            "execution_performed": False,
            "step_status": _safe_string(context["result"], "status"),
            "result_summary": _safe_string(context["result"], "result_summary"),
            "inspection_status": _safe_string(context["inspection"], "inspection_status"),
            "failure_action": context["failure_action"],
            "decision": context["decision"],
        }
        for context in contexts
    ]
    assert_json_serializable(rows)
    return rows


def write_manager_replay_artifacts(
    replay_result: Mapping[str, Any],
    out_dir: str | Path,
) -> dict[str, Any]:
    manager_notes = build_manager_notes(replay_result)
    tool_call_log_rows = build_tool_call_log_rows(replay_result)

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    manager_notes_path = root / "manager_notes.json"
    tool_call_log_path = root / "tool_call_log.jsonl"

    manager_notes_path.write_text(
        json.dumps(manager_notes, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tool_call_log_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in tool_call_log_rows
        ),
        encoding="utf-8",
    )

    result = {
        "schema_version": MANAGER_REPLAY_ARTIFACTS_SCHEMA_VERSION,
        "manager_notes_path": str(manager_notes_path),
        "tool_call_log_path": str(tool_call_log_path),
        "artifact_paths": [
            str(manager_notes_path),
            str(tool_call_log_path),
        ],
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "MANAGER_NOTES_SCHEMA_VERSION",
    "TOOL_CALL_LOG_ROW_SCHEMA_VERSION",
    "MANAGER_REPLAY_ARTIFACTS_SCHEMA_VERSION",
    "build_manager_notes",
    "build_tool_call_log_rows",
    "write_manager_replay_artifacts",
]
