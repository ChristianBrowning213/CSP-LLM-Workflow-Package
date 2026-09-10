"""Offline QLIP smoke solve using the six bundled SrTiO3 POT files."""

from __future__ import annotations

from collections import Counter
from io import StringIO

from ase.io import read

from qlip import solve
from qlip.core.validate import validate_request
from qlip.resources import bundled_spp_root


def request() -> dict:
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
        "context": {"pot_root": str(bundled_spp_root())},
    }


def main() -> None:
    solve_request = request()
    validation = validate_request(solve_request, strict=True)
    if not validation.valid:
        raise RuntimeError(validation.to_dict())

    result = solve(solve_request)
    if result.status != "OPTIMAL" or not result.outputs.cif:
        raise RuntimeError(result.to_dict())

    atoms = read(StringIO(result.outputs.cif), format="cif")
    print(f"status={result.status}")
    print(f"objective={result.summary.objective_value:.15g}")
    print(f"composition={dict(Counter(atoms.get_chemical_symbols()))}")
    print(result.outputs.cif)


if __name__ == "__main__":
    main()
