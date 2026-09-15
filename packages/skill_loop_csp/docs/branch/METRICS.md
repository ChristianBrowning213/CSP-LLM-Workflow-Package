# Metrics Schema

Metrics payload schema: `metrics.result.v1`.

Required per-run row fields:

- `feasible`
- `time_to_first_feasible_s`
- `objective_value`
- `retry_count`
- `analogue_distance`
- `space_group_match`
- `evidence_completeness`
- `reproducible`

This schema is used for:

- benchmark reports,
- pairwise baseline-vs-guided comparisons,
- regression comparisons over bounded iterations.

Property-aware comparisons:

- paired reports include `property_key`, `baseline_property`, `guided_property`,
  and `property_assertion_status`.
- benchmark reports aggregate property assertion pass/fail counts when such values are available.
