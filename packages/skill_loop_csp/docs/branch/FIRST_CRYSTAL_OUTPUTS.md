# First Crystal Outputs

First-crystal experiments produce two top-level artifacts:

- `experiment_manifest.json`
- `first_crystal_summary.json`

under:

- `.sokllm_workspace/experiments/first_crystal/<experiment_id>/`

Repeated analysis mode adds:

- `repeated_manifest.json`
- `first_crystal_repeated_summary.json`

under:

- `.sokllm_workspace/experiments/first_crystal_repeated/<repeated_experiment_id>/`

Guided-variant sweep mode adds:

- `guided_variant_sweep_results.json`
- `guided_variant_sweep_report.json`

under:

- `.sokllm_workspace/experiments/guided_sweep/<sweep_id>/`

## Best-structure linkage model

Each case summary row includes:

- `case_id`
- `session_id`
- `best_iteration_index`
- `best_action_id`
- `best_action_family`
- `best_structure_artifact_path`
- `best_structure_linkage` (session/run linkage metadata)
- `profile` (action-profile metadata used for that case)
- `clarification_answers` (pre-supplied answers, if any)
- `action_diversity_count`
- `family_diversity_count`
- `score_diversity_count`
- `compiled_config_diversity_count`
- `executable_diversity_count`
- `best_remained_iteration_zero`
- `first_improvement_iteration`
- `flat_objective_flag`
- `likely_flatness_reason`
- `objective_total_diversity_count`
- `objective_term_signature_diversity_count`
- `backend_sensitivity_classification`
- `dimension_sensitivity_summary`
- `diagnostic_recommendation`
- `guidance_active`, `guidance_iteration_count`, `guidance_ids_used`
- `spp_term_present_count`, `initial_spp_term`, `final_best_spp_term`, `spp_term_delta`
- `initial_property_x`, `final_best_property_x`, `property_x_delta`
- `initial_objective_total`, `final_best_objective_total`, `objective_total_delta`
- `analysis_metric_view`, `analysis_metric_initial`, `analysis_metric_final_best`, `analysis_metric_delta`
- `selection_metric_view` (optimizer loop selection view used for that run)
- `progress_signal_mode` (`total_flat_property_gain`, `total_objective_improved`, etc)
- `weighting_profiles_tried`
- `structure_perturbation_profiles_tried`
- `template_seed_profiles_tried`
- `lattice_candidate_profiles_tried`
- `symmetry_relaxation_profiles_tried`
- `ordering_perturbation_profiles_tried`
- `structure_change_rate`
- `unique_structure_signature_count`
- `same_structure_despite_guidance_variation_rate`
- `dominance_warning`, `dominance_recommendation`
- `structure_change_rate_by_regime`
- `unique_structure_signature_count_by_regime`
- `property_gain_by_regime`
- `dominance_warning_by_regime`
- `recommended_structure_moving_regimes`
- `recommended_next_regime`
- `challenge_class`, `guidance_rationale`, `recommended_guidance_focus`
- `suggested_corpus_bias`, `suggested_perturbation_bias`, `suggested_structural_dimensions`
- `hypotheses`, `hypothesis_ids`, `hypothesis_count`
- `hypotheses_tried`, `active_hypothesis_by_iteration`
- `branch_switch_count`, `branch_switch_events`, `best_hypothesis_id`
- `hypothesis_branch_summary`

The linkage is derived from optimization session/report artifacts and is reproducible via summary regeneration.

## How linkage is formed

1. The optimization loop records per-iteration `run_reference`.
2. Best-so-far tracks the winning iteration index and action.
3. The optimization report resolves:
- best iteration
- best action/family
- best structure path from `run_reference.structure_artifact_path`
4. First-crystal summary copies these fields per case.

## Flatness diagnostics

The optimization report now captures per-iteration signatures and deltas so first-crystal summaries can diagnose flat runs:

- `compiled_config_signature` and `executable_signature` per iteration
- config-delta category and changed knobs
- score/objective deltas vs previous iteration

This allows operators to distinguish:

- repeated same action
- different actions collapsing to same effective execution config
- varied actions/configs with invariant backend objective

For controlled backend sensitivity checks independent of optimizer search:

```bash
sokllm experiment sensitivity --mode stub --query "TiO2 optimize high property x"
```

## Regeneration

Regenerate summary from saved artifacts without rerunning sessions:

```bash
sokllm experiment summarize --manifest <path-to-experiment_manifest.json>
```

This emits `first_crystal_summary.regenerated.json` by default.

For repeated manifests, regeneration emits `first_crystal_repeated_summary.regenerated.json` by default.

Repeated summaries include multi-view best-so-far diagnostics:

- `aggregate.view_summary.total_objective`
- `aggregate.view_summary.property_aware`
- `aggregate.preferred_variant_by_run`
- `aggregate.preferred_variant_stabilization_rate`

This is the side-by-side view for "total objective flat but property-aware progress present."

Session-level optimization reports additionally expose `regime_level_summary`
for dynamic weighting/perturbation diagnostics:

- `unique_weighting_profiles`
- `unique_structure_perturbation_profiles`
- per-regime `structure_change_rate`
- per-regime `property_gain_rate`
- per-regime dominance warning rates
- `recommended_next_regime`
