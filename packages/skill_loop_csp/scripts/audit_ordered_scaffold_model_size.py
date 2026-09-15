"""Build-only model-size audit for representative ordered scaffolds.

This diagnostic does not solve, generate, select Dataset E targets, or define a
scientific scaffold. Frozen garnet CIFs are read only to measure the production
model size of their legitimate 80/96-site primitive representations.
"""

from __future__ import annotations

import csv
import json
from math import comb
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

import numpy as np
import pyomo.environ as pyo
from ase import Atoms
from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import (  # noqa: E402
    build_family_scaffold_alternatives,
)
from sok_llm_orchestrator.workflow.runner import (  # noqa: E402
    _explicit_site_runtime_limits,
)
from qlip.allocation import Allocation  # noqa: E402


OUT = (
    REPO
    / "artifacts"
    / "Paper_scaffolds_september"
    / "Dataset_E_complex_topology_showcase"
)
GARNET_DB = Path(
    r"C:\Users\brown\Documents\GitHub\Crystal-DB\artifacts\Paper_scaffolds_september"
    r"\specialist_corpora\families\GARNET\PAPER_SCAFFOLDS_GARNET_V1\crystaldb.sqlite"
)


class _UnitPairCost:
    include_diagonal_pair_terms = False

    def pair_cost_matrix(self, pair: tuple[str, str], positions: Atoms) -> np.ndarray:
        matrix = np.ones((len(positions), len(positions)), dtype=float)
        np.fill_diagonal(matrix, 0.0)
        return matrix


def _orbit(
    orbit_id: str,
    indices: list[int],
    allowed: list[str],
    *,
    fixed: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "orbit_id": orbit_id,
        "site_indices": indices,
        "allowed_species": allowed,
        "required_occupancy": True,
        "vacancy_allowed": False,
        "allow_partial_occupation": False,
    }
    if fixed is not None:
        record["fixed_species"] = fixed
    return record


