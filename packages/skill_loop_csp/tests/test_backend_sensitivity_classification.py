from __future__ import annotations

from sok_llm_orchestrator.optimization.backend_sensitivity import classify_backend_sensitivity


def test_backend_sensitivity_classification_categories() -> None:
    assert (
        classify_backend_sensitivity(
            unique_action_ids=2,
            unique_compiled_signatures=2,
            unique_executable_signatures=2,
            unique_objective_totals=2,
            unique_objective_term_signatures=2,
        )
        == "different_action_different_config_different_objective"
    )
    assert (
        classify_backend_sensitivity(
            unique_action_ids=3,
            unique_compiled_signatures=3,
            unique_executable_signatures=3,
            unique_objective_totals=1,
            unique_objective_term_signatures=1,
        )
        == "different_action_different_config_same_objective"
    )
    assert (
        classify_backend_sensitivity(
            unique_action_ids=3,
            unique_compiled_signatures=3,
            unique_executable_signatures=1,
            unique_objective_totals=1,
            unique_objective_term_signatures=1,
        )
        == "different_action_same_effective_request"
    )
    assert (
        classify_backend_sensitivity(
            unique_action_ids=3,
            unique_compiled_signatures=3,
            unique_executable_signatures=3,
            unique_objective_totals=1,
            unique_objective_term_signatures=2,
        )
        == "different_action_same_total_different_objective_terms"
    )

