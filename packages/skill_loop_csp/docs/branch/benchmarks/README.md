# Internal Rediscovery Benchmark Pack

Case file: `internal_rediscovery_cases.json`
Optimization behavior pack: `internal_optimization_behavior_cases.json`
First-crystal pack: `first_crystal_cases.json`
Complex first-crystal pack: `complex_first_crystal_cases.json`
Hard structural-guidance pack: `hard_structural_guidance_cases.json`
Hard structure-moving focus pack: `hard_structure_moving_focus_cases.json`
Multi-hypothesis complex pack: `multi_hypothesis_complex_cases.json`
Adversarial hard pack: `adversarial_hard_crystal_cases.json`
External staged datasets:
- `benchmarks/external/mp_20/raw/{train,val,test}.lmdb`
- `benchmarks/external/perov_5/raw/{train,val,test}.lmdb`
- `benchmarks/external/mpts_52/raw/{train,val,test}.lmdb`

Usage:

- `sokllm benchmark run --mode stub --cases docs/branch/benchmarks/internal_rediscovery_cases.json`
- `sokllm benchmark run --mode stub --execution-family optimization --cases docs/branch/benchmarks/internal_optimization_behavior_cases.json`
- `sokllm experiment run --mode stub --cases docs/branch/benchmarks/first_crystal_cases.json --max-iterations 4`
- `sokllm experiment run --mode live --cases docs/branch/benchmarks/complex_first_crystal_cases.json --max-iterations 6 --repeats 8 --action-profile live_structural --analysis-metric-view property_x --selection-view property_aware`
- `sokllm experiment run --mode live --cases docs/branch/benchmarks/hard_structural_guidance_cases.json --max-iterations 6 --repeats 4 --action-profile live_structural --analysis-metric-view property_x --selection-view property_aware`
- `sokllm experiment run --mode live --cases docs/branch/benchmarks/hard_structure_moving_focus_cases.json --max-iterations 3 --action-profile hard_structure_probe --analysis-metric-view property_x --selection-view property_decomp_aware`
- `sokllm experiment run --mode live --cases docs/branch/benchmarks/multi_hypothesis_complex_cases.json --max-iterations 6 --repeats 3 --action-profile multi_hypothesis_branching --analysis-metric-view property_x --selection-view property_decomp_aware --include-baseline-control`
- `sokllm experiment run --mode live --cases docs/branch/benchmarks/adversarial_hard_crystal_cases.json --max-iterations 7 --repeats 3 --action-profile multi_hypothesis_branching --analysis-metric-view property_x --selection-view property_decomp_aware --include-baseline-control`
- `sokllm benchmark import-external --dataset all`
- `sokllm benchmark run-external --mode stub --dataset all --splits test --regimes all --max-cases-per-split 4 --max-iterations 3 --selection-view property_decomp_aware`
- `sokllm benchmark regenerate-external --results .sokllm_workspace/benchmarks/external_matrix/<matrix_id>/external_benchmark_matrix_results.json`
- `sokllm benchmark compare-external --left <report_a.json> --right <report_b.json>`

This pack is designed for deterministic stub execution first, then live-mode expansion later.

## Current Regularised SPP Weighting Default

The current recommended regularised SPP setting for medium-size
paper-evidence-style runs is Config C from the 100-case regularised weight
optimisation sweep:

```text
--spp-guidance-weight 10.0
--spp-regularisation-weight 2.0
--spp-missing-pair-policy soft_repulsive
```

This default uses task/retrieval SPP as query-specific soft guidance,
ICSD/global SPP as a broad contact-realism regulariser, and `soft_repulsive` as
missing-pair fallback. It does not introduce hard prototypes, fixed Wyckoff
templates, or physical-stability claims.

Config C is recommended because it improved final-CIF rate and live Robocrys
intent alignment over the earlier Config A baseline while keeping zero
`<1.5 A` contacts. Config F remains a high-yield experimental setting, but is
not the default because one MgCO3/magnesite case produced a `1.15 A` contact.

Detailed report:

- `docs/WEIGHT_OPTIMISATION_100_REGULARISED.md`

The detailed report includes plots of final CIF rate, short-contact warnings,
rule rank score, and the A/C/F live-LLM comparison.

## Why The Hard Structural-Guidance Pack Exists

This pack targets a specific question for the current branch:

- does structural guidance help on cases with genuine motif/framework/ordering ambiguity?

