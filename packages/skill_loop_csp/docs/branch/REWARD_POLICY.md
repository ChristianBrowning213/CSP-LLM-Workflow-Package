# Reward Policy (v1)

This branch optimizes a single scalar derived from each iteration outcome:

- `score = primary_objective` for feasible runs
- infeasible runs receive a large penalty (`score -= infeasible_penalty`)
- missing objective (`primary_objective is None`) is treated as invalid/scored at `-infeasible_penalty`

Implementation reference: `src/sok_llm_orchestrator/optimization/scoring.py`.

## Exact v1 behavior

1. **Primary scalar optimized**
- `primary_objective` from the iteration reward record.
- `objective_direction="maximize"` in the current loop path.

2. **Feasible vs infeasible**
- Feasible: score is objective (or negated objective if minimize mode is requested).
- Infeasible: score is objective minus the fixed infeasible penalty.

3. **Invalid-run handling**
- Reward records include `valid_for_learning`.
- Invalid runs can be scored for traceability but are excluded from policy updates when `valid_for_learning=False`.

4. **Tie behavior**
- Best-result promotion is strict-greater-only.
- Equal scores do not replace current best (deterministic first-winner retention).

5. **Recorded but not directly optimized in v1**
- `novelty`, `property_estimate`, `analogue_quality`, `solver_stability`.
- These are preserved in artifacts/reporting for analysis and future policy versions.

6. **Novelty extension point**
- Novelty can be added as a weighted term (`novelty_weight`) without changing current v1 default behavior.
- In current loop operation, novelty weight is effectively zero.

## Scope discipline

This reward policy supports branch claims about objective improvement under a fixed composition/objective contract.
It does not imply validated physical-property optimization beyond solver-emitted estimates.

