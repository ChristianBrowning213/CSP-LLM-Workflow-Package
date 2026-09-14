import random
from typing import Iterable, List, Optional

from .db import connect, init_db
from .policy import get_policy

ELEMENTS = [
    "Li", "Na", "K", "Mg", "Ca", "Al", "Si", "P", "S", "Cl",
    "Fe", "Co", "Ni", "Cu", "Zn", "O", "F", "C", "N", "H",
]

SPACE_GROUPS = ["P1", "P2_1/c", "Fm-3m", "Pnma", "R-3m", "C2/m"]


def _elements_csv(elements: Iterable[str]) -> str:
    return "," + ",".join(elements) + ","


def _reduced_formula(elements: List[str], counts: List[int]) -> str:
    parts = []
    for el, cnt in zip(elements, counts):
        parts.append(f"{el}{cnt if cnt != 1 else ''}")
    return "".join(parts)


def _make_cif(structure_id: str, formula: str, space_group: str, a: float, b: float, c: float) -> str:
    return (
        f"data_{structure_id}\n"
        f"_symmetry_space_group_name_H-M '{space_group}'\n"
        f"_cell_length_a {a:.3f}\n"
        f"_cell_length_b {b:.3f}\n"
        f"_cell_length_c {c:.3f}\n"
        f"_cell_angle_alpha 90\n"
        f"_cell_angle_beta 90\n"
        f"_cell_angle_gamma 90\n"
        f"_chemical_formula_sum '{formula}'\n"
    )


def ingest_sample(db_path: Optional[str] = None, count: int = 100) -> List[str]:
    rng = random.Random(42)
    conn = connect(db_path)
    init_db(conn)

    structure_ids: List[str] = []
    retrieved_at = "2026-02-04T00:00:00Z"
    policy = get_policy("synthetic")

    for i in range(1, count + 1):
        n_elements = 2 if i % 3 else 3
        elements = rng.sample(ELEMENTS, n_elements)
        counts = [rng.randint(1, 4) for _ in elements]
        formula = _reduced_formula(elements, counts)
        reduced = formula
        nsites = rng.randint(2, 20)
        volume = round(rng.uniform(20.0, 300.0), 3)
        space_group = rng.choice(SPACE_GROUPS)
        band_gap = round(rng.uniform(0.0, 5.0), 3) if i % 5 else None
        structure_id = f"crystal-{i:04d}"
        source_id = f"syn-{i:04d}"

        a = rng.uniform(3.0, 10.0)
        b = rng.uniform(3.0, 10.0)
        c = rng.uniform(3.0, 10.0)
        cif_text = _make_cif(structure_id, formula, space_group, a, b, c)

        license_restricted = 1 if i % 17 == 0 else 0
        if license_restricted:
            license_notes = "restricted: synthetic placeholder"
            allow_cif_return = 0
        else:
            license_notes = policy.license_notes
            allow_cif_return = 1 if policy.allow_cif_return else 0

        allow_cif_store = 1 if policy.allow_cif_store else 0
        allow_derivatives = 1 if policy.allow_derivatives else 0
        allow_export = 1 if policy.allow_export else 0

        conn.execute(
            "INSERT OR REPLACE INTO structures (structure_id, cif_text, reduced_formula, nsites, volume, license_restricted) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                structure_id,
                cif_text if allow_cif_store else None,
                reduced,
                nsites,
                volume,
                license_restricted,
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata (structure_id, formula, elements_csv, space_group, band_gap_eV) "
            "VALUES (?, ?, ?, ?, ?)",
            (structure_id, formula, _elements_csv(elements), space_group, band_gap),
        )
        conn.execute(
            "INSERT OR REPLACE INTO provenance (structure_id, source, source_id, retrieved_at, license_notes, "
            "policy_id, allow_cif_store, allow_cif_return, allow_derivatives, allow_export) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                structure_id,
                "synthetic",
                source_id,
                retrieved_at,
                license_notes,
                policy.name,
                allow_cif_store,
                allow_cif_return,
                allow_derivatives,
                allow_export,
            ),
        )
        structure_ids.append(structure_id)

    conn.commit()
    conn.close()
    return structure_ids
