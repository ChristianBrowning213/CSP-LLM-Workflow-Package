from __future__ import annotations

import importlib.util
from pathlib import Path

from pymatgen.core import Lattice, Structure


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/acquire_paper_scaffolds_new_families.py"
SPEC = importlib.util.spec_from_file_location("acquire_paper_scaffolds_new_families", SCRIPT)
acquire = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(acquire)


def test_rocksalt_requires_the_actual_b1_prototype_not_formula_alone():
    rocksalt = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    cesium_chloride = Structure(
        Lattice.cubic(4.1), ["Cs", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )

    assert acquire.classify_structure("ROCKSALT", rocksalt, [])[0] is True
    assert acquire.classify_structure("ROCKSALT", cesium_chloride, [])[0] is False


def test_prototype_filter_is_deterministic_and_rejects_distorted_structure():
    template = Structure(
        Lattice.orthorhombic(5, 6, 7),
        ["Li", "Fe", "P", "O", "O", "O", "O"],
        [[0, 0, 0], [0.2, 0.2, 0.2], [0.4, 0.4, 0.4], [0.1, 0.3, 0.5], [0.3, 0.5, 0.7], [0.5, 0.7, 0.1], [0.7, 0.1, 0.3]],
    )
    equivalent = template.copy()
    distorted = template.copy()
    distorted.translate_sites([1], [0.35, 0.35, 0.35], frac_coords=True)

    assert acquire.anonymous_prototype_fit(equivalent, [template]) == 0
    assert acquire.anonymous_prototype_fit(equivalent, [template]) == 0
    assert acquire.anonymous_prototype_fit(distorted, [template]) is None


def test_oxygen_stoichiometry_prevents_anonymous_species_remapping_false_positive():
    valid_rp = Structure(
        Lattice.tetragonal(4, 12),
        ["Sr", "Sr", "Ti", "O", "O", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.2], [0, 0, 0.5], [0.2, 0.2, 0.2], [0.8, 0.8, 0.8], [0.3, 0.7, 0.5], [0.7, 0.3, 0.5]],
    )
    oxygen_poor = Structure(
        valid_rp.lattice,
        ["Sr", "Sr", "Sr", "Sr", "P", "P", "O"],
        valid_rp.frac_coords,
    )

    assert acquire.oxygen_stoichiometry_matches("RUDDLESDEN_POPPER", valid_rp)
    assert not acquire.oxygen_stoichiometry_matches("RUDDLESDEN_POPPER", oxygen_poor)
