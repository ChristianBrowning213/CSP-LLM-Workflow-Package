from pathlib import Path

from sca.pipelines.crystallm_style import evaluate_one_cif
from sca.schemas import AlignnResult


FIXTURES = Path(__file__).parent / "fixtures"


def test_crystallm_pipeline_valid_record() -> None:
    record, structure = evaluate_one_cif(FIXTURES / "tiny_valid.cif", target_formula="NaCl")

    assert structure is not None
    assert record.parse_ok is True
    assert record.target_formula_match is True
    assert record.pre_dft_valid is True


def test_crystallm_pipeline_alignn_is_mockable(monkeypatch) -> None:
    def fake_predict(path, model_name="mp_e_form_alignn"):
        return AlignnResult(
            alignn_ok=True,
            alignn_model=model_name,
            formation_energy_per_atom=-3.0,
        )

    monkeypatch.setattr("sca.pipelines.crystallm_style.predict_alignn_formation_energy", fake_predict)

    record, _ = evaluate_one_cif(FIXTURES / "tiny_valid.cif", run_alignn=True)

    assert record.alignn_ok is True
    assert record.formation_energy_per_atom == -3.0
