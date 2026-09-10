from llm_csp.generation import compile_qlip_request
from llm_csp.schemas import CSPWorkflowRequest, GenerationConfig, SPPConfig


def _request():
    return CSPWorkflowRequest(
        "SrTiO3", "SrTiO3",
        {
            "template": {"name": "cubic", "lattice": {"a": 3.9, "b": 3.9, "c": 3.9, "alpha": 90.0, "beta": 90.0, "gamma": 90.0, "units": "angstrom"}},
            "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
        },
    )


def test_regulator_only_weight_and_context() -> None:
    pairs = ["O-O", "O-Sr", "O-Ti", "Sr-Sr", "Sr-Ti", "Ti-Ti"]
    spp = {
        "ready": True, "required_pairs": pairs, "request_supported_pairs": [],
        "regulator_fallback_pairs": pairs, "request_root": "request", "regulator_root": "regulator",
    }
    config = SPPConfig(request_mode="disabled", outer_objective_scale=10, regulator_coefficient=2)
    compiled = compile_qlip_request(
        request=_request(), spp=spp, spp_config=config,
        generation=GenerationConfig(), run_id="run",
    )
    assert compiled["guidance"][0]["weight"] == 20
    assert compiled["guidance"][0]["params"]["mode"] == "complete"
    assert compiled["context"]["pot_root"] == "regulator"


def test_mixed_request_uses_partial_plus_regulator_contract() -> None:
    spp = {
        "ready": True, "required_pairs": ["O-O", "O-Sr"],
        "request_supported_pairs": ["O-O"], "regulator_fallback_pairs": ["O-Sr"],
        "request_root": "request", "regulator_root": "regulator",
    }
    compiled = compile_qlip_request(
        request=_request(), spp=spp, spp_config=SPPConfig(),
        generation=GenerationConfig(), run_id="run",
    )
    params = compiled["guidance"][0]["params"]
    assert params["mode"] == "partial"
    assert params["supported_pairs"] == ["O-O"]
    assert params["missing_pairs"] == ["O-Sr"]
    assert params["regularisation_weight"] == 2.0
