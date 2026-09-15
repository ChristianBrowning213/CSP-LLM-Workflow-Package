# QLIP MCP Boundary V5 Skill
## Purpose
- Prevent brittle MCP client failures (LM Studio/OpenAI wrapper variance, stringified arguments, envelope mismatches).
- Treat inbound payloads as untrusted: parse/canonicalize at boundary, then apply strict validation where required.

## Scope
- Boundary-only behavior: envelope extraction, trace propagation, payload caps, warning/error normalization, uniform response envelope.
- Non-scope:
  - No solver, plugin, or optimization behavior changes.
  - No coercion inside `constraints[].params` or `guidance[].params`.
  - `qlip.validate_request` and `qlip.solve` remain strict (`additionalProperties: false` behavior preserved).

## Canonical Call Discipline (Clients)
- General rule: send a plain JSON args object for each tool; avoid wrapper nesting unless required by your client SDK.
- `qlip.shapes`: `{"include_examples": false}` or `{"tool":"qlip.solve","include_examples":true}`
- `qlip.list_constraints`: `{"include_params_schema": true}` (optional `ids`, `tags_any` arrays only)
- `qlip.list_guidance`: `{"include_params_schema": true}` (optional `ids`, `tags_any` arrays only)
- `qlip.validate_request`: top-level SolveRequest object (preferred; no extra keys)
- `qlip.solve`: top-level SolveRequest object (preferred; no extra keys)
- `qlip.debug_boundary_parse`: `{"payload": {<raw inbound envelope>}}`
- Input hygiene:
  - Use real JSON booleans/numbers, not quoted scalars.
  - Omit `ids`/`tags_any` unless arrays.
  - For validate/solve, prefer direct SolveRequest over wrappers.

## Tolerated Inputs (Boundary)
- Envelope variants accepted:
  - Raw args object
  - `{"arguments": {...}}`
  - `{"params": {...}}`
  - `{"function":{"name":"<tool>","arguments": {...}}}`
  - `{"tool_calls":[{"function":{"name":"<tool>","arguments": {...}}]}`
- JSON-string args container is parsed via `json.loads(...)`; warning code: `COERCED_JSON_STRING_ARGS`.
- Metadata tools (`qlip.shapes`, `qlip.list_constraints`, `qlip.list_guidance`) drop unknown arg keys and emit `UNKNOWN_ARG_DROPPED`.
- `qlip.validate_request` / `qlip.solve` stay strict; unknown keys fail with schema errors (`SCHEMA_VALIDATION_ERROR`).

## Payload Limits
- Shared caps:
  - `max_bytes`: 512 KB
  - `max_depth`: 40
  - `max_keys_total`: 25,000
  - `max_list_total`: 100,000
  - `max_string_len`: 65,536 bytes/chars per string
  - `max_total_string_bytes`: 262,144 bytes aggregate strings
- Validate/solve caps:
  - `constraints` length <= 5,000
  - `guidance` length <= 5,000
  - `problem.design_space.sites.explicit_fractional_sites` length <= 50,000
- Limit failures return `PAYLOAD_LIMIT_EXCEEDED` with `meta.which_limit`, `meta.actual`, `meta.limit`.

## Response Contract
- Uniform envelope:
  - `ok`, `tool`, `trace_id`, `result`, `errors[]`, `warnings[]`, `meta`, optional `primary_error`.
- Trace:
  - `trace_id` is extracted from `trace_id | request_id | id | meta.trace_id` or generated.
- Hash:
  - `meta.payload_sha256` is computed from parsed args (post envelope parse/JSON-string parse, pre normalization and pre metadata unknown-key dropping).
- Timing:
  - `meta.duration_ms` is per-dispatch wall-time.
- Warnings:
  - Objects with `code`, `message`, `severity` (`INFO|WARN`), optional `pointer`, optional `meta`.
- Errors:
  - Deterministically sorted; `primary_error` equals first error.
  - Error metadata includes category/retryable classification (`FORMAT|LIMIT|SCHEMA|PLUGIN|RUNTIME`, `retryable: bool`).

## Debugging
- `QLIP_MCP_DUMP_ERRORS=1` enables error-only JSONL dumps (off by default).
- Optional dump path: `QLIP_MCP_DUMP_ERRORS_PATH`; defaults to `qlip_mcp_error_dump.jsonl` at repo root.
- Use `qlip.debug_boundary_parse` to inspect extracted tool name, parsed args, dropped metadata keys, warnings, and payload hash without running schema validation or solver/plugins.

## Acceptance Tests (Must Exist)
- Skill fixture round-trip:
  - `skills/qlip_mcp_boundary_v5/fixtures/good.json` dispatches successfully and matches expected envelope assertions.
- Strictness preserved:
  - Unknown top-level SolveRequest keys still fail for `qlip.validate_request`/`qlip.solve`.
- Metadata tolerance split:
  - Metadata tools drop unknown args with `UNKNOWN_ARG_DROPPED`; strict tools reject unknown keys.
- Warning contract stability:
  - Warning objects keep `code`, `message`, `severity` (+ optional `meta`/`pointer`).
