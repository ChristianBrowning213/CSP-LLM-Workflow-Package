import importlib.util
from pathlib import Path

from pymatgen.core import Lattice, Structure


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_mp_oxide_family_datasets.py"
SPEC = importlib.util.spec_from_file_location("build_mp_oxide_family_datasets", SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(builder)


class FakeSummary:
    def search(self, **kwargs):
        if kwargs["num_elements"] == 2:
            return [
                {"material_id": "mp-fe3o4", "formula_pretty": "Fe3O4"},
                {"material_id": "mp-feo", "formula_pretty": "FeO"},
            ]
        return [
            {"material_id": "mp-mgal2o4", "formula_pretty": "MgAl2O4"},
            {"material_id": "mp-al2o3", "formula_pretty": "Al2O3"},
        ]


class FakeInsertion:
    def search(self, *, working_ion, **kwargs):
        return [
            {
                "id_discharge": f"mp-{working_ion.lower()}coo2",
                "formula_discharge": f"{working_ion}CoO2",
                "working_ion": working_ion,
            },
            {
                "id_discharge": f"mp-{working_ion.lower()}fepo4",
                "formula_discharge": f"{working_ion}FePO4",
                "working_ion": working_ion,
            },
        ]


class FakeMaterials:
    summary = FakeSummary()
    insertion_electrodes = FakeInsertion()


class FakeMPRester:
    materials = FakeMaterials()


def test_spinel_discovery_applies_stoichiometry_and_preserves_query_provenance():
    rows = builder.discover_spinel(FakeMPRester())

    assert [row["material_id"] for row in rows] == ["mp-fe3o4", "mp-mgal2o4"]
    assert rows[0]["source_query"]["num_elements"] == 2
    assert rows[1]["source_query"]["num_elements"] == 3


def test_layered_discovery_keeps_oxide_and_audits_polyanion_rejection():
    rows, rejected = builder.discover_layered(FakeMPRester())

    assert [row["formula"] for row in rows] == ["LiCoO2", "NaCoO2"]
    assert len(rejected) == 2
    assert all(row["reason_codes"] == ["OUT_OF_SCOPE_POLYANION_OR_HALIDE"] for row in rejected)


def test_robocrys_is_skipped_only_when_common_precheck_must_reject():
    valid = Structure(
        Lattice.cubic(5),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.25, 0.25, 0.25], [0.75, 0.75, 0.75]],
    )
    oversized = valid * (2, 2, 2)

    assert builder.requires_robocrys("layered", valid)
    assert not builder.requires_robocrys("layered", oversized)
