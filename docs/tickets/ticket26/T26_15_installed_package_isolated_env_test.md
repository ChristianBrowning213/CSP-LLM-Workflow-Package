# T26_15 — Installed-Package Isolated-Environment Test

## Owner

Claude. Not delegated: this is a release/deployment-adjacent verification
step (build + isolated install), reserved to the supervising engineer per
the repository's responsibility split, not "implementation work."

## Depends on

T26_11 (compatibility wrapper decisions finalized).

## Objective

Build the restored `spp-maker-qlip` package into a wheel and install it
into a fresh, isolated virtual environment with no sibling `SPP-Maker-QLIP`
checkout reachable on `sys.path`, then verify imports and CLI/MCP entry
points work from the installed artifact rather than the editable source
tree.

## Authoritative source

`packages/spp_maker_qlip/pyproject.toml` as finalized through T26_03–T26_10.

## Archive files expected to change

None — this is a verification-only subticket. Any packaging defect found
here is routed back as a narrow correction to the relevant earlier
subticket (T26_03), not fixed inline here.

## In-scope behavior

- `python -m build` (or equivalent) producing a wheel for
  `packages/spp_maker_qlip/`.
- `pip install <wheel>` into a throwaway venv created outside this
  repository (e.g. under the scratchpad directory).
- `import spp_maker`, `import spp_maker_qlip`, `import spp_maker_mcp`.
- `spp-maker --help`, `spp-maker-mcp --help` (or its actual invocation
  form) from that venv.
- Confirm `spp_maker.__file__` resolves inside the venv's `site-packages`,
  not the sibling `SPP-Maker-QLIP` checkout or this repo's source tree.

## Forbidden changes

None applicable — read/verify only.

## Implementation requirements

Performed directly by Claude via Bash, in the scratchpad directory, using a
disposable venv that is deleted afterward.

## Source-fidelity / parity requirements

N/A — packaging verification, not source comparison.

## Tests the grunt must run

N/A — no grunt invocation.

## Tests Claude must independently rerun

This entire subticket is Claude's own independent test; there is no
separate "rerun" step distinct from the subticket's execution.

## Acceptance criteria

- [ ] Wheel builds cleanly.
- [ ] Fresh isolated venv installs it without error.
- [ ] All three namespace imports succeed from the installed wheel.
- [ ] CLI and MCP entry points work from the installed wheel.
- [ ] No sibling checkout appears on `sys.path`.

## Expected outputs / artifacts

- Isolated-install verification evidence for Ticket 26 completion report
  (§Installed package test / Part 46).
