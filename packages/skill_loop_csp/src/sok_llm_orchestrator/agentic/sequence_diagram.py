from __future__ import annotations

from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict


def _safe_step_count(executable_plan: Mapping[str, Any] | None) -> int:
    if not isinstance(executable_plan, Mapping):
        return 0
    steps = executable_plan.get("executable_steps")
    if not isinstance(steps, list):
        return 0
    return len([item for item in steps if isinstance(item, Mapping)])


def _tool_sequence(parse_report: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(parse_report, Mapping):
        return []
    sequence = parse_report.get("tool_sequence")
    if not isinstance(sequence, list):
        return []
    return [str(item) for item in sequence if isinstance(item, str) and item.strip()]


def _plan_source(run_plan: Mapping[str, Any] | None) -> str:
    if not isinstance(run_plan, Mapping):
        return "live_llm"
    metadata = run_plan.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get("plan_source")
        if isinstance(value, str) and value.strip():
            return value
    return "live_llm"


def build_demo_loop_mermaid_sequence(
    *,
    run_plan: Mapping[str, Any] | None,
    compile_result: Mapping[str, Any] | None,
    executable_plan: Mapping[str, Any] | None,
    execution_run: Mapping[str, Any] | None,
    tool_parse_report: Mapping[str, Any] | None = None,
) -> str:
    run_plan_dict = to_json_dict(run_plan) if isinstance(run_plan, Mapping) else None
    _ = to_json_dict(compile_result) if isinstance(compile_result, Mapping) else None
    _ = to_json_dict(execution_run) if isinstance(execution_run, Mapping) else None

    step_count = _safe_step_count(executable_plan)
    tool_sequence = _tool_sequence(tool_parse_report)
    tool_sequence_label = ", ".join(tool_sequence) if tool_sequence else "parsed tool sequence"
    plan_source = _plan_source(run_plan_dict)
    loop_label = (
        f"Each parsed executable step ({step_count} step{'s' if step_count != 1 else ''})"
        if step_count
        else "Each parsed executable step"
    )

    if plan_source == "deterministic_showcase":
        lines = [
            "```mermaid",
            "sequenceDiagram",
            "    participant User as Researcher/User",
            "    participant Showcase as Showcase Plan Builder",
            "    participant Parser as Tool Parser",
            "    participant Adapter as Executable Plan Adapter",
            "    participant Executor as Gated Executor",
            "    participant ToolAdapter as Tool Adapter",
            "    participant MCP as MCP/Tool Server",
            "    participant Reporter as Report Writer",
            "    Note over User,Reporter: No old hardcoded pipeline control loop is used. Parsed executable_plan drives execution.",
            "    User->>Showcase: richer CSP goal",
            "    Showcase->>Parser: deterministic RunPlan with six tool_hint lines",
            f"    Note over Parser: Parsed tools: {tool_sequence_label}",
            "    Parser->>Adapter: build executable_plan",
            "    Adapter->>Executor: explicit execution gate",
            f"    loop {loop_label}",
            "        Executor->>ToolAdapter: call parsed tool step",
            "        ToolAdapter->>MCP: actual tool call",
            "        alt tool succeeds",
            "            MCP-->>ToolAdapter: tool output/artifact refs",
            "            ToolAdapter-->>Executor: normalized result",
            "        else tool blocked/fails",
            "            MCP-->>ToolAdapter: blocked or failed result",
            "            ToolAdapter-->>Executor: normalized blocked/failed result",
            "        end",
            "    end",
            "    Executor->>Reporter: execution_run + step_log",
            "    Reporter->>User: Markdown report + artifact bundle",
            "```",
        ]
    else:
        lines = [
            "```mermaid",
            "sequenceDiagram",
            "    participant User as Researcher/User",
            "    participant Planner as LLM Planner",
            "    participant Runtime as Prompt/Schema Runtime",
            "    participant Parser as Tool Parser",
            "    participant Adapter as Executable Plan Adapter",
            "    participant Executor as Gated Executor",
            "    participant ToolAdapter as Tool Adapter",
            "    participant MCP as MCP/Tool Server",
            "    participant Reporter as Report Writer",
            "    Note over User,Reporter: No old hardcoded pipeline control loop is used. Parsed executable_plan drives execution.",
            "    User->>Planner: scientific goal",
            "    Planner->>Runtime: JSON RunPlan",
            "    Runtime->>Parser: extract tool_hint lines",
            f"    Note over Parser: Parsed tools: {tool_sequence_label}",
            "    Parser->>Adapter: build executable_plan",
            "    Adapter->>Executor: explicit execution gate",
            f"    loop {loop_label}",
            "        Executor->>ToolAdapter: call parsed tool step",
            "        ToolAdapter->>MCP: actual tool call",
            "        alt tool succeeds",
            "            MCP-->>ToolAdapter: tool output/artifact refs",
            "            ToolAdapter-->>Executor: normalized result",
            "        else tool blocked/fails",
            "            MCP-->>ToolAdapter: blocked or failed result",
            "            ToolAdapter-->>Executor: normalized blocked/failed result",
            "        end",
            "    end",
            "    Executor->>Reporter: execution_run + step_log",
            "    Reporter->>User: Markdown report + artifact bundle",
            "```",
        ]
    diagram = "\n".join(lines) + "\n"
    assert_json_serializable({"diagram": diagram})
    return diagram


__all__ = ["build_demo_loop_mermaid_sequence"]
