from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.contracts.phase3_external_predictors import (
    phase3_external_predictor_report,
    require_phase3_external_predictor_for_benchmark,
)
from sok_llm_orchestrator.external_predictors import megnet_adapters
from sok_llm_orchestrator.external_predictors.adapters import normalize_external_predictor_requests
from sok_llm_orchestrator.external_predictors.megnet_loader import (
    CANONICAL_MEGNET_MODEL_IDS,
    megnet_loader_report,
)


def _silicon_structure() -> Structure:
    lattice = Lattice.cubic(5.43)
    return Structure(lattice, ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])


def test_phase3_doctor_surface_reports_megnet_loader() -> None:
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "sok_llm_orchestrator.cli", "doctor", "phase3-external-predictors"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "phase3.external_predictor_library.v1"
    assert payload["phase1_native_objective_registry"] == "separate"
    assert payload["counts"]["implemented_now"] == 4
    assert payload["megnet_loader"]["production_loader"]["uses_megnet_utils_models_load_model"] is False


def test_megnet_loader_report_finds_canonical_models() -> None:
    report = megnet_loader_report()
    assert report["canonical_model_ids"] == list(CANONICAL_MEGNET_MODEL_IDS)
    assert report["production_loader"]["uses_paired_json_config"] is True
    assert report["production_loader"]["reconstructs_graph_model"] is True
    if not report["runtime_available"]:
        pytest.skip(report["runtime_error"])
    model_ids = {row["model_id"] for row in report["models"]}
    assert model_ids == set(CANONICAL_MEGNET_MODEL_IDS)
    assert all(row["model_exists"] for row in report["models"])
    assert all(row["config_exists"] for row in report["models"])


def test_mixed_external_predictor_normalization_accepts_phase2_and_phase3() -> None:
    requests = normalize_external_predictor_requests(
        [
            "phase2.external.pymatgen_composition_descriptor",
            {"predictor_id": "phase3.external.megnet_bulk_modulus"},
        ]
    )
    assert [item["schema_version"] for item in requests] == [
        "phase2.external_predictor_request.v1",
        "phase3.external_predictor_request.v1",
    ]
    assert requests[1]["value_state"] == "raw_log10"


def test_phase3_strict_benchmark_accepts_implemented_entry() -> None:
    request = require_phase3_external_predictor_for_benchmark("phase3.external.megnet_band_gap")
    assert request["predictor_id"] == "phase3.external.megnet_band_gap"
    assert request["target"] == "band_gap"


def test_phase3_registry_report_is_truthful_about_benchmark_status() -> None:
    report = phase3_external_predictor_report()
    assert report["counts"]["implemented_now"] == 4
    assert report["counts"]["benchmark_approved"] == 0
    assert report["counts"]["exploratory_only"] == 4
    bulk = [
        item for item in report["all_entries"] if item["id"] == "phase3.external.megnet_bulk_modulus"
    ][0]
    assert bulk["backend_model_id"] == "logK_MP_2018"
    assert bulk["unit"] == "log10(GPa)"
    assert bulk["value_state"] == "raw_log10"
    assert bulk["modulus_semantics"]["postprocess_to_linear_gpa_applied"] is False


def test_megnet_adapter_payload_preserves_raw_log_modulus_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModel:
        def predict_structure(self, _structure: Structure) -> float:
            return 1.23

    monkeypatch.setattr(megnet_adapters, "load_megnet_model", lambda _model_id: FakeModel())
    monkeypatch.setattr(megnet_adapters, "get_model_path", lambda model_id: Path(f"C:/models/{model_id}.hdf5"))
    monkeypatch.setattr(megnet_adapters, "get_config_path", lambda model_id: Path(f"C:/models/{model_id}.hdf5.json"))

    result = megnet_adapters.run_external_megnet_predictors(
        ["phase3.external.megnet_shear_modulus"],
        structure=_silicon_structure(),
    )
    assert result["ok"] is True
    prediction = result["predictions"][0]
    assert prediction["predictor_id"] == "phase3.external.megnet_shear_modulus"
    assert prediction["value"] == 1.23
    assert prediction["unit"] == "log10(GPa)"
    assert prediction["value_state"] == "raw_log10"
    assert prediction["provenance"]["backend_model_id"] == "logG_MP_2018"
    assert prediction["provenance"]["transformation_applied"] is False
    assert prediction["modulus_semantics"]["raw_model_output"] == "log10(G)"
