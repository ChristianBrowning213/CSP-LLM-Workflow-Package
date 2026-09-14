# T26_09 — Calibration, Publishing, Corpus-Prep & Plotting Restoration

## Owner

Grunt (local-grunt), Claude-reviewed.

## Depends on

T26_04 (accepted). Originally sequenced after T26_08 in the initial draft
plan, but DAG reconstruction after T26_04's acceptance found no actual file
or logic overlap between the two (T26_08 touches `qlip_package.py` ×2,
`qlip_outputs_index.py`, `qlip_outputs_packages.py`, `QLIP_Outputs/`;
this ticket touches `calibration.py`, `publish.py`, `meta_csv.py`,
`weights_csv.py`, `gr_dump.py`, and a disjoint set of `scripts/*.py`) —
scheduled to run concurrently with T26_08 instead.

## Objective

Restore the remaining operational software surfaces: calibration,
publishing/index registry, corpus-preparation, and plotting/reporting code
— using only relocation-level path/import changes.

## Authoritative source

- `spp_maker/calibration.py` (447 lines)
- `spp_maker/publish.py` (178 lines)
- `spp_maker/meta_csv.py`, `spp_maker/weights_csv.py`
- `spp_maker/gr_dump.py`, `scripts/plot_gr_dump.py`
- `scripts/mp_phaseA_build_corpus.py` (corpus preparation)
- `scripts/demo_property_conditioned_spp.py`,
  `scripts/diagnose_pair_extraction.py`, `scripts/probe_mcp_run_pipeline.py`,
  `scripts/print_qlip_snippet.py`, `scripts/qlip_outputs_list.py`,
  `scripts/publish_qlip_outputs.py`, `scripts/check_pot_compat.py`

All verbatim from T26_02 baseline.

## Archive files expected to change

Path/import adjustments only in the files above, for relocation into
`packages/spp_maker_qlip/`.

## In-scope behavior

- Calibration commands runnable against restored `spp_maker`.
- Publishing/index registry operational if it was operational at the
  scientific revision (verify via source tests before assuming so).
- Corpus-prep script runnable against fixture CIFs.
- Plotting/reporting code restored as supported CLI/runtime surface;
  generated plots/reports themselves are not committed to the package.

## Forbidden changes

- No changes to calibration statistics/metrics logic, publishing schema, or
  corpus-preparation algorithms.
- Do not commit any generated plot, report, or corpus output as a package
  asset.

## Implementation requirements

Verify via the migrated test suite (T26_04) which of these modules are
actually exercised/operational at the scientific revision before restoring
wiring for anything the source itself doesn't exercise — do not invent
operational status for dead code.

## Source-fidelity / parity requirements

Diff against T26_02 baseline: only path/import lines.

## Tests the grunt must run

Run all tests with `cwd=packages/spp_maker_qlip` and `PYTHONPATH` including
both `packages/spp_maker_qlip/src` and `packages/spp_maker_qlip` itself —
this matches the source repo's own invocation convention (some tests use
CWD-relative paths, e.g. `test_calibration_stats_and_lambda.py`) and how
`scripts` resolves as a top-level import.

- `tests/test_calibrate_outputs_explain_sign.py`,
  `tests/test_calibration_stats_and_lambda.py`,
  `tests/test_cli_calibrate_no_bandpass.py`,
  `tests/test_cli_calibrate_smoke.py`,
  `tests/test_cli_calibrate_supercell_method.py`,
  `tests/test_publish_kinds.py`, `tests/test_publish_qlip_outputs.py`,
  `tests/test_demo_script_smoke.py`, `tests/test_gr_phi_roundtrip.py`,
  `tests/test_supercell_gr.py`, `tests/test_supercell_support.py`.

## Tests Claude must independently rerun

- Re-run the same suite.
- Confirm no generated artifact (plot/report/corpus file) was committed.

## Acceptance criteria

- [ ] Calibration software restored and tests pass.
- [ ] Publishing/index registry restored where operational at this
      revision, documented as such if not operational.
- [ ] Corpus-prep software restored (software only, no generated corpora).
- [ ] Plotting/reporting code restored as CLI/runtime surface only.

## Expected outputs / artifacts

- Passing test results for the Ticket 26 completion report (§12
  Calibration/publishing).
