from __future__ import annotations

from sok_llm_orchestrator.contracts.phase2_external_predictors import (
    list_phase2_external_predictors,
    phase2_external_predictor_report,
    validate_phase2_external_predictor_registry,
)


def test_phase2_external_predictor_registry_is_separate_and_machine_readable() -> None:
    validate_phase2_external_predictor_registry()
    report = phase2_external_predictor_report()
    assert report["schema_version"] == "phase2.external_predictor_library.v1"
    assert report["phase1_native_objective_registry"] == "separate"
    assert report["counts"]["implemented_now"] == 1
    assert report["counts"]["not_implemented"] == 1


def test_phase2_external_predictor_registry_entries_include_provenance_metadata() -> None:
    rows = {item.id: item.to_dict() for item in list_phase2_external_predictors()}
    implemented = rows["phase2.external.pymatgen_composition_descriptor"]
    assert implemented["backend"] == "pymatgen"
    assert implemented["implementation_status"] == "implemented_now"
    assert implemented["benchmark_approved"] is False
    assert implemented["calibration_status"] == "uncalibrated_exploratory"
    assert "backend_version" in implemented["provenance_requirements"]
