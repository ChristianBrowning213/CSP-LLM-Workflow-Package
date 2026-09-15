from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


COORDINATION_CUTOFFS_ANGSTROM = {"Zr": 2.55, "Si": 2.05, "P": 2.05}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coordination_counts(structure: Structure, species: str, cutoff: float) -> list[int]:
    counts: list[int] = []
    for site in structure:
        if site.specie.symbol != species:
            continue
        counts.append(
            sum(
                1
                for neighbor in structure.get_neighbors(site, cutoff)
                if neighbor.specie.symbol == "O"
            )
        )
    return counts


def build_reference_artifacts(
    *,
    source_cif: Path,
    source_manifest: Path,
    material_id: str,
    out_dir: Path,
) -> dict[str, Any]:
    manifest_rows = [json.loads(line) for line in source_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    source_row = next((row for row in manifest_rows if row.get("material_id") == material_id), None)
    if source_row is None:
        raise ValueError(f"Material ID {material_id!r} is absent from {source_manifest}")

    structure = Structure.from_file(source_cif)
    if not structure.is_ordered:
        raise ValueError("Selected reference contains partial occupancy or occupational disorder")
    occupancies = sorted({float(value) for site in structure for value in site.species.values()})
    if occupancies != [1.0]:
        raise ValueError(f"Selected reference is not fully occupied: {occupancies}")

    analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
    symmetrized = analyzer.get_symmetrized_structure()
    out_dir.mkdir(parents=True, exist_ok=True)
    reference_cif = out_dir / "reference.cif"
    shutil.copyfile(source_cif, reference_cif)

    orbit_rows: list[dict[str, Any]] = []
    species_orbit_counter: dict[str, int] = {}
    for equivalent_indices, wyckoff_label in zip(
        symmetrized.equivalent_indices,
        symmetrized.wyckoff_symbols,
    ):
        representative = structure[equivalent_indices[0]]
        species = representative.specie.symbol
        species_orbit_counter[species] = species_orbit_counter.get(species, 0) + 1
        orbit_id = f"{species.lower()}_{species_orbit_counter[species]}_{wyckoff_label.lower()}"
        role = {
            "Na": "mobile-ion cavity/channel site",
            "Zr": "ZrO6 framework octahedron centre",
            "Si": "SiO4 framework tetrahedron centre",
            "P": "PO4 framework tetrahedron centre",
            "O": "framework anion / polyhedron vertex",
        }[species]
        qlip_mode = "variable Si/P orbit assignment" if species in {"Si", "P"} else "fixed"
        orbit_rows.append(
            {
                "species": species,
                "Wyckoff label": wyckoff_label,
                "multiplicity": len(equivalent_indices),
                "fractional coordinates or free parameters": " ".join(
                    f"{float(value):.10f}" for value in representative.frac_coords
                ),
                "occupancy": 1.0,
                "coordination role": role,
                "fixed or variable in QLIP": qlip_mode,
                "orbit_id": orbit_id,
                "site_indices": " ".join(str(index) for index in equivalent_indices),
            }
        )

    orbit_table = out_dir / "orbit_table.csv"
    with orbit_table.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(orbit_rows[0]))
        writer.writeheader()
        writer.writerows(orbit_rows)

    primitive = analyzer.find_primitive()
    coordination = {
        species: _coordination_counts(structure, species, cutoff)
        for species, cutoff in COORDINATION_CUTOFFS_ANGSTROM.items()
    }
    metadata = {
        "schema_version": "nasicon_reference_metadata.v1",
        "target_reduced_formula": "Na3Zr2Si2PO12",
        "selected_material_id": material_id,
        "source": source_row.get("source"),
        "source_id": material_id,
        "source_version": "Materials Project API record retrieved 2026-08-03",
        "retrieval_timestamp": source_row.get("retrieved_at"),
        "source_query": source_row.get("source_query"),
        "source_cif_sha256": source_row.get("cif_sha256"),
        "frozen_reference_cif_sha256": _sha256(reference_cif),
        "license_policy": {
            "acquisition_route": "mp-api via Crystal-DB scripts/build_crystaldb_corpus.py",
            "web_scraping_used": False,
            "intended_use": "local research benchmark artifact",
        },
        "phase": "ordered low-symmetry C2 model",
        "space_group_symbol": analyzer.get_space_group_symbol(),
        "space_group_number": analyzer.get_space_group_number(),
        "crystal_system": analyzer.get_crystal_system(),
        "cell_choice": "downloaded 40-site cell; primitive finder also returns 40 sites",
        "lattice": structure.lattice.as_dict(),
        "full_cell_formula": structure.composition.formula,
        "reduced_formula": structure.composition.reduced_formula,
        "total_atom_count": len(structure),
        "primitive_atom_count": len(primitive) if primitive is not None else len(structure),
        "is_ordered": structure.is_ordered,
        "occupancy_values": occupancies,
        "partial_occupancy_present": False,
        "si_p_ordering": "explicit, fully ordered across four symmetry-distinct tetrahedral orbit groups",
        "na_ordering": "explicit, fully occupied across four symmetry-distinct Na orbit groups",
        "coordination_cutoffs_angstrom": COORDINATION_CUTOFFS_ANGSTROM,
        "coordination_counts": coordination,
        "orbit_count": len(orbit_rows),
        "qlip_first_scope": {
            "fixed_species": ["Na", "Zr", "O"],
            "variable_species": ["Si", "P"],
            "variable_orbit_multiplicities": [
                row["multiplicity"] for row in orbit_rows if row["species"] in {"Si", "P"}
            ],
            "feasible_tetrahedral_species_allocations": 3,
            "reference_assignment_is_one_of_feasible_alternatives": True,
        },
        "scientific_claim_limits": [
            "Materials Project energy fields are provenance metadata, not a new stability calculation.",
            "Reference selection does not prove NASICON topology recovery by QLIP.",
            "Experimental realizability and novelty are not established.",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "reference_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze and audit an ordered NASICON reference structure.")
    parser.add_argument("--source-cif", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--material-id", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata = build_reference_artifacts(
        source_cif=args.source_cif,
        source_manifest=args.source_manifest,
        material_id=args.material_id,
        out_dir=args.out_dir,
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
