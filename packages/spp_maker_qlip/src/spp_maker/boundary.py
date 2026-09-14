"""MCP boundary parsing, validation, and dispatch helpers."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence


WarningObj = dict[str, Any]
CanonicalCall = dict[str, Any]
StructuredError = dict[str, Any]


@dataclass(frozen=True)
class BoundaryParseError(Exception):
    """Structured parse error for tool invocation envelopes."""

    error: StructuredError
    warnings: list[WarningObj]

    def __str__(self) -> str:
        return str(self.error.get("message", "parse error"))


def _path_join(base: str, key: str) -> str:
    if not base:
        return key
    if key.startswith("["):
        return f"{base}{key}"
    return f"{base}.{key}"


def _make_warning(
    *,
    code: str,
    message: str,
    path: str | None = None,
    dropped_keys: Sequence[str] | None = None,
) -> WarningObj:
    warning: WarningObj = {"code": str(code), "message": str(message)}
    if path is not None:
        warning["path"] = str(path)
    if dropped_keys is not None:
        warning["dropped_keys"] = list(dropped_keys)
    return warning


def _make_parse_error(*, code: str, message: str, details: list[dict[str, Any]] | None = None) -> StructuredError:
    error: StructuredError = {"type": "parse_error", "code": str(code), "message": str(message)}
    if details is not None:
        error["details"] = details
    return error


def _ensure_trace_id(trace_id: str | None = None) -> str:
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id.strip()
    return f"trace_{uuid.uuid4().hex[:16]}"


def _generate_call_id(tool_name: str, arguments: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"tool_name": tool_name, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"call_{digest}"


def filter_unknown_keys(obj: Mapping[str, Any], allowed_keys: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
    """
    Return a filtered copy and sorted dropped keys.

    Input is never mutated.
    """
    allowed = set(str(key) for key in allowed_keys)
    filtered = {key: value for key, value in obj.items() if key in allowed}
    dropped = sorted([str(key) for key in obj.keys() if key not in allowed])
    return filtered, dropped


def normalize_warnings(warnings: Sequence[Mapping[str, Any]]) -> list[WarningObj]:
    """
    Deduplicate and stable-sort warnings by (code, path, message).
    """
    canonical: list[WarningObj] = []
    for warning in warnings:
        if not isinstance(warning, Mapping):
            continue
        code = str(warning.get("code", "warning_unknown")).strip() or "warning_unknown"
        message = str(warning.get("message", "unspecified warning")).strip() or "unspecified warning"
        path_val = warning.get("path")
        path = str(path_val) if path_val is not None else ""
        normalized: WarningObj = {"code": code, "message": message}
        if path:
            normalized["path"] = path
        dropped = warning.get("dropped_keys")
        if isinstance(dropped, Sequence) and not isinstance(dropped, (str, bytes)):
            dropped_clean = sorted({str(item) for item in dropped})
            if dropped_clean:
                normalized["dropped_keys"] = dropped_clean
        canonical.append(normalized)

    dedup: dict[tuple[str, str, str], WarningObj] = {}
    for warning in canonical:
        code = str(warning["code"])
        message = str(warning["message"])
        path = str(warning.get("path", ""))
        key = (code, path, message)
        existing = dedup.get(key)
        if existing is None:
            dedup[key] = warning
            continue
        existing_dropped = set(existing.get("dropped_keys", []))
        new_dropped = set(warning.get("dropped_keys", []))
        merged = sorted(existing_dropped | new_dropped)
        if merged:
            existing["dropped_keys"] = merged

    return [
        dedup[key]
        for key in sorted(dedup.keys(), key=lambda item: (item[0], item[1], item[2]))
    ]


def _coerce_arguments(value: Any, *, path: str) -> tuple[dict[str, Any], list[WarningObj]]:
    warnings: list[WarningObj] = []

    if value is None:
        warnings.append(
            _make_warning(
                code="arguments_defaulted_empty",
                message="arguments missing; defaulted to empty object",
                path=path,
            )
        )
        return {}, warnings

    if isinstance(value, Mapping):
        return dict(value), warnings

    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise BoundaryParseError(
                error=_make_parse_error(
                    code="invalid_arguments_json",
                    message="arguments string is not valid JSON",
                    details=[{"path": path, "message": str(exc)}],
                ),
                warnings=warnings,
            ) from exc
        if not isinstance(decoded, Mapping):
            raise BoundaryParseError(
                error=_make_parse_error(
                    code="arguments_not_object",
                    message="arguments JSON must decode to an object",
                    details=[
                        {
                            "path": path,
                            "message": "decoded arguments value is not an object",
                            "received": type(decoded).__name__,
                        }
                    ],
                ),
                warnings=warnings,
            )
        warnings.append(
            _make_warning(
                code="arguments_json_decoded",
                message="arguments decoded from JSON string",
                path=path,
            )
        )
        return dict(decoded), warnings

    raise BoundaryParseError(
        error=_make_parse_error(
            code="arguments_not_object",
            message="arguments must be an object or JSON string encoding an object",
            details=[
                {
                    "path": path,
                    "message": "unsupported arguments type",
                    "received": type(value).__name__,
                }
            ],
        ),
        warnings=warnings,
    )


def _canonical_from_candidate(
    candidate: Mapping[str, Any],
    *,
    path: str,
    allowed_keys: Iterable[str],
) -> tuple[CanonicalCall, list[WarningObj]]:
    warnings: list[WarningObj] = []
    filtered, dropped = filter_unknown_keys(candidate, allowed_keys)
    if dropped:
        warnings.append(
            _make_warning(
                code="unknown_keys_filtered",
                message="unknown keys were filtered from envelope object",
                path=path,
                dropped_keys=dropped,
            )
        )

    tool_name_raw = filtered.get("tool_name", filtered.get("name"))
    if tool_name_raw is None:
        raise BoundaryParseError(
            error=_make_parse_error(
                code="missing_tool_name",
                message="tool name not found in candidate envelope",
                details=[{"path": path, "message": "expected key 'tool_name' or 'name'"}],
            ),
            warnings=warnings,
        )
    tool_name = str(tool_name_raw).strip()
    if not tool_name:
        raise BoundaryParseError(
            error=_make_parse_error(
                code="invalid_tool_name",
                message="tool name must be a non-empty string",
                details=[{"path": _path_join(path, "name"), "message": "empty tool name"}],
            ),
            warnings=warnings,
        )

    arguments_raw = filtered.get("arguments", filtered.get("input", filtered.get("parameters")))
    arguments, arg_warnings = _coerce_arguments(arguments_raw, path=_path_join(path, "arguments"))
    warnings.extend(arg_warnings)

    call_id_raw = filtered.get("call_id", filtered.get("tool_call_id", filtered.get("id")))
    if call_id_raw is None:
        call_id = _generate_call_id(tool_name, arguments)
        warnings.append(
            _make_warning(
                code="call_id_generated",
                message="call_id missing; generated deterministic fallback id",
                path=path,
            )
        )
    else:
        call_id = str(call_id_raw).strip()
        if not call_id:
            call_id = _generate_call_id(tool_name, arguments)
            warnings.append(
                _make_warning(
                    code="call_id_generated",
                    message="call_id empty; generated deterministic fallback id",
                    path=path,
                )
            )

    return {"tool_name": tool_name, "arguments": arguments, "call_id": call_id}, warnings


def _is_direct_shape(payload: Mapping[str, Any]) -> bool:
    if "tool_name" in payload:
        return True
    return "name" in payload and ("arguments" in payload or "parameters" in payload)


def _extract_candidates(payload: Any) -> list[tuple[str, Mapping[str, Any], str]]:
    candidates: list[tuple[str, Mapping[str, Any], str]] = []

    def walk(node: Any, *, path: str, depth: int) -> None:
        if depth > 6:
            return
        if isinstance(node, Mapping):
            if "function" in node and isinstance(node.get("function"), Mapping):
                func = node["function"]
                if "name" in func and ("arguments" in func or "input" in func):
                    candidates.append((_path_join(path, "function"), func, "function"))

            has_tool_name = "tool_name" in node
            has_name_with_args = "name" in node and (
                "arguments" in node or "input" in node or "parameters" in node
            )
            is_tool_use = node.get("type") == "tool_use" and "name" in node and "input" in node
            if has_tool_name or has_name_with_args or is_tool_use:
                candidates.append((path or "$", node, "generic"))

            for key in sorted(node.keys(), key=lambda k: str(k)):
                value = node[key]
                walk(value, path=_path_join(path or "$", str(key)), depth=depth + 1)
            return

        if isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, path=f"{path or '$'}[{idx}]", depth=depth + 1)

    walk(payload, path="$", depth=0)
    uniq: dict[tuple[str, str], tuple[str, Mapping[str, Any], str]] = {}
    for entry in candidates:
        path, _, kind = entry
        uniq[(path, kind)] = entry
    return [uniq[key] for key in sorted(uniq.keys(), key=lambda item: (item[0], item[1]))]


def parse_tool_invocation(payload: Any) -> tuple[CanonicalCall, list[WarningObj]]:
    """
    Parse messy envelopes into canonical tool invocation representation.
    """
    warnings: list[WarningObj] = []
    if not isinstance(payload, Mapping):
        raise BoundaryParseError(
            error=_make_parse_error(
                code="payload_not_object",
                message="tool invocation payload must be an object",
                details=[{"path": "$", "message": "expected object envelope"}],
            ),
            warnings=warnings,
        )

    payload_obj = dict(payload)

    if _is_direct_shape(payload_obj):
        allowed_top = {"tool_name", "name", "arguments", "parameters", "call_id", "tool_call_id", "id"}
        call, local_warnings = _canonical_from_candidate(
            payload_obj,
            path="$",
            allowed_keys=allowed_top,
        )
        return call, normalize_warnings(warnings + local_warnings)

    if "tool" in payload_obj and isinstance(payload_obj["tool"], Mapping):
        top_allowed = {"tool", "call_id", "tool_call_id", "id"}
        _, dropped_top = filter_unknown_keys(payload_obj, top_allowed)
        if dropped_top:
            warnings.append(
                _make_warning(
                    code="unknown_keys_filtered",
                    message="unknown top-level keys were filtered",
                    path="$",
                    dropped_keys=dropped_top,
                )
            )
        wrapper_allowed = {"tool_name", "name", "arguments", "parameters", "input", "call_id", "tool_call_id", "id"}
        wrapper_obj = dict(payload_obj["tool"])
        call, local_warnings = _canonical_from_candidate(
            wrapper_obj,
            path="$.tool",
            allowed_keys=wrapper_allowed,
        )
        top_call_id = payload_obj.get("call_id", payload_obj.get("tool_call_id", payload_obj.get("id")))
        if top_call_id is not None:
            call["call_id"] = str(top_call_id).strip() or call["call_id"]
        return call, normalize_warnings(warnings + local_warnings)

    candidates = _extract_candidates(payload_obj)
    if not candidates:
        raise BoundaryParseError(
            error=_make_parse_error(
                code="no_tool_invocation_found",
                message="no tool invocation found in envelope",
                details=[{"path": "$", "message": "searched known envelope patterns"}],
            ),
            warnings=warnings,
        )

    if len(candidates) > 1:
        warnings.append(
            _make_warning(
                code="multiple_candidates_found",
                message="multiple tool invocation candidates found; selected first deterministically",
                path="$",
            )
        )

    selected_path, selected_obj, _ = candidates[0]
    allowed = {"tool_name", "name", "arguments", "parameters", "input", "call_id", "tool_call_id", "id", "type"}
    call, local_warnings = _canonical_from_candidate(
        selected_obj,
        path=selected_path,
        allowed_keys=allowed,
    )
    return call, normalize_warnings(warnings + local_warnings)


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _type_matches(expected_type: str, value: Any) -> bool:
    t = expected_type
    if t == "object":
        return isinstance(value, Mapping)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    return False


def _detail(path: str, message: str, *, expected: str | None = None, received: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": path, "message": message}
    if expected is not None:
        payload["expected"] = expected
    if received is not None:
        payload["received"] = received
    return payload


def _validate_schema(schema: Mapping[str, Any], value: Any, *, path: str, details: list[dict[str, Any]]) -> None:
    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        type_ok = any(_type_matches(str(t), value) for t in expected_type)
        if not type_ok:
            details.append(
                _detail(
                    path,
                    "type mismatch",
                    expected=f"type in {sorted(str(t) for t in expected_type)}",
                    received=f"type={_json_type_name(value)}",
                )
            )
            return
    elif isinstance(expected_type, str):
        if not _type_matches(expected_type, value):
            details.append(
                _detail(
                    path,
                    "type mismatch",
                    expected=f"type={expected_type}",
                    received=f"type={_json_type_name(value)}",
                )
            )
            return

    if "enum" in schema and value not in schema["enum"]:
        details.append(
            _detail(
                path,
                "value not in enum",
                expected=f"enum={schema['enum']}",
                received=repr(value),
            )
        )
        return

    if "const" in schema and value != schema["const"]:
        details.append(
            _detail(
                path,
                "value does not match const",
                expected=repr(schema["const"]),
                received=repr(value),
            )
        )
        return

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in sorted(str(item) for item in required):
                if key not in value:
                    details.append(
                        _detail(
                            _path_join(path, key),
                            "required property missing",
                            expected="present",
                            received="missing",
                        )
                    )

        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if not isinstance(properties, Mapping):
            properties = {}

        for key in sorted(value.keys(), key=lambda k: str(k)):
            str_key = str(key)
            next_path = _path_join(path, str_key)
            if str_key in properties and isinstance(properties[str_key], Mapping):
                _validate_schema(properties[str_key], value[key], path=next_path, details=details)
                continue

            if additional is False:
                details.append(
                    _detail(
                        next_path,
                        "additional property not allowed",
                        expected="absent",
                        received="present",
                    )
                )
                continue
            if isinstance(additional, Mapping):
                _validate_schema(additional, value[key], path=next_path, details=details)

        min_props = schema.get("minProperties")
        if isinstance(min_props, int) and len(value) < min_props:
            details.append(
                _detail(
                    path,
                    "object has too few properties",
                    expected=f">={min_props}",
                    received=str(len(value)),
                )
            )
        max_props = schema.get("maxProperties")
        if isinstance(max_props, int) and len(value) > max_props:
            details.append(
                _detail(
                    path,
                    "object has too many properties",
                    expected=f"<={max_props}",
                    received=str(len(value)),
                )
            )
        return

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            details.append(
                _detail(
                    path,
                    "array has too few items",
                    expected=f">={min_items}",
                    received=str(len(value)),
                )
            )
        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            details.append(
                _detail(
                    path,
                    "array has too many items",
                    expected=f"<={max_items}",
                    received=str(len(value)),
                )
            )
        items = schema.get("items")
        if isinstance(items, Mapping):
            for idx, item in enumerate(value):
                _validate_schema(items, item, path=f"{path}[{idx}]", details=details)
        return

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            details.append(
                _detail(
                    path,
                    "string shorter than minLength",
                    expected=f">={min_length}",
                    received=str(len(value)),
                )
            )
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            details.append(
                _detail(
                    path,
                    "string longer than maxLength",
                    expected=f"<={max_length}",
                    received=str(len(value)),
                )
            )
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            if re.search(pattern, value) is None:
                details.append(
                    _detail(
                        path,
                        "string does not match pattern",
                        expected=f"pattern={pattern}",
                        received=repr(value),
                    )
                )
        return

    if (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and float(value) < float(minimum):
            details.append(
                _detail(
                    path,
                    "number below minimum",
                    expected=f">={minimum}",
                    received=str(value),
                )
            )
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and float(value) > float(maximum):
            details.append(
                _detail(
                    path,
                    "number above maximum",
                    expected=f"<={maximum}",
                    received=str(value),
                )
            )


def validate_arguments_against_schema(
    arguments: Mapping[str, Any],
    schema: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return deterministic validation details for a JSON-schema-like object."""
    if schema is None:
        return []
    if not isinstance(schema, Mapping):
        return [
            _detail(
                "$",
                "invalid schema object",
                expected="mapping",
                received=type(schema).__name__,
            )
        ]
    details: list[dict[str, Any]] = []
    _validate_schema(schema, dict(arguments), path="$", details=details)
    return sorted(
        details,
        key=lambda item: (
            str(item.get("path", "")),
            str(item.get("message", "")),
            str(item.get("expected", "")),
            str(item.get("received", "")),
        ),
    )


