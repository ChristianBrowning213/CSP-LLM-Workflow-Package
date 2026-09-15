from __future__ import annotations

from sok_llm_orchestrator.optimization.backend_sensitivity import classify_override_propagation


def test_override_propagation_classification_rules() -> None:
    dropped = {
        "compiled_config_diff": {"changed": True},
        "builder_input_diff": {"changed": False, "variant_dropped_override_keys": ["retrieval_mode"]},
        "executable_request_diff": {"request_structure_changed": False},
        "objective_diff": {"changed": False},
    }
    assert classify_override_propagation(dropped, override_key="retrieval_mode") == "dropped_before_request"

    metadata_only = {
        "compiled_config_diff": {"changed": True},
        "builder_input_diff": {"changed": True, "variant_dropped_override_keys": []},
        "executable_request_diff": {
            "request_structure_changed": False,
            "guidance_structure_changed": False,
            "constraint_structure_changed": False,
            "objective_structure_changed": False,
        },
        "objective_diff": {"changed": False},
    }
    assert classify_override_propagation(metadata_only) == "changes_request_metadata_only"

    propagated_no_effect = {
        "compiled_config_diff": {"changed": True},
        "builder_input_diff": {"changed": True, "variant_dropped_override_keys": []},
        "executable_request_diff": {
            "request_structure_changed": True,
            "guidance_structure_changed": True,
            "constraint_structure_changed": False,
            "objective_structure_changed": True,
        },
        "objective_diff": {"changed": False},
    }
    assert classify_override_propagation(propagated_no_effect) == "propagates_but_no_backend_effect"

    propagated_structure = {
        "compiled_config_diff": {"changed": True},
        "builder_input_diff": {"changed": True, "variant_dropped_override_keys": []},
        "executable_request_diff": {
            "request_structure_changed": True,
            "guidance_structure_changed": True,
            "constraint_structure_changed": False,
            "objective_structure_changed": True,
        },
        "objective_diff": {"changed": True},
    }
    assert classify_override_propagation(propagated_structure) == "propagates_to_request_structure"

