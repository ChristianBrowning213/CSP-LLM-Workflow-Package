from __future__ import annotations

from sok_llm_orchestrator.optimization.backend_sensitivity import build_request_objective_diff_summary


def test_request_objective_diff_summary_detects_changes() -> None:
    baseline = {
        "compiled_action": {
            "action_id": "baseline_control",
            "action_family": "baseline_control",
            "compiled_id": "a",
            "execution_mode": "paired",
            "query_suffix": "",
            "guided_with_spp": False,
            "baseline_overrides": {"retrieval_mode": "metadata"},
            "guided_overrides": {"retrieval_mode": "metadata", "guidance_mode": "none"},
        },
        "request_trace": {
            "qlip_request_signature": "req-a",
            "effective_overrides": {"retrieval_mode": "metadata", "guidance_mode": "none"},
        },
        "objective_audit": {
            "objective_total": 0.2,
            "objective_terms_signature": "terms-a",
            "solver_summary": {"status": "ok"},
        },
        "run_reference": {"structure_artifact_path": "a.cif"},
    }
    variant = {
        "compiled_action": {
            "action_id": "guided_hybrid_balanced",
            "action_family": "guided_exploit",
            "compiled_id": "b",
            "execution_mode": "paired",
            "query_suffix": "",
            "guided_with_spp": True,
            "baseline_overrides": {"retrieval_mode": "metadata"},
            "guided_overrides": {"retrieval_mode": "hybrid", "guidance_mode": "guidance_only"},
        },
        "request_trace": {
            "qlip_request_signature": "req-b",
            "effective_overrides": {"retrieval_mode": "hybrid", "guidance_mode": "guidance_only"},
        },
        "objective_audit": {
            "objective_total": 0.45,
            "objective_terms_signature": "terms-b",
            "solver_summary": {"status": "ok", "n_terms": 2},
        },
        "run_reference": {"structure_artifact_path": "b.cif"},
    }
    diff = build_request_objective_diff_summary(baseline, variant)
    assert diff["compiled_config_diff"]["changed"] is True
    assert "guided_overrides" in diff["compiled_config_diff"]["changed_top_level_keys"]
    assert set(diff["executable_request_diff"]["changed_effective_override_keys"]) == {
        "guidance_mode",
        "retrieval_mode",
    }
    assert diff["objective_diff"]["objective_total_changed"] is True
    assert diff["objective_diff"]["objective_terms_changed"] is True
    assert diff["objective_diff"]["solver_summary_changed"] is True
    assert diff["artifact_diff"]["changed"] is True

