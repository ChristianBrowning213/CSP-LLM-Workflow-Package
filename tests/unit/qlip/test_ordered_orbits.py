from __future__ import annotations

import numpy as np
import pyomo.environ as pyo
from ase import Atoms

from qlip.allocation import Allocation
from qlip.core.validate import validate_request


class _ZeroCost:
    include_diagonal_pair_terms = False

    def pair_cost_matrix(self, pair, positions):
        return np.zeros((len(positions), len(positions)), dtype=float)


def _request():
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "Si2P2"},
            "design_space": {
                "template": {
                    "lattice": {
                        "a": 5.0, "b": 5.0, "c": 5.0,
                        "alpha": 90.0, "beta": 90.0, "gamma": 90.0,
                    }
                },
                "sites": {
                    "mode": "explicit_fractional_sites",
                    "explicit_fractional_sites": [
                        [0.0, 0.0, 0.0], [0.5, 0.0, 0.0],
                        [0.0, 0.5, 0.0], [0.5, 0.5, 0.0],
                    ],
                    "ordered_orbits": [
                        {"orbit_id": "tet_1", "site_indices": [0, 1], "allowed_species": ["Si", "P"], "required_occupancy": True},
                        {"orbit_id": "tet_2", "site_indices": [2, 3], "allowed_species": ["Si", "P"], "required_occupancy": True},
                    ],
                },
            },
            "objective": {"type": "none"},
        },
        "constraints": [], "guidance": [],
        "solver": {"name": "gurobi"},
    }


def test_ordered_orbit_request_schema_and_semantics_validate(monkeypatch, tmp_path):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    # Objective-none validation still performs the normal data preflight, so
    # use a partial neutral SPP declaration to isolate the site semantics.
    request = _request()
    request["problem"]["objective"] = {"type": "spp_energy"}
    request["guidance"] = [{
        "id": "objective.energy_spp",
        "params": {
            "pot_root": str(tmp_path), "mode": "partial",
            "supported_pairs": [], "missing_pairs": ["P-P", "P-Si", "Si-Si"],
            "missing_pair_policy": "neutral", "strict_pair_coverage": False,
        },
    }]
    report = validate_request(request, strict=True)
    assert not any(issue.code.startswith("ordered_orbit") for issue in report.errors)
    assert not any("ordered_orbits" in issue.path and issue.code == "schema_validation_error" for issue in report.errors)


def test_ordered_orbit_constraints_close_species_assignments():
    allocation = Allocation(Atoms("Si2P2"))
    allocation.positions = Atoms("H4", cell=[5.0, 5.0, 5.0], pbc=True)
    allocation.positions.set_scaled_positions([
        [0.0, 0.0, 0.0], [0.5, 0.0, 0.0],
        [0.0, 0.5, 0.0], [0.5, 0.5, 0.0],
    ])
    allocation.cost = _ZeroCost()
    allocation.ordered_orbits = _request()["problem"]["design_space"]["sites"]["ordered_orbits"]
    allocation.encode()
    for site in range(4):
        assert allocation.m.vacancy[site].fixed
        assert pyo.value(allocation.m.vacancy[site]) == 0
    for site in range(4):
        allocation.m.x["Si", site].set_value(1 if site < 2 else 0)
        allocation.m.x["P", site].set_value(0 if site < 2 else 1)
    for constraint in allocation.m.ordered_orbit_constraints.values():
        value = pyo.value(constraint.body)
        if constraint.lower is not None:
            assert value >= pyo.value(constraint.lower)
        if constraint.upper is not None:
            assert value <= pyo.value(constraint.upper)


def test_ordered_orbit_validation_rejects_overlap_and_unknown_species(monkeypatch, tmp_path):
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))
    request = _request()
    request["problem"]["design_space"]["sites"]["ordered_orbits"][1]["site_indices"] = [1, 3]
    request["problem"]["design_space"]["sites"]["ordered_orbits"][1]["allowed_species"] = ["Ge"]
    report = validate_request(request, strict=True)
    codes = {issue.code for issue in report.errors}
    assert "ordered_orbit_site_overlap" in codes
    assert "ordered_orbit_species_unknown" in codes
