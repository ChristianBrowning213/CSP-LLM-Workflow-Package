from __future__ import annotations

from collections import Counter
from io import StringIO
import os
from pathlib import Path

import numpy as np
import pyomo.environ as pyo
import pytest
from ase import Atoms
from ase.io import read

from qlip.core.solve import _build_positions, solve
from qlip.interactions.spp import SPPCollection


POT_ROOT = Path(os.environ["LLM_CSP_EXTERNAL_POT_ROOT"]).resolve() if os.environ.get("LLM_CSP_EXTERNAL_POT_ROOT") else None
pytestmark = pytest.mark.requires_external_scientific_assets


def _srtio3_density2_request() -> dict:
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
            "objective": {"type": "spp_energy"},
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi", "time_limit_s": 30},
        "artifacts": {"return_cif": True},
        "context": {"pot_root": str(POT_ROOT)},
    }


def _load_srtio3_spp() -> SPPCollection:
    spp = SPPCollection(POT_ROOT)
    spp.load([("O", "O"), ("O", "Sr"), ("O", "Ti"), ("Sr", "Sr"), ("Sr", "Ti"), ("Ti", "Ti")])
    return spp


def _score(spp: SPPCollection, atoms: Atoms) -> float:
    return float(spp.score(atoms.get_chemical_symbols(), atoms.get_positions(), atoms.cell, pbc=True))


def _rounded_scaled_sites(atoms: Atoms) -> list[tuple[float, float, float]]:
    return [tuple(np.round(site, 6)) for site in atoms.get_scaled_positions(wrap=True)]


def test_spp_enabled_srtio3_density2_generates_expected_formula_and_periodic_score():
    """
    Tiny real-POT SPP benchmark.

    This uses invariant matching instead of exact crystal matching: the 2x2x2
    SrTiO3 grid has symmetry-equivalent optima, so the regression checks the
    returned CIF, exact composition, valid occupied grid sites, finite periodic
    SPP score, scorer/objective equality, and improvement over a deterministic
    bad assignment on the same candidate grid.
    """
    if POT_ROOT is None:
        pytest.skip("set LLM_CSP_EXTERNAL_POT_ROOT to a lawful compatible SrTiO3 POT library")
    solver = pyo.SolverFactory("gurobi")
    if solver is None or not solver.available(exception_flag=False):
        pytest.skip("Gurobi not available")

    request = _srtio3_density2_request()
    result = solve(request)

    assert result.status == "OPTIMAL"
    assert result.outputs.cif
    assert not result.errors
    assert result.summary.objective_value is not None

    atoms = read(StringIO(result.outputs.cif), format="cif")
    assert Counter(atoms.get_chemical_symbols()) == {"O": 3, "Sr": 1, "Ti": 1}
    assert len(atoms) == 5

    occupied_sites = _rounded_scaled_sites(atoms)
    assert len(set(occupied_sites)) == len(occupied_sites)
    grid_sites = {
        tuple(np.round(site, 6))
        for site in _build_positions(request["problem"]["design_space"]).get_scaled_positions()
    }
    assert set(occupied_sites) <= grid_sites

    distances = atoms.get_all_distances(mic=True)
    nonzero_distances = distances[distances > 1e-12]
    assert float(np.min(nonzero_distances)) > 0.0

    spp = _load_srtio3_spp()
    optimized_score = _score(spp, atoms)
    assert np.isfinite(optimized_score)
    assert optimized_score == pytest.approx(float(result.summary.objective_value), abs=1e-9)

    grid = _build_positions(request["problem"]["design_space"])
    bad = Atoms(symbols=["O", "O", "O", "Sr", "Ti"], cell=grid.cell, pbc=True)
    bad.set_scaled_positions(grid.get_scaled_positions()[:5])
    bad_score = _score(spp, bad)

    assert np.isfinite(bad_score)
    assert optimized_score < bad_score
