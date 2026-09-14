# T26_05 — CLI Entry-Point Restoration

## Owner

Grunt (local-grunt), Claude-reviewed.

## Depends on

T26_03.

## Objective

Confirm and wire the original `spp-maker` CLI exactly as implemented in
`src/spp_maker/cli.py` at the scientific revision — exact subcommand names,
exact executable name, no `llm-csp`-style renaming.

## Authoritative source

`spp_maker/cli.py` (verbatim, from T26_02 baseline).

**Ground truth already confirmed by Claude (do not re-derive, do not
invent additional commands):** the actual CLI exposes exactly four
subcommands, defined at `cli.py:1316` (`fit`), `:1488` (`score`), `:1554`
(`calibrate`), `:1642` (`run`). `run` is the end-to-end pipeline ("fit ->
calibrate -> package -> final QLIP handoff in one command") and internally
covers what Ticket 26 Part 22's illustrative list calls "quality",
"package/export", and "required-pair operations" — those are **not**
separate top-level subcommands in this source revision. Confirmed via
`spp-maker --help` executed against the actual restored module. Do not
add a `quality`, `package`, `export`, or `required-pair` subcommand — that
would be inventing CLI surface the source does not have.

## Archive files expected to change

- Root `pyproject.toml` / `packages/spp_maker_qlip/pyproject.toml`
  `[project.scripts]` entry for `spp-maker` (packaging only).
- No changes to `cli.py` itself unless a resource/config default path must
  be adjusted for repository relocation (allowed category).

## In-scope behavior

- `spp-maker --help` lists every subcommand exactly as named in source.
- Each subcommand's own `--help` works.

## Forbidden changes

- Renaming any subcommand or the executable itself.
- Adding new subcommands.
- Changing default values of any scientific parameter exposed via CLI flags.

## Implementation requirements

If a default path (e.g. a POT root or config directory) is hardcoded
relative to the old standalone repo layout, adjust only that path constant,
and record the change in the path-rewrite ledger (T26_13 will transcribe
it — this subticket should leave a clear comment/note for that).

## Source-fidelity / parity requirements

`cli.py` diff against T26_02 baseline: zero lines changed, or only path-
constant lines changed with an explicit inline comment `# repo-relocation`.

## Tests the grunt must run

- `spp-maker --help`
- `spp-maker <each-subcommand> --help` for every subcommand found in source.
- Existing CLI smoke tests migrated in T26_04
  (`tests/test_cli_help.py`, `tests/test_cli_fit_smoke.py`,
  `tests/test_cli_calibrate_smoke.py`, etc.).

## Tests Claude must independently rerun

- Re-run `spp-maker --help` and diff its output textually against
  `git show <scientific-rev>:src/spp_maker/cli.py` subcommand definitions to
  confirm no name was invented or dropped.
- Re-run the CLI smoke tests.

## Acceptance criteria

- [ ] `spp-maker` executable installed and preserved exactly.
- [ ] Every source subcommand present; no renamed or invented commands.
- [ ] CLI smoke tests pass.
- [ ] `cli.py` diff contains at most repo-relocation path changes.

## Expected outputs / artifacts

- Enumerated CLI surface for inclusion in the Ticket 26 completion report
  (§10 CLI).
