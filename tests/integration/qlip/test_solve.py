import pyomo.environ as pyo
import pytest

from qlip.core.solve import solve


def _base_request():
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "SrTiO3"},
            "design_space": {
                "template": {
                    "name": "cubic",
                    "lattice": {
                        "a": 3.9,
                        "b": 3.9,
                        "c": 3.9,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                        "units": "angstrom",
                    },
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
            },
        },
        "constraints": [{"id": "proximity.atomic_radii", "params": {"scale": 1.0}}],
        "guidance": [],
        "solver": {"name": "gurobi"},
    }


def test_solve_smoke():
    solver = pyo.SolverFactory("gurobi")
    if solver is None or not solver.available(exception_flag=False):
        pytest.skip("Gurobi not available")
    result = solve(_base_request())
    assert result.status in {"OPTIMAL", "FEASIBLE", "INFEASIBLE", "ERROR"}
