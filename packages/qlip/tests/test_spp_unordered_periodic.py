import tempfile
from pathlib import Path

import numpy as np
import pytest
from ase.build import bulk
from ase.io import write

from qlip.interactions.spp import SPPCollection
from tools.audit_spp_objective import audit as audit_spp_objective


class _ConstantSPP:
    def __call__(self, distance):
        return 1.0


def _collection(*pairs, cutoff):
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = float(cutoff)
    collection.spps = {tuple(sorted(pair)): _ConstantSPP() for pair in pairs}
    collection.missing_pair_policy = "neutral"
    collection.regularisation_spps = {}
    collection.regularisation_weight = 0.0
    return collection


def _score(collection, atoms):
    return float(
        collection.score(
            atoms.get_chemical_symbols(),
            atoms.get_positions(),
            atoms.cell,
            pbc=True,
        )
    )


def test_one_atom_periodic_self_images_use_unordered_count():
    collection = _collection(("H", "H"), cutoff=5.1)

    score = collection.score(
        ["H"],
        np.array([[0.0, 0.0, 0.0]]),
        np.diag([5.0, 5.0, 5.0]),
        pbc=True,
    )

    # The six directed translations are three unordered +/-T image pairs.
    assert score == 3.0


def test_distinct_species_off_diagonal_count_is_unchanged():
    collection = _collection(("H", "He"), cutoff=5.1)
    atoms = bulk("Cu", "sc", a=5.0).repeat((2, 1, 1))
    atoms.set_chemical_symbols(["H", "He"])

    # The atoms at fractional x=0 and x=1/2 have two boundary-equivalent
    # periodic images at distance 2.5 A; this existing i<j convention remains.
    assert _score(collection, atoms) == 2.0


def test_nonperiodic_scoring_is_unchanged():
    collection = _collection(("H", "He"), cutoff=2.0)

    score = collection.score(
        ["H", "He"],
        np.array([[0.0, 0.0, 0.0], [1.25, 0.0, 0.0]]),
        np.diag([10.0, 10.0, 10.0]),
        pbc=False,
    )

    assert score == 1.0


def test_rocksalt_primitive_conventional_and_supercell_scores_per_atom_are_invariant():
    collection = _collection(("Na", "Na"), ("Cl", "Cl"), cutoff=4.1)
    primitive = bulk("NaCl", "rocksalt", a=5.64)
    conventional = bulk("NaCl", "rocksalt", a=5.64, cubic=True)
    supercell = primitive.repeat((2, 2, 2))

    scores_per_atom = [
        _score(collection, atoms) / len(atoms)
        for atoms in (primitive, conventional, supercell)
    ]

    assert scores_per_atom == pytest.approx([6.0, 6.0, 6.0], abs=1e-12)
    assert max(scores_per_atom) - min(scores_per_atom) < 1e-12


def test_objective_audit_applies_half_weight_to_symmetric_self_images():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pot_path = root / "pots" / "H-H" / "H-H.POT"
        pot_path.parent.mkdir(parents=True)
        pot_path.write_text(
            "0.5 1.0\n2.0 1.0\n5.0 1.0\n6.0 1.0\n",
            encoding="utf-8",
        )
        cif_path = root / "one_atom.cif"
        atoms = bulk("H", "sc", a=5.0)
        write(cif_path, atoms)

        payload = audit_spp_objective(
            cif_path,
            root / "pots",
            cutoff=5.1,
            missing_pair_policy="neutral",
            guidance_weight=1.0,
        )

    diagonal = [row for row in payload["contributions"] if row["diagonal_self_image"]]
    assert len(diagonal) == 6
    assert {row["interaction_multiplicity"] for row in diagonal} == {0.5}
    assert payload["summary"]["diagonal_self_image_equivalent_pair_count"] == 3.0
    assert payload["summary"]["total_spp_score"] == pytest.approx(3.0, abs=1e-12)
