from __future__ import annotations

from sok_llm_orchestrator.verification.qlip_outputs import validate_qlip_outputs


def test_qlip_outputs_validation() -> None:
    payload = {
        "result": {
            "result": {
                "outputs": {
                    "objective_terms": [{"term": "baseline", "value": 1.0}, {"term": "SPP", "value": -0.3}]
                }
            }
        }
    }
    report = validate_qlip_outputs(payload, guidance_expected=True)
    assert report["ok"] is True
    assert report["objective_metadata"]["objective_terms"] == payload["result"]["result"]["outputs"]["objective_terms"]


def test_qlip_outputs_validation_preserves_live_solver_error_diagnostics() -> None:
    payload = {
        "result": {
            "ok": True,
            "result": {
                "status": "ERROR",
                "error": "SPP POT file not found for pair Ba-Ba",
                "outputs": {"cif": None},
                "certificates": {
                    "diagnostics": {
                        "spp_guidance": {
                            "mode": "partial",
                            "missing_pair_policy": "soft_repulsive",
                            "regularisation_spp_dir": r"C:\Users\brown\Downloads\SPP\SPP\SPP\SPP",
                            "regularisation_weight": 2.0,
                        }
                    }
                },
            },
        }
    }
    report = validate_qlip_outputs(payload, guidance_expected=True)
    assert report["ok"] is False
    assert "qlip_solver_status:ERROR" in report["errors"]
    assert any(error.startswith("qlip_solver_error:SPP POT file not found") for error in report["errors"])
    assert report["objective_metadata"]["spp_guidance"]["missing_pair_policy"] == "soft_repulsive"


def test_qlip_outputs_validation_reports_missing_objective_metadata_clearly() -> None:
    payload = {"result": {"result": {"status": "SUCCESS", "outputs": {"cif": "out.cif"}}}}
    report = validate_qlip_outputs(payload, guidance_expected=True)
    assert report["ok"] is False
    assert report["errors"] == ["objective_metadata_missing"]
