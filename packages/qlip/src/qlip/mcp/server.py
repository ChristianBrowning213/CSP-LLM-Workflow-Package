from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from jsonschema import Draft202012Validator, RefResolver
from jsonschema.exceptions import ValidationError
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool as MCPTool
try:
    from mcp.server.fastmcp.exceptions import ToolError
except Exception:  # pragma: no cover - fallback for older SDKs
    ToolError = None

from qlip.core.solve import solve as core_solve
from qlip.core.validate import validate_request
from qlip.mcp.boundary import (
    apply_payload_limits,
    extract_trace_id,
    filter_unknown_keys,
    parse_tool_invocation,
)
from qlip.mcp.normalize import normalize_tool_args
from qlip.plugins.registry import ConstraintRegistry, GuidanceRegistry
from qlip.resources import schema_path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _schema_bundle() -> Dict[str, Any]:
    return json.loads(schema_path("MCP_SCHEMA.json").read_text(encoding="utf-8"))


_SCHEMAS = _schema_bundle()


def normalize_refs(obj: Any) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "$ref" and isinstance(value, str):
                if value.startswith("$defs/"):
                    obj[key] = "#/" + value
                elif value.startswith("/$defs/"):
                    obj[key] = "#" + value
            else:
                normalize_refs(value)
    elif isinstance(obj, list):
        for item in obj:
            normalize_refs(item)


def _resolve_pointer(root: Any, pointer: str) -> Any:
    if pointer in ("", "#"):
        return root
    if pointer.startswith("#"):
        pointer = pointer[1:]
    if not pointer:
        return root
    if not pointer.startswith("/"):
        raise ValueError(f"Unsupported pointer: {pointer}")
    current = root
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def _resolve_ref(ref: str, root: Dict[str, Any], store: Dict[str, Any]) -> Dict[str, Any]:
    if ref.startswith("$defs/"):
        ref = "#/" + ref
    elif ref.startswith("/$defs/"):
        ref = "#" + ref
    if ref.startswith("#"):
        return _resolve_pointer(root, ref)
    if ref in store:
        return store[ref]
    raise KeyError(f"Unknown ref: {ref}")


def _inline_schema_refs(
    schema: Any,
    root: Dict[str, Any],
    store: Dict[str, Any],
    seen: Set[str],
) -> Any:
    if isinstance(schema, dict):
        if "$ref" in schema and isinstance(schema["$ref"], str):
            ref = schema["$ref"]
            if ref in seen:
                return {}
            resolved = _resolve_ref(ref, root, store)
            next_root = root if ref.startswith("#") else resolved
            return _inline_schema_refs(copy.deepcopy(resolved), next_root, store, seen | {ref})
        cleaned: Dict[str, Any] = {}
        for key, value in schema.items():
            if key == "$id":
                continue
            cleaned[key] = _inline_schema_refs(value, root, store, seen)
        return cleaned
    if isinstance(schema, list):
        return [_inline_schema_refs(item, root, store, seen) for item in schema]
    return schema


def _strip_schema_defs(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _strip_schema_defs(v) for k, v in schema.items() if k != "$defs" and k != "$id"}
    if isinstance(schema, list):
        return [_strip_schema_defs(item) for item in schema]
    return schema


def _collect_base_defs(schemas: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key in sorted(schemas.keys()):
        schema = schemas[key]
        if isinstance(schema, dict) and isinstance(schema.get("$defs"), dict):
            merged.update(schema["$defs"])
    return merged


_BASE_DEFS = _collect_base_defs(_SCHEMAS)
_SCHEMA_STORE = {}
for schema in _SCHEMAS.values():
    if isinstance(schema, dict) and "$id" in schema:
        normalized_schema = copy.deepcopy(schema)
        normalize_refs(normalized_schema)
        _SCHEMA_STORE[normalized_schema["$id"]] = normalized_schema


def _tool_defs_list() -> List[Dict[str, Any]]:
    tool_defs_path = schema_path("MCP_TOOL_DEFS.json")
    tool_defs = json.loads(tool_defs_path.read_text(encoding="utf-8"))
    return list(tool_defs)


_TOOL_DEFS_LIST = _tool_defs_list()
_TOOL_DEFS = {tool["name"]: tool for tool in _TOOL_DEFS_LIST}


def _tool_def(name: str) -> Dict[str, Any]:
    return _TOOL_DEFS[name]


_LMSTUDIO_ALLOWED_KEYS: Set[str] = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "default",
    "description",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
}


