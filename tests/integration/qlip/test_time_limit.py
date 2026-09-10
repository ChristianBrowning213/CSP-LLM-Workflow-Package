"""Focused, synthetic (no real Gurobi solve) coverage for the
TIME_LIMIT-incumbent status fix.

Forensic background: a Gurobi TIME_LIMIT termination does not by itself
mean no feasible incumbent was found -- Pyomo's Gurobi interface loads a
feasible incumbent's variable values into the Pyomo model whenever
SolCount>=1, even under TIME_LIMIT. Before this fix, `solve()` mapped
every non-optimal/feasible/infeasible termination (including a
TIME_LIMIT with a real incumbent already loaded) to a generic "ERROR"
status and never attempted to decode a candidate from it. These tests
prove the corrected, explicit three-way split:

- TIME_LIMIT with a decodable incumbent -> FEASIBLE_TIME_LIMIT, with a
  real CIF and objective value, never labelled OPTIMAL.
- TIME_LIMIT with no incumbent variables set -> TIME_LIMIT_NO_SOLUTION,
  no fabricated CIF.
- OPTIMAL is unaffected (see test_solve_success_returns_non_placeholder_cif.py).
"""

import importlib

import pyomo.environ as pyo

from tests.qlip_support.solve_test_support import (
    DummySPP,
    assign_sequential_solution,
    base_request,
    make_solver_result,
)

solve_mod = importlib.import_module("qlip.core.solve")


def _assign_and_return_time_limit(allocation, solver_cfg):
    assign_sequential_solution(allocation)
    return make_solver_result(pyo.TerminationCondition.maxTimeLimit)


def _return_time_limit_with_no_assignment(allocation, solver_cfg):
    return make_solver_result(pyo.TerminationCondition.maxTimeLimit)


def test_time_limit_with_incumbent_exports_feasible_time_limit_candidate(monkeypatch):
    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)
    monkeypatch.setattr(solve_mod, "_solve_model", _assign_and_return_time_limit)

    result = solve_mod.solve(base_request("SrTiO3"))

    assert result.status == "FEASIBLE_TIME_LIMIT"
    assert result.status != "OPTIMAL"
    assert result.status not in {"OPTIMAL", "FEASIBLE"}
    assert result.outputs.cif is not None
    assert result.outputs.cif.strip() != "data_solution"
    assert "_cell_length_a" in result.outputs.cif
    assert "_atom_site_fract_x" in result.outputs.cif
    assert result.summary.objective_value is not None
    assert not result.errors


def test_time_limit_without_incumbent_does_not_fabricate_a_candidate(monkeypatch):
    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)
    monkeypatch.setattr(solve_mod, "_solve_model", _return_time_limit_with_no_assignment)

    result = solve_mod.solve(base_request("SrTiO3"))

    assert result.status == "TIME_LIMIT_NO_SOLUTION"
    assert result.status not in {"OPTIMAL", "FEASIBLE", "FEASIBLE_TIME_LIMIT"}
    assert result.outputs.cif is None
    assert result.summary.objective_value is None
    assert result.errors
    assert result.errors[0].code == "solve_terminated_without_solution"


def test_infeasible_still_does_not_fabricate_a_candidate(monkeypatch):
    # Regression guard: INFEASIBLE must remain completely unaffected by the
    # new TIME_LIMIT branch (it is handled by an earlier, untouched elif).
    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)
    monkeypatch.setattr(
        solve_mod,
        "_solve_model",
        lambda allocation, solver_cfg: make_solver_result(pyo.TerminationCondition.infeasible),
    )

    result = solve_mod.solve(base_request("SrTiO3"))

    assert result.status == "INFEASIBLE"
    assert result.outputs.cif is None
    assert result.errors[0].code == "infeasible"


def test_optimal_is_unaffected_by_the_time_limit_branch(monkeypatch):
    # Regression guard mirroring test_solve_success_returns_non_placeholder_cif.py.
    monkeypatch.setattr(solve_mod, "SPPCollection", DummySPP)

    def _assign_and_return_optimal(allocation, solver_cfg):
        assign_sequential_solution(allocation)
        return make_solver_result(pyo.TerminationCondition.optimal)

    monkeypatch.setattr(solve_mod, "_solve_model", _assign_and_return_optimal)

    result = solve_mod.solve(base_request("SrTiO3"))

    assert result.status == "OPTIMAL"
    assert result.outputs.cif is not None
    assert not result.errors
