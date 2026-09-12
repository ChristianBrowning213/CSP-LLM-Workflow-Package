from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_csp.schemas.workflow import CSPWorkflowRequest, WorkflowConfig


ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_EXAMPLE = ROOT / "configs" / "examples" / "srtio3_production.json"


def _example() -> dict:
    return json.loads(PRODUCTION_EXAMPLE.read_text(encoding="utf-8"))


def test_production_example_parses_through_released_request_models() -> None:
    payload = _example()

    request = CSPWorkflowRequest.from_dict(payload["request"])
    config = WorkflowConfig.from_dict(payload["config"])

    assert request.formula == "SrTiO3"
    assert request.design_space["sites"]["mode"] == "uniform_grid"
    assert config.retrieval.model_name == "text-embedding-bge-m3"
    assert config.spp.regulator_root is not None
    assert config.generation.solver_name == "gurobi"
    assert config.validation.enabled is True
    assert config.output_root.as_posix() == "runs/production"


def test_missing_formula_is_rejected_at_request_boundary() -> None:
    payload = _example()["request"]
    payload.pop("formula")

    with pytest.raises(TypeError):
        CSPWorkflowRequest.from_dict(payload)


def test_invalid_retrieval_engine_is_rejected_at_config_boundary() -> None:
    payload = _example()["config"]
    payload["retrieval"]["embed_engine"] = "implicit-fallback"

    with pytest.raises(ValueError, match="retrieval embed_engine"):
        WorkflowConfig.from_dict(payload)


def test_empty_qlip_design_space_is_rejected_at_request_boundary() -> None:
    payload = _example()["request"]
    payload["design_space"] = {}

    with pytest.raises(ValueError, match="explicit packaged QLIP design space"):
        CSPWorkflowRequest.from_dict(payload)


def test_missing_output_configuration_is_rejected_at_config_boundary() -> None:
    payload = _example()["config"]
    payload.pop("output_root")

    with pytest.raises(KeyError, match="output_root"):
        WorkflowConfig.from_dict(payload)
