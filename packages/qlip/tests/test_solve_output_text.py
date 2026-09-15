import importlib
from pathlib import Path

import numpy as np
import pyomo.environ as pyo

from tests.helpers.solve_test_support import assign_sequential_solution, make_solver_result

solve_mod = importlib.import_module("qlip.core.solve")


def _base_request():
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "SrTiO3"},
            "design_space": {
                "template": {
                    "lattice": {
                        "a": 1.0,
                        "b": 1.0,
                        "c": 1.0,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                    }
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
            },
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
        "context": {
            "pot_root": str(
                Path(__file__).resolve().parents[1]
                / "src"
                / "qlip"
                / "interactions"
                / "SPP"
                / "SPP"
            )
        },
    }


class _DummySPP:
    def __init__(self, *args, **kwargs):
        pass

    def load(self, pairs):
        return None

    def __call__(self, pair, distances):
        return np.zeros_like(distances, dtype=float)


class _BytesStrError(Exception):
    def __str__(self):  # intentionally wrong to mimic buggy libraries
        return b"bytes error"


def test_solve_rejects_invalid_cif_bytes(monkeypatch):
    monkeypatch.setattr(solve_mod, "_build_cif_text", lambda allocation: b"data")
    monkeypatch.setattr(
        solve_mod,
        "_solve_model",
        lambda allocation, solver_cfg: make_solver_result(pyo.TerminationCondition.optimal),
    )
    monkeypatch.setattr(solve_mod, "SPPCollection", _DummySPP)

    result = solve_mod.solve(_base_request())

    assert result.status == "ERROR"
    assert result.outputs.cif is None
    assert result.errors
    assert result.errors[0].code == "invalid_cif_output"


def test_build_cif_text_returns_str(monkeypatch):
    from ase import Atoms

    task = type("Task", (), {})()
    task.positions = Atoms("H", cell=[1.0, 1.0, 1.0], pbc=True)
    monkeypatch.setattr(solve_mod, "_extract_placements", lambda _: {"H": [(0.0, 0.0, 0.0)]})

    text = solve_mod._build_cif_text(task)

    assert isinstance(text, str)
    assert "data_" in text


def test_solve_decodes_valid_cif_bytes(monkeypatch):
    monkeypatch.setattr(
        solve_mod,
        "_solve_model",
        lambda allocation, solver_cfg: _assign_and_return_optimal(allocation),
    )
    monkeypatch.setattr(solve_mod, "SPPCollection", _DummySPP)

    result = solve_mod.solve(_base_request())

    assert result.status == "OPTIMAL"
    assert isinstance(result.outputs.cif, str)
    assert "_atom_site_fract_x" in result.outputs.cif


def test_solve_error_handles_bytes_str(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise _BytesStrError()

    monkeypatch.setattr(solve_mod, "_solve_model", _raise)
    monkeypatch.setattr(solve_mod, "SPPCollection", _DummySPP)

    result = solve_mod.solve(_base_request())

    assert result.status == "ERROR"
    assert result.errors
    assert isinstance(result.errors[0].message, str)
    assert "BytesStrError" in result.errors[0].message


def _assign_and_return_optimal(allocation):
    assign_sequential_solution(allocation)
    return make_solver_result(pyo.TerminationCondition.optimal)
