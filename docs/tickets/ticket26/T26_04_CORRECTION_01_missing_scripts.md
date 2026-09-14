# T26_04_CORRECTION_01 — Restore the 5 Omitted Source Scripts

## Owner

Grunt (local-grunt, single heavyweight worker — NOT swarm; this gates
everything downstream and must not run concurrently with anything else).

## Depends on

T26_02 (verbatim baseline), T26_03 (packaging wired). Corrects a gap left
by T26_01/T26_02's original staging scope.

## Objective

T26_04's migrated test suite fails to collect with:

```
ModuleNotFoundError: No module named 'scripts.diagnose_pair_extraction'
```

Root cause: T26_01/T26_02 never staged the source repository's top-level
`scripts/*.py` files, which 7 migrated test files depend on. This ticket
restores exactly those 5 files, verbatim, with zero content changes.

## Authoritative source

Already extracted, byte-verified, and staged by Claude at:

```
.grunt-staging/spp_maker_source/3a2d557811973265f3373ec881cc8057a89789d2/scripts/
    check_pot_compat.py
    demo_property_conditioned_spp.py
    diagnose_pair_extraction.py
    publish_qlip_outputs.py
    print_qlip_snippet.py
```

These are exact `git show <scientific-rev>:scripts/<name>` extractions from
`C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP` — already confirmed
byte-for-byte correct against the source repository by Claude via SHA-256.
**Use these staged files as your ONLY source. Do not re-fetch, retype, or
reconstruct their content from anywhere else, including your own
knowledge or the sibling checkout.**

## Archive files expected to change

Copy each staged file verbatim (byte-for-byte, e.g. `cp`, not retyped) to:

```
packages/spp_maker_qlip/scripts/check_pot_compat.py
packages/spp_maker_qlip/scripts/demo_property_conditioned_spp.py
packages/spp_maker_qlip/scripts/diagnose_pair_extraction.py
packages/spp_maker_qlip/scripts/publish_qlip_outputs.py
packages/spp_maker_qlip/scripts/print_qlip_snippet.py
```

This mirrors the source repository's own layout (`scripts/` sits alongside
`src/` and `tests/` at the repo root there; `packages/spp_maker_qlip/`
plays that same "repo root" role here, exactly as already established for
`tests/` in T26_02).

No other file in `packages/spp_maker_qlip/` should change. Do not add an
`__init__.py` to the new `scripts/` directory — the source `scripts/`
directory has none (confirmed via `git ls-tree`); adding one would deviate
from verbatim source structure and is not needed (Python 3 implicit
namespace packages resolve `import scripts.X` from a plain directory as
long as its parent is on `sys.path`).

## In-scope behavior

Pure file copy. Verify the copy succeeded and the suite can now at least
attempt to import/run these modules.

## Forbidden changes

- No edits to the copied files' content — not even a trailing newline
  change, path constant, or comment.
- No changes to any test file.
- No changes to any other file in `packages/spp_maker_qlip/src/**`.
- Do not invent a `scripts/__init__.py`.
- Do not touch `pyproject.toml` (root or package) — this ticket needs no
  packaging change. `scripts` becomes importable purely via the `PYTHONPATH`
  convention Claude will use when rerunning tests (adding
  `packages/spp_maker_qlip` itself, not just its `src/`, to `PYTHONPATH`)
  — this is a test-invocation detail, not something to encode in this
  ticket's files.

## Implementation requirements

```
cp .grunt-staging/spp_maker_source/3a2d557811973265f3373ec881cc8057a89789d2/scripts/check_pot_compat.py packages/spp_maker_qlip/scripts/check_pot_compat.py
```
(and the same for the other 4 files — create the `packages/spp_maker_qlip/scripts/`
directory first).

After copying, run this sanity check and include its output in your report:

```
python -c "import hashlib,sys
for name in ['check_pot_compat.py','demo_property_conditioned_spp.py','diagnose_pair_extraction.py','publish_qlip_outputs.py','print_qlip_snippet.py']:
    a = open(f'.grunt-staging/spp_maker_source/3a2d557811973265f3373ec881cc8057a89789d2/scripts/{name}','rb').read()
    b = open(f'packages/spp_maker_qlip/scripts/{name}','rb').read()
    print(name, 'MATCH' if hashlib.sha256(a).hexdigest()==hashlib.sha256(b).hexdigest() else 'MISMATCH')"
```

Then attempt the collection check yourself (informational only — Claude
will independently rerun this):

```
PYTHONPATH="src;packages/qlip/src;packages/crystal_db/src;packages/spp_maker_qlip/src;packages/spp_maker_qlip" python -m pytest packages/spp_maker_qlip/tests -q --collect-only
```

If this still fails with a *different* missing-module error, report it as a
BLOCKER — do not invent or stub a replacement module.

## Source-fidelity / parity requirements

All 5 copied files must show `MATCH` in the sanity check above. This is a
hard acceptance gate — a single `MISMATCH` means REJECT, not accept-with-
caveats.

## Tests the grunt must run

- The hash sanity check above.
- The `--collect-only` check above (informational; do not attempt to fix
  any further collection error beyond reporting it).

## Tests Claude must independently rerun

- Re-run the hash sanity check independently (not trusting the grunt's
  reported output).
- Re-run full `pytest packages/spp_maker_qlip/tests -q` (not just
  `--collect-only`) with the extended `PYTHONPATH`, and reconcile the
  pass/fail count against Ticket 26's stated baseline (128 passed, 1
  dependency-sensitive schema-snapshot failure).
- Re-run the sibling-checkout sanity check
  (`spp_maker.__file__` must resolve under `packages/spp_maker_qlip/src`).
- Diff `packages/spp_maker_qlip/scripts/*.py` against
  `git show 3a2d557811973265f3373ec881cc8057a89789d2:scripts/<name>` in the
  authoritative source repo directly (belt-and-suspenders beyond the
  staged-file hash check).

## Acceptance criteria

- [ ] All 5 scripts present at `packages/spp_maker_qlip/scripts/`.
- [ ] All 5 byte-identical to source (verified independently by Claude
      against the live source repo, not just the staged copy).
- [ ] No other file changed.
- [ ] No `__init__.py` added.
- [ ] Test collection error for `scripts.diagnose_pair_extraction` is
      resolved (any *different* remaining gap is reported, not papered
      over).

## Expected outputs / artifacts

- `packages/spp_maker_qlip/scripts/` populated with the 5 verbatim files.
- Clears the way for T26_04's full test-suite acceptance.
