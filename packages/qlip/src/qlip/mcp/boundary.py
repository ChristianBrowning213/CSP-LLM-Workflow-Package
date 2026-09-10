from __future__ import annotations

import copy
import difflib
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple


Warning = Dict[str, Any]
Meta = Dict[str, Any]
Error = Dict[str, Any]

DEFAULT_MAX_BYTES = 512 * 1024
DEFAULT_MAX_DEPTH = 40
DEFAULT_MAX_KEYS_TOTAL = 25_000
DEFAULT_MAX_LIST_TOTAL = 100_000

_SOLVE_VALIDATE_TOOLS = {"qlip.validate_request", "qlip.solve"}
_WRAPPER_KEYS = {"request", "solverequest", "solve_request", "payload"}

_METADATA_KNOWN_KEYS = {
    "qlip.shapes": {"tool", "include_examples"},
    "qlip.list_constraints": {"ids", "tags_any", "include_params_schema"},
    "qlip.list_guidance": {"ids", "tags_any", "include_params_schema"},
}

_TOOL_NAME_PATHS: List[Tuple[str | int, ...]] = [
    ("tool_calls", 0, "function", "name"),
    ("tool_call", "function", "name"),
    ("function", "name"),
    ("tool",),
    ("name",),
    ("method",),
]

_ARGS_PATHS: List[Tuple[str | int, ...]] = [
    ("tool_calls", 0, "function", "arguments"),
    ("tool_call", "function", "arguments"),
    ("function", "arguments"),
    ("arguments",),
    ("params",),
    ("args",),
]

_ENVELOPE_KEYS = {
    "tool",
    "name",
    "method",
    "arguments",
    "params",
    "args",
    "function",
    "tool_call",
    "tool_calls",
}


def _warn(
    warnings: List[Warning],
    code: str,
    message: str,
    pointer: str = "/",
    meta: Dict[str, Any] | None = None,
) -> None:
    issue: Warning = {
        "code": code,
        "message": message,
        "pointer": pointer,
        "path": pointer,
    }
    if meta is not None:
        issue["meta"] = dict(meta)
    warnings.append(issue)


def _error(
    errors: List[Error],
    code: str,
    message: str,
    pointer: str = "/",
    hint: str | None = None,
    meta: Dict[str, Any] | None = None,
) -> None:
    issue: Error = {
        "code": code,
        "message": message,
        "pointer": pointer,
    }
    if hint is not None:
        issue["hint"] = hint
    if meta is not None:
        issue["meta"] = dict(meta)
    errors.append(issue)


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _escape_pointer_part(part: Any) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def _join_pointer(pointer: str, part: Any) -> str:
    escaped = _escape_pointer_part(part)
    if pointer in {"", "/"}:
        return f"/{escaped}"
    return f"{pointer}/{escaped}"


def _path_to_pointer(path: Tuple[str | int, ...]) -> str:
    if not path:
        return "/"
    return "/" + "/".join(_escape_pointer_part(part) for part in path)


def _closest_matches(value: str, options: Iterable[str], limit: int = 3) -> List[str]:
    unique = sorted({str(option) for option in options if isinstance(option, str)})
    if not value:
        return []
    return difflib.get_close_matches(value, unique, n=limit, cutoff=0.0)


def extract_trace_id(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    for key in ("trace_id", "request_id", "id"):
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)

    meta = payload.get("meta")
    if isinstance(meta, dict):
        trace_value = meta.get("trace_id")
        if isinstance(trace_value, str) and trace_value:
            return trace_value
        if isinstance(trace_value, int) and not isinstance(trace_value, bool):
            return str(trace_value)

    return None


