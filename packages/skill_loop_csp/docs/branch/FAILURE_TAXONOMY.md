# Failure Taxonomy (v1)

The optimizer emits a stable failure taxonomy in optimization reports.

Implementation reference: `src/sok_llm_orchestrator/optimization/failure_taxonomy.py`.

## Categories

1. **repeated_infeasibility**
- Triggered when blocked state reason is repeated infeasibility.
- Typical response: clarify/relax constraints.

2. **stagnation**
- Triggered when blocked state reason indicates objective stagnation.
- Typical response: increase exploration or request chemist guidance.

3. **invalid-action rejection**
- Triggered when LLM action proposals are rejected and fallback is used.
- Typical response: continue with legal fallback and keep logging.

4. **budget_exhaustion**
- Triggered when termination reason starts with `budget_exhausted:`.
- Typical response: stop or increase budget limits.

5. **blocked-clarification-needed**
- Triggered when termination reason is `midloop_clarification_required`.
- Typical response: wait for chemist clarification input.

6. **oscillation** (supported heuristic)
- Triggered by alternating action-family pattern in the latest window (A/B/A/B).
- Typical response: constrain action-family switching or reduce exploration.

7. **unclassified**
- Fallback for stopped/failed sessions without a specific detected class.

## Output shape

Reports include:
- `primary_category`
- `categories` (ordered stable list)
- `termination_reason`
- `recommended_next_step`

This taxonomy is diagnostic control logic, not a scientific claim by itself.