def _hints_from_details(details: Sequence[Mapping[str, Any]]) -> list[str]:
    hints: set[str] = set()
    for item in details:
        path = str(item.get("path", "$"))
        message = str(item.get("message", ""))
        expected = str(item.get("expected", ""))

        if message == "required property missing":
            hints.add(f"Add required field at {path}.")
        elif message == "type mismatch":
            hints.add(f"Field {path} must satisfy {expected}.")
        elif message == "additional property not allowed":
            hints.add(f"Remove unknown field at {path} or relax additionalProperties.")
        elif message == "value not in enum":
            hints.add(f"Field {path} must be one of the allowed enum values.")
        elif message == "number below minimum":
            hints.add(f"Increase value at {path} to meet the minimum bound.")
        elif message == "number above maximum":
            hints.add(f"Decrease value at {path} to meet the maximum bound.")
        else:
            hints.add(f"Check field {path}: {message}.")
    return sorted(hints)


def _invoke_runner(
    runner: Callable[..., Any],
    canonical_call: Mapping[str, Any],
    *,
    trace_id: str,
) -> Any:
    sig = inspect.signature(runner)
    params = sig.parameters
    if "canonical_call" in params:
        kwargs: dict[str, Any] = {"canonical_call": canonical_call}
        if "trace_id" in params:
            kwargs["trace_id"] = trace_id
        return runner(**kwargs)
    if "tool_name" in params and "arguments" in params:
        kwargs = {
            "tool_name": canonical_call["tool_name"],
            "arguments": canonical_call["arguments"],
        }
        if "call_id" in params:
            kwargs["call_id"] = canonical_call.get("call_id")
        if "trace_id" in params:
            kwargs["trace_id"] = trace_id
        return runner(**kwargs)
    if len(params) >= 2:
        return runner(canonical_call["tool_name"], canonical_call["arguments"])
    return runner(canonical_call)


