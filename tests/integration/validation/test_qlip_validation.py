from __future__ import annotations

import pytest
import pyomo.environ as pyo

from llm_csp.validation import validate_cif
from qlip.core.solve import solve
from qlip.resources import bundled_spp_root


def _request(pot_root):
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
        "context": {"pot_root": str(pot_root)},
    }


def test_packaged_qlip_cif_is_accepted_by_validation(tmp_path, monkeypatch) -> None:
    solver = pyo.SolverFactory("gurobi")
    if solver is None or not solver.available(exception_flag=False):
        pytest.skip("Gurobi not available")
    pot_root = bundled_spp_root()
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(pot_root.parent))

    solved = solve(_request(pot_root))
    assert solved.status == "OPTIMAL"
    assert solved.summary.objective_value == pytest.approx(4.883033620558714, abs=1e-9)
    cif_path = tmp_path / "qlip_srtio3.cif"
    cif_path.write_text(solved.outputs.cif, encoding="utf-8")

    validated = validate_cif(cif_path, target_formula="SrTiO3", run_id="qlip-srtio3")
    assert validated.status == "evaluated"
    assert validated.parseable is True
    assert validated.composition["target_formula_match"] is True
    assert validated.backend.version == "0.1.0"
