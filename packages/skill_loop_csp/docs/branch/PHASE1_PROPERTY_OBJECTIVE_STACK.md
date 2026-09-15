# Phase 1 Property/Objective Stack (QLIP + SPP)

This document is the canonical, audit-friendly Phase 1 library for Loop-CSP.

Scope for this tranche:

- objectives/properties runnable in current QLIP + SPP integration,
- downstream consumption of QLIP runtime objective families `spp_energy`, `none`,
  `density_packing`, `linear_property`, and `threshold_tradeoff`.

Out of scope here:

- external black-box property predictors (Phase 2),
- benchmark-specific paper-emulation objectives (Phase 3),
- motif objectives.

## Canonical Source

Runtime source of truth:

- `src/sok_llm_orchestrator/contracts/phase1_properties.py`

CLI inspection:

```bash
sokllm doctor phase1-properties
```

Implemented-only view:

```bash
sokllm doctor phase1-properties --implemented-only
```

## Phase 1 Table

| id | source_system | formulation_type | direction | status | benchmark-ready now | notes |
|---|---|---|---|---|---|---|
| `qlip.objective.energy_proxy` | `qlip_native` | `objective` | `maximize` | `implemented_now` | yes | Primary loop objective from `summary.objective_value`. |
| `qlip.property.property_x_estimate` | `qlip_native` | `objective` | `maximize` | `implemented_now` | yes | Only explicitly wired property-bias key (`property_x`) in current loop/report flow. |
| `spp.guidance.energy_spp_term` | `hybrid` | `guidance` | `bounded` | `implemented_now` | yes | `objective.energy_spp` is compiled/validated and visible in objective decomposition. |
| `spp.guidance.lambda_weight_override` | `hybrid` | `guidance` | `bounded` | `implemented_now` | yes | `lambda_override` is a live control knob in guidance payload. |
| `spp.calibration.recommended_lambda` | `spp_native` | `guidance` | `bounded` | `implemented_now` | yes | Auto-applied when no stronger override exists; source/value provenance is emitted in run artifacts. |
| `qlip.native.density_packing_proxy` | `qlip_native` | `objective` | `maximize` | `implemented_now` | yes | Maps to `objective.type=density_packing`, `proxy=pair_distance_packing`; this is a packing/contact proxy, not literal physical mass density. |
| `qlip.native.linear_property_proxy` | `qlip_native` | `objective` | `maximize` | `implemented_now` | yes | Maps to `objective.type=linear_property` with native occupancy-linear terms. It does not imply external hardness/modulus predictors. |
| `qlip.native.threshold_tradeoff` | `qlip_native` | `threshold` | `bounded` | `implemented_now` | yes | Maps to `objective.type=threshold_tradeoff`: hard bound over a linear property, optional `spp_energy`/`none` base, optional weighted property term. |

## Truthfulness Rules Used

- `implemented_now` means the repo can run it now through current contracts/builders/loop.
- `small_wiring_needed` remains a valid registry status, but the current Phase 1 stack has no entries in that state.
- unknown requests fail clearly through the resolver instead of silently becoming arbitrary `property_bias` strings.
- malformed `qlip_objective` payloads fail schema validation before solve.

## Current Benchmark-Ready Subset

- `qlip.objective.energy_proxy`
- `qlip.property.property_x_estimate`
- `spp.guidance.energy_spp_term`
- `spp.guidance.lambda_weight_override`
- `spp.calibration.recommended_lambda`
- `qlip.native.density_packing_proxy`
- `qlip.native.linear_property_proxy`
- `qlip.native.threshold_tradeoff`

All eight Phase 1 entries are safe to treat as runnable Phase 1 objectives/control surfaces in current benchmark runs.

## Native QLIP Objective Payloads

Density/packing:

```json
{"type": "density_packing", "proxy": "pair_distance_packing"}
```

Linear property:

```json
{
  "type": "linear_property",
  "linear_property": {
    "kind": "occupancy_linear",
    "intercept": 0.0,
    "terms": [{"species": "Ti", "coefficient": 1.0}]
  }
}
```

Threshold/tradeoff:

```json
{
  "type": "threshold_tradeoff",
  "linear_property": {
    "kind": "occupancy_linear",
    "terms": [{"species": "O", "coefficient": 1.0}]
  },
  "threshold": {"operator": ">=", "value": 0.2},
  "base": {"type": "none"},
  "property_weight": 0.4
}
```

Omitting `objective` preserves the old default behavior. Supplying `{"type": "spp_energy"}` is also accepted.

## Strict Benchmark Mode

Benchmark and experiment entry points support strict Phase 1 enforcement:

- `sokllm benchmark run --strict-phase1 true ...` (default true)
- `sokllm experiment run --strict-phase1 true ...`

Strict mode rejects:

- unresolved legacy property labels,
- malformed objective payloads,
- objective payloads whose `type` conflicts with the canonical Phase 1 request id.
