# Phase 3 MEGNet External Predictors

This document is the canonical Phase 3 surface for MEGNet-backed external property predictors.

Phase 3 predictors are external surrogates. They are separate from native Phase 1 QLIP/SPP objectives and from Phase 2 composition descriptors.

## Source Of Truth

Runtime registry:

- `src/sok_llm_orchestrator/contracts/phase3_external_predictors.py`

Compatibility loader:

- `src/sok_llm_orchestrator/external_predictors/megnet_loader.py`

CLI inspection:

```bash
sokllm doctor phase3-external-predictors
```

Implemented-only view:

```bash
sokllm doctor phase3-external-predictors --implemented-only
```

## Implemented Predictors

| id | upstream MEGNet id | target | unit | value state | benchmark-approved |
|---|---|---|---|---|---|
| `phase3.external.megnet_formation_energy` | `Eform_MP_2018` | formation energy | `eV/atom` | `raw` | no |
| `phase3.external.megnet_band_gap` | `Bandgap_MP_2018` | band gap | `eV` | `raw` | no |
| `phase3.external.megnet_bulk_modulus` | `logK_MP_2018` | bulk modulus | `log10(GPa)` | `raw_log10` | no |
| `phase3.external.megnet_shear_modulus` | `logG_MP_2018` | shear modulus | `log10(GPa)` | `raw_log10` | no |

## Loader Contract

Production predictor code does not call `megnet.utils.models.load_model`.

The compatibility loader resolves paths through `megnet.utils.models.MODEL_MAPPING`, `MODEL_PATH`, and `LOCAL_MODEL_PATH`; loads Keras models with `tensorflow.keras.models.load_model(..., custom_objects=_CUSTOM_OBJECTS, compile=False)`; loads the paired `.json` config with `monty.serialization.loadfn`; and reconstructs `megnet.models.GraphModel(model=model, **configs)`.

## Valid Structure Input

Phase 3 runtime prediction requires one of:

- a real `pymatgen.Structure`, or
- a parseable CIF artifact path whose content includes atom-site fields and can be loaded by `pymatgen`

The repo stubbed QLIP runtime now emits a deterministic parseable CIF by default so the end-to-end Phase 3 path can be exercised in non-live tests.

## Modulus Semantics

The MEGNet `logK_MP_2018` and `logG_MP_2018` models emit log-space values. The adapter reports the raw model output as `log10(K)` or `log10(G)` where the underlying modulus is measured in GPa. It does not exponentiate to linear GPa.

## Invalid Structure Handoff

When the Phase 3 handoff cannot produce a real structure, the prediction payload fails truthfully. `external_predictions.json` records a Phase 3 structure handoff block plus explicit error codes for cases such as:

- missing CIF artifact path
- unreadable or unparseable CIF content
- structurally incomplete CIF content with no atom sites
- invalid or missing `pymatgen.Structure`

In those cases the run does not fake success: predictions stay empty, errors are explicit, and pipeline failure reporting preserves the external-prediction failure reason.

## Benchmark Rules

Strict benchmark mode rejects malformed, unknown, and non-implemented Phase 3 predictor requests. The current MEGNet entries are implemented and provenance-complete, but remain `benchmark_approved: false` and `exploratory_only: true` until project-local calibration and benchmark validation are completed.
