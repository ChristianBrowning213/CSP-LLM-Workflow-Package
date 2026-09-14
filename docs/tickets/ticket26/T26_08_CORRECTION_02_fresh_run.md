# T26_08_CORRECTION_02 — Generate a Fresh Legitimate SPP Run for QLIP_Outputs

## Owner

Grunt (swarm — single bounded correction pass).

## Depends on

T26_08_CORRECTION_01 (ACCEPTED — static QLIP_Outputs content restored) and
T26_09 (ACCEPTED — `publish.py`/`calibration.py` verified working, no
changes needed).

## Objective

The 20 tests found failing during T26_04's review
(`test_qlip_package_pot_handoff.py` ×14, `test_unified_qlip_output.py` ×5,
`test_qlip_outputs_assets.py::test_integration_md_exists_and_mentions_sppcollection`
×1) need a REAL, freshly-generated SPP run published into
`QLIP_Outputs/SPP/`, because the source revision's own `latest.txt`
pointed at a run that only ever existed as untracked local state on the
original author's machine. This subticket generates one legitimate fresh
run using the now-verified-working pipeline, on safe fixture data only.

## Authoritative source

A proven, already-tested CLI invocation pattern — copy this exactly, do
not invent your own arguments. This is taken directly from
`packages/spp_maker_qlip/tests/test_run_orchestrator_smoke.py`, which
already exercises this exact command successfully:

```
spp-maker run --name qlip_outputs_seed --cif_dir tests/fixtures/cifs --out_dir <tmp_or_real_out_dir> --fit_method neighbors --calib_score_method neighbors --target 5.0 --max_calib 2 --no_bandpass --publish_to QLIP_Outputs
```

Run this from `packages/spp_maker_qlip/` (so `tests/fixtures/cifs` and
`QLIP_Outputs` resolve correctly), with `PYTHONPATH` including
`packages/spp_maker_qlip/src` (and the usual `src`, `packages/qlip/src`,
`packages/crystal_db/src`).

`--publish_to QLIP_Outputs` causes `run_orchestrator.py` to call
`publish_registry_artifact()` (in `publish.py`, verified working by T26_09)
for `spp`, `guidance`, and `package` kinds — this SHOULD automatically
write `QLIP_Outputs/SPP/latest.txt` (and `GUIDANCES/latest.txt`) correctly.
Do not hand-write `latest.txt` yourself — let the real software produce it.

## Archive files expected to change

- New generated run content under `packages/spp_maker_qlip/QLIP_Outputs/SPP/runs/<new-run-id>/`
  and `packages/spp_maker_qlip/QLIP_Outputs/GUIDANCES/runs/<new-run-id>/`
  (whatever the real pipeline produces — do not hand-construct this
  structure).
- `packages/spp_maker_qlip/QLIP_Outputs/SPP/latest.txt` and
  `GUIDANCES/latest.txt` — updated BY THE SOFTWARE ITSELF via
  `--publish_to`, not by you.

## In-scope behavior

1. Run the exact command above.
2. If it fails, report the exact error as a BLOCKER — do not work around it
   by hand-writing output.
3. If it succeeds, run the 20 previously-failing tests listed above (with
   `cwd=packages/spp_maker_qlip` and `PYTHONPATH` including
   `packages/spp_maker_qlip` itself) and report the new pass/fail count.

## Forbidden changes

- Do not hand-write any file under `QLIP_Outputs/SPP/` or
  `QLIP_Outputs/GUIDANCES/` — everything in this subticket's output must
  come from actually running the CLI command above.
- Do not modify `run_orchestrator.py`, `publish.py`, `cli.py`, or any other
  source file — this ticket only RUNS the software, it does not change it.
- Do not use production/real CIF data — only the fixture CIFs already at
  `tests/fixtures/cifs/`.
- Do not touch the static content restored by T26_08_CORRECTION_01
  (`INTEGRATION.md`, `README.md`, `CONSTRAINTS/*`).

## Implementation requirements

Run the command from `packages/spp_maker_qlip/` exactly as given above. Do
not add, remove, or change any flag.

## Source-fidelity / parity requirements

The generated run's content is produced by unmodified, already-restored
software — no scientific/mathematical code is touched by this ticket.

## Tests the grunt must run

- The `spp-maker run ... --publish_to QLIP_Outputs` command above.
- All 20 previously-failing tests (see Objective) — report exact pass/fail
  per test.

## Tests Claude must independently rerun

- Re-run the same CLI command independently (or verify the worker's actual
  generated output in its worktree) to confirm it wasn't fabricated.
- Re-run all 20 tests independently.
- Confirm `QLIP_Outputs/SPP/latest.txt`'s content actually resolves to a
  real, existing directory with real `.POT` files under it (not another
  dangling pointer).

## Acceptance criteria

- [ ] The CLI command runs successfully, unmodified.
- [ ] `QLIP_Outputs/SPP/latest.txt` / `GUIDANCES/latest.txt` are written by
      the software itself and point to real, existing generated content.
- [ ] All (or as many as genuinely resolvable) of the 20 previously-failing
      tests now pass.
- [ ] No source file modified — only generated output added.

## Expected outputs / artifacts

- A fresh, real SPP run under `QLIP_Outputs/SPP/runs/` and
  `QLIP_Outputs/GUIDANCES/runs/`, correctly registered via `latest.txt`.
