# Optimization Config

New config keys:

- `optimization_max_iterations`
- `optimization_max_solver_calls`
- `optimization_max_retrieval_calls`
- `optimization_max_failed_iterations`
- `optimization_stagnation_window`
- `optimization_exploration_rate`
- `optimization_allow_midloop_clarification`
- `optimization_selection_metric_view`
- `optimization_max_wall_clock_s`
- `optimization_action_family_limits`
- `optimization_action_allowlist`

Defaults support running optimization without overrides.

`optimization_selection_metric_view` controls which scalar is used by the loop for
selection/bandit updates (`objective_total`, `property_aware`, or
`property_decomp_aware`).

- `objective_total`: legacy total-objective-first behavior.
- `property_aware`: property-driven selection with objective as a secondary
  tie-break signal.
- `property_decomp_aware`: property + SPP/objective-decomposition-aware mode
  used for deeper guided exploration runs.

For structural live experiments:

- `live_structural` defaults to `property_aware`.
- `spp_deep_explore` defaults to `property_decomp_aware`.

The deep exploration profile also enables explicit, named regime controls that
are tracked in artifacts:

- `weighting_profile`: `base_dominant|balanced|guidance_dominant|property_push_strong|experimental_extreme`
- `structure_perturbation_profile`: `minimal|moderate|aggressive|template_shuffle`
- `template_seed_profile`: `canonical|polymorph_mix|framework_bias|ordering_bias`
- `lattice_candidate_profile`: `narrow|expanded|multibasin`
- `symmetry_relaxation_profile`: `strict|soft|relaxed`
- `ordering_perturbation_profile`: `none|site_shuffle|cation_swap_bias`

These profiles are validator-gated action settings, not free-form numeric
inputs.

For focused hard-case diagnostics, use `action_profile=hard_structure_probe`
with the `hard_structure_moving_focus_cases.json` pack.
