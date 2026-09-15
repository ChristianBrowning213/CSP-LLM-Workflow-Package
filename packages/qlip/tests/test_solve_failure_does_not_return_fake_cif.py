import importlib

import pyomo.environ as pyo

from tests.helpers.solve_test_support import DummySPP, base_request, make_solver_result

solve_mod = importlib.import_module("qlip.core.solve")


def test_solve_failure_does_not_return_fake_cif(monkeypatch):
    called = {"build_cif": False}

    def _build_placeholder(_allocation):
        called["build_cif"] = True
        return "data_solution"

    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)
    monkeypatch.setattr(
        solve_mod,
        "_solve_model",
        lambda allocation, solver_cfg: make_solver_result(pyo.TerminationCondition.infeasible),
    )
    monkeypatch.setattr(solve_mod, "_build_cif_text", _build_placeholder)

    result = solve_mod.solve(base_request("SrTiO3"))

    assert result.status == "INFEASIBLE"
    assert result.outputs.cif is None
    assert result.errors
    assert result.errors[0].code == "infeasible"
    assert called["build_cif"] is False
