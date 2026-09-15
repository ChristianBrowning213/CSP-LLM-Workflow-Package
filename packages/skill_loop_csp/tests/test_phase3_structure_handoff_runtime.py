from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.external_predictors.megnet_adapters import run_external_megnet_predictors
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def _settings_for_workdir(workdir: Path) -> Settings:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    return settings


def test_phase3_prediction_succeeds_from_parseable_cif_fixture() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "phase3" / "si_parseable.cif"
    result = run_external_megnet_predictors(
        ["phase3.external.megnet_formation_energy"],
        cif_path=str(fixture),
    )
    assert result["ok"] is True
    assert result["structure_handoff"]["ok"] is True
    assert result["structure_handoff"]["source"] == "cif_path"
    assert result["structure_handoff"]["site_count"] == 2
    prediction = result["predictions"][0]
    assert prediction["predictor_id"] == "phase3.external.megnet_formation_energy"
    assert prediction["provenance"]["backend"] == "megnet"
    assert prediction["provenance"]["input_structure_source"] == "cif_path"
    assert prediction["calibration"]["benchmark_approved"] is False
    assert prediction["calibration"]["exploratory_only"] is True


def test_phase3_rejects_missing_cif_artifact() -> None:
    result = run_external_megnet_predictors(
        ["phase3.external.megnet_band_gap"],
        cif_path="C:/definitely_missing/phase3_missing.cif",
    )
    assert result["ok"] is False
    assert result["predictions"] == []
    assert result["structure_handoff"]["error_code"] == "MEGNET_CIF_PATH_MISSING"
    assert result["errors"][0]["error_code"] == "MEGNET_CIF_PATH_MISSING"


def test_phase3_rejects_unparseable_cif(workdir: Path) -> None:
    cif_path = workdir / "bad_phase3.cif"
    cif_path.write_text("not_a_cif\nthis will not parse\n", encoding="utf-8")
    result = run_external_megnet_predictors(
        ["phase3.external.megnet_band_gap"],
        cif_path=str(cif_path),
    )
    assert result["ok"] is False
    assert result["structure_handoff"]["error_code"] == "MEGNET_CIF_PARSE_FAILED"
    assert result["errors"][0]["error_code"] == "MEGNET_CIF_PARSE_FAILED"


def test_phase3_rejects_structurally_incomplete_cif(workdir: Path) -> None:
    cif_path = workdir / "incomplete_phase3.cif"
    cif_path.write_text(
        "\n".join(
            [
                "data_incomplete",
                "_symmetry_space_group_name_H-M 'P 1'",
                "_cell_length_a 4.00000000",
                "_cell_length_b 4.00000000",
                "_cell_length_c 4.00000000",
                "_cell_angle_alpha 90.00000000",
                "_cell_angle_beta 90.00000000",
                "_cell_angle_gamma 90.00000000",
                "_chemical_formula_sum 'Ti O2'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_external_megnet_predictors(
        ["phase3.external.megnet_bulk_modulus"],
        cif_path=str(cif_path),
    )
    assert result["ok"] is False
    assert result["structure_handoff"]["error_code"] == "MEGNET_CIF_STRUCTURALLY_INCOMPLETE"
    assert result["errors"][0]["error_code"] == "MEGNET_CIF_STRUCTURALLY_INCOMPLETE"


def test_phase3_rejects_invalid_or_missing_structure_inputs() -> None:
    invalid = run_external_megnet_predictors(
        ["phase3.external.megnet_shear_modulus"],
        structure=object(),
    )
    assert invalid["ok"] is False
    assert invalid["structure_handoff"]["error_code"] == "MEGNET_STRUCTURE_OBJECT_INVALID"

    missing = run_external_megnet_predictors(
        ["phase3.external.megnet_shear_modulus"],
    )
    assert missing["ok"] is False
    assert missing["structure_handoff"]["error_code"] == "MEGNET_STRUCTURE_INPUT_MISSING"


def test_phase3_pipeline_runtime_succeeds_with_parseable_stub_cif(workdir: Path) -> None:
    settings = _settings_for_workdir(workdir)
    run = run_csp_pipeline(
        query="TiO2 external predictor phase3.external.megnet_formation_energy",
        with_spp=False,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={"guidance_mode": "none"},
    )
    assert run.status == "SUCCEEDED"
    payload = json.loads((run.run_dir / "artifacts" / "external_predictions.json").read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["phase3_structure_handoff"]["ok"] is True
    assert payload["phase3_structure_handoff"]["source"] == "cif_path"
    prediction = payload["predictions"][0]
    assert prediction["predictor_id"] == "phase3.external.megnet_formation_energy"
    assert prediction["provenance"]["backend"] == "megnet"
    assert prediction["calibration"]["calibration_status"] == "not_calibrated"
    assert prediction["calibration"]["validation_status"] == "not_validated"
    assert prediction["calibration"]["benchmark_approved"] is False
    assert prediction["calibration"]["exploratory_only"] is True


def test_phase3_pipeline_reports_structure_handoff_failure_truthfully(
    monkeypatch,
    workdir: Path,
) -> None:
    monkeypatch.setenv("FAKE_QLIP_INCOMPLETE_CIF", "1")
    settings = _settings_for_workdir(workdir)
    run = run_csp_pipeline(
        query="TiO2 external predictor phase3.external.megnet_band_gap",
        with_spp=False,
        mode="stub",
        workspace=workdir,
        settings=settings,
        execution_overrides={"guidance_mode": "none"},
    )
    assert run.status == "FAILED"
    payload = json.loads((run.run_dir / "artifacts" / "external_predictions.json").read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["phase3_structure_handoff"]["ok"] is False
    assert payload["phase3_structure_handoff"]["error_code"] == "MEGNET_CIF_STRUCTURALLY_INCOMPLETE"
    assert payload["errors"][0]["error_code"] == "MEGNET_CIF_STRUCTURALLY_INCOMPLETE"
    manifest = json.loads((run.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "external_predictions_failed" in str(manifest.get("failure_reason"))
