from collections import Counter
from io import StringIO
import os
from pathlib import Path

import pytest
import pyomo.environ as pyo
from ase.io import read

from llm_csp.spp import export_required_pot_subset
from qlip.core.solve import solve
from qlip.interactions.spp import SPPCollection
EXPECTED_PAIRS = ["O-O", "O-Sr", "O-Ti", "Sr-Sr", "Sr-Ti", "Ti-Ti"]
pytestmark = pytest.mark.requires_external_scientific_assets


def _request(pot_root):
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "SrTiO3"},
            "design_space": {
                "template": {
                    "name": "cubic",
                    "lattice": {"a": 3.9, "b": 3.9, "c": 3.9, "alpha": 90.0, "beta": 90.0, "gamma": 90.0, "units": "angstrom"},
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
            },
            "objective": {"type": "spp_energy"},
        },
        "constraints": [], "guidance": [],
        "solver": {"name": "gurobi", "time_limit_s": 30},
        "artifacts": {"return_cif": True},
        "context": {"pot_root": str(pot_root)},
    }


def test_srtio3_subset_is_exactly_six_and_qlip_solve_remains_optimal(tmp_path, monkeypatch):
    raw_root = os.environ.get("LLM_CSP_EXTERNAL_POT_ROOT")
    if not raw_root:
        pytest.skip("set LLM_CSP_EXTERNAL_POT_ROOT to a lawful compatible SrTiO3 POT library")
    source_root = Path(raw_root).resolve()
    solver = pyo.SolverFactory("gurobi")
    if solver is None or not solver.available(exception_flag=False):
        pytest.skip("Gurobi not available")
    output = tmp_path / "spp_root"
    export = export_required_pot_subset(
        formula="SrTiO3", source_pot_root=source_root, output_root=output
    )
    assert export["complete"] is True
    assert export["required_pairs"] == EXPECTED_PAIRS
    assert sorted(path.parent.name for path in output.rglob("*.POT")) == EXPECTED_PAIRS
    monkeypatch.setenv("QLIP_ALLOWED_PATH_ROOTS", str(tmp_path))

    loaded = SPPCollection(output)
    loaded.load([tuple(pair.split("-")) for pair in EXPECTED_PAIRS])
    result = solve(_request(output))
    assert result.status == "OPTIMAL"
    assert result.summary.objective_value is not None
    atoms = read(StringIO(result.outputs.cif), format="cif")
    assert Counter(atoms.get_chemical_symbols()) == {"O": 3, "Sr": 1, "Ti": 1}
    periodic_score = loaded.score(atoms.get_chemical_symbols(), atoms.positions, atoms.cell, pbc=True)
    assert periodic_score == pytest.approx(result.summary.objective_value, abs=1e-9)