def _get_path_value(root: Any, path: Tuple[str | int, ...]) -> Tuple[bool, Any]:
    current = root
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return False, None
            current = current[part]
            continue
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _parse_json_string_args(
    source: str,
    pointer: str,
) -> Tuple[Dict[str, Any], List[Warning], List[Error]]:
    warnings: List[Warning] = []
    errors: List[Error] = []

    try:
        decoded = json.loads(source)
    except json.JSONDecodeError:
        _error(
            errors,
            code="JSON_DECODE_FAILED",
            message="Tool arguments were a string but could not be parsed as JSON.",
            pointer=pointer,
            hint="Ensure the MCP client sends a JSON object for tool arguments; avoid quoting the entire JSON.",
        )
        return {}, warnings, errors

    _warn(
        warnings,
        code="COERCED_JSON_STRING_ARGS",
        message="Parsed tool arguments from JSON string.",
        pointer=pointer,
        meta={"original_type": "string"},
    )

    if not isinstance(decoded, dict):
        _error(
            errors,
            code="INVALID_ARGS_TYPE",
            message="Tool arguments must decode to a JSON object.",
            pointer=pointer,
            hint="Send a JSON object for tool arguments (e.g., {\"include_examples\": true}).",
            meta={"expected_type": "object", "got_type": _json_type_name(decoded)},
        )
        return {}, warnings, errors

    return copy.deepcopy(decoded), warnings, errors


def _parse_args_value(value: Any, pointer: str) -> Tuple[Dict[str, Any], List[Warning], List[Error]]:
    warnings: List[Warning] = []
    errors: List[Error] = []
    if isinstance(value, str):
        parsed, parse_warnings, parse_errors = _parse_json_string_args(value, pointer)
        warnings.extend(parse_warnings)
        errors.extend(parse_errors)
        return parsed, warnings, errors
    if isinstance(value, dict):
        return copy.deepcopy(value), warnings, errors
    _error(
        errors,
        code="INVALID_ARGS_TYPE",
        message="Tool arguments must be a JSON object.",
        pointer=pointer,
        hint="Send a JSON object for tool arguments.",
        meta={"expected_type": "object", "got_type": _json_type_name(value)},
    )
    return {}, warnings, errors


def parse_tool_invocation(
    payload: Any,
    *,
    dispatched_tool_name: str | None = None,
    allowed_tool_names: Iterable[str] | None = None,
) -> Tuple[str | None, Dict[str, Any], List[Warning], Meta, List[Error]]:
    warnings: List[Warning] = []
    errors: List[Error] = []
    meta: Meta = {"envelope_type": "raw", "ignored_keys": []}

    allowed = sorted({name for name in (allowed_tool_names or []) if isinstance(name, str)})
    chosen_tool: str | None = dispatched_tool_name if isinstance(dispatched_tool_name, str) and dispatched_tool_name else None

    if payload is None:
        args: Dict[str, Any] = {}
    elif isinstance(payload, str):
        args, parse_warnings, parse_errors = _parse_json_string_args(payload, "/")
        warnings.extend(parse_warnings)
        errors.extend(parse_errors)
        meta["envelope_type"] = "raw_json_string"
    elif not isinstance(payload, dict):
        args = {}
        _error(
            errors,
            code="INVALID_ARGS_TYPE",
            message="Tool arguments must be a JSON object.",
            pointer="/",
            hint="Send a JSON object for tool arguments.",
            meta={"expected_type": "object", "got_type": _json_type_name(payload)},
        )
        meta["envelope_type"] = "invalid"
    else:
        envelope = payload
        tool_name_candidates: List[Tuple[Tuple[str | int, ...], str]] = []
        args_candidates: List[Tuple[Tuple[str | int, ...], Any]] = []

        found_tool_calls, tool_calls_value = _get_path_value(envelope, ("tool_calls",))
        if found_tool_calls and isinstance(tool_calls_value, list) and len(tool_calls_value) > 1:
            _warn(
                warnings,
                code="MULTIPLE_TOOL_CALLS",
                message="Multiple tool calls provided; using the first element only.",
                pointer="/tool_calls",
                meta={"count": len(tool_calls_value)},
            )

        for path in _TOOL_NAME_PATHS:
            found, value = _get_path_value(envelope, path)
            if found and isinstance(value, str) and value:
                tool_name_candidates.append((path, value))

        for path in _ARGS_PATHS:
            found, value = _get_path_value(envelope, path)
            if found:
                args_candidates.append((path, value))

        if tool_name_candidates:
            chosen_path, candidate_name = tool_name_candidates[0]
            chosen_tool = candidate_name
            meta["selected_tool_source"] = _path_to_pointer(chosen_path)
            if (
                isinstance(dispatched_tool_name, str)
                and dispatched_tool_name
                and dispatched_tool_name != chosen_tool
            ):
                _warn(
                    warnings,
                    "ENVELOPE_TOOL_NAME_MISMATCH",
                    f"Envelope tool '{chosen_tool}' does not match dispatched tool '{dispatched_tool_name}'. Using envelope tool.",
                    _path_to_pointer(chosen_path),
                    meta={"dispatched_tool_name": dispatched_tool_name},
                )
        elif chosen_tool is not None:
            meta["selected_tool_source"] = "dispatched"

        if args_candidates:
            chosen_args_path, chosen_args_value = args_candidates[0]
            meta["selected_args_source"] = _path_to_pointer(chosen_args_path)
            args, parse_warnings, parse_errors = _parse_args_value(
                chosen_args_value,
                _path_to_pointer(chosen_args_path),
            )
            warnings.extend(parse_warnings)
            errors.extend(parse_errors)
            meta["envelope_type"] = "envelope"
            selected_root = str(chosen_args_path[0]) if chosen_args_path else "arguments"
            meta["ignored_keys"] = sorted(
                key
                for key in envelope.keys()
                if key != selected_root
            )
        else:
            uses_complex_envelope = any(
                key in envelope for key in {"arguments", "params", "args", "function", "tool_call", "tool_calls"}
            )
            uses_name_only_envelope = any(key in envelope for key in {"tool", "name", "method"})
            has_non_envelope_keys = any(key not in _ENVELOPE_KEYS for key in envelope.keys())
            uses_envelope = uses_complex_envelope or (
                uses_name_only_envelope
                and chosen_tool != dispatched_tool_name
                and not has_non_envelope_keys
            )
            if uses_envelope:
                args = {}
                meta["envelope_type"] = "envelope"
                meta["ignored_keys"] = sorted(envelope.keys())
                meta["selected_args_source"] = "default_empty"
            else:
                args = copy.deepcopy(envelope)
                meta["envelope_type"] = "raw"
                meta["selected_args_source"] = "raw"

    if chosen_tool is None:
        _error(
            errors,
            code="MISSING_TOOL_NAME",
            message="Tool name is missing from invocation envelope.",
            pointer="/",
            hint="Provide a tool name via tool/name/method/function.name/tool_calls[0].function.name.",
        )
        return None, args, warnings, meta, errors

    if allowed and chosen_tool not in allowed:
        _error(
            errors,
            code="UNKNOWN_TOOL_NAME",
            message=f"Unknown tool name '{chosen_tool}'.",
            pointer="/",
            hint="Use one of the registered tool names.",
            meta={
                "allowed_tools": allowed,
                "suggestions": _closest_matches(chosen_tool, allowed, limit=3),
            },
        )

    return chosen_tool, args, warnings, meta, errors


