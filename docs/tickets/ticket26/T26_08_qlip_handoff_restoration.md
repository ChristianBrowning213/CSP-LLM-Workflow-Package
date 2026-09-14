# T26_08 — QLIP Handoff Restoration

## Owner

Grunt (local-grunt), Claude-reviewed.

## Depends on

T26_07 (regulator/common_contract classification must exist before touching
anything regulator-adjacent in the handoff path).

## Objective

Restore the complete operational `qlip_package` module (both
`spp_maker/qlip_package.py` and `spp_maker_qlip/qlip_package.py`),
`QLIP_Outputs` registry semantics, and `Final_QLIP_output` layout exactly —
relocating only the filesystem base directory required by living inside
this unified repository.

## Authoritative source

- `spp_maker/qlip_package.py` (85 lines)
- `spp_maker_qlip/qlip_package.py` (1,369 lines)
- `spp_maker/qlip_outputs_index.py` (219 lines)
- `spp_maker/qlip_outputs_packages.py` (216 lines)
- Source `QLIP_Outputs/` directory conventions (`CONSTRAINTS/`,
  `GUIDANCES/`, `SPP/`, each with `latest.txt` and `runs/`).

All verbatim from T26_02 baseline.

**Finding from T26_04's independent review (do not re-derive):** T26_01/T26_02
wrongly excluded `QLIP_Outputs/` entirely, treating it as pure generated
runtime state. It is not — `git ls-tree` at the scientific revision shows
these ARE genuinely tracked static source files that must be restored
verbatim as part of this subticket:

```
QLIP_Outputs/CONSTRAINTS/.gitkeep
QLIP_Outputs/CONSTRAINTS/latest.txt   (empty file at this revision)
QLIP_Outputs/CONSTRAINTS/runs/.gitkeep
QLIP_Outputs/GUIDANCES/.gitkeep
QLIP_Outputs/GUIDANCES/latest.txt
QLIP_Outputs/GUIDANCES/runs/.gitkeep
QLIP_Outputs/INTEGRATION.md
QLIP_Outputs/README.md
QLIP_Outputs/SPP/latest.txt
QLIP_Outputs/SPP/runs/.gitkeep
```

Separately, `QLIP_Outputs/SPP/latest.txt`'s *content* at this revision points
to `SPP/runs/20260514_090416_CoAs2_safflorite_dmytro_fit_neighbors_calib_scaled_285e1305/`
— a run directory that is **untracked local state on the original author's
machine** (confirmed: `git status --short` on the live source repo shows
nothing for `QLIP_Outputs/`, and the directory is absent from `git ls-tree`
at the frozen revision). Restoring `latest.txt` verbatim will therefore
still point at a run that does not exist in this archive — this is
expected and correct per Ticket 26 Part 36 (generated request-specific
output is not an archive asset). Do not fabricate that run directory's
contents. Instead, this subticket should additionally **generate one
fresh, legitimate run** using the now-verified-working `spp-maker run`
pipeline against the safe fixture CIFs already present at
`packages/spp_maker_qlip/tests/fixtures/cifs/{nacl,sic}.cif`, publish it
under `QLIP_Outputs/SPP/runs/`, and update `latest.txt` to point at that
fresh run — this unblocks the 20 tests in
`test_qlip_package_pot_handoff.py` / `test_unified_qlip_output.py` /
`test_qlip_outputs_assets.py` that T26_04 found failing for exactly this
reason (see `docs/tickets/ticket26/PROGRESS.md`'s T26_04 row for the full
diagnosis). This is legitimate operational use of already-restored,
unmodified software on safe fixture data — not a scientific-behavior
change, and not restoration of anyone's production data.

## Archive files expected to change

- Path constants only, in the above files, for the `QLIP_Outputs` base
  directory location (e.g. from a standalone-repo-root assumption to a
  location under `packages/spp_maker_qlip/` or a configurable root — must
  remain overridable via the same environment variable/config mechanism the
  source already uses, not a new one).
- No new abstraction (do not introduce a "v0.1 run-root" style wrapper —
  Part 19 explicitly forbids replacing `QLIP_Outputs` with that).
- `packages/spp_maker_qlip/QLIP_Outputs/{CONSTRAINTS,GUIDANCES}/{.gitkeep,latest.txt,runs/.gitkeep}`,
  `QLIP_Outputs/SPP/runs/.gitkeep`, `QLIP_Outputs/INTEGRATION.md`,
  `QLIP_Outputs/README.md` (new — verbatim from source, per the finding
  above).
- One freshly-generated run under `QLIP_Outputs/SPP/runs/<new-run-id>/`
  (produced by actually running `spp-maker run` against the safe fixture
  CIFs — see finding above), with `QLIP_Outputs/SPP/latest.txt` updated to
  point at it (this is the one file whose *content* legitimately differs
  from source, since source's own `latest.txt` pointed at data that was
  never in git).

## In-scope behavior

- `QLIP_Outputs/{CONSTRAINTS,GUIDANCES,SPP}/{latest.txt,runs/}` structure
  exists and is populated by the restored pipeline exactly as source does.
- `Final_QLIP_output` helper functions preserve names, directory structure,
  manifest semantics, and POT/QLIP-request locations.

## Forbidden changes

- No change to POT package creation logic, QLIP handoff metadata content,
  request packaging logic, or result/output organization beyond the base
  path.
- No renaming of `QLIP_Outputs` or `Final_QLIP_output`.
- No touching QLIP's own scientific/objective code (only the SPP-side
  producer of the handoff).

## Implementation requirements

Adjust only the base-directory resolution; preserve every other constant,
filename, and directory name verbatim.

## Source-fidelity / parity requirements

Diff of `qlip_package.py` (both copies), `qlip_outputs_index.py`,
`qlip_outputs_packages.py` against T26_02 baseline: only base-path lines
change.

## Tests the grunt must run

- Migrated `tests/test_publish_qlip_outputs.py`,
  `tests/test_qlip_outputs_assets.py`, `tests/test_print_qlip_snippet.py`,
  `tests/spp_maker_qlip/test_qlip_package_pot_handoff.py` (all 14 cases),
  `tests/spp_mcp/test_unified_qlip_output.py` (all 5 cases),
  `tests/mcp/test_package_for_qlip.py`,
  `tests/mcp/test_publish_to_qlip_outputs.py`.
- Run with `cwd=packages/spp_maker_qlip` and `PYTHONPATH` including both
  `packages/spp_maker_qlip/src` and `packages/spp_maker_qlip` itself (the
  convention T26_04 established — see its PROGRESS.md row).
- These 20 tests are EXPECTED to go from failing to passing once the fresh
  run is generated and `latest.txt` points at it — this is the concrete
  acceptance bar for this subticket, not just "no regression."

## Tests Claude must independently rerun

- Re-run the same suite.
- Line-diff `qlip_package.py` (both copies) against baseline; confirm only
  path constants changed.
- Manually run `spp-maker package` (or equivalent source command) against a
  small fixture and inspect the produced directory tree by hand for
  fidelity to source naming.

## Acceptance criteria

- [ ] `QLIP_Outputs` registry structure and semantics restored exactly.
- [ ] `Final_QLIP_output` layout, manifest semantics, and POT/QLIP-request
      locations restored exactly.
- [ ] Only the filesystem base path changed; every other name/structure
      untouched.
- [ ] All listed tests pass.

## Expected outputs / artifacts

- Working QLIP handoff path for Ticket 26 completion report (§9 QLIP
  packaging).
