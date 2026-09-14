import json
import tempfile
from pathlib import Path

from pymatgen.core import Lattice, Structure

from crystal_db.family_dataset import (
    layered_oxide_candidate_reason,
    spinel_stoichiometry_compatible,
    structure_bundle_complete,
    write_json_atomic,
    write_structure_bundle,
)


def test_candidate_chemistry_rules_are_strict():
    assert spinel_stoichiometry_compatible("MgAl2O4")
    assert spinel_stoichiometry_compatible("Fe3O4")
    assert not spinel_stoichiometry_compatible("MgAl2O3")
    assert layered_oxide_candidate_reason("LiCoO2", "Li") is None
    assert layered_oxide_candidate_reason("NaFeO2", "Na") is None
    assert layered_oxide_candidate_reason("LiFePO4", "Li") == "OUT_OF_SCOPE_POLYANION_OR_HALIDE"
    assert layered_oxide_candidate_reason("CoO2", "Li") == "WORKING_ION_ABSENT"


def test_structure_bundle_has_verified_source_primitive_and_conventional_forms():
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        structure = Structure.from_spacegroup(
            "R-3m",
            Lattice.hexagonal(2.82, 14.05),
            ["Li", "Co", "O"],
            [[0, 0, 0], [0, 0, 0.5], [0, 0, 0.24]],
        )

        bundle = write_structure_bundle(tmp_path, "mp-test", structure)

        assert structure_bundle_complete(bundle)
        assert set(bundle["paths"]) == {"source", "primitive", "conventional"}
        assert all(bundle["site_counts"][name] > 0 for name in bundle["site_counts"])


def test_atomic_json_manifest_is_valid():
    with tempfile.TemporaryDirectory() as temporary_directory:
        tmp_path = Path(temporary_directory)
        path = tmp_path / "manifest.json"

        write_json_atomic(path, {"rows": [{"material_id": "mp-test"}]})

        assert json.loads(path.read_text(encoding="utf-8"))["rows"][0]["material_id"] == "mp-test"
        assert not (tmp_path / ".manifest.json.tmp").exists()
