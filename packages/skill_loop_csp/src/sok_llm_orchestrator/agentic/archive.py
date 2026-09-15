from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .runtime import summarize_tool_validation_results
from .schemas import assert_json_serializable, to_json_dict
from .trace_render import LLM_TRACE_MARKDOWN_WRITE_SCHEMA_VERSION, render_agentic_llm_trace_markdown

ARCHIVE_WRITE_SCHEMA_VERSION = "agentic_csp.archive_write.v1"
LLM_TRACE_WRITE_SCHEMA_VERSION = "agentic_csp.llm_trace_write.v1"
AGENT_TRACE_ARCHIVE_RUN_SCHEMA_VERSION = "agentic_csp.agent_trace_archive_run.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def _markdown_summary(run_record: Mapping[str, Any]) -> str:
    agent_order = run_record.get("agent_order")
    if isinstance(agent_order, list):
        agent_order_text = ", ".join(str(value) for value in agent_order)
    else:
        agent_order_text = ""

    orchestrator_output = run_record.get("orchestrator_output")
    if isinstance(orchestrator_output, Mapping):
        decision = _safe_string(orchestrator_output, "decision")
        reason = _safe_string(orchestrator_output, "reason")
    else:
        decision = ""
        reason = ""

    tool_validation_results = run_record.get("tool_validation_results")
    tool_validation_lines: list[str] = []
    if isinstance(tool_validation_results, list) and tool_validation_results:
        for item in tool_validation_results:
            if not isinstance(item, Mapping):
                continue
            tool_name = _safe_string(item, "tool_name", "unknown.tool")
            valid = item.get("valid") is True
            if valid:
                tool_validation_lines.append(f"- {tool_name}: valid")
                continue

            errors = item.get("errors")
            if isinstance(errors, list) and errors:
                error_text = "; ".join(str(error) for error in errors)
                tool_validation_lines.append(f"- {tool_name}: invalid - {error_text}")
            else:
                tool_validation_lines.append(f"- {tool_name}: invalid")
    else:
        tool_validation_lines.append("- No tool proposals were validated.")

    tool_validation_summary = run_record.get("tool_validation_summary")
    if isinstance(tool_validation_summary, Mapping):
        proposal_count = tool_validation_summary.get("proposal_count", 0)
        valid_count = tool_validation_summary.get("valid_count", 0)
        invalid_count = tool_validation_summary.get("invalid_count", 0)
        warning_count = tool_validation_summary.get("warning_count", 0)
    else:
        derived_summary = summarize_tool_validation_results(
            tool_validation_results if isinstance(tool_validation_results, list) else []
        )
        proposal_count = derived_summary["proposal_count"]
        valid_count = derived_summary["valid_count"]
        invalid_count = derived_summary["invalid_count"]
        warning_count = derived_summary["warning_count"]

    proposal_readiness = run_record.get("proposal_readiness")
    if isinstance(proposal_readiness, Mapping):
        readiness_status = _safe_string(proposal_readiness, "status")
        readiness_reason = _safe_string(proposal_readiness, "reason")
        readiness_execute = proposal_readiness.get("can_execute_later", False)
    else:
        readiness_status = ""
        readiness_reason = ""
        readiness_execute = False

    lines = [
        "# Agentic Run Summary",
        "",
        f"- Run ID: {_safe_string(run_record, 'run_id')}",
        f"- Overall Goal: {_safe_string(run_record, 'overall_goal')}",
        f"- Run Goal: {_safe_string(run_record, 'run_goal')}",
        f"- Stage: {_safe_string(run_record, 'stage')}",
        f"- Agent Order: {agent_order_text}",
    ]
    if decision or reason:
        lines.extend(
            [
                "",
                "## Orchestrator Decision",
                "",
                f"- Decision: {decision}",
                f"- Reason: {reason}",
            ]
        )
    lines.extend(
        [
            "",
            "## Proposal Audit",
            "",
            f"- proposals: {proposal_count}",
            f"- valid: {valid_count}",
            f"- invalid: {invalid_count}",
            f"- warnings: {warning_count}",
            "",
            "## Proposal Readiness",
            "",
            f"- status: {readiness_status}",
            f"- can execute later: {str(bool(readiness_execute)).lower()}",
            f"- reason: {readiness_reason}",
            "",
            "## Tool Validation",
            "",
            *tool_validation_lines,
        ]
    )
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class AgenticArchiveWriter:
    """Write archive-ready agentic run-record artifacts as plain files only."""

    def write(
        self,
        run_record: Mapping[str, Any],
        out_dir: Path | str,
        *,
        write_markdown: bool = True,
    ) -> dict[str, Any]:
        record_dict = to_json_dict(run_record)
        assert_json_serializable(record_dict)

        root = Path(out_dir)
        root.mkdir(parents=True, exist_ok=True)

        record_json_path = root / "agentic_run_record.json"
        record_json_path.write_text(
            json.dumps(record_dict, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        summary_markdown_path: Path | None = None
        artifact_paths = [str(record_json_path)]

        if write_markdown:
            summary_markdown_path = root / "agentic_run_summary.md"
            summary_markdown_path.write_text(
                _markdown_summary(record_dict),
                encoding="utf-8",
            )
            artifact_paths.append(str(summary_markdown_path))

        result = {
            "schema_version": ARCHIVE_WRITE_SCHEMA_VERSION,
            "run_id": _safe_string(record_dict, "run_id"),
            "record_json_path": str(record_json_path),
            "summary_markdown_path": (
                str(summary_markdown_path) if summary_markdown_path is not None else None
            ),
            "artifact_paths": artifact_paths,
        }
        assert_json_serializable(result)
        return result


def write_agentic_run_record(
    run_record: Mapping[str, Any],
    out_dir: Path | str,
    write_markdown: bool = True,
) -> dict[str, Any]:
    """Write a run record to plain JSON and optional Markdown artifacts."""

    return AgenticArchiveWriter().write(
        run_record,
        out_dir,
        write_markdown=write_markdown,
    )


def write_agentic_llm_trace(
    trace: Mapping[str, Any],
    out_dir: Path | str,
    agent_name: str,
) -> dict[str, Any]:
    """Write an archive-ready LLM trace artifact as plain JSON only."""

    trace_dict = to_json_dict(trace)
    assert_json_serializable(trace_dict)

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    safe_agent_name = agent_name.strip().replace(" ", "_") or "unknown_agent"
    trace_json_path = root / f"agentic_llm_trace_{safe_agent_name}.json"
    trace_json_path.write_text(
        json.dumps(trace_dict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = {
        "schema_version": LLM_TRACE_WRITE_SCHEMA_VERSION,
        "agent_name": safe_agent_name,
        "trace_json_path": str(trace_json_path),
        "artifact_paths": [str(trace_json_path)],
    }
    assert_json_serializable(result)
    return result


def write_agentic_llm_trace_markdown(
    trace: Mapping[str, Any],
    out_dir: Path | str,
    agent_name: str,
) -> dict[str, Any]:
    """Write a human-readable archive-ready LLM trace artifact as Markdown."""

    trace_dict = to_json_dict(trace)
    assert_json_serializable(trace_dict)

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    safe_agent_name = agent_name.strip().replace(" ", "_") or "unknown_agent"
    markdown_path = root / f"agentic_llm_trace_{safe_agent_name}.md"
    markdown_path.write_text(
        render_agentic_llm_trace_markdown(trace_dict, safe_agent_name),
        encoding="utf-8",
    )

    result = {
        "schema_version": LLM_TRACE_MARKDOWN_WRITE_SCHEMA_VERSION,
        "agent_name": safe_agent_name,
        "markdown_path": str(markdown_path),
        "artifact_paths": [str(markdown_path)],
    }
    assert_json_serializable(result)
    return result


def run_agent_and_archive_trace(
    runtime: Any,
    agent_name: str,
    input_payload: Mapping[str, Any],
    expected_schema_name: str,
    out_dir: Path | str,
) -> dict[str, Any]:
    """Run one LLM-backed agent call and persist its trace as archive-ready JSON."""

    if not isinstance(input_payload, Mapping):
        msg = "input_payload must be a mapping"
        raise TypeError(msg)

    trace = runtime.run_agent(
        agent_name,
        input_payload,
        expected_schema_name,
    )
    trace_write = write_agentic_llm_trace(
        trace,
        out_dir,
        agent_name,
    )
    result = {
        "schema_version": AGENT_TRACE_ARCHIVE_RUN_SCHEMA_VERSION,
        "agent_name": agent_name,
        "parsed_output": to_json_dict(trace.get("parsed_output"))
        if isinstance(trace.get("parsed_output"), Mapping)
        else None,
        "trace_write": trace_write,
        "attempts": [
            to_json_dict(item) for item in trace.get("attempts", []) if isinstance(item, Mapping)
        ]
        if isinstance(trace.get("attempts"), list)
        else [],
        "validation_errors": [str(item) for item in trace.get("validation_errors", [])]
        if isinstance(trace.get("validation_errors"), list)
        else [],
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "ARCHIVE_WRITE_SCHEMA_VERSION",
    "LLM_TRACE_WRITE_SCHEMA_VERSION",
    "AGENT_TRACE_ARCHIVE_RUN_SCHEMA_VERSION",
    "AgenticArchiveWriter",
    "run_agent_and_archive_trace",
    "write_agentic_llm_trace_markdown",
    "write_agentic_llm_trace",
    "write_agentic_run_record",
]