It is intentionally small (5 cases) and focused on challenge types where `qlip_guidance` and SPP-conditioned guidance should matter:

- `polymorph_ambiguous`: `SrTiO3`, `BaTiO3`
- `framework_sensitive`: `Na3Zr2Si2PO12` (NASICON-like)
- `coordination_sensitive`: `MgAl2O4` (spinel-like tetrahedral/octahedral roles)
- `ordering_sensitive`: `Sr2FeMoO6` (double-perovskite-like B-site ordering)

## First Protocol Recommendation

Use a bounded protocol first:

- `action_profile`: `live_structural`
- `analysis_metric_view`: `property_x`
- `selection_metric_view`: `property_aware`
- repeats: `4`
- max iterations: `6`
- structural allowlist: `guided_property_push`, `guided_hybrid_balanced`

Interpret success primarily from guidance-sensitive signals:

- guidance activation and guidance IDs
- SPP-term presence/objective-term movement
- `property_x` movement under repeated runs

Treat total objective as a secondary comparison view when it stays flat.

## Focused Structure-Moving Protocol

Use `hard_structure_moving_focus_cases.json` when diagnosing whether new
perturbation semantics can move solved structures on the most relevant hard
classes:

- `hard_srtio3_polymorph`
- `hard_na3zr2si2po12_framework`
- `hard_sr2femoo6_ordering`

Recommended initial mode:

- `action_profile`: `hard_structure_probe`
- `analysis_metric_view`: `property_x`
- `selection_metric_view`: `property_decomp_aware`
- max iterations: `3` (bounded diagnostic run)

## Multi-Hypothesis Complex Pack

This pack targets a richer decision problem than prior hard packs: each case
contains multiple plausible structural hypotheses so the optimizer has to branch
across:

- hypothesis family
- retrieval corpus strategy
- SPP package/payload settings
- guidance weighting
- perturbation regime

Included cases:

- `mh_srtio3_polymorph` (`SrTiO3`)
- `mh_batio3_polymorph` (`BaTiO3`)
- `mh_na3zr2si2po12_framework` (`Na3Zr2Si2PO12`)
- `mh_sr2femoo6_ordering` (`Sr2FeMoO6`)

Recommended first protocol:

- `action_profile`: `multi_hypothesis_branching` (or `spp_deep_explore` for a less branch-focused control)
- `analysis_metric_view`: `property_x`
- `selection_metric_view`: `property_decomp_aware`
- repeats: `3`
- max iterations: `6`
- include baseline control: `true` (as explicit comparator)

Success signals to inspect first:

- hypothesis-switch evidence per case (row-level `hypothesis_ids` + selected actions)
- corpus/package/payload diversity
- structure-change diagnostics
- property movement under guided hypotheses, even when total objective is flat

## Adversarial Hard Pack

This pack is intentionally adversarial: each case is designed to stress a
different optimizer failure mode where wrong priors, weak corpus support, or
early branch collapse can dominate.

Included cases and probe intent:

- `adv_li4brocl_unseen`: low-support hypothetical mixed-anion case
- `adv_coas2_hard_rediscovery`: broad-corpus rediscovery trap
- `adv_sr2femoo6_ordering`: ordering-sensitive basin trap
- `adv_na3zr2si2po12_framework`: framework/topology ambiguity trap
- `adv_batio3_polymorph`: polymorph early-collapse trap

Recommended first protocol:

- `action_profile`: `multi_hypothesis_branching`
- `selection_metric_view`: `property_decomp_aware`
- `analysis_metric_view`: `property_x`
- repeats: `3`
- max iterations: `7`
- include baseline control: `true`

Primary success signals:

- branch switches under stagnation
- hypothesis diversity (`hypotheses_tried`)
- corpus/package/weighting/perturbation diversity under adversarial cases
- structure-change and property movement by branch, even when total objective is flat

## External Benchmark Matrix (MP-20 / Perov-5 / MPTS-52)

The external matrix path is designed for local staged data only and supports:

- dataset normalization from LMDB to JSONL
- bounded baseline/orchestrator matrix runs
- regeneration from saved matrix artifacts
- report-to-report comparison

Regimes:

- `qlip_baseline`
- `qlip_fixed_spp`
- `qlip_retrieval_spp`
- `qlip_full_orchestrator`

Grouped reporting dimensions:

- dataset
- split
- regime
- budget (`max_iterations`)

See:

- `docs/branch/benchmarks/external/EXTERNAL_BENCHMARK_SETUP.md`
