# Ticket 27 — SPP/POT operational assets

Status: `SPP_POT_ASSETS_BLOCKED_PROVENANCE`.

The canonical runtime regulator is
`qlip/data/spp/regulators/icsd_broad_regulator_v1` in the QLIP working tree.
`WorkflowConfig.regulator_id` selects it and
`ProductionWorkflowStages._regulator_root` resolves either the explicit
configuration root, `SKILL_LOOP_REGULATOR_SPP_ROOT`, or the QLIP data-root
layout. The library has 20,328 files, 3,388 distinct pair POTs, and
263,829,560 bytes. Its POT-only canonical tree hash is
`be0a8f620fca62aa3bb755d76ac9edeeb8aa1ac507c4800001e4018b94c6cf0c`.

Source documentation associates the global ICSD SPP library with an external
local input tree and provides no redistribution grant. It is untracked and
ignored in QLIP. Consequently, zero canonical-regulator bytes were copied.
The full source-side POT hashes are preserved in
`SPP_POT_ASSET_HASHES.txt` so a lawfully regenerated/supplied tree can be
verified without reserialization.

The nine tracked QLIP built-in POTs and the tracked SPP-Maker QLIP-output
fixtures are project-authored MIT material and were copied byte-for-byte.
Request outputs, historical runs, paper outputs, and duplicate copies were not
archived. Regeneration from fixture CIFs uses the restored `spp-maker run` and
`spp.package_for_qlip` implementations; reproducing the broad regulator still
requires provenance-cleared input structures and the source generator setup.