def _limit_error(
    which_limit: str,
    actual: int,
    limit: int,
    pointer: str = "/",
    hint: str = "Reduce payload size or nesting before retrying.",
) -> Error:
    return {
        "code": "PAYLOAD_LIMIT_EXCEEDED",
        "message": f"Payload exceeded limit '{which_limit}' ({actual} > {limit}).",
        "pointer": pointer,
        "hint": hint,
        "meta": {
            "which_limit": which_limit,
            "actual": actual,
            "limit": limit,
        },
    }


def _encoded_payload_bytes(payload: Any) -> int:
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return len(text.encode("utf-8"))


def _solve_payload_candidate(tool: str | None, payload: Any) -> Any:
    if tool not in _SOLVE_VALIDATE_TOOLS or not isinstance(payload, dict):
        return payload
    if len(payload) != 1:
        return payload
    key = next(iter(payload.keys()))
    value = payload.get(key)
    if key.lower() in _WRAPPER_KEYS and isinstance(value, dict):
        return value
    return payload


def apply_payload_limits(
    tool: str | None,
    payload: Any,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_keys_total: int = DEFAULT_MAX_KEYS_TOTAL,
    max_list_total: int = DEFAULT_MAX_LIST_TOTAL,
    max_string_len: int = 65_536,
    max_total_string_bytes: int = 262_144,
) -> List[Error]:
    try:
        payload_bytes = _encoded_payload_bytes(payload)
    except Exception:
        payload_bytes = len(str(payload).encode("utf-8", errors="replace"))

    if payload_bytes > max_bytes:
        return [
            _limit_error(
                which_limit="max_bytes",
                actual=payload_bytes,
                limit=max_bytes,
                hint="Reduce large string/list fields, or split the request into smaller chunks.",
            )
        ]

    keys_total = 0
    list_total = 0
    string_total_bytes = 0
    stack: List[Tuple[Any, int, str]] = [(payload, 1, "/")]

    while stack:
        current, depth, pointer = stack.pop()
        if depth > max_depth:
            return [
                _limit_error(
                    which_limit="max_depth",
                    actual=depth,
                    limit=max_depth,
                    pointer=pointer,
                    hint="Reduce nested object/list depth in tool arguments.",
                )
            ]

        if isinstance(current, dict):
            keys_total += len(current)
            if keys_total > max_keys_total:
                return [
                    _limit_error(
                        which_limit="max_keys_total",
                        actual=keys_total,
                        limit=max_keys_total,
                        pointer=pointer,
                        hint="Reduce total object keys in the payload.",
                    )
                ]
            items = list(current.items())
            for key, value in reversed(items):
                stack.append((value, depth + 1, _join_pointer(pointer, key)))
            continue

        if isinstance(current, list):
            list_total += len(current)
            if list_total > max_list_total:
                return [
                    _limit_error(
                        which_limit="max_list_total",
                        actual=list_total,
                        limit=max_list_total,
                        pointer=pointer,
                        hint="Reduce total list entries in the payload.",
                    )
                ]
            for idx in range(len(current) - 1, -1, -1):
                stack.append((current[idx], depth + 1, _join_pointer(pointer, idx)))
            continue

        if isinstance(current, str):
            string_len = len(current)
            if string_len > max_string_len:
                return [
                    _limit_error(
                        which_limit="STRING_LEN",
                        actual=string_len,
                        limit=max_string_len,
                        pointer=pointer,
                        hint="Reduce the size of individual string values (max 64KB).",
                    )
                ]

            encoded_len = len(current.encode("utf-8"))
            string_total_bytes += encoded_len
            if string_total_bytes > max_total_string_bytes:
                return [
                    _limit_error(
                        which_limit="STRING_TOTAL_BYTES",
                        actual=string_total_bytes,
                        limit=max_total_string_bytes,
                        pointer=pointer,
                        hint="Reduce aggregate string data size in the payload (max 256KB).",
                    )
                ]

    solve_payload = _solve_payload_candidate(tool, payload)
    if tool in _SOLVE_VALIDATE_TOOLS and isinstance(solve_payload, dict):
        constraints = solve_payload.get("constraints")
        if isinstance(constraints, list) and len(constraints) > 5_000:
            return [
                _limit_error(
                    which_limit="constraints_len",
                    actual=len(constraints),
                    limit=5_000,
                    pointer="/constraints",
                    hint="Reduce constraints[] entries to <= 5000.",
                )
            ]

        guidance = solve_payload.get("guidance")
        if isinstance(guidance, list) and len(guidance) > 5_000:
            return [
                _limit_error(
                    which_limit="guidance_len",
                    actual=len(guidance),
                    limit=5_000,
                    pointer="/guidance",
                    hint="Reduce guidance[] entries to <= 5000.",
                )
            ]

        explicit_fractional_sites = (
            solve_payload.get("problem", {})
            .get("design_space", {})
            .get("sites", {})
            .get("explicit_fractional_sites")
        )
        if isinstance(explicit_fractional_sites, list) and len(explicit_fractional_sites) > 50_000:
            return [
                _limit_error(
                    which_limit="explicit_fractional_sites_len",
                    actual=len(explicit_fractional_sites),
                    limit=50_000,
                    pointer="/problem/design_space/sites/explicit_fractional_sites",
                    hint="Reduce explicit_fractional_sites length to <= 50000.",
                )
            ]

    return []


def filter_unknown_keys(tool: str, args: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Warning]]:
    warnings: List[Warning] = []
    known = _METADATA_KNOWN_KEYS.get(tool)
    if known is None:
        return dict(args), warnings

    filtered: Dict[str, Any] = {}
    for key, value in args.items():
        if key in known:
            filtered[key] = value
            continue
        _warn(
            warnings,
            "UNKNOWN_ARG_DROPPED",
            f"Dropped unknown key '{key}' for metadata tool '{tool}'.",
            f"/{key}",
        )
    return filtered, warnings