def _sanitize_schema_node(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    cleaned: Dict[str, Any] = {}
    for key, value in schema.items():
        if key in {"$ref", "$defs", "oneOf", "anyOf", "allOf"}:
            continue
        if key not in _LMSTUDIO_ALLOWED_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {k: _sanitize_schema_node(v) for k, v in value.items()}
        elif key == "items":
            cleaned[key] = _sanitize_schema_node(value)
        else:
            cleaned[key] = value
    return cleaned


def _sanitize_input_schema_for_lmstudio(
    tool_name: str,
    schema: Dict[str, Any] | None,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }
    if schema:
        resolved = copy.deepcopy(schema)
        normalize_refs(resolved)
        resolved = _inline_schema_refs(resolved, resolved, _SCHEMA_STORE, set())
        resolved = _strip_schema_defs(resolved)
        sanitized = _sanitize_schema_node(resolved)
        if isinstance(sanitized, dict) and isinstance(sanitized.get("properties"), dict):
            base["properties"] = sanitized["properties"]
        if isinstance(sanitized, dict) and isinstance(sanitized.get("required"), list):
            base["required"] = sanitized["required"]
    return base


def _sanitize_output_schema_for_lmstudio() -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": True}


def _build_tool_listing() -> List[MCPTool]:
    tools: List[MCPTool] = []
    for tool in _TOOL_DEFS_LIST:
        input_schema = _sanitize_input_schema_for_lmstudio(
            tool["name"], tool.get("inputSchema")
        )
        output_schema = _sanitize_output_schema_for_lmstudio()
        tools.append(
            MCPTool(
                name=tool["name"],
                title=tool.get("title"),
                description=tool.get("description", ""),
                inputSchema=input_schema,
                outputSchema=output_schema,
            )
        )
    return tools


_RE_REQUIRED = re.compile(r"'(?P<field>[^']+)' is a required property")
_RE_ADDITIONAL_PROP = re.compile(r"\('(?P<field>[^']+)' was unexpected\)")
_RE_UNKNOWN_CONSTRAINT = re.compile(r"Unknown constraint id '([^']+)'")
_RE_UNKNOWN_GUIDANCE = re.compile(r"Unknown guidance id '([^']+)'")


def _escape_pointer_part(part: Any) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def _pointer_from_parts(parts: List[Any]) -> str:
    if not parts:
        return "/"
    return "/" + "/".join(_escape_pointer_part(part) for part in parts)


def _extract_missing_property(message: str) -> Optional[str]:
    match = _RE_REQUIRED.search(message)
    if match:
        return match.group("field")
    return None


def _extract_additional_property(message: str) -> Optional[str]:
    match = _RE_ADDITIONAL_PROP.search(message)
    if match:
        return match.group("field")
    return None


def _closest_matches(value: str, options: List[str], limit: int = 3) -> List[str]:
    if not value:
        return []
    universe = sorted({item for item in options if isinstance(item, str)})
    return difflib.get_close_matches(value, universe, n=limit, cutoff=0.0)


def _targeted_schema_hint(
    err: ValidationError,
    pointer: str,
    expected_type: Optional[str],
    got_type: Optional[str],
) -> Optional[str]:
    if pointer == "/constraints" and expected_type == "array" and got_type == "object":
        return "constraints must be an array of objects, e.g. [] or [{\"id\":\"...\",\"params\":{}}]."
    if pointer == "/guidance" and expected_type == "array" and got_type == "object":
        return "guidance must be an array of objects, e.g. [] or [{\"id\":\"...\",\"params\":{}}]."
    if pointer == "/problem/design_space/sites/mode" and err.validator == "required":
        return "Set /problem/design_space/sites/mode to either 'uniform_grid' or 'explicit_fractional_sites'."
    if pointer == "/problem/design_space/sites/uniform_grid" and err.validator == "required":
        return "When mode is 'uniform_grid', provide /problem/design_space/sites/uniform_grid with density."
    if pointer == "/problem/design_space/sites/uniform_grid/density":
        return "When mode is 'uniform_grid', provide an integer density >= 1 at /problem/design_space/sites/uniform_grid/density."
    if pointer.startswith("/problem/design_space/sites/explicit_fractional_sites/"):
        return "Each explicit_fractional_sites entry must be a 3-element numeric array [x, y, z]."
    if pointer == "/solver/name":
        return "Set solver.name to 'gurobi'."
    return None


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


def _join_pointer(pointer: str, part: str) -> str:
    escaped = _escape_pointer_part(part)
    if pointer in {"", "/"}:
        return f"/{escaped}"
    return f"{pointer}/{escaped}"


def _validation_error_to_structured(err: ValidationError) -> Dict[str, Any]:
    missing = _extract_missing_property(err.message) if err.validator == "required" else None
    pointer = _pointer_from_parts(list(err.path))
    message = err.message
    expected_type: Optional[str] = None
    got_type: Optional[str] = None
    hint: Optional[str] = None

    if missing:
        pointer = _join_pointer(pointer, missing)
        message = f"missing required property '{missing}'"

    if err.validator == "additionalProperties":
        unexpected = _extract_additional_property(err.message)
        if unexpected:
            pointer = _join_pointer(pointer, unexpected)
            hint = f"Remove unknown key '{unexpected}'."

    if err.validator == "type":
        validator_value = err.validator_value
        if isinstance(validator_value, list):
            expected_type = "|".join(sorted(str(v) for v in validator_value))
        else:
            expected_type = str(validator_value)
        got_type = _json_type_name(err.instance)
        if expected_type == "boolean" and got_type == "string":
            if isinstance(err.instance, str) and err.instance.strip().lower() in {"true", "false"}:
                hint = "Send a JSON boolean true/false, not a string."
        if expected_type == "array" and got_type == "object":
            hint = 'Omit the field or send an array (e.g., [] or ["..."]).'

    targeted_hint = _targeted_schema_hint(err, pointer, expected_type, got_type)
    if targeted_hint is not None:
        hint = targeted_hint

    issue: Dict[str, Any] = {
        "code": "SCHEMA_VALIDATION_ERROR",
        "pointer": pointer,
        "message": message,
    }
    meta: Dict[str, Any] = {}
    if expected_type is not None:
        issue["expected_type"] = expected_type
        meta["expected_type"] = expected_type
    if got_type is not None:
        issue["got_type"] = got_type
        meta["got_type"] = got_type
    if hint is not None:
        issue["hint"] = hint
    if meta:
        issue["meta"] = meta
    return issue


def _collect_jsonschema_errors(
    schema: Dict[str, Any],
    data: Any,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    resolver = RefResolver.from_schema(schema, store=_SCHEMA_STORE)
    validator = Draft202012Validator(schema, resolver=resolver)
    issues = [_validation_error_to_structured(err) for err in validator.iter_errors(data)]
    issues.sort(
        key=lambda issue: (
            issue.get("pointer", "/"),
            issue.get("code", ""),
            issue.get("message", ""),
        )
    )
    if limit is not None:
        return issues[:limit]
    return issues


def format_jsonschema_errors(schema: Dict[str, Any], data: Dict[str, Any], limit: int = 5) -> str:
    issues = _collect_jsonschema_errors(schema, data, limit=limit)
    if not issues:
        return ""
    return "\n".join(f"{issue.get('pointer', '/')}: {issue.get('message', '')}" for issue in issues)


def _log_validation_error(message: str) -> None:
    if os.environ.get("QLIP_DEBUG_MCP") == "1":
        print(message, file=sys.stderr, flush=True)


def _raise_tool_error(message: str) -> None:
    if ToolError is not None:
        raise ToolError(message)
    raise ValueError(message)


def _validate_schema(tool_name: str, schema: Dict[str, Any], payload: Dict[str, Any], schema_label: str) -> None:
    issues = _collect_jsonschema_errors(schema, payload, limit=5)
    if not issues:
        return
    formatted = "\n".join(f"{issue['pointer']}: {issue['message']}" for issue in issues)
    if schema_label == "input":
        message = f"Invalid request parameters for {tool_name}:\n{formatted}"
    else:
        message = f"Invalid {schema_label} parameters for {tool_name}:\n{formatted}"
    _log_validation_error(message)
    _raise_tool_error(message)


def _tool_schema_for_validation(tool_name: str, schema_key: str) -> Dict[str, Any]:
    tool = _TOOL_DEFS[tool_name]
    combined = copy.deepcopy(tool[schema_key])
    normalize_refs(combined)
    base_defs = _SCHEMAS.get("$defs")
    if not isinstance(base_defs, dict):
        base_defs = _BASE_DEFS
    if not isinstance(combined.get("$defs"), dict):
        combined["$defs"] = dict(base_defs)
    else:
        merged_defs = dict(base_defs)
        merged_defs.update(combined["$defs"])
        combined["$defs"] = merged_defs
    return combined


def _self_contained_tool_schema(tool_name: str, schema_key: str) -> Dict[str, Any]:
    combined = _tool_schema_for_validation(tool_name, schema_key)
    combined = _inline_schema_refs(combined, combined, _SCHEMA_STORE, set())
    combined = _strip_schema_defs(combined)
    return combined


def _validate_tool_input(tool_name: str, payload: Dict[str, Any]) -> None:
    schema = _tool_schema_for_validation(tool_name, "inputSchema")
    _validate_schema(tool_name, schema, payload, "input")


def _validate_tool_input_errors(tool_name: str, payload: Any) -> List[Dict[str, Any]]:
    schema = _tool_schema_for_validation(tool_name, "inputSchema")
    return _collect_jsonschema_errors(schema, payload, limit=None)


def _validate_tool_output(tool_name: str, payload: Dict[str, Any]) -> None:
    schema = _tool_schema_for_validation(tool_name, "outputSchema")
    _validate_schema(tool_name, schema, payload, "output")


def _validate_tool_output_errors(tool_name: str, payload: Any) -> List[Dict[str, Any]]:
    schema = _tool_schema_for_validation(tool_name, "outputSchema")
    return _collect_jsonschema_errors(schema, payload, limit=None)


def _emit_normalization_warnings(tool_name: str, warnings: List[Dict[str, Any]]) -> None:
    for warning in warnings:
        code = warning.get("code", "NORMALIZED")
        path = warning.get("path", "/")
        message = warning.get("message", "")
        print(f"[mcp-normalize] {tool_name} {code} {path}: {message}", file=sys.stderr, flush=True)


def _schema_required_note(schema: Dict[str, Any]) -> Optional[str]:
    required = schema.get("required")
    if isinstance(required, list) and required:
        return "Required top-level fields: " + ", ".join(str(field) for field in required)
    return None


def _schema_additional_properties_note(schema: Dict[str, Any]) -> Optional[str]:
    if schema.get("additionalProperties") is False:
        return "additionalProperties=false: unknown fields are rejected."
    return None


def _append_normalization_warnings(output: Dict[str, Any], warnings: List[Dict[str, Any]]) -> None:
    if not warnings:
        return
    output.setdefault("warnings", [])
    output["warnings"].extend(_normalize_warning_records(warnings))


def _normalize_warning_records(warnings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for warning in warnings:
        pointer = warning.get("pointer", warning.get("path", "/"))
        code = warning.get("code", "mcp_normalize")
        default_severity = "INFO" if str(code).startswith("COERCED") else "WARN"
        severity = warning.get("severity", default_severity)
        if severity not in {"INFO", "WARN"}:
            severity = "WARN"
        item: Dict[str, Any] = {
            "code": code,
            "message": warning.get("message", ""),
            "pointer": pointer,
            "path": pointer,
            "severity": severity,
        }
        if isinstance(warning.get("meta"), dict):
            item["meta"] = dict(warning.get("meta"))
        before = warning.get("before")
        after = warning.get("after")
        if before is not None or after is not None:
            details = {"before": before, "after": after}
            item["details"] = details
            item.setdefault("meta", {})
            item["meta"].update(details)
        normalized.append(item)
    return normalized


def _run_tool_with_details(
    tool_name: str,
    args: Any,
    impl,
    validate_input: bool = True,
) -> tuple[Dict[str, Any], Any, List[Dict[str, Any]]]:
    normalized, warnings = normalize_tool_args(tool_name, args)
    if warnings:
        _emit_normalization_warnings(tool_name, warnings)
    if validate_input:
        _validate_tool_input(tool_name, normalized)
    elif not isinstance(normalized, dict):
        _validate_tool_input(tool_name, normalized)
    output = impl(normalized)
    _validate_tool_output(tool_name, output)
    return output, normalized, warnings


def _run_tool(
    tool_name: str,
    args: Any,
    impl,
    include_output_warnings: bool = False,
    validate_input: bool = True,
) -> Dict[str, Any]:
    output, _, warnings = _run_tool_with_details(
        tool_name,
        args,
        impl,
        validate_input=validate_input,
    )
    if include_output_warnings and warnings:
        _append_normalization_warnings(output, warnings)
        _validate_tool_output(tool_name, output)
    return output


_METADATA_TOOLS = {"qlip.shapes", "qlip.list_constraints", "qlip.list_guidance"}
_DEBUG_TOOL_NAME = "qlip.debug_boundary_parse"

_ERROR_CATEGORY_MAP: Dict[str, tuple[str, bool]] = {
    "MISSING_TOOL_NAME": ("FORMAT", True),
    "UNKNOWN_TOOL_NAME": ("FORMAT", True),
    "UNKNOWN_TOOL": ("FORMAT", True),
    "JSON_DECODE_FAILED": ("FORMAT", True),
    "INVALID_ARGS_TYPE": ("FORMAT", True),
    "PAYLOAD_LIMIT_EXCEEDED": ("LIMIT", True),
    "SCHEMA_VALIDATION_ERROR": ("SCHEMA", True),
    "UNKNOWN_PLUGIN_ID": ("PLUGIN", True),
    "unknown_constraint_id": ("PLUGIN", True),
    "unknown_guidance_id": ("PLUGIN", True),
    "invalid_constraint_params": ("PLUGIN", True),
    "invalid_guidance_params": ("PLUGIN", True),
    "pot_root_missing": ("SCHEMA", True),
    "pot_root_outside_allowed_roots": ("SCHEMA", True),
    "pot_root_no_pot_files": ("SCHEMA", True),
    "pot_pair_missing": ("SCHEMA", True),
    "radii_data_missing": ("SCHEMA", True),
    "oxidation_state_missing": ("SCHEMA", True),
    "neighbor_graph_missing": ("SCHEMA", True),
    "lattice_template_missing": ("SCHEMA", True),
    "motif_root_missing": ("SCHEMA", True),
    "motif_artifacts_missing": ("SCHEMA", True),
    "motif_dir_missing": ("SCHEMA", True),
    "property_table_missing": ("SCHEMA", True),
    "beta_table_missing": ("SCHEMA", True),
    "unsupported_element_data": ("SCHEMA", True),
    "solve_data_preflight_failed": ("SCHEMA", True),
    "artifact_path_missing": ("SCHEMA", True),
    "path_outside_allowed_roots": ("SCHEMA", True),
    "path_invalid": ("SCHEMA", True),
    "TOOL_EXECUTION_ERROR": ("RUNTIME", False),
}


def _extract_context_run_id(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    context = payload.get("context")
    if not isinstance(context, dict):
        return None
    run_id = context.get("run_id")
    if isinstance(run_id, str) and run_id:
        return run_id
    return None


def _canonical_payload_sha256(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _safe_payload_sha256(payload: Any) -> str:
    try:
        return _canonical_payload_sha256(payload)
    except Exception:
        return hashlib.sha256(str(payload).encode("utf-8", errors="replace")).hexdigest()


def _merge_response_warnings(
    boundary_warnings: List[Dict[str, Any]],
    payload_warnings: Any,
) -> List[Dict[str, Any]]:
    merged = list(boundary_warnings)
    if isinstance(payload_warnings, list):
        merged.extend(_normalize_warning_records([warning for warning in payload_warnings if isinstance(warning, dict)]))
    return merged


def _warnings_count_by_code(warnings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for warning in warnings:
        code = str(warning.get("code", ""))
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1
    return counts


def _classify_error(code: str) -> tuple[str, bool]:
    category, retryable = _ERROR_CATEGORY_MAP.get(code, ("RUNTIME", False))
    return category, retryable


def _enrich_error_metadata(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for issue in errors:
        item = dict(issue)
        code = str(item.get("code", ""))
        category, retryable = _classify_error(code)
        meta = dict(item.get("meta") or {})
        meta.setdefault("category", category)
        meta.setdefault("retryable", retryable)
        item["meta"] = meta
        enriched.append(item)
    return enriched


def _order_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered_errors = sorted(
        list(errors),
        key=lambda issue: (
            issue.get("pointer", ""),
            issue.get("code", ""),
            issue.get("message", ""),
        ),
    )
    return ordered_errors


def _maybe_dump_error_response(response: Dict[str, Any]) -> None:
    if os.environ.get("QLIP_MCP_DUMP_ERRORS") != "1":
        return
    try:
        dump_path = os.environ.get("QLIP_MCP_DUMP_ERRORS_PATH")
        if not dump_path:
            dump_path = str(_repo_root() / "qlip_mcp_error_dump.jsonl")
        path = Path(dump_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "trace_id": response.get("trace_id"),
            "tool": response.get("tool"),
            "ok": response.get("ok"),
            "primary_error": response.get("primary_error"),
            "errors_count": len(response.get("errors", [])) if isinstance(response.get("errors"), list) else 0,
            "warnings_count": len(response.get("warnings", [])) if isinstance(response.get("warnings"), list) else 0,
            "payload_sha256": (response.get("meta") or {}).get("payload_sha256"),
            "category": (response.get("meta") or {}).get("category"),
            "retryable": (response.get("meta") or {}).get("retryable"),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except Exception:
        pass


def _build_dispatch_envelope(
    *,
    ok: bool,
    tool_name: str,
    trace_id: str,
    result: Any,
    warnings: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    payload_sha256: str,
    duration_ms: int,
    run_id: Optional[str],
) -> Dict[str, Any]:
    enriched_errors = _enrich_error_metadata(errors)
    ordered_errors = _order_errors(enriched_errors)
    normalized_warnings = _normalize_warning_records(warnings)
    if ordered_errors:
        primary_meta = ordered_errors[0].get("meta", {})
        category = primary_meta.get("category", "RUNTIME")
        retryable = bool(primary_meta.get("retryable", False))
    else:
        category = "RUNTIME"
        retryable = False
    meta: Dict[str, Any] = {
        "trace_id": trace_id,
        "payload_sha256": payload_sha256,
        "duration_ms": int(duration_ms),
        "warnings_count_by_code": _warnings_count_by_code(normalized_warnings),
        "category": category,
        "retryable": retryable,
    }
    if run_id:
        meta["run_id"] = run_id

    response: Dict[str, Any] = {
        "ok": bool(ok),
        "tool": tool_name,
        "trace_id": trace_id,
        "result": result if ok else None,
        "errors": ordered_errors,
        "warnings": normalized_warnings,
        "meta": meta,
    }
    if ordered_errors:
        response["primary_error"] = ordered_errors[0]
        _maybe_dump_error_response(response)
    return response


def _build_dispatch_response(
    *,
    tool_name: str,
    output: Dict[str, Any],
    trace_id: str,
    warnings: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    payload_sha256: str,
    duration_ms: int,
    run_id: Optional[str],
) -> Dict[str, Any]:
    merged_warnings = _merge_response_warnings(warnings, output.get("warnings"))
    return _build_dispatch_envelope(
        ok=len(errors) == 0,
        tool_name=tool_name,
        trace_id=trace_id,
        result=output,
        errors=errors,
        warnings=merged_warnings,
        payload_sha256=payload_sha256,
        duration_ms=duration_ms,
        run_id=run_id,
    )


def _build_dispatch_error(
    *,
    tool_name: str,
    trace_id: str,
    warnings: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    payload_sha256: str,
    duration_ms: int,
    run_id: Optional[str],
) -> Dict[str, Any]:
    return _build_dispatch_envelope(
        ok=False,
        tool_name=tool_name,
        trace_id=trace_id,
        result=None,
        errors=errors,
        warnings=warnings,
        payload_sha256=payload_sha256,
        duration_ms=duration_ms,
        run_id=run_id,
    )


def _extract_unknown_plugin(error: Dict[str, Any]) -> tuple[str, str] | None:
    code = str(error.get("code", ""))
    message = str(error.get("message", ""))

    if code == "unknown_constraint_id":
        match = _RE_UNKNOWN_CONSTRAINT.search(message)
        if match:
            return "constraints", match.group(1)
    if code == "unknown_guidance_id":
        match = _RE_UNKNOWN_GUIDANCE.search(message)
        if match:
            return "guidance", match.group(1)

    if code == "UNKNOWN_PLUGIN_ID":
        details = error.get("details")
        if isinstance(details, dict):
            registry = details.get("registry")
            plugin_id = details.get("plugin_id")
            if isinstance(registry, str) and isinstance(plugin_id, str):
                return registry, plugin_id

    return None


def _plugin_suggestions(registry: str, plugin_id: str) -> List[str]:
    if registry == "constraints":
        ids = [entry.id for entry in ConstraintRegistry.list(include_params_schema=False)]
    elif registry == "guidance":
        ids = [entry.id for entry in GuidanceRegistry.list(include_params_schema=False)]
    else:
        return []
    return _closest_matches(plugin_id, ids, limit=3)


def _registry_ids(registry: str) -> List[str]:
    if registry == "constraints":
        return sorted(entry.id for entry in ConstraintRegistry.list(include_params_schema=False))
    if registry == "guidance":
        return sorted(entry.id for entry in GuidanceRegistry.list(include_params_schema=False))
    return []


def _registry_version_hash(ids: List[str]) -> str:
    joined = "\n".join(ids)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _unknown_plugin_envelope_error(registry: str, plugin_id: str) -> Dict[str, Any]:
    ids = _registry_ids(registry)
    return {
        "code": "UNKNOWN_PLUGIN_ID",
        "pointer": "/",
        "message": f"Unknown {registry} plugin id '{plugin_id}'.",
        "hint": f"Call qlip.list_{registry} to discover valid ids.",
        "meta": {
            "registry": registry,
            "plugin_id": plugin_id,
            "suggestions": _closest_matches(plugin_id, ids, limit=3),
            "registry_version": _registry_version_hash(ids),
            "allowed_count": len(ids),
            "sample_allowed": ids[:25],
        },
    }


def _collect_unknown_plugin_errors(tool_name: str, output: Dict[str, Any]) -> List[Dict[str, Any]]:
    source_errors: List[Dict[str, Any]] = []
    if tool_name == "qlip.validate_request":
        errors = output.get("errors")
        if isinstance(errors, list):
            source_errors.extend(item for item in errors if isinstance(item, dict))
    elif tool_name == "qlip.solve":
        result = output.get("result")
        if isinstance(result, dict):
            errors = result.get("errors")
            if isinstance(errors, list):
                source_errors.extend(item for item in errors if isinstance(item, dict))

    diagnostics: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for error in source_errors:
        parsed = _extract_unknown_plugin(error)
        if parsed is None:
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        registry, plugin_id = parsed
        diagnostics.append(_unknown_plugin_envelope_error(registry, plugin_id))
    return diagnostics


def _build_tool_notes(tool_name: str, args_schema: Dict[str, Any], include_placeholders: bool) -> List[str]:
    notes: List[str] = []
    extra_note = _schema_additional_properties_note(args_schema)
    if extra_note:
        notes.append(extra_note)
    required_note = _schema_required_note(args_schema)
    if required_note:
        notes.append(required_note)
    if tool_name in {"qlip.list_constraints", "qlip.list_guidance"}:
        notes.append("Pass {} or omit fields; do not send ids:{} or tags_any:{} (must be arrays if present).")
        notes.append(
            "LM Studio Form mode may inject ids/tags_any as {}; the server tolerates this. Prefer omitting ids/tags_any unless arrays."
        )
        notes.append("include_params_schema must be boolean; string values like \"true\"/\"false\" are tolerated but discouraged.")
    if tool_name == "qlip.shapes":
        notes.append("include_examples accepts boolean; string values like \"true\"/\"false\" or \"1\"/\"0\" are tolerated but discouraged.")
    if tool_name in {"qlip.validate_request", "qlip.solve"}:
        notes.append(
            "Preferred call shape is top-level SolveRequest; the server unwraps {request:...}, {SolveRequest:...}, {solve_request:...}, or {payload:...} when they are the only key."
        )
        notes.append(
            "Stringified scalars are coerced only for a small allowlist (solver limits, lattice dims, uniform_grid settings, artifacts flags, runtime limits). Plugin params are not coerced."
        )
    if include_placeholders:
        notes.append("If plugin IDs are unknown, call qlip.list_constraints and qlip.list_guidance first.")
    return notes


def _boundary_envelope_patterns() -> List[str]:
    return [
        "raw args object",
        "{\"arguments\": {...}}",
        "{\"params\": {...}}",
        "{\"function\":{\"name\":\"<tool>\",\"arguments\": {...}}}",
        "{\"tool_calls\":[{\"function\":{\"name\":\"<tool>\",\"arguments\": {...}}]}",
    ]


def _is_strict_schema(tool_name: str) -> bool:
    schema = _TOOL_DEFS[tool_name].get("inputSchema", {})
    if isinstance(schema, dict):
        if schema.get("additionalProperties") is False:
            return True
        if "$ref" in schema:
            return True
    return False


def _canonical_args_example(tool_name: str) -> Dict[str, Any]:
    if tool_name == "qlip.shapes":
        return {"include_examples": False}
    if tool_name in {"qlip.list_constraints", "qlip.list_guidance"}:
        return {"include_params_schema": True}
    if tool_name in {"qlip.validate_request", "qlip.solve"}:
        example, _ = _minimal_solve_request_example()
        return example
    if tool_name == _DEBUG_TOOL_NAME:
        return {"payload": {"arguments": {"include_examples": True}}}
    return {}


def _boundary_unknown_arg_policy(tool_name: str) -> str:
    if tool_name in _METADATA_TOOLS:
        return "drop_with_warning"
    return "error"


def _minimal_solve_request_example() -> tuple[Dict[str, Any], bool]:
    constraint_ids = {entry.id for entry in ConstraintRegistry.list(include_params_schema=False)}
    guidance_ids = {entry.id for entry in GuidanceRegistry.list(include_params_schema=False)}
    has_constraint = "proximity.atomic_radii" in constraint_ids
    has_guidance = "objective.energy_spp" in guidance_ids

    constraints: List[Dict[str, Any]] = []
    guidance: List[Dict[str, Any]] = []
    if has_constraint:
        constraints.append(
            {
                "id": "proximity.atomic_radii",
                "params": {"scale": 1.0, "allow_self_overlap": False},
            }
        )
    else:
        constraints.append({"id": "constraint.id", "params": {}})
    if has_guidance:
        guidance.append({"id": "objective.energy_spp", "params": {}})
    else:
        guidance.append({"id": "guidance.id", "params": {}})

    example = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "SrTiO3"},
            "design_space": {
                "template": {
                    "lattice": {
                        "a": 3.9,
                        "b": 3.9,
                        "c": 3.9,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                        "units": "angstrom",
                    }
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}},
            },
        },
        "constraints": constraints,
        "guidance": guidance,
        "solver": {"name": "gurobi"},
        "context": {"pot_root": "/path/to/your/pot/library"},
    }
    placeholders_needed = not (has_constraint and has_guidance)
    return example, placeholders_needed

_LIST_CONSTRAINTS_DEF = _tool_def("qlip.list_constraints")
_LIST_GUIDANCE_DEF = _tool_def("qlip.list_guidance")
_SHAPES_DEF = _tool_def("qlip.shapes")
_VALIDATE_REQUEST_DEF = _tool_def("qlip.validate_request")
_SOLVE_DEF = _tool_def("qlip.solve")

mcp = FastMCP("qlip")


def _list_constraints_impl(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = [
        entry.to_dict()
        for entry in ConstraintRegistry.list(
            ids=payload.get("ids"),
            tags_any=payload.get("tags_any"),
            include_params_schema=payload.get("include_params_schema", True),
        )
    ]
    return {"items": items}


def _list_guidance_impl(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = [
        entry.to_dict()
        for entry in GuidanceRegistry.list(
            ids=payload.get("ids"),
            tags_any=payload.get("tags_any"),
            include_params_schema=payload.get("include_params_schema", True),
        )
    ]
    return {"items": items}


@mcp.tool(
    name=_LIST_CONSTRAINTS_DEF["name"],
    title=_LIST_CONSTRAINTS_DEF.get("title"),
    description=_LIST_CONSTRAINTS_DEF.get("description"),
)
def list_constraints(
    ids: Optional[List[str]] = None,
    tags_any: Optional[List[str]] = None,
    include_params_schema: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"include_params_schema": include_params_schema}
    if ids is not None:
        payload["ids"] = ids
    if tags_any is not None:
        payload["tags_any"] = tags_any
    return _run_tool("qlip.list_constraints", payload, _list_constraints_impl)


@mcp.tool(
    name=_LIST_GUIDANCE_DEF["name"],
    title=_LIST_GUIDANCE_DEF.get("title"),
    description=_LIST_GUIDANCE_DEF.get("description"),
)
def list_guidance(
    ids: Optional[List[str]] = None,
    tags_any: Optional[List[str]] = None,
    include_params_schema: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"include_params_schema": include_params_schema}
    if ids is not None:
        payload["ids"] = ids
    if tags_any is not None:
        payload["tags_any"] = tags_any
    return _run_tool("qlip.list_guidance", payload, _list_guidance_impl)


@mcp.tool(
    name=_SHAPES_DEF["name"],
    title=_SHAPES_DEF.get("title"),
    description=_SHAPES_DEF.get("description"),
)
def shapes(
    tool: Optional[str] = None,
    include_examples: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if tool is not None:
        payload["tool"] = tool
    if include_examples is not None:
        payload["include_examples"] = include_examples
    return _run_tool("qlip.shapes", payload, _shapes_impl)


def _shapes_impl(payload: Dict[str, Any]) -> Dict[str, Any]:
    tool = payload.get("tool")
    include_examples = bool(payload.get("include_examples", False))
    if tool is not None and tool not in _TOOL_DEFS:
        _raise_tool_error(f"Unknown tool: {tool}")

    tools: List[Dict[str, Any]] = []
    for tool_def in _TOOL_DEFS_LIST:
        if tool is not None and tool_def["name"] != tool:
            continue
        name = tool_def["name"]
        args_schema = _self_contained_tool_schema(name, "inputSchema")

        example_args: Optional[Dict[str, Any]] = None
        placeholders_needed = False
        if include_examples:
            if name in {"qlip.validate_request", "qlip.solve"}:
                example_args, placeholders_needed = _minimal_solve_request_example()
            else:
                example_args = {}

        notes = _build_tool_notes(name, args_schema, placeholders_needed)

        entry: Dict[str, Any] = {
            "name": name,
            "description": tool_def.get("description", ""),
            "args_schema": args_schema,
            "notes": notes,
            "strict_schema": _is_strict_schema(name),
            "boundary_accepts_envelopes": _boundary_envelope_patterns(),
            "boundary_unknown_arg_policy": _boundary_unknown_arg_policy(name),
            "canonical_args_example": _canonical_args_example(name),
        }
        if include_examples:
            entry["example_args"] = example_args
        tools.append(entry)

    return {"tools": tools}


@mcp.tool(
    name=_VALIDATE_REQUEST_DEF["name"],
    title=_VALIDATE_REQUEST_DEF.get("title"),
    description=_VALIDATE_REQUEST_DEF.get("description"),
)
def validate_request_tool(request: Dict[str, Any]) -> Dict[str, Any]:
    return _run_tool(
        "qlip.validate_request",
        request,
        _validate_request_impl,
        include_output_warnings=True,
        validate_input=False,
    )


def _validate_request_impl(payload: Dict[str, Any]) -> Dict[str, Any]:
    report = validate_request(payload, strict=True)
    return report.to_dict()


@mcp.tool(
    name=_SOLVE_DEF["name"],
    title=_SOLVE_DEF.get("title"),
    description=_SOLVE_DEF.get("description"),
)
def solve_tool(request: Dict[str, Any]) -> Dict[str, Any]:
    return _run_tool("qlip.solve", request, _solve_impl, validate_input=False)


def _solve_impl(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = core_solve(payload)
    run_id = payload.get("context", {}).get("run_id") or str(uuid.uuid4())
    return {"run_id": run_id, "result": result.to_dict()}


def _debug_boundary_parse_impl(payload: Dict[str, Any], trace_id: str, allowed_tools: List[str]) -> Dict[str, Any]:
    target_payload = payload.get("payload", payload)
    dispatched = payload.get("dispatched_tool_name")
    dispatched_tool_name = dispatched if isinstance(dispatched, str) and dispatched else None

    tool_name, parsed_args, warnings, meta, errors = parse_tool_invocation(
        target_payload,
        dispatched_tool_name=dispatched_tool_name,
        allowed_tool_names=allowed_tools,
    )

    unknown_args_dropped: List[str] = []
    drop_warnings: List[Dict[str, Any]] = []
    if isinstance(tool_name, str) and tool_name in _METADATA_TOOLS and isinstance(parsed_args, dict):
        _, raw_drop_warnings = filter_unknown_keys(tool_name, parsed_args)
        drop_warnings = _normalize_warning_records(raw_drop_warnings)
        for warning in drop_warnings:
            pointer = warning.get("pointer", "")
            if isinstance(pointer, str) and pointer.startswith("/") and len(pointer) > 1:
                unknown_args_dropped.append(pointer[1:])

    normalized_warnings = _normalize_warning_records(warnings) + drop_warnings
    return {
        "extracted_tool_name": tool_name,
        "parsed_args": parsed_args,
        "unknown_args_dropped": sorted(set(unknown_args_dropped)),
        "warnings": normalized_warnings,
        "errors": errors,
        "trace_id": trace_id,
        "payload_sha256": _safe_payload_sha256(parsed_args),
        "parse_meta": meta,
    }


_HANDLER_MAP = {
    "qlip.list_constraints": _list_constraints_impl,
    "qlip.list_guidance": _list_guidance_impl,
    "qlip.shapes": _shapes_impl,
    "qlip.validate_request": _validate_request_impl,
    "qlip.solve": _solve_impl,
    _DEBUG_TOOL_NAME: lambda payload: payload,
}


def _dispatch_tool_call(name: str, raw_params: Any) -> Dict[str, Any]:
    started = time.perf_counter()
    inbound_trace_id = extract_trace_id(raw_params)
    trace_id = inbound_trace_id or str(uuid.uuid4())
    allowed_tools = sorted(_HANDLER_MAP.keys())
    tool_name, args, boundary_warnings, _, boundary_errors = parse_tool_invocation(
        raw_params,
        dispatched_tool_name=name,
        allowed_tool_names=allowed_tools,
    )
    if name == _DEBUG_TOOL_NAME:
        tool_name = _DEBUG_TOOL_NAME
    boundary_warning_records = _normalize_warning_records(boundary_warnings)
    run_id = _extract_context_run_id(args)
    payload_sha256 = _safe_payload_sha256(args)

    def _duration_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    tool_label = tool_name if isinstance(tool_name, str) and tool_name else name
    if boundary_errors:
        return _build_dispatch_error(
            tool_name=tool_label,
            trace_id=trace_id,
            warnings=boundary_warning_records,
            errors=boundary_errors,
            payload_sha256=payload_sha256,
            duration_ms=_duration_ms(),
            run_id=run_id,
        )

    if not isinstance(tool_name, str) or not tool_name:
        return _build_dispatch_error(
            tool_name=name,
            trace_id=trace_id,
            warnings=boundary_warning_records,
            errors=[{"code": "MISSING_TOOL_NAME", "pointer": "/", "message": "Tool name is required."}],
            payload_sha256=payload_sha256,
            duration_ms=_duration_ms(),
            run_id=run_id,
        )

    handler = _HANDLER_MAP.get(tool_name)
    if handler is None:
        return _build_dispatch_error(
            tool_name=tool_name,
            trace_id=trace_id,
            warnings=boundary_warning_records,
            errors=[
                {
                    "code": "UNKNOWN_TOOL_NAME",
                    "pointer": "/",
                    "message": f"Unknown tool name '{tool_name}'.",
                    "meta": {
                        "allowed_tools": allowed_tools,
                        "suggestions": _closest_matches(tool_name, allowed_tools, limit=3),
                    },
                }
            ],
            payload_sha256=payload_sha256,
            duration_ms=_duration_ms(),
            run_id=run_id,
        )

    limit_errors = apply_payload_limits(tool_name, args)
    if limit_errors:
        return _build_dispatch_error(
            tool_name=tool_name,
            trace_id=trace_id,
            warnings=boundary_warning_records,
            errors=limit_errors,
            payload_sha256=payload_sha256,
            duration_ms=_duration_ms(),
            run_id=run_id,
        )

    if tool_name == _DEBUG_TOOL_NAME:
        debug_result = _debug_boundary_parse_impl(args if isinstance(args, dict) else {}, trace_id, allowed_tools)
        return _build_dispatch_response(
            tool_name=tool_name,
            output=debug_result,
            trace_id=trace_id,
            warnings=boundary_warning_records,
            errors=[],
            payload_sha256=payload_sha256,
            duration_ms=_duration_ms(),
            run_id=run_id,
        )

    if tool_name in _METADATA_TOOLS:
        args, metadata_warnings = filter_unknown_keys(tool_name, args)
        boundary_warning_records.extend(_normalize_warning_records(metadata_warnings))

    normalized_args, normalization_warnings = normalize_tool_args(tool_name, args)
    if normalization_warnings:
        _emit_normalization_warnings(tool_name, normalization_warnings)
    all_warnings = boundary_warning_records + _normalize_warning_records(normalization_warnings)
    run_id = _extract_context_run_id(normalized_args) or run_id

    input_errors = _validate_tool_input_errors(tool_name, normalized_args)
    if input_errors:
        return _build_dispatch_error(
            tool_name=tool_name,
            trace_id=trace_id,
            warnings=all_warnings,
            errors=input_errors,
            payload_sha256=payload_sha256,
            duration_ms=_duration_ms(),
            run_id=run_id,
        )

    try:
        output = handler(normalized_args)
    except Exception as exc:
        return _build_dispatch_error(
            tool_name=tool_name,
            trace_id=trace_id,
            warnings=all_warnings,
            errors=[{"code": "TOOL_EXECUTION_ERROR", "pointer": "/", "message": str(exc)}],
            payload_sha256=payload_sha256,
            duration_ms=_duration_ms(),
            run_id=run_id,
        )

    output_errors = _validate_tool_output_errors(tool_name, output)
    if output_errors:
        return _build_dispatch_error(
            tool_name=tool_name,
            trace_id=trace_id,
            warnings=all_warnings,
            errors=output_errors,
            payload_sha256=payload_sha256,
            duration_ms=_duration_ms(),
            run_id=run_id,
        )

    if run_id is None and isinstance(output, dict):
        output_run_id = output.get("run_id")
        if isinstance(output_run_id, str) and output_run_id:
            run_id = output_run_id

    diagnostic_errors = _collect_unknown_plugin_errors(tool_name, output)
    return _build_dispatch_response(
        tool_name=tool_name,
        output=output,
        trace_id=trace_id,
        warnings=all_warnings,
        errors=diagnostic_errors,
        payload_sha256=payload_sha256,
        duration_ms=_duration_ms(),
        run_id=run_id,
    )


@mcp.resource("qlip://catalog/constraints")
def catalog_constraints() -> Dict[str, Any]:
    return list_constraints()


@mcp.resource("qlip://catalog/guidance")
def catalog_guidance() -> Dict[str, Any]:
    return list_guidance()


@mcp.resource("qlip://schemas/solve_request/v1")
def schema_solve_request() -> Dict[str, Any]:
    return _SCHEMAS["solve_request"]


@mcp.resource("qlip://schemas/solve_result/v1")
def schema_solve_result() -> Dict[str, Any]:
    return _SCHEMAS["solve_result"]


@mcp._mcp_server.list_tools()
async def _list_tools_override() -> List[MCPTool]:
    return _build_tool_listing()


@mcp._mcp_server.call_tool(validate_input=False)
async def _call_tool_override(name: str, arguments: Any | None) -> Dict[str, Any]:
    payload = arguments if arguments is not None else None
    return _dispatch_tool_call(name, payload)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
