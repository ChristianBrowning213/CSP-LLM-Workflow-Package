from __future__ import annotations

from sok_llm_orchestrator.optimization.backend_sensitivity import classify_override_key_effect


def test_override_key_classification_rules() -> None:
    assert (
        classify_override_key_effect(
            {
                "compiled_config_diff": {"changed": True, "metadata_only_compiled_change": False},
                "executable_request_diff": {"changed": True},
                "objective_diff": {"changed": True},
            }
        )
        == "objective_coupled"
    )
    assert (
        classify_override_key_effect(
            {
                "compiled_config_diff": {"changed": True, "metadata_only_compiled_change": False},
                "executable_request_diff": {"changed": True},
                "objective_diff": {"changed": False},
            }
        )
        == "request_changes_no_objective_effect"
    )
    assert (
        classify_override_key_effect(
            {
                "compiled_config_diff": {"changed": True, "metadata_only_compiled_change": True},
                "executable_request_diff": {"changed": False},
                "objective_diff": {"changed": False},
            }
        )
        == "metadata_only"
    )
    assert (
        classify_override_key_effect(
            {
                "compiled_config_diff": {"changed": True, "metadata_only_compiled_change": False},
                "executable_request_diff": {"changed": False},
                "objective_diff": {"changed": False},
            }
        )
        == "same_effective_request"
    )
    assert (
        classify_override_key_effect(
            {
                "compiled_config_diff": {"changed": False, "metadata_only_compiled_change": False},
                "executable_request_diff": {"changed": False},
                "objective_diff": {"changed": False},
            }
        )
        == "unclear"
    )

