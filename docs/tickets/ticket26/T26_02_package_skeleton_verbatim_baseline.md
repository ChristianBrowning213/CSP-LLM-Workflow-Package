# T26_02 — Package Skeleton & Verbatim Namespace Baseline

## Owner

Claude. NOT delegated: this is the fidelity-critical exact copy that every
later grunt diff is checked against. An LLM retyping 2,380 lines of
`spp_maker_mcp/server.py` risks silent transcription drift in code the
ticket explicitly forbids altering.

## Depends on

T26_01 (staged verbatim source must exist).

## Objective

Create `packages/spp_maker_qlip/` following the existing
`packages/qlip/` / `packages/crystal_db/` layout precedent, and commit the
verbatim (byte-identical) source content into it — zero logic edits at this
stage. This is the immutable baseline every subsequent subticket's diff is
measured against.

## Authoritative source

Staged snapshot from T26_01 (`.grunt-staging/spp_maker_source/<rev>/`),
itself sourced from `3a2d557811973265f3373ec881cc8057a89789d2` in
`SPP-Maker-QLIP`.

## Archive files expected to change

- `packages/spp_maker_qlip/pyproject.toml` (new — verbatim copy of source
  `pyproject.toml`, `name`/`version`/`dependencies`/`scripts` unchanged)
- `packages/spp_maker_qlip/src/spp_maker/**` (new, verbatim)
- `packages/spp_maker_qlip/src/spp_maker_qlip/**` (new, verbatim)
- `packages/spp_maker_qlip/src/spp_maker_mcp/**` (new, verbatim)
- `packages/spp_maker_qlip/tests/**` (new, verbatim copy of source `tests/`)
- `packages/spp_maker_qlip/rules/covalent_rules.yaml` (new, verbatim)
- `packages/spp_maker_qlip/README.md` (new, verbatim)

## In-scope behavior

Pure file placement. No package is wired into the root repository yet — that
is T26_03. This subticket only proves a faithful namespace exists on disk.

## Forbidden changes

- No edit to any copied file's content.
- No renaming of any module, class, function, or CLI/MCP tool name.
- No new files beyond directory-required `__init__.py` files that already
  exist verbatim in source (do not add new ones).

## Implementation requirements

Copy files exactly from the T26_01 staging tree. Do not run any
find/replace across file contents in this step.

## Source-fidelity / parity requirements

`git diff --no-index <staging-file> packages/spp_maker_qlip/<path>` must be
empty for every file.

## Tests the grunt must run

N/A — no grunt invocation.

## Tests Claude must independently rerun

- For every file under `packages/spp_maker_qlip/{src,tests,rules}`,
  `git show <scientific-rev>:<original-relative-path>` piped to `diff -`
  against the new file must show zero differences.
- Confirm no file exists in the new package tree that isn't traceable to a
  source path in the T26_01 manifest.

## Acceptance criteria

- [ ] `packages/spp_maker_qlip/` exists with `pyproject.toml`, `src/`,
      `tests/`, `rules/`, `README.md`.
- [ ] Every file is byte-identical to its source-revision counterpart.
- [ ] No file is present that lacks a source-manifest entry.
- [ ] Package is not yet importable from the unified environment (expected —
      root wiring is T26_03).

## Expected outputs / artifacts

- `packages/spp_maker_qlip/` verbatim baseline tree, left as an uncommitted
  working-tree checkpoint (per parent Ticket 26 Phase 5: no commit happens
  until final Ticket-26 acceptance in T26_16) that every later subticket's
  diff is measured against.
