from __future__ import annotations

from sok_llm_orchestrator.evals.live_llm import EvalCase, validate_case_response


def test_validate_case_response_spp_pass() -> None:
    case = EvalCase(case_id="x", query="TiO2", with_spp=True)
    response = """
{
  "version": "1.0",
  "problem": {
    "chemistry": {"formula": "TiO2"},
    "design_space": {"template": {}, "sites": {}},
    "objective": {"type": "spp_energy"}
  },
  "constraints": [],
  "guidance": [
    {"id": "objective.energy_spp", "params": {"spp_package_path": "SPPs/TEST_RUN"}}
  ],
  "solver": {"name": "gurobi"}
}
"""
    ok, reason = validate_case_response(case, response)
    assert ok is True
    assert reason == "ok"


def test_validate_case_response_detects_wrong_guidance() -> None:
    case = EvalCase(case_id="x", query="TiO2", with_spp=False)
    response = """
{
  "version": "1.0",
  "problem": {
    "chemistry": {"formula": "TiO2"},
    "design_space": {"template": {}, "sites": {}},
    "objective": {"type": "spp_energy"}
  },
  "constraints": [],
  "guidance": [
    {"id": "objective.energy_spp", "params": {"spp_package_path": "SPPs/TEST_RUN"}}
  ],
  "solver": {"name": "gurobi"}
}
"""
    ok, reason = validate_case_response(case, response)
    assert ok is False
    assert reason == "unexpected_spp_guidance"
