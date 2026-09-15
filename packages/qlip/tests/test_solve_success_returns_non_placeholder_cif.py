import importlib

import pyomo.environ as pyo

from tests.helpers.solve_test_support import (
    DummySPP,
    assign_sequential_solution,
    base_request,
    make_solver_result,
)

solve_mod = importlib.import_module("qlip.core.solve")


def test_solve_success_returns_non_placeholder_cif(monkeypatch):
    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)
    monkeypatch.setattr(solve_mod, "_solve_model", _assign_and_return_optimal)

    result = solve_mod.solve(base_request("SrTiO3"))

    assert result.status == "OPTIMAL"
    assert result.outputs.cif is not None
    assert result.outputs.cif.strip() != "data_solution"
    assert len(result.outputs.cif.strip()) > 100
    assert "_cell_length_a" in result.outputs.cif
    assert "_atom_site_fract_x" in result.outputs.cif
    assert not result.errors


def _assign_and_return_optimal(allocation, solver_cfg):
    assign_sequential_solution(allocation)
    return make_solver_result(pyo.TerminationCondition.optimal)
