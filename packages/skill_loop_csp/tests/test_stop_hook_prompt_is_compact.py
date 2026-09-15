from __future__ import annotations

import json

from sok_llm_orchestrator.optimization.stop_hook import build_compact_stop_hook_prompt


def test_stop_hook_prompt_is_compact() -> None:
    context = {
        "query_text": "TiO2 rutile-like optimize property x",
        "hard_constraints": {
            "composition_target": "TiO2",
            "symmetry_request": {"hardness": "hard", "space_group": "P42/mnm"},
        },
        "stuck_reason": "repeated_infeasibility",
        "infeasible_streak": 6,
        "recovery_stage": 3,
        "recovery_regime": "strong_structure_perturbation",
        "recovery_regimes_tried": [f"regime_{i}" for i in range(20)],
        "recovery_attempt_count": 9,
        "recovery_exhausted": True,
        "remaining_iterations": 2,
        "hard_constraint_boundary_reached": True,
        "task_meaning_ambiguity": False,
        "best_so_far": {"score": -999.0, "action_id": "guided_hybrid_balanced"},
        "recent_iterations": [{"huge": "x" * 2000} for _ in range(10)],
    }
    prompt = build_compact_stop_hook_prompt(context=context, allow_user_clarification=True)
    raw = json.dumps(prompt, separators=(",", ":"), sort_keys=True)
    assert len(raw) < 3000
    assert "recent_iterations" not in raw
    assert "huge" not in raw
