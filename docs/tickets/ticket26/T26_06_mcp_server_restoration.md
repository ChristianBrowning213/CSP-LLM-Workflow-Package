# T26_06 — MCP Server Restoration & Surface Manifest

## Owner

Grunt (local-grunt), Claude-reviewed.

## Depends on

T26_03.

## Objective

Confirm the original `spp_maker_mcp` server is wired and importable, and
produce a machine-readable manifest of every MCP tool it actually exposes.

## Authoritative source

`src/spp_maker_mcp/server.py` (2,380 lines) and `contracts.py`, verbatim
from T26_02 baseline.

## Archive files expected to change

- `docs/fidelity/spp_maker_mcp_surface.json` (new)
- Packaging wiring for `spp-maker-mcp` console script (same mechanism as
  T26_03/T26_05).
- No changes to `server.py`/`contracts.py` logic; only path/config-lookup
  fixes for relocation, if any.

## In-scope behavior

- `spp_maker_mcp.server` imports and its `main()`/tool-registration path
  constructs without error.
- For every MCP tool actually registered in `server.py`, record in the
  manifest: `name`, `source implementation` (file:line or function name),
  `input schema`, `output schema`, `archive implementation` (path in this
  repo), `parity status` (`IDENTICAL` if the implementation is untouched
  verbatim source, else a note).

## Forbidden changes

- No invented tool names — every entry in the manifest must trace to an
  actual tool registration in `server.py`.
- No schema redesign.
- No transport change.

## Implementation requirements

Extract the tool list mechanically (grep/AST-walk `server.py` for tool
registration calls) rather than summarizing from memory. This is an
enumeration task, not a design task.

## Source-fidelity / parity requirements

Every tool name and schema reference in
`docs/fidelity/spp_maker_mcp_surface.json` must be independently greppable
in `server.py`/`contracts.py`.

## Tests the grunt must run

Run all tests with `cwd=packages/spp_maker_qlip` and `PYTHONPATH` including
both `packages/spp_maker_qlip/src` and `packages/spp_maker_qlip` itself —
matches the source repo's own invocation convention (established during
T26_04's independent review; see `docs/tickets/ticket26/PROGRESS.md`).

- `python -c "import spp_maker_mcp.server"`
- Migrated `tests/mcp/**` suite (`test_server_schema.py`,
  `test_run_pipeline_dry_run.py`, `test_package_for_qlip.py`,
  `test_publish_to_qlip_outputs.py`, `test_lenient_calls.py`,
  `test_check_compat.py`), including the existing `tests/mcp/snapshots/
  tool_schemas.json` snapshot comparison.

## Tests Claude must independently rerun

- Re-run the `tests/mcp/**` suite.
- Grep `server.py` for every tool-registration pattern and cross-check
  against `spp_maker_mcp_surface.json` for completeness (no missing tool)
  and accuracy (no invented tool).

## Acceptance criteria

- [ ] `spp_maker_mcp` importable; `spp-maker-mcp` entry point installed.
- [ ] `spp_maker_mcp_surface.json` lists every actual source tool, and only
      actual source tools.
- [ ] `tests/mcp/**` suite passes, including the schema snapshot test.
- [ ] No transport/schema/tool-name change from source.

## Expected outputs / artifacts

- `docs/fidelity/spp_maker_mcp_surface.json`
- MCP test results for the Ticket 26 completion report (§11 MCP).
