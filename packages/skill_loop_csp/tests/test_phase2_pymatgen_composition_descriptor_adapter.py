from __future__ import annotations

from sok_llm_orchestrator.external_predictors.adapters import run_external_predictors


def test_phase2_pymatgen_composition_descriptor_adapter_predicts_with_provenance() -> None:
    result = run_external_predictors(
        [
            {
                "predictor_id": "phase2.external.pymatgen_composition_descriptor",
                "target": "mean_atomic_number",
            }
        ],
        formula="TiO2",
    )
    assert result["ok"] is True
    prediction = result["predictions"][0]
    assert prediction["predictor_id"] == "phase2.external.pymatgen_composition_descriptor"
    assert abs(float(prediction["value"]) - ((22.0 + 8.0 + 8.0) / 3.0)) < 1e-9
    assert prediction["native_phase1_objective"] is False
    assert prediction["provenance"]["backend"] == "pymatgen"
    assert prediction["provenance"]["calibration_applied"] is False
    assert prediction["calibration"]["benchmark_approved"] is False
