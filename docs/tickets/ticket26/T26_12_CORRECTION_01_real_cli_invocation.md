# T26_12_CORRECTION_01 — Rewrite Parity Harness Using Real, Verified CLI Invocation

## Owner

Grunt (swarm — single bounded correction pass).

## Depends on

T26_12 attempt 1 — REJECTED. All 5 scripts imported entirely fabricated
Python APIs that do not exist anywhere in the source or archive:
`spp_maker_qlip.fitting.fit_potential`, `spp_maker_qlip.scoring.score_potential`
— neither module (`fitting.py`, `scoring.py`) exists at all. Real
functionality is only reachable via the `spp-maker` CLI (`fit`/`score`/
`calibrate`/`run` subcommands) or the real internal modules
(`spp_maker.fit_hist`, `spp_maker.fit_phi`, `spp_maker.score`,
`spp_maker.run_orchestrator` — but do not import these directly either;
use the CLI, see below). Attempt 1 also duplicated the fixture CIFs at the
WRONG location (`tests/fixtures/cifs/` at the unified repo root — must not
exist there) instead of the correct, already-existing
`packages/spp_maker_qlip/tests/fixtures/cifs/`, and left a stray
`test_parity_scripts.py` at the repo root.

## Objective

Rewrite all 5 parity scripts to invoke the `spp-maker` CLI via `subprocess`
— the exact same proven pattern already used successfully by
`packages/spp_maker_qlip/tests/test_run_orchestrator_smoke.py` and
`tests/test_cli_fit_smoke.py`. Do not import any internal
`spp_maker`/`spp_maker_qlip` Python function directly in these scripts —
subprocess-invoking the CLI is safer because its interface is already
proven and tested; guessing internal function signatures is exactly what
caused attempt 1 to fail completely.

## Pre-verified ground truth — use exactly these, do not invent flags

**Fixture CIFs (already exist, do not duplicate or recreate):**
`packages/spp_maker_qlip/tests/fixtures/cifs/nacl.cif`,
`packages/spp_maker_qlip/tests/fixtures/cifs/sic.cif`.

**Real CLI subcommand syntax** (verified via `grep -n "add_argument" cli.py`):

```
spp-maker fit --cif_dir <dir> --out_root <dir> --fit_method neighbors --r_cut 4.0
spp-maker score --spp_root <dir> --cif <file> --json
spp-maker calibrate --spp_root <dir> --cif_dir <dir> --target 5.0
spp-maker run --name <name> --cif_dir <dir> --out_dir <dir> --fit_method neighbors --calib_score_method neighbors --target 5.0 --max_calib 2 --no_bandpass [--publish_to <dir>]
```

Invoke exactly like `test_run_orchestrator_smoke.py` does:

```python
subprocess.run(
    [sys.executable, "-m", "spp_maker.cli", *args],
    capture_output=True, text=True, check=False,
    env={**os.environ, "PYTHONPATH": <src_path>},
    cwd=<repo_root_for_that_side>,
)
```

**Source side:** `PYTHONPATH=C:\Users\brown\.spp-source-frozen-3a2d557\src`,
`cwd=C:\Users\brown\.spp-source-frozen-3a2d557`.
**Archive side:** `PYTHONPATH` = `packages/spp_maker_qlip/src` (plus the
usual `src;packages/qlip/src;packages/crystal_db/src`), `cwd` = repo root
of this unified archive, but pass `--cif_dir packages/spp_maker_qlip/tests/fixtures/cifs`
(full relative path from that cwd) since the archive's fixtures live one
level deeper than the source's own `tests/fixtures/cifs`.

## Archive files expected to change

- Rewrite the 5 existing files in place:
  `packages/spp_maker_qlip/tests/parity/{parity_fitting,parity_scoring,parity_qlip_packaging,parity_regulator,parity_failure}.py`.
- Remove the wrongly-placed `tests/fixtures/cifs/{nacl,sic}.cif` at the
  unified repo root (only the existing
  `packages/spp_maker_qlip/tests/fixtures/cifs/` copies are correct).
- Remove the stray `test_parity_scripts.py` at the repo root.
- `docs/fidelity/evidence/SPP_PARITY_RESULTS.json` (rewrite with actual
  comparison output, not `{}`).

## In-scope behavior, per script

- **parity_fitting.py**: run `fit` on both sides against
  `tests/fixtures/cifs` (both CIFs, one at a time or as a directory),
  compare: required pairs (parse from the `manifest.json` the fit produces
  under `--out_root`), POT file bytes (byte-exact per the comparison rules
  already in the original ticket), quality metrics/manifest JSON (exact
  equality except explicitly-excluded environment-specific fields).
- **parity_scoring.py**: run `fit` first (or reuse fitting output) to get
  an `spp_root`, then run `score --spp_root <that> --cif <fixture> --json`
  on both sides; compare the JSON score output with the exact/tolerance
  rule from the original ticket.
- **parity_qlip_packaging.py**: run `run --publish_to <tmp qlip_outputs>`
  on both sides against the same fixture; compare directory structure,
  filenames, POT hashes, manifest structure between the two `--publish_to`
  trees.
- **parity_regulator.py**: this one cannot use a CLI subcommand directly
  (no regulator-specific CLI verb exists) — if you cannot construct a real,
  verified test using only real CLI/library entry points, report this as a
  BLOCKER with the reason, rather than inventing one. Do not fabricate an
  API.
- **parity_failure.py**: run `fit`/`score`/`run` with deliberately invalid
  arguments (missing `--cif_dir`, nonexistent path, etc.) on both sides;
  compare exit code and stderr's exception type name (grep for the
  exception class name in stderr, not full message text).

## Forbidden changes

- Do not import any `spp_maker.*`/`spp_maker_qlip.*` Python module directly
  in these scripts — CLI subprocess invocation only.
- Do not invent a function, class, or module name that you have not
  independently confirmed exists via `grep` first — if you need to check
  something exists, grep for it and show the grep output in your report.
- Do not create any file outside `packages/spp_maker_qlip/tests/parity/`
  and `docs/fidelity/evidence/`.
- Do not duplicate the fixture CIFs anywhere.

## Tests the grunt must run

- Each rewritten script, once, capturing real output.
- Report the exact grep command + output you used to confirm each CLI flag
  exists before using it, if you used any flag not already listed above.

## Tests Claude must independently rerun

- Every script, independently, from a clean shell.
- Verify no internal Python import of `spp_maker`/`spp_maker_qlip` appears
  in any of the 5 scripts (grep for `^from spp_maker\|^import spp_maker`).

## Acceptance criteria

- [ ] All 5 scripts run without `ModuleNotFoundError` or other crash from
      a fabricated API.
- [ ] Only real, `grep`-verified CLI flags used.
- [ ] Fixture CIFs not duplicated; stray files removed.
- [ ] `SPP_PARITY_RESULTS.json` contains real comparison output (or a
      documented BLOCKER for `parity_regulator.py` if no real entry point
      exists).

## Expected outputs / artifacts

- 5 working parity scripts using only verified real interfaces.
