from __future__ import annotations

from sok_llm_orchestrator.optimization.infeasibility_recovery import (
    derive_recovery_state,
    recovery_regime_for_stage,
)


def test_recovery_ladder_escalates_regimes() -> None:
    history_0 = [{"feasible": True}]
    history_1 = [{"feasible": False}]
    history_3 = [{"feasible": False}, {"feasible": False}, {"feasible": False}]
    history_5 = [{"feasible": False} for _ in range(5)]
    history_6 = [{"feasible": False} for _ in range(6)]

    s0 = derive_recovery_state(iteration_history=history_0, repeated_infeasible_limit=3)
    s1 = derive_recovery_state(iteration_history=history_1, repeated_infeasible_limit=3)
    s3 = derive_recovery_state(iteration_history=history_3, repeated_infeasible_limit=3)
    s5 = derive_recovery_state(iteration_history=history_5, repeated_infeasible_limit=3)
    s6 = derive_recovery_state(iteration_history=history_6, repeated_infeasible_limit=3)

    assert s0.stage == 0
    assert s1.stage == 1
    assert s3.stage == 3
    assert s3.regime == recovery_regime_for_stage(3)
    assert s5.stage == 5
    assert s5.regime == recovery_regime_for_stage(5)
    assert s6.stage == 5
