"""Select and freeze Dataset E final targets after the method freeze."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow.paper_scaffolds_dataset_e import (  # noqa: E402
    build_dataset_e_alternatives,
)


OUT = REPO / "artifacts" / "Paper_scaffolds_september" / "Dataset_E_complex_topology_showcase"
CRYSTAL = Path(
    r"C:\Users\brown\Documents\GitHub\Crystal-DB\artifacts\Paper_scaffolds_september\specialist_corpora"
)
DATABASES = {
    "NASICON": CRYSTAL / "families" / "NASICON" / "PAPER_SCAFFOLDS_NASICON_V1" / "crystaldb.sqlite",
    "RUDDLESDEN_POPPER": CRYSTAL / "families" / "RUDDLESDEN_POPPER" / "PAPER_SCAFFOLDS_RUDDLESDEN_POPPER_V1" / "crystaldb.sqlite",
    "GARNET": CRYSTAL / "families" / "GARNET" / "PAPER_SCAFFOLDS_GARNET_V1" / "crystaldb.sqlite",
    "ARGYRODITE": CRYSTAL / "argyrodite_v2" / "PAPER_SCAFFOLDS_ARGYRODITE_ORDERED_V2.sqlite",
}
FINAL = {
    "NASICON_R3_PHOSPHATE": [
        "materials_project-d45fe362",
        "materials_project-9c8457d0",
        "materials_project-933a1cf8",
    ],
    "RP_N1": [
        "materials_project-36a1285e",
        "materials_project-5a724b90",
        "materials_project-5e1e8ccc",
    ],
    "RP_N2": [
        "materials_project-2fee4323",
        "materials_project-97e5e9fe",
        "materials_project-e87f5b2a",
    ],
    "GARNET_IA3D": [
        "materials_project-03e2cee1",
        "materials_project-5f2aa239",
        "materials_project-b2222728",
    ],
    "GARNET_I41ACD": ["materials_project-20e51f8a"],
    "ARGYRODITE_F43M": ["materials_project-d05c0575", "materials_project-4d6d1409"],
    "ARGYRODITE_PNA21": ["materials_project-3cd94477", "materials_project-5b065b87"],
    "ARGYRODITE_CC": ["materials_project-3c828ac7"],
}
FAMILY = {
    "NASICON_R3_PHOSPHATE": "NASICON",
    "RP_N1": "RUDDLESDEN_POPPER",
    "RP_N2": "RUDDLESDEN_POPPER",
    "GARNET_IA3D": "GARNET",
    "GARNET_I41ACD": "GARNET",
    "ARGYRODITE_F43M": "ARGYRODITE",
    "ARGYRODITE_PNA21": "ARGYRODITE",
    "ARGYRODITE_CC": "ARGYRODITE",
}
REQUEST = {
    "NASICON_R3_PHOSPHATE": "Generate an ordered NASICON-type structure with composition {formula}.",
    "RP_N1": "Generate an ordered n=1 Ruddlesden-Popper structure with composition {formula}.",
    "RP_N2": "Generate an ordered n=2 Ruddlesden-Popper structure with composition {formula}.",
    "GARNET_IA3D": "Generate an ordered garnet structure with composition {formula}.",
    "GARNET_I41ACD": "Generate an ordered tetragonal garnet structure with composition {formula}.",
    "ARGYRODITE_F43M": "Generate an ordered argyrodite structure with composition {formula}.",
    "ARGYRODITE_PNA21": "Generate an ordered argyrodite structure with composition {formula}.",
    "ARGYRODITE_CC": "Generate an ordered argyrodite structure with composition {formula}.",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(database: Path, structure_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT s.structure_id, s.reduced_formula, p.source_id,
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
        raise RuntimeError(f"missing final target {structure_id}")
    return dict(row)


def main() -> int:
    method = OUT / "METHOD_FREEZE.json"
    validation = OUT / "VALIDATION_METHOD_FREEZE.json"
    development_path = OUT / "DEVELOPMENT_ROSTER.csv"
    development_ids = {
        row["structure_id"]
        for row in csv.DictReader(development_path.open(newline="", encoding="utf-8"))
    }
    rows = []
    for subtype, structure_ids in FINAL.items():
        family = FAMILY[subtype]
        database = DATABASES[family]
        for offset, structure_id in enumerate(structure_ids, start=1):
            if structure_id in development_ids:
                raise RuntimeError(f"final target overlaps development: {structure_id}")
            item = record(database, structure_id)
            formula = str(item["reduced_formula"])
            alternatives = build_dataset_e_alternatives(
                {"formula": formula, "family": family, "topology_subclass": subtype}
            )
            rows.append(
                {
                    "row_id": f"E_{subtype}_{offset:02d}",
                    "family": family,
                    "subtype": subtype,
                    "formula": formula,
                    "request": REQUEST[subtype].format(formula=formula),
                    "target_reference_id": structure_id,
                    "target_source_id": item["source_id"],
                    "target_cif_sha256": item["cif_sha256"],
                    "database_sha256": sha256(database),
                    "annotation": json.dumps(
                        json.loads(item["family_assignment_evidence_json"]),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "pre_generation_alternative_count": len(alternatives),
                    "target_reference_exclusion_required": True,
                    "target_coordinates_or_lattice_read_for_scaffold": False,
                    "replacement_if_failed": False,
                }
            )
    roster = OUT / "FINAL_SHOWCASE_ROSTER.csv"
    with roster.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    freeze = {
        "schema_version": "dataset_e.final_showcase_roster_freeze.v1",
        "frozen_before_retrieval_spp_or_generation": True,
        "row_count": len(rows),
        "counts_by_subtype": {
            subtype: sum(row["subtype"] == subtype for row in rows) for subtype in FINAL
        },
        "roster_sha256": sha256(roster),
        "method_freeze_sha256": sha256(method),
        "validation_method_freeze_sha256": sha256(validation),
        "development_roster_sha256": sha256(development_path),
        "development_overlap_count": 0,
        "target_reference_exclusion_required_for_all": True,
        "denominator_locked": True,
        "failed_rows_may_not_be_replaced": True,
        "selection_note": "18 scientifically representable, chemically diverse rows; counts were not forced where ordered development orbits did not support additional chemistry.",
    }
    (OUT / "FINAL_SHOWCASE_ROSTER_FREEZE.json").write_text(
        json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(freeze, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
