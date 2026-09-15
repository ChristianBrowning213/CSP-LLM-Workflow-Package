from __future__ import annotations

import json
from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

LLM_TRACE_MARKDOWN_WRITE_SCHEMA_VERSION = "agentic_csp.llm_trace_markdown_write.v1"
_REDACTED = "[REDACTED]"
_SECRET_KEYS = ("api_key", "authorization", "token", "secret", "password", "bearer")


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(secret_key in lowered for secret_key in _SECRET_KEYS)


def _redact_json_value(value: Any, key_hint: str | None = None) -> Any:
    if key_hint is not None and _is_secret_key(key_hint):
        return _REDACTED
    if isinstance(value, Mapping):
        return {
            str(key): _redact_json_value(item, str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(secret_key in lowered for secret_key in _SECRET_KEYS):
            return _REDACTED
    return value


def redact_trace_for_display(trace: Mapping[str, Any]) -> dict[str, Any]:
    redacted = _redact_json_value(to_json_dict(trace))
    if not isinstance(redacted, dict):
        msg = "Trace must render to a dictionary."
        raise TypeError(msg)
    assert_json_serializable(redacted)
    return redacted


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def _json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, indent=2, sort_keys=True) + "\n```"


def render_agentic_llm_trace_markdown(trace: Mapping[str, Any], agent_name: str) -> str:
    display_trace = redact_trace_for_display(trace)
    runtime_context = display_trace.get("runtime_context")
    runtime_context_mapping = runtime_context if isinstance(runtime_context, Mapping) else {}
    attempts = display_trace.get("attempts")
    attempt_count = len(attempts) if isinstance(attempts, list) else 0
    validation_errors = display_trace.get("validation_errors")
    validation_error_lines = (
        "\n".join(f"- {item}" for item in validation_errors)
        if isinstance(validation_errors, list) and validation_errors
        else "- None"
    )
    lines = [
        f"# Agentic LLM Trace: {agent_name}",
        "",
        "## Metadata",
        "",
        f"- Agent: {_safe_string(display_trace, 'agent_name', agent_name)}",
        f"- Model: {_safe_string(runtime_context_mapping, 'model', 'unknown')}",
        f"- Base URL: {_safe_string(runtime_context_mapping, 'base_url', 'unknown')}",
        f"- Attempt Count: {attempt_count}",
        "",
        "## System Prompt",
        "",
        _safe_string(display_trace, "system_prompt"),
        "",
        "## User Payload",
        "",
        _json_block(display_trace.get("user_payload", {})),
        "",
        "## Raw Model Output",
        "",
        "```text",
        str(display_trace.get("raw_output", "")),
        "```",
        "",
        "## Parsed Output",
        "",
        _json_block(display_trace.get("parsed_output")),
        "",
        "## Validation Errors",
        "",
        validation_error_lines,
        "",
        "## Attempts",
        "",
        _json_block(attempts if isinstance(attempts, list) else []),
    ]
    markdown = "\n".join(lines) + "\n"
    return markdown


__all__ = [
    "LLM_TRACE_MARKDOWN_WRITE_SCHEMA_VERSION",
    "redact_trace_for_display",
    "render_agentic_llm_trace_markdown",
]
