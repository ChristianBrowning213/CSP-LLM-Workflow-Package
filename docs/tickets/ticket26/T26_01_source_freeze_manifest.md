# T26_01 — Source Freeze & Manifest

## Owner

Claude (supervising engineer). NOT delegated to local-grunt: this subticket
requires read access to a sibling repository
(`C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP`) outside any grunt worktree
sandbox, and is investigation/provenance work per the repository's
responsibility split.

## Depends on

None. First subticket in the Ticket 26 stack.

## Objective

Freeze the exact state of the authoritative source repository at the
scientific and licensing revisions named by Ticket 26, record that state,
and stage a byte-exact verbatim snapshot of the operational source tree for
downstream subtickets to adapt.

## Authoritative source

Repository: `C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP`

- Scientific revision: `3a2d557811973265f3373ec881cc8057a89789d2`
- Licensing revision: `82114cd05f0cb40149d13c20adeafe4c437a03ae`

Read-only. Do not modify this repository (no checkout, no commit, no branch
change) — inspect only via `git show`, `git ls-tree`, `git log`.

## Archive files expected to change

- `docs/fidelity/evidence/SPP_MAKER_SOURCE_MANIFEST.csv` (new)
- A local, untracked staging snapshot under
  `.grunt-staging/spp_maker_source/<rev>/...` inside this repository's
  working tree (untracked, not gitignored, so it is visible to any later
  grunt worktree snapshot; never committed as final content — it is
  superseded by T26_02's real package commit).

## In-scope behavior

- Record `git rev-parse HEAD` and `git status --short` evidence for both
  revisions.
- Enumerate every tracked file at the scientific revision via
  `git ls-tree -r --name-only <rev>`.
- For every tracked *operational source* file (excludes `.docx` binaries,
  generated `artifacts/*.POT`, and `QLIP_Outputs/**` runtime state), compute
  path, size, and SHA-256, and write them into the manifest CSV.
- Extract verbatim byte content (via `git show <rev>:<path>`) for:
  - `src/spp_maker/**`
  - `src/spp_maker_qlip/**`
  - `src/spp_maker_mcp/**`
  - `rules/covalent_rules.yaml`
  - `scripts/**` (operational scripts only, not one-off diagnostics unless
    referenced by CLI/tests)
  - `tests/**` (full tree, including fixtures)
  - `pyproject.toml`, `README.md`, `docs/DYMTR0_REFERENCE_SPP_CONTRACT.md`,
    `docs/mcp/API.md`, `docs/SPP_BLEND_POLICY.md`,
    `docs/spp_pair_extraction_audit.md`, `docs/REQUEST_SCALE_FACTOR_AUDIT.md`
  into the staging directory, preserving relative paths under a `src-rev/`
  subtree keyed by revision.

## Forbidden changes

- No modification of any kind to the source repository.
- No edits to extracted content during staging — this is a pure copy step.

## Implementation requirements

Use `git show <rev>:<path> > <dest>` (or equivalent Python using
`subprocess`) for every extracted file. Do not open files in an editor or
regenerate content from memory.

## Source-fidelity / parity requirements

Every staged file's SHA-256 must equal `git show <rev>:<path> | sha256sum`
computed independently at verification time.

## Tests the grunt must run

N/A — no grunt invocation for this subticket.

## Tests Claude must independently rerun

- Re-run the SHA-256 check for a random sample (at least 10 files, including
  `spp_maker_mcp/server.py` and `spp_maker_qlip/qlip_package.py`) comparing
  the manifest CSV's recorded hash against a fresh `git show | sha256sum`.

## Acceptance criteria

- [ ] `SPP_MAKER_SOURCE_MANIFEST.csv` exists and lists every tracked
      operational source file at the scientific revision with path/size/sha256.
- [ ] Staging snapshot under `.grunt-staging/spp_maker_source/` contains
      byte-identical copies of `spp_maker`, `spp_maker_qlip`, `spp_maker_mcp`,
      `tests/`, and named docs.
- [ ] Source repository working tree/HEAD unchanged (verified by
      `git status --short` before and after).
- [ ] Sampled hash re-check passes.

## Expected outputs / artifacts

- `docs/fidelity/evidence/SPP_MAKER_SOURCE_MANIFEST.csv`
- `.grunt-staging/spp_maker_source/<scientific-rev>/...` (untracked staging)
