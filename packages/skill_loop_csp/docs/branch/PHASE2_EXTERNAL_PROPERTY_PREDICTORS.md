# Phase 2 External Property Predictors

This document is the canonical Phase 2 surface for external property predictors.

Phase 2 predictors are separate from native Phase 1 QLIP/SPP objectives. They produce post-hoc or orchestration-level estimates and must not be described as solver-native objectives.

## Source Of Truth

Runtime registry:

- `src/sok_llm_orchestrator/contracts/phase2_external_predictors.py`

CLI inspection:

```bash
sokllm doctor phase2-external-predictors
```

Implemented-only view:

```bash
sokllm doctor phase2-external-predictors --implemented-only
```

## Implemented Predictors

| id | backend | input | prediction_type | status | benchmark-approved | calibration | notes |
|---|---|---|---|---|---|---|---|
| `phase2.external.pymatgen_composition_descriptor` | `pymatgen` | formula | composition descriptor scalar | `implemented_now` | no | `uncalibrated_exploratory` | Computes raw formula-level descriptors: `mean_atomic_number`, `mean_atomic_mass`, `mean_electronegativity`. |

## Scaffolded Predictors

| id | backend | status | notes |
|---|---|---|---|
| `phase2.external.matminer_formation_energy_rf` | `matminer/sklearn` | `not_implemented` | Placeholder for a future trained external model. It is intentionally rejected by strict benchmark mode. |

## Request Shape

Benchmark cases and execution overrides may request external predictors with:

```json
{
  "external_predictors": [
    {
      "predictor_id": "phase2.external.pymatgen_composition_descriptor",
      "target": "mean_atomic_number",
      "use": "reporting"
    }
  ]
}
```

The normalized task/request form is:

```json
{
  "schema_version": "phase2.external_predictor_request.v1",
  "predictor_id": "phase2.external.pymatgen_composition_descriptor",
  "target": "mean_atomic_number",
  "use": "reporting",
  "value_state": "raw"
}
```

## Provenance

Every emitted prediction records:

- backend and backend version,
- predictor id,
- adapter name,
- input formula and optional structure artifact path,
- target,
- value state,
- calibration, normalization, and transformation flags.

The current pymatgen adapter emits raw values only:

- `calibration_applied: false`
- `normalization_applied: false`
- `transformation_applied: false`
- `benchmark_approved: false`
- `exploratory_only: true`

## Benchmark Rules

Strict benchmark mode rejects:

- unknown external predictor ids,
- known but non-implemented external predictors,
- malformed external predictor requests,
- unsupported predictor targets.

External predictor values appear under `external_phase2` in paired and benchmark reports. Native Phase 1 objective identity remains under native fields such as `qlip_objective_family`, `property_key`, and objective audit traces.

## Phase 3 Boundary

Paper-specific benchmark/property alignment is Phase 3. Phase 2 only establishes clean external predictor plumbing, provenance, and strictness.
