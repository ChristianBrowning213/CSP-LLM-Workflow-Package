# QLIP MCP Client Contract

This document defines the boundary contract for MCP clients calling QLIP tools.

## Uniform Response Envelope
All MCP tool responses use this envelope:

```json
{
  "ok": true,
  "tool": "qlip.shapes",
  "trace_id": "8ce0d9b8-8ab7-4b3f-a8e8-8c7b8db5f6d8",
  "result": {},
  "errors": [],
  "warnings": [],
  "meta": {
    "trace_id": "8ce0d9b8-8ab7-4b3f-a8e8-8c7b8db5f6d8",
    "payload_sha256": "sha256hex",
    "duration_ms": 2,
    "warnings_count_by_code": {},
    "category": "RUNTIME",
    "retryable": false
  }
}
```

Field notes:
- `ok`: `true` when no top-level envelope errors exist.
- `tool`: resolved tool name used for dispatch.
- `trace_id`: propagated from `trace_id|request_id|id|meta.trace_id` when present, otherwise UUID4.
- `result`: tool-specific payload on success, otherwise `null`.
- `errors`: deterministic order by `(pointer, code, message)`.
- `warnings`: objects with `code`, `message`, optional `pointer`, `severity` (`INFO|WARN`), optional `meta`.
- `meta.payload_sha256`: hash of parsed args object (post envelope parse, pre normalization).
- `meta.category`: one of `FORMAT|LIMIT|SCHEMA|PLUGIN|RUNTIME`.
- `meta.retryable`: retry hint based on primary error category.

## Strict vs Tolerant
- Metadata tools (`qlip.shapes`, `qlip.list_constraints`, `qlip.list_guidance`):
  - Unknown args are dropped with warning `UNKNOWN_ARG_DROPPED`.
  - Boundary accepts multiple envelope formats.
- Strict tools (`qlip.validate_request`, `qlip.solve`):
  - SolveRequest strict schema is preserved.
  - Unknown top-level keys still fail schema validation.
  - No coercion is applied inside `constraints[].params` or `guidance[].params`.

## Error and Warning Glossary
Common error codes:
- `MISSING_TOOL_NAME`
- `UNKNOWN_TOOL_NAME`
- `JSON_DECODE_FAILED`
- `INVALID_ARGS_TYPE`
- `PAYLOAD_LIMIT_EXCEEDED`
- `SCHEMA_VALIDATION_ERROR`
- `UNKNOWN_PLUGIN_ID`
- `TOOL_EXECUTION_ERROR`

Common warning codes:
- `COERCED_JSON_STRING_ARGS`
- `COERCED_TYPE`
- `UNWRAPPED_WRAPPER`
- `MULTIPLE_TOOL_CALLS`
- `UNKNOWN_ARG_DROPPED`
- `ENVELOPE_TOOL_NAME_MISMATCH`
- `ENVELOPE_BOTH_ARGUMENTS_AND_PARAMS`

## Canonical Call Examples

### OpenAI `tool_calls` envelope
```json
{
  "tool_calls": [
    {
      "function": {
        "name": "qlip.shapes",
        "arguments": {
          "include_examples": true
        }
      }
    }
  ]
}
```

### OpenAI `function.arguments` JSON string
```json
{
  "function": {
    "name": "qlip.shapes",
    "arguments": "{\"include_examples\": true}"
  }
}
```

### LM Studio form-mode oddity example
```json
{
  "arguments": {
    "ids": {},
    "tags_any": "",
    "include_params_schema": "true"
  }
}
```

### Minimal canonical args per tool
- `qlip.shapes`: `{"include_examples": false}`
- `qlip.list_constraints`: `{"include_params_schema": true}`
- `qlip.list_guidance`: `{"include_params_schema": true}`
- `qlip.validate_request`: a strict SolveRequest object at top level
- `qlip.solve`: a strict SolveRequest object at top level
- `qlip.debug_boundary_parse`: `{"payload": {"arguments": {"include_examples": true}}}`

## Fixture-backed Examples
The following fixtures are used in tests to prevent contract drift:
- `tests/fixtures/lmstudio_payloads/08_tool_calls_openai_style.json`
- `tests/fixtures/lmstudio_payloads/09_function_arguments_json_string.json`

## Claude Code Skill Pack
- Skill path: `skills/qlip_mcp_boundary_v5/SKILL.md`
- Skill output schema: `skills/qlip_mcp_boundary_v5/output.schema.json`
- Skill fixture: `skills/qlip_mcp_boundary_v5/fixtures/good.json`
- This contract + skill pack are the authoritative operator/client guide for Boundary V5 behavior.
