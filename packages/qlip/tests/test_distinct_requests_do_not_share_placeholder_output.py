import importlib

import pyomo.environ as pyo

from tests.helpers.solve_test_support import (
    DummySPP,
    assign_sequential_solution,
    base_request,
    make_solver_result,
)

solve_mod = importlib.import_module("qlip.core.solve")


def test_distinct_requests_do_not_share_placeholder_output(monkeypatch):
    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)
    monkeypatch.setattr(solve_mod, "_solve_model", _assign_and_return_optimal)

    tio2 = solve_mod.solve(base_request("TiO2"))
    srtio3 = solve_mod.solve(base_request("SrTiO3"))

    assert tio2.status == "OPTIMAL"
    assert srtio3.status == "OPTIMAL"
    assert tio2.outputs.cif is not None
    assert srtio3.outputs.cif is not None
    assert tio2.outputs.cif.strip() != "data_solution"
    assert srtio3.outputs.cif.strip() != "data_solution"
    assert tio2.outputs.cif != srtio3.outputs.cif


def _assign_and_return_optimal(allocation, solver_cfg):
    assign_sequential_solution(allocation)
    return make_solver_result(pyo.TerminationCondition.optimal)
