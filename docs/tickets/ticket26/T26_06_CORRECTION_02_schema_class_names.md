# T26_06_CORRECTION_02 — Fix Fabricated Schema Names & Metadata

## Owner

Grunt (swarm — single bounded correction pass).

## Depends on

T26_06 attempts 1 and 2 (both REJECTED). Attempt 1: correct tool
names/lines, invalid JSON syntax. Attempt 2: valid JSON, but fabricated
`archive_implementation` (a tarball filename, not a repo path) and
fabricated `input_schema`/`output_schema` class names ending in
`Arguments`, which do not exist anywhere in `contracts.py`.

## Objective

Rewrite `docs/fidelity/spp_maker_mcp_surface.json` using ONLY the
pre-verified values below. Do not independently re-derive, guess, or
"improve" any of these values — every one has already been confirmed by
grepping the actual source files. Transcribe exactly.

## Pre-verified ground truth (use exactly as-is)

Verified via `grep -n "@mcp.tool\|^def tool_" packages/spp_maker_qlip/src/spp_maker_mcp/server.py`:

```
spp.run_pipeline            -> server.py:2278  (decorator line)
spp.check_compat            -> server.py:2284
spp.package_for_qlip        -> server.py:2290
spp.publish_to_qlip_outputs -> server.py:2296
```

Verified via `grep -n "^class " packages/spp_maker_qlip/src/spp_maker_mcp/contracts.py`
— the ONLY real request/result class names are:

```
spp.run_pipeline            -> input: RunPipelineRequest,            output: RunPipelineResult
spp.check_compat            -> input: CheckCompatRequest,            output: CheckCompatResult
spp.package_for_qlip        -> input: PackageForQLIPRequest,         output: PackageForQLIPResult
spp.publish_to_qlip_outputs -> input: PublishToQLIPOutputsRequest,   output: PublishToQLIPOutputsResult
```

There is NO class ending in `Arguments` anywhere in `contracts.py`. Do not
use that suffix.

`archive_implementation` for every tool (all four tools are implemented in
the same file, this is a single restored module, not four separate files):

```
packages/spp_maker_qlip/src/spp_maker_mcp/server.py
```

`parity_status` for every tool: `IDENTICAL` (the exact word Ticket 26 Part
25 specifies for untouched verbatim source — `server.py` was not modified).

## Archive files expected to change

- `docs/fidelity/spp_maker_mcp_surface.json` (rewrite).

## In-scope behavior

Write valid JSON (use `json.dump`, not manual string construction) as a
top-level array of 4 objects, each with exactly these keys: `name`,
`source_implementation`, `input_schema`, `output_schema`,
`archive_implementation`, `parity_status` — using only the pre-verified
values above.

## Forbidden changes

- No value other than what is listed above.
- No new/different key names.
- No re-deriving values by reading the source files yourself — use the
  ground truth given here. (This is deliberate: two prior attempts each
  fabricated a different plausible-sounding but wrong value when asked to
  derive this themselves.)

## Tests the grunt must run

- `python -c "import json; json.load(open('docs/fidelity/spp_maker_mcp_surface.json', encoding='utf-8'))"` must succeed.
- Print the final file content in your report for Claude's review.

## Tests Claude must independently rerun

- Re-parse the JSON.
- Re-grep both source files to confirm every value matches exactly.

## Acceptance criteria

- [ ] Valid JSON.
- [ ] Every value matches the pre-verified ground truth exactly — no
      substitutions, no invented class/field names.
- [ ] No other file changed.

## Expected outputs / artifacts

- Correct, valid `docs/fidelity/spp_maker_mcp_surface.json`.
