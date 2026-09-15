import pytest
from pymatgen.core import Structure
from sok_llm_orchestrator.external_predictors.megnet_loader import load_megnet_graphmodel
from sok_llm_orchestrator.external_predictors.megnet_adapters import run_external_megnet_predictors

# Simple silicon diamond structure (from pymatgen) used for quick testing
silicon = Structure.from_file("tests/structures/Si.cif") if False else None

# Test loader resolution
@pytest.mark.parametrize("model_id", ["Eform_MP_2018", "Bandgap_MP_2018", "logK_MP_2018", "logG_MP_2018"])
def test_loader_resolves_and_loads(model_id):
    graph = load_megnet_graphmodel(model_id)
    assert graph is not None
    assert hasattr(graph, "predict")

# Test a full prediction flow (requires a valid structure)
# def test_megnet_prediction_flow():
#     if silicon is None:
#         return
#     request = ["phase3.external.megnet_formation_energy"]
#     result = run_external_megnet_predictors(request, structure=silicon)
#     assert result["ok"]
#     assert len(result["predictions"]) == 1
#     pred = result["predictions"][0]
#     assert pred["value_state"] in {"raw", "raw_log10"}
#     assert "model_file" in pred