def dispatch_mcp_tool_call(
    payload: Any,
    *,
    runner: Callable[..., Any],
    tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    trace_id: str | None = None,
    override_payload: Any | None = None,
) -> dict[str, Any]:
    """
    Robust MCP dispatcher entrypoint for messy tool-call envelopes.
    """
    resolved_trace_id = _ensure_trace_id(trace_id)
    warnings: list[WarningObj] = []
    active_payload = payload if override_payload is None else override_payload
    if override_payload is not None:
        warnings.append(
            _make_warning(
                code="override_payload_used",
                message="override payload was provided and used for dispatch",
                path="$",
            )
        )

    try:
        canonical_call, parse_warnings = parse_tool_invocation(active_payload)
    except BoundaryParseError as exc:
        error = dict(exc.error)
        error["trace_id"] = resolved_trace_id
        return {
            "ok": False,
            "trace_id": resolved_trace_id,
            "tool_name": None,
            "result": None,
            "error": error,
            "warnings": normalize_warnings(warnings + exc.warnings),
        }

    warnings.extend(parse_warnings)
    canonical_allowed = {"tool_name", "arguments", "call_id"}
    canonical_filtered, dropped = filter_unknown_keys(canonical_call, canonical_allowed)
    if dropped:
        warnings.append(
            _make_warning(
                code="unknown_keys_filtered",
                message="unknown keys were filtered from canonical call",
                path="$.canonical_call",
                dropped_keys=dropped,
            )
        )

    tool_name = str(canonical_filtered["tool_name"])
    arguments = dict(canonical_filtered["arguments"])
    call_id = str(canonical_filtered.get("call_id") or _generate_call_id(tool_name, arguments))
    canonical_filtered["call_id"] = call_id

    schema = None
    if tool_schemas is not None:
        schema = tool_schemas.get(tool_name)
        if schema is None:
            warnings.append(
                _make_warning(
                    code="schema_not_found",
                    message="no schema found for tool; skipping argument schema validation",
                    path=f"$.tool_schemas.{tool_name}",
                )
            )

    details = validate_arguments_against_schema(arguments, schema)
    if details:
        error = {
            "type": "validation_error",
            "tool_name": tool_name,
            "trace_id": resolved_trace_id,
            "details": details,
            "hints": _hints_from_details(details),
        }
        return {
            "ok": False,
            "trace_id": resolved_trace_id,
            "tool_name": tool_name,
            "result": None,
            "error": error,
            "warnings": normalize_warnings(warnings),
        }

    try:
        result = _invoke_runner(runner, canonical_filtered, trace_id=resolved_trace_id)
    except Exception as exc:
        error = {
            "type": "execution_error",
            "tool_name": tool_name,
            "trace_id": resolved_trace_id,
            "message": str(exc),
        }
        return {
            "ok": False,
            "trace_id": resolved_trace_id,
            "tool_name": tool_name,
            "result": None,
            "error": error,
            "warnings": normalize_warnings(warnings),
        }

    return {
        "ok": True,
        "trace_id": resolved_trace_id,
        "tool_name": tool_name,
        "result": result,
        "error": None,
        "warnings": normalize_warnings(warnings),
    }
