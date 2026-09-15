# First Crystal Experiment Protocol

This protocol defines a small, fixed, reproducible first pass for crystal-generation experiments.

## Purpose

- Run bounded optimization sessions over a fixed case pack.
- Capture best-so-far crystal outputs per case.
- Summarize initial vs final score changes without overclaiming.

## Recommended first run

1. Case pack: `docs/branch/benchmarks/first_crystal_cases.json`
2. Mode: `stub` first, then `live` only in configured environments
3. Budget:
- `max_iterations`: `3` to `5`
- keep solver/retrieval caps small and fixed across cases
4. Reward version: `v1`
5. Action profile: `default`
   - For live runs where early clarification stalls are common, use `live_assisted`
6. Execution: sequential only

## Command

```bash
sokllm experiment run --mode stub --cases docs/branch/benchmarks/first_crystal_cases.json --max-iterations 4
```

Repeated structural-focused analysis run (bounded):

```bash
sokllm experiment run --mode live --cases docs/branch/benchmarks/first_crystal_cases.json --max-iterations 3 --repeats 3 --action-profile live_structural --analysis-metric-view property_x --selection-view property_aware --clarification-answer "symmetry soft"
```

Hard structural-guidance run (recommended next diagnostic pack):

```bash
sokllm experiment run --mode live --cases docs/branch/benchmarks/hard_structural_guidance_cases.json --max-iterations 6 --repeats 4 --action-profile live_structural --analysis-metric-view property_x --selection-view property_aware --clarification-answer "symmetry soft"
```

`live_structural` defaults to a narrowed structural allowlist:

- `guided_property_push`
- `guided_hybrid_balanced`

Multi-hypothesis complex run (richer branching benchmark problem):

```bash
sokllm experiment run --mode live --cases docs/branch/benchmarks/multi_hypothesis_complex_cases.json --max-iterations 6 --repeats 3 --action-profile multi_hypothesis_branching --analysis-metric-view property_x --selection-view property_decomp_aware --include-baseline-control --clarification-answer "explore multiple structural hypotheses before convergence"
```

This protocol is intended for richer optimizer branching across:

- structural hypothesis families
- corpus/package choices
- guidance weighting
- perturbation regimes

Adversarial hard-pack run (misleading priors + weak support + branch recovery):

```bash
sokllm experiment run --mode live --cases docs/branch/benchmarks/adversarial_hard_crystal_cases.json --max-iterations 7 --repeats 3 --action-profile multi_hypothesis_branching --analysis-metric-view property_x --selection-view property_decomp_aware --include-baseline-control --clarification-answer "recover from wrong structural hypotheses if branches stagnate"
```

Use this pack to stress:

- low-support hypothetical behavior
- broad-corpus failure recovery
- ordering/framework/polymorph branch traps

Baseline is optional control-only and can be included explicitly:

```bash
sokllm experiment run --mode live --cases docs/branch/benchmarks/first_crystal_cases.json --max-iterations 3 --repeats 2 --action-profile live_structural --analysis-metric-view property_x --selection-view property_aware --include-baseline-control
```

Live-assisted variant with pre-supplied clarification context:

```bash
sokllm experiment run --mode live --cases docs/branch/benchmarks/first_crystal_cases.json --max-iterations 4 --action-profile live_assisted --clarification-answer "symmetry soft" --clarification-answer "optimize objective first"
```

This writes:
- experiment manifest
- per-case session links
- first-crystal summary

To inspect why a session did or did not improve:

```bash
sokllm optimize diagnose --session-id <session_id>
```

For repeated-run regeneration from artifacts:

```bash
sokllm experiment summarize --manifest <path-to-repeated_manifest.json>
```

For bounded structural-variant productivity sweeps:

```bash
sokllm experiment guided-sweep --mode live --cases docs/branch/benchmarks/first_crystal_cases.json --repeats 2 --variants baseline_control,guided_hybrid_balanced,guided_property_push --metric-view property_aware
```

For deeper in-loop SPP exploration with dynamic weighting and perturbation
regimes:

```bash
sokllm experiment run --mode live --cases docs/branch/benchmarks/first_crystal_cases.json --max-iterations 3 --action-profile spp_deep_explore --selection-view property_decomp_aware --analysis-metric-view property_x --clarification-answer "prioritize structural diversity while staying composition-consistent"
```

`spp_deep_explore` is the bounded profile for richer guided exploration and
includes named regime controls (`weighting_profile`,
`structure_perturbation_profile`) so stagnation escalation can move to stronger
regimes while remaining validator-gated.

Focused hard-case structure-moving protocol (3-case diagnostic subset):

```bash
sokllm experiment run --mode live --cases docs/branch/benchmarks/hard_structure_moving_focus_cases.json --max-iterations 3 --action-profile hard_structure_probe --selection-view property_decomp_aware --analysis-metric-view property_x --clarification-answer "prioritize basin diversity with composition consistency"
```

`hard_structure_probe` keeps the run bounded and biases action selection toward
structure-moving controls:

- `template_seed_profile`
- `lattice_candidate_profile`
- `symmetry_relaxation_profile`
- `ordering_perturbation_profile`

To run a forced legal-action backend sensitivity check:

```bash
sokllm experiment sensitivity --mode stub --query "TiO2 optimize high property x"
```

## What must be held fixed

- case pack
- budget settings
- reward/scoring version
- action profile
- execution family (optimization)

Changing these turns it into a different experiment.

## What to inspect after run

For each case:
- initial score
- final best score
- improvement delta
- stop reason
- best iteration/action
- linked best structure artifact path

## Interpreting improvement

Use this tranche only for controlled optimizer-behavior interpretation:
- objective-level improvement under fixed protocol
- action-path traceability
- structure-artifact linkage
- repeated-run movement in `property_x`, SPP-term presence, and guidance activation
- treat total objective as a core signal, but not the only signal in repeated live analysis

Do not interpret this tranche as physical validation, synthesis viability, or broad discovery proof.
