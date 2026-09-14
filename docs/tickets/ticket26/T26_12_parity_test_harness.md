# T26_12 — Parity Test Harness

## Owner

Grunt implements the harness scripts to Claude's exact specification; Claude
interprets every result. The grunt reports raw comparison output — it does
not decide PASS/FAIL.

## Depends on

T26_09 (full software surface restored and wired).

## Objective

Build scripted comparisons between an isolated install of the source
package (built directly from `SPP-Maker-QLIP` at the scientific revision)
and the restored archive package, using safe fixture data only
(`tests/fixtures/cifs/nacl.cif`, `sic.cif`, and any other fixture already
present in source — no production/POT-library data).

## Authoritative source

**Already set up by Claude — use exactly this, do not build your own venv
or attempt `pip install`:** an isolated, read-only `git worktree` checkout
of the source repo at the frozen scientific revision, at
`C:\Users\brown\.spp-source-frozen-3a2d557` (detached HEAD at
`3a2d557811973265f3373ec881cc8057a89789d2`), confirmed importable via
`PYTHONPATH=C:\Users\brown\.spp-source-frozen-3a2d557\src` (no install
needed — the same `ase`/`numpy`/`pydantic` already used by the archive are
already present in the base Python environment; this sidesteps both the
sandbox's lack of network access and the unrelated root `pyproject.toml`
packaging defect documented in T26_03). Run source-side commands with only
that one `PYTHONPATH` entry (not mixed with any archive path) to guarantee
you are actually invoking source, not the restored archive.

Archive side: `PYTHONPATH` as established throughout Ticket 26 —
`src;packages/qlip/src;packages/crystal_db/src;packages/spp_maker_qlip/src;packages/spp_maker_qlip`,
`cwd=packages/spp_maker_qlip`.

## Claude-specified comparison rules (use exactly these — do not invent
your own tolerance or invent a looser rule)

- **POT files** (fitting output, QLIP packaging): PRIMARY rule is
  byte-exact comparison (SHA-256 match) — the source's own algorithms are
  documented as deterministic (fixed bins, fixed cutoffs, deterministic
  sorted CIF loading order), so byte-exact should hold. If a genuine
  floating-point non-determinism is observed (byte-exact fails), FALLBACK
  to parsing the POT `(r, u)` arrays and comparing with `rtol=1e-9,
  atol=1e-12` — but you MUST report every instance where the fallback was
  needed, with the actual byte diff, as a flagged item for Claude's review,
  not silently pass it.
- **Scores** (scoring parity): exact float equality; if that fails, same
  `rtol=1e-9, atol=1e-12` fallback, flagged the same way.
- **Manifests/JSON metadata**: exact key-value equality EXCEPT fields that
  are inherently environment-specific and must be excluded from comparison
  (list exactly which fields you excluded, and why): absolute file paths,
  timestamps/run IDs, `git_sha` (source vs. archive are different repos).
- **Required-pair sets / regulator union / fallback decisions**: exact set
  or categorical equality — no tolerance concept applies here at all.
- **Failure parity**: compare exception class name and any structured
  `status`/`reason` field — NOT raw error message text (messages may
  legitimately embed different absolute paths between source and archive
  locations).

## Archive files expected to change

- New harness scripts under
  `packages/spp_maker_qlip/tests/parity/` (or
  `docs/fidelity/evidence/spp_parity/`), e.g.:
  - `parity_fitting.py` — required pairs, histograms, potential arrays, POT
    bytes, quality metrics, manifest.
  - `parity_scoring.py` — identical CIF/Atoms + POT set → exact score.
  - `parity_qlip_packaging.py` — selected files, directory structure, POT
    hashes, manifest, QLIP request data.
  - `parity_regulator.py` — request-specific + regulator pair union and
    fallback decisions.
  - `parity_failure.py` — missing CIF corpus / missing required pair / bad
    POT / incomplete regulator coverage / invalid config / invalid formula
    / invalid QLIP output location, comparing exception/status behavior.
- `docs/fidelity/evidence/SPP_PARITY_RESULTS.json` (new — raw comparison
  output, not a pass/fail verdict).

## In-scope behavior

Each script must: run the same input through both installations, capture
outputs (or exceptions) from each side, and emit a structured diff — no
interpretation, no rounding/tolerance decisions beyond what Claude
specifies per artifact type.

## Forbidden changes

- No modification to the source install.
- No tolerance/threshold invented by the grunt — Claude specifies exact or
  source-defined numerical comparison rules per Part 40 ("No tolerance
  change unless source numerical serialization requires it") before this
  subticket starts, and the harness must implement exactly that rule, not a
  looser one.
- The grunt must not report "PASS"/"COMPLETE" framing over a parity
  question — only raw comparison data.

## Implementation requirements

Claude supplies, as part of this ticket's input, the exact fixture files,
the exact comparison rule per artifact type (byte-equality vs. specified
numerical tolerance), and the exact list of failure scenarios to construct.

## Source-fidelity / parity requirements

This entire subticket exists to produce that evidence — its own output is
the parity requirement's proof, so there is no separate meta-check beyond
Claude re-running every harness script itself.

## Tests the grunt must run

- Each parity script, once, capturing output into
  `SPP_PARITY_RESULTS.json`.

## Tests Claude must independently rerun

- **Every** harness script, from a clean shell, independently — this
  subticket's entire purpose is parity evidence, so Claude never accepts
  the grunt's captured JSON without reproducing it firsthand.
- Manual spot-check of at least one POT file's bytes and one score value by
  hand (not just via the script) to rule out a harness bug hiding a real
  mismatch.

## Acceptance criteria

- [ ] All five harness scripts exist and run against both installations.
- [ ] Direct fitting parity: exact or source-defined numerical match.
- [ ] Scoring parity: exact score match.
- [ ] QLIP packaging parity: identical structure/hashes/manifest.
- [ ] Regulator parity: identical union/fallback decisions.
- [ ] Failure parity: identical exception/status behavior.
- [ ] Claude has independently reproduced every result before treating any
      of them as evidence.

## Expected outputs / artifacts

- `docs/fidelity/evidence/SPP_PARITY_RESULTS.json`
- Parity evidence for Ticket 26 completion report (§17–20), and the gating
  input for T26_11.