def _garnet(space_group_number: int) -> tuple[str, Structure, list[dict[str, Any]]]:
    connection = sqlite3.connect(f"file:{GARNET_DB.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT s.structure_id, s.cif_text
            FROM structures AS s
            JOIN structure_annotations AS a USING (structure_id)
            WHERE json_extract(a.family_assignment_evidence_json, '$.space_group_number') = ?
            ORDER BY s.structure_id
            LIMIT 1
            """,
            (space_group_number,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError(f"no frozen garnet diagnostic row for space group {space_group_number}")
    structure = Structure.from_str(row["cif_text"], fmt="cif")
    primitive = SpacegroupAnalyzer(structure, symprec=0.05).get_primitive_standard_structure()
    analyzer = SpacegroupAnalyzer(primitive, symprec=0.05)
    if analyzer.get_space_group_number() != space_group_number:
        raise RuntimeError("garnet diagnostic standardization changed the expected space group")
    symmetrized = analyzer.get_symmetrized_structure()
    orbits = []
    for orbit_index, indices in enumerate(symmetrized.equivalent_indices):
        species = sorted({str(primitive[index].specie.symbol) for index in indices})
        if len(species) != 1:
            raise RuntimeError("diagnostic garnet symmetry orbit contains mixed species")
        orbits.append(_orbit(f"garnet_orbit_{orbit_index:02d}", list(indices), species, fixed=species[0]))
    return str(row["structure_id"]), primitive, orbits


def _v2_spinel() -> tuple[str, Structure, list[dict[str, Any]], Atoms]:
    alternative = build_family_scaffold_alternatives(
        {"formula": "MgFe2O4", "family": "spinel"}
    )[0]
    chemistry = Atoms("Mg8Fe16O32")
    return (
        alternative.alternative_id,
        alternative.structure,
        [dict(orbit) for orbit in alternative.ordered_orbits],
        chemistry,
    )


def _measure(
    *,
    label: str,
    source_id: str,
    structure: Structure,
    orbits: list[dict[str, Any]],
    chemistry: Atoms | None = None,
) -> dict[str, Any]:
    design_space = {
        "sites": {
            "mode": "explicit_fractional_sites",
            "explicit_fractional_sites": structure.frac_coords.tolist(),
            "ordered_orbits": orbits,
        }
    }
    limits = _explicit_site_runtime_limits(design_space)
    allocation = Allocation(chemistry or structure.to_ase_atoms())
    allocation.positions = structure.to_ase_atoms()
    allocation.cost = _UnitPairCost()
    allocation.ordered_orbits = orbits
    started = time.perf_counter()
    allocation.encode()
    build_runtime = time.perf_counter() - started
    model = allocation.m
    variables = list(model.component_data_objects(pyo.Var, active=True))
    constraints = list(model.component_data_objects(pyo.Constraint, active=True))
    species_count = len(allocation.types)
    off_diagonal_quadratic_terms = species_count * species_count * comb(len(structure), 2)
    claimed = [index for orbit in orbits for index in orbit["site_indices"]]
    if sorted(claimed) != list(range(len(structure))):
        raise RuntimeError(f"{label}: ordered orbits do not preserve the complete site domain")
    return {
        "case": label,
        "source_id": source_id,
        "source_role": "NON_SCIENTIFIC_MODEL_BUILD_DIAGNOSTIC_ONLY",
        "raw_site_count": len(structure),
        "ordered_orbit_count": len(orbits),
        "allowed_species_domain_count": sum(len(orbit["allowed_species"]) for orbit in orbits),
        "chemical_species_count": species_count,
        "binary_variable_count": sum(variable.is_binary() for variable in variables),
        "total_active_variable_count": len(variables),
        "allocation_off_diagonal_quadratic_term_count": off_diagonal_quadratic_terms,
        "active_constraint_count": len(constraints),
        "ordered_site_limit": limits["max_sites"],
        "model_build_runtime_s": round(build_runtime, 6),
        "presolve_model_size": "NOT_EXPOSED_MODEL_BUILD_ONLY",
        "solve_runtime_s": "NOT_RUN",
        "site_domain_complete": True,
    }


def main() -> int:
    spinel_id, spinel, spinel_orbits, spinel_chemistry = _v2_spinel()
    cubic_id, cubic, cubic_orbits = _garnet(230)
    tetragonal_id, tetragonal, tetragonal_orbits = _garnet(142)
    rows = [
        _measure(
            label="existing_v2_spinel",
            source_id=spinel_id,
            structure=spinel,
            orbits=spinel_orbits,
            chemistry=spinel_chemistry,
        ),
        _measure(
            label="garnet_Ia-3d_80_site",
            source_id=cubic_id,
            structure=cubic,
            orbits=cubic_orbits,
        ),
        _measure(
            label="garnet_I41-acd_96_site",
            source_id=tetragonal_id,
            structure=tetragonal,
            orbits=tetragonal_orbits,
        ),
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "ORDERED_SCAFFOLD_MODEL_SIZE_AUDIT.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    table = [
        "| case | sites | orbits | domains | binary vars | quadratic terms | constraints | build s |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        table.append(
            "| {case} | {raw_site_count} | {ordered_orbit_count} | "
            "{allowed_species_domain_count} | {binary_variable_count} | "
            "{allocation_off_diagonal_quadratic_term_count} | "
            "{active_constraint_count} | {model_build_runtime_s:.6f} |".format(**row)
        )
    report = "\n".join(
        [
            "# Ordered-scaffold model-size audit",
            "",
            "Build-only diagnostic; no solve or Dataset E generation was run.",
            "",
            *table,
            "",
            "The garnet inputs are read-only representatives from the frozen corpus and are used only to measure model construction. They do not define Dataset E scaffolds, rosters, targets, coordinates, lattice candidates, or validation thresholds.",
            "",
            "`binary vars` counts all active Pyomo binary variable data, including vacancy variables that ordered full-occupancy orbits fix to zero. `quadratic terms` is the exact off-diagonal allocation expression count for the current species domain before presolve. QLIP does not expose a presolve size during build-only operation, and solver execution was intentionally not run.",
            "",
        ]
    )
    (OUT / "ORDERED_SCAFFOLD_MODEL_SIZE_AUDIT.md").write_text(report, encoding="utf-8")
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
