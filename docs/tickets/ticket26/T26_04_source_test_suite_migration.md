# T26_04 — Source Test-Suite Migration

## Owner

Grunt (local-grunt), Claude-reviewed.

## Depends on

T26_03 (package importable and wired).

## Objective

Get the verbatim `packages/spp_maker_qlip/tests/` suite collecting and
running against the newly wired package, adapting only test-collection
paths/fixture paths/conftest roots — no assertion changes.

## Authoritative source

Original test baseline (from Ticket 26 text): `128 passed, 1
dependency-sensitive schema snapshot failure`, at the scientific revision.

## Archive files expected to change

- `packages/spp_maker_qlip/tests/**` — path/fixture/conftest adjustments
  only (e.g. `rootdir`-relative imports that assumed the standalone repo
  layout).
- `packages/spp_maker_qlip/pyproject.toml` or a new
  `packages/spp_maker_qlip/pytest.ini` — test discovery configuration only.
- Root test runner config (e.g. `pyproject.toml [tool.pytest.ini_options]`)
  if the unified suite needs an additional `testpaths` entry to include this
  package — additive only, must not change existing test collection.

## In-scope behavior

- Making `pytest packages/spp_maker_qlip/tests -q` collect and execute all
  66 test files without collection errors.
- Fixing import paths broken purely by relocation (e.g.
  `from spp_maker import ...` continuing to work is the point; a test that
  imported via a relative path assuming repo-root position may need a
  `sys.path`/conftest fix).

## Forbidden changes

- No weakening, deleting, or skipping any existing assertion.
- No modifying expected values to make a test pass.
- No new test logic beyond what already exists in source, except the single
  dependency-sensitive schema-snapshot failure, which must be marked with an
  explicit, documented skip/xfail **only if** T26_07-adjacent investigation
  (done by Claude, not this subticket) confirms it is environment drift —
  do not decide this classification inside this subticket.

## Implementation requirements

**Critical environment hazard — read before running anything:** this
machine has a pre-existing, unrelated `pip install -e .` done directly
against the sibling checkout `C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP`,
registered as a global `__editable__.spp_maker-0.1.0.pth` in
site-packages. A bare `import spp_maker` with no `PYTHONPATH` override
resolves to that sibling checkout, NOT to
`packages/spp_maker_qlip/src/spp_maker` — silently testing the wrong tree
and producing a false pass. `pip install -e .` for THIS unified repo
currently cannot be used to override it either (see T26_03's documented,
user-acknowledged pre-existing `project.license` schema blocker). Therefore:

- Every test invocation in this subticket MUST set
  `PYTHONPATH=src;packages/qlip/src;packages/crystal_db/src;packages/spp_maker_qlip/src`
  (Windows path-separator `;`) before running `pytest`, so PYTHONPATH
  entries take precedence over the stray site-packages `.pth` entry.
- Before trusting any test result, run
  `python -c "import spp_maker; print(spp_maker.__file__)"` with that same
  `PYTHONPATH` set and confirm the printed path is under
  `packages\spp_maker_qlip\src\spp_maker\__init__.py` — if it ever prints a
  path under `SPP-Maker-QLIP`, stop and report a BLOCKER; do not proceed.

Run the suite, capture failures, and fix only fixture/path/collection
issues. Any failure that looks scientific/behavioral must be reported back
as a BLOCKER, not silently patched.

## Source-fidelity / parity requirements

Test file contents (assertions, fixtures, expected values) must remain
byte-identical to the T26_02 baseline except for import/path lines.

## Tests the grunt must run

- With `PYTHONPATH` set as above:
  `pytest packages/spp_maker_qlip/tests -q` — report full pass/fail counts.
- The `spp_maker.__file__` sibling-checkout sanity check described above,
  run immediately before the suite.

## Tests Claude must independently rerun

- Re-run the full suite from a clean shell.
- Diff every modified test file against the T26_02 baseline to confirm only
  path/import lines changed.
- Independently classify the one expected schema-snapshot failure (env
  drift / real defect / snapshot incompatibility) per Ticket 26 Part 44 —
  this classification is Claude's, not the grunt's.

## Acceptance criteria

- [ ] Suite collects with zero collection errors.
- [ ] 128 tests pass (or the exact count present in this revision's test
      files, reconciled against the manifest from T26_01).
- [ ] At most the one documented dependency-sensitive failure remains, and
      it is classified (by Claude) rather than silently fixed.
- [ ] No assertion or expected value differs from source.

## Expected outputs / artifacts

- Passing (or precisely accounted-for) test run output, captured in the
  Ticket-26 progress record.
