from pathlib import Path

import pytest

from llm_csp.schemas import CSPWorkflowRequest, SPPConfig, WorkflowConfig


DESIGN_SPACE = {
    "template": {
        "name": "cubic",
        "lattice": {
            "a": 3.9, "b": 3.9, "c": 3.9,
            "alpha": 90.0, "beta": 90.0, "gamma": 90.0, "units": "angstrom",
        },
    },
    "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
}


def test_structured_request_and_config_round_trip(tmp_path) -> None:
    request = CSPWorkflowRequest("cubic strontium titanate", "SrTiO3", DESIGN_SPACE)
    config = WorkflowConfig(output_root=tmp_path, spp=SPPConfig(request_mode="disabled"))

    assert CSPWorkflowRequest.from_dict(request.to_dict()) == request
    rebuilt = WorkflowConfig.from_dict(config.to_dict())
    assert rebuilt.output_root == Path(tmp_path)
    assert rebuilt.spp.request_mode == "disabled"


def test_request_rejects_implicit_design_space() -> None:
    with pytest.raises(ValueError, match="design_space"):
        CSPWorkflowRequest("query", "SrTiO3", {})


def test_output_root_is_mandatory() -> None:
    with pytest.raises(TypeError):
        WorkflowConfig()  # type: ignore[call-arg]
