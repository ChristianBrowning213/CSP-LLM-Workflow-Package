"""Freeze Dataset E development rows and development-only scaffold prototypes."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "artifacts" / "Paper_scaffolds_september" / "Dataset_E_complex_topology_showcase"
CRYSTAL = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB\artifacts\Paper_scaffolds_september\specialist_corpora")
DATABASES = {
    "NASICON": CRYSTAL / "families" / "NASICON" / "PAPER_SCAFFOLDS_NASICON_V1" / "crystaldb.sqlite",
    "RUDDLESDEN_POPPER": CRYSTAL / "families" / "RUDDLESDEN_POPPER" / "PAPER_SCAFFOLDS_RUDDLESDEN_POPPER_V1" / "crystaldb.sqlite",
    "GARNET": CRYSTAL / "families" / "GARNET" / "PAPER_SCAFFOLDS_GARNET_V1" / "crystaldb.sqlite",
    "ARGYRODITE": CRYSTAL / "argyrodite_v2" / "PAPER_SCAFFOLDS_ARGYRODITE_ORDERED_V2.sqlite",
}
DEVELOPMENT = {
    "NASICON_R3_PHOSPHATE": ["materials_project-6a117951", "materials_project-1a84a0fe"],
    "RP_N1": ["materials_project-fc84a6aa", "materials_project-d5d0dbf3", "materials_project-a2bd7b92"],
    "RP_N2": ["materials_project-a96a4830", "materials_project-4050df5c", "materials_project-6cfede75"],
    "GARNET_IA3D": ["materials_project-109b736f", "materials_project-ebf000d4", "materials_project-40a9e1e2"],
    "GARNET_I41ACD": ["materials_project-03e91377", "materials_project-9a3ead25"],
    "ARGYRODITE_F43M": ["materials_project-450a7387"],
    "ARGYRODITE_PNA21": ["materials_project-b2c946b3"],
    "ARGYRODITE_CC": ["materials_project-7ef895a7"],
}
FAMILY_FOR_SUBTYPE = {
    "NASICON_R3_PHOSPHATE": "NASICON",
    "RP_N1": "RUDDLESDEN_POPPER",
    "RP_N2": "RUDDLESDEN_POPPER",
    "GARNET_IA3D": "GARNET",
    "GARNET_I41ACD": "GARNET",
    "ARGYRODITE_F43M": "ARGYRODITE",
    "ARGYRODITE_PNA21": "ARGYRODITE",
    "ARGYRODITE_CC": "ARGYRODITE",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(database: Path, structure_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT s.structure_id, s.reduced_formula, s.cif_text, p.source_id,
                   a.cif_sha256, a.family_assignment_evidence_json
            FROM structures AS s
            JOIN provenance AS p USING (structure_id)
            JOIN structure_annotations AS a USING (structure_id)
            WHERE s.structure_id = ?
            """,
            (structure_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError(f"missing development row {structure_id}")
    return dict(row)


def _template(row: dict[str, Any], subtype: str, database: Path) -> dict[str, Any]:
    structure = Structure.from_str(row["cif_text"], fmt="cif")
    primitive = SpacegroupAnalyzer(structure, symprec=0.05).get_primitive_standard_structure()
    analyzer = SpacegroupAnalyzer(primitive, symprec=0.05)
    symmetrized = analyzer.get_symmetrized_structure()
    orbits = []
    for index, indices in enumerate(symmetrized.equivalent_indices):
        species = sorted({str(primitive[item].specie.symbol) for item in indices})
        if len(species) != 1:
            raise RuntimeError(f"{row['structure_id']} orbit {index} mixes source species")
        orbits.append({
            "orbit_id": f"orbit_{index:02d}",
            "site_indices": list(indices),
            "source_species": species[0],
            "multiplicity": len(indices),
        })
    return {
        "template_id": f"{subtype}__{row['structure_id']}",
        "subtype": subtype,
        "development_structure_id": row["structure_id"],
        "development_source_id": row["source_id"],
        "development_cif_sha256": row["cif_sha256"],
        "database_path": str(database),
        "database_sha256": sha(database),
        "standardization": "pymatgen SpacegroupAnalyzer(symprec=0.05).get_primitive_standard_structure",
        "space_group_symbol": analyzer.get_space_group_symbol(),
        "space_group_number": analyzer.get_space_group_number(),
        "site_count": len(primitive),
        "lattice_matrix": primitive.lattice.matrix.tolist(),
        "fractional_coordinates": primitive.frac_coords.tolist(),
        "source_species_by_site": [str(site.specie.symbol) for site in primitive],
        "orbits": orbits,
        "use_restriction": "DEVELOPMENT_DERIVED_REUSABLE_PROTOTYPE_ONLY_NOT_A_FINAL_TARGET",
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    roster = []
    templates = []
    for subtype, structure_ids in DEVELOPMENT.items():
        family = FAMILY_FOR_SUBTYPE[subtype]
        database = DATABASES[family]
        for structure_id in structure_ids:
            row = _record(database, structure_id)
            evidence = json.loads(row["family_assignment_evidence_json"])
            roster.append({
                "subtype": subtype,
                "family": family,
                "structure_id": structure_id,
                "source_id": row["source_id"],
                "formula": row["reduced_formula"],
                "cif_sha256": row["cif_sha256"],
                "database_sha256": sha(database),
                "annotation": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                "selection_role": "DEVELOPMENT_ONLY_EXCLUDED_FROM_FINAL_SHOWCASE",
            })
            templates.append(_template(row, subtype, database))
    roster_path = OUT / "DEVELOPMENT_ROSTER.csv"
    with roster_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(roster[0]))
        writer.writeheader()
        writer.writerows(roster)
    template_path = OUT / "DEVELOPMENT_SCAFFOLD_TEMPLATES.json"
    template_path.write_text(json.dumps({
        "schema_version": "dataset_e.development_scaffold_templates.v1",
        "scientific_rule": "Only development rows define reusable topology prototypes; final rows are not selected or read here.",
        "templates": templates,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    freeze = {
        "schema_version": "dataset_e.development_roster_freeze.v1",
        "selected_before_final_showcase_roster": True,
        "row_count": len(roster),
        "roster_sha256": sha(roster_path),
        "templates_sha256": sha(template_path),
        "database_hashes": {family: sha(path) for family, path in DATABASES.items()},
        "prohibitions": [
            "development rows cannot enter final showcase",
            "development coordinates/lattices cannot be described as generated answers",
            "final target coordinates and lattice constants cannot enter scaffold construction",
        ],
    }
    (OUT / "DEVELOPMENT_ROSTER_FREEZE.json").write_text(
        json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(freeze, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
