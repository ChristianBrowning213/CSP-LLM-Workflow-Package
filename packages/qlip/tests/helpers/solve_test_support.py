from __future__ import annotations

import io
from typing import Any

import numpy as np
import pyomo.environ as pyo
from ase import Atoms
from ase.io import write


def base_request(formula: str = "SrTiO3", density: int = 2) -> dict[str, Any]:
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": formula},
            "design_space": {
                "template": {
                    "lattice": {
                        "a": 3.9,
                        "b": 3.9,
                        "c": 3.9,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                        "units": "angstrom",
                    }
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": density}},
            },
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
        "context": {
            "pot_root": "src/qlip/interactions/SPP/SPP",
        },
    }


class DummySPP:
    def __init__(self, *args, **kwargs):
        pass

    def load(self, pairs):
        return None

    def __call__(self, pair, distances):
        return np.zeros_like(distances, dtype=float)


def make_solver_result(termination) -> Any:
    solver_block = type(
        "DummySolverBlock",
        (),
        {"termination_condition": termination, "best_bound": None, "mip_gap": None},
    )()
    return type("DummyResult", (), {"solver": solver_block})()


def assign_sequential_solution(allocation, *, first_site: int = 0) -> None:
    site_cursor = first_site
    site_count = len(allocation.positions)
    for species in allocation.types:
        needed = int(allocation.count[species])
        assigned_sites = range(site_cursor, site_cursor + needed)
        if site_cursor + needed > site_count:
            raise AssertionError("Not enough sites to assign the requested dummy solution.")
        for site in allocation.m.Pos:
            allocation.m.x[species, site].set_value(1 if site in assigned_sites else 0)
        site_cursor += needed


def make_real_cif_text() -> str:
    atoms = Atoms("H", cell=[1.0, 1.0, 1.0], pbc=True)
    atoms.set_scaled_positions([[0.0, 0.0, 0.0]])
    buf = io.BytesIO()
    write(buf, atoms, format="cif")
    return buf.getvalue().decode("latin-1")
