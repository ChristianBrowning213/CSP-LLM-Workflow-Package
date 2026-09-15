import importlib

import pyomo.environ as pyo

from tests.helpers.solve_test_support import DummySPP, base_request, make_solver_result

solve_mod = importlib.import_module("qlip.core.solve")


def test_placeholder_detection_guard(monkeypatch):
    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)
    monkeypatch.setattr(
        solve_mod,
        "_solve_model",
        lambda allocation, solver_cfg: make_solver_result(pyo.TerminationCondition.optimal),
    )
    monkeypatch.setattr(solve_mod, "_build_cif_text", lambda allocation: "data_solution")

    result = solve_mod.solve(base_request("SrTiO3"))

    assert result.status == "ERROR"
    assert result.outputs.cif is None
    assert result.errors
    assert result.errors[0].code == "invalid_cif_output"
    assert result.errors[0].details["artifact_status"] == "placeholder"
