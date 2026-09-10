# Workflow packaging notes

## Frozen source

- Repository: `C:\Users\brown\Documents\GitHub\Skill-Loop-CSP`
- Branch: `Agentic-Loop`
- Commit: `b2130661b4690623877e852dc03132506aa720dd`
- Canonical entry point: `sok_llm_orchestrator.workflow.runner.run_csp_workflow`
- Source status: only known unrelated untracked `benchmarks/external/OMatG/`

The source was not modified. The pre-implementation selection is recorded in
`WORKFLOW_MIGRATION_FILESET.md`.

## Ownership replacements

- Database routing/storage assumptions become packaged
  `crystal_db.retrieval.text_search` plus result normalization.
- Source SPP imports become `llm_csp.spp.export_required_pair_spp_root`,
  `export_required_pot_subset`, and packaged POT quality inspection.
- QLIP calls use packaged `validate_request`, `solve`, and the canonical
  periodic scorer for objective parity.
- Direct SCA imports become `llm_csp.validation.validate_cif` and
  `validate_family_topology`.
- Paper scaffold builders are excluded. Requests supply a packaged QLIP design
  space and may retain a configured scaffold identifier.

## Regulator contract

The frozen workflow requires a usable global regulator for every required pair,
even when a request POT exists. Request-usable pairs use additive
request-plus-regulator guidance. Missing/insufficient request pairs use
regulator-only fallback. If request guidance is disabled, the regulator becomes
the primary complete POT root. Request/regulator coefficients and outer scale
remain explicit. POT bytes and hashes are retained.

The broad regulator tree is never bundled. It enters through
`SPPConfig.regulator_root`, falling back only to Ticket 6's explicit
`SPP_SOURCE_POT_ROOT` boundary.

## Portable structural differences

The source normalizer has a finite hard-coded task/alias map. The package
requires the caller to provide the resolved formula and QLIP design space. This
removes hidden research mappings without claiming a general language parser.
Repository discovery, Git subprocess probes, repository output defaults, paper
registry routing, and large attempt trees become installed metadata and one
caller-owned run root.

The source raises after persisting controlled failures. The package returns a
serializable blocked/failed result after persisting reached-stage evidence.

## Scientific parity

For the offline regulator-only boundary, frozen source and packaged adapters
produce identical required pairs, QLIP context, complete POT mode, 11 Angstrom
cutoff, guidance ID, and weight. Regulator hashes match Ticket 4 byte-for-byte.
QLIP retains objective `4.883033620558714`; independent periodic scoring gives
`4.883033620558713`. SCA evaluates the generated `Sr1 Ti1 O3` CIF and confirms
the target formula.

Fresh request SPP fitting uses Ticket 6 but does not restore the excluded source
calibration campaign or common-contract research builder. Those require a
separately scoped migration if adopted as supported product contracts.

## Deferred real retrieval

The 10k database and BGE-M3/LM Studio service are outside the offline gate.
Crystal-DB `text_search` currently invokes schema initialization, so the
production-index test is explicitly skipped until a verified strictly read-only
connection path exists.

## Ticket 8 verification

- Workflow unit: 13 passed.
- Workflow integration/failure paths: 6 passed, 1 explicitly skipped real-index test.
- Offline E2E: 1 passed.
- Installed-wheel offline E2E: 1 passed.
- Repository-wide: 150 passed, 2 skipped.
- Frozen source/package regulator-only QLIP adapter output: exact match.
- Installed offline result: six required Sr/Ti/O pairs, complete regulator
  fallback, QLIP `OPTIMAL`, objective `4.883033620558714`, independent score
  `4.883033620558713`, generated CIF retained, SCA `evaluated`, parseable,
  formula `Sr1 Ti1 O3`, and target formula match true.

The isolated target was
`C:\Users\brown\AppData\Local\Temp\ticket8-installed-7f4f95093e23440eb2a8a9921b1a821b\venv`.
`llm_csp`, `crystal_db`, `qlip`, and `sca` all resolved beneath its
`Lib\site-packages` directory after development checkout paths were removed.
