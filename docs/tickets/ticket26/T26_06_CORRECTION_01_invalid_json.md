# T26_06_CORRECTION_01 — Fix Invalid JSON in MCP Surface Manifest

## Owner

Grunt (local-grunt or swarm — single bounded correction pass).

## Depends on

T26_06's first attempt (REJECTED — content was correct, syntax was not).

## Objective

The previous attempt produced `docs/fidelity/spp_maker_mcp_surface.json`
with the right tool names and line numbers, but the file is **not valid
JSON** — it contains literal backslash characters instead of double quotes
(e.g. `\name\: \spp.run_pipeline\,` instead of `"name": "spp.run_pipeline",`),
confirmed by `json.load()` raising `Invalid \escape`. This was very likely
caused by writing the file via a shell string with manual quote-escaping
instead of using a JSON serializer.

## Authoritative source

The correct tool names/line numbers are already established and must be
preserved exactly:

```
spp.run_pipeline            -> server.py:2278
spp.check_compat            -> server.py:2284
spp.package_for_qlip        -> server.py:2290
spp.publish_to_qlip_outputs -> server.py:2296
```

## Archive files expected to change

- `docs/fidelity/spp_maker_mcp_surface.json` (rewrite, same 4 tools).

## In-scope behavior

Regenerate this file using Python's `json.dump`/`json.dumps` (or an
equivalent proper JSON serializer) — **never** hand-construct JSON via
string concatenation or shell here-strings with manual quote escaping.
After writing, validate it yourself with `python -c "import json;
json.load(open('docs/fidelity/spp_maker_mcp_surface.json'))"` and include
that command's success/failure in your report.

Keep the same schema shape as before (`tools` array of objects with `name`,
`source_implementation`, `input_schema`, `output_schema`,
`archive_implementation`, `parity_status`), but improve
`input_schema`/`output_schema` to reference the actual contract class names
from `spp_maker_mcp/contracts.py` (e.g. `RunPipelineArguments`,
`RunPipelineResult`) as plain strings — the previous attempt's approach of
using an import-statement string for these fields is acceptable and may be
kept as-is; only the malformed JSON syntax needs fixing.

## Forbidden changes

Same as T26_06: no invented tool names, no schema redesign.

## Implementation requirements

Use `json.dump(data, fh, indent=2)` in Python. Do not write raw JSON text
by hand.

## Source-fidelity / parity requirements

Same as T26_06.

## Tests the grunt must run

- `python -c "import json; json.load(open('docs/fidelity/spp_maker_mcp_surface.json', encoding='utf-8'))"`
  must succeed with no exception.

## Tests Claude must independently rerun

- Re-run the same JSON validation independently.
- Re-cross-check tool names against `server.py` via grep.

## Acceptance criteria

- [ ] File is valid, parseable JSON.
- [ ] Same 4 tools, same line-number citations as the rejected attempt.
- [ ] No other file changed.

## Expected outputs / artifacts

- Valid `docs/fidelity/spp_maker_mcp_surface.json`.
