from __future__ import annotations

import pytest

from qlip.data.registry import default_registry
from scripts.validate_base_data import validate


def test_base_data_files_validate():
    validate()


def test_default_registry_loads_all_element_radii():
    default_registry.cache_clear()
    registry = default_registry()
    symbols = registry.element_symbols()

    assert len(symbols) == 118
    assert registry.atomic_radius("Fe") > 0
    assert registry.atomic_radius("Og") > 0
    assert registry.radius_source("Fe")
    assert set(symbols) == set(registry.atomic_radius_map())


def test_required_legacy_symbols_have_default_radius():
    default_registry.cache_clear()
    registry = default_registry()
    required = ["Co", "As", "O", "Li", "Sr", "Zn", "Zr", "Ca", "Mg", "Al", "Si", "Ti", "P", "S", "Y"]

    for symbol in required:
        assert registry.get_default_radius(symbol) > 0
        assert registry.get_radius_record(symbol)["qlip_default_radius_source_id"]


def test_registry_returns_default_covalent_radius_for_co_and_as():
    default_registry.cache_clear()
    registry = default_registry()

    for symbol in ("Co", "As"):
        record = registry.get_radius_record(symbol)
        assert registry.get_default_radius(symbol) == record["qlip_default_radius_angstrom"]
        assert record["qlip_default_radius_kind"] == "covalent"


def test_registry_exposes_real_ionic_radii_rows_for_common_ions():
    default_registry.cache_clear()
    registry = default_registry()

    for symbol in ("Fe", "O", "Ti", "Sr", "Ca"):
        rows = registry.get_ionic_radii(symbol)
        assert rows
        assert any(row["method"] == "smact_shannon" for row in rows)
        assert all(row["radius_angstrom"] > 0 for row in rows)


def test_registry_unsupported_element_is_precise():
    default_registry.cache_clear()
    registry = default_registry()

    with pytest.raises(KeyError, match="No QLIP radius data for element 'Xx'"):
        registry.get_default_radius("Xx")


def test_no_forbidden_radius_source_ids():
    default_registry.cache_clear()
    registry = default_registry()
    forbidden = {"synthetic", "fake", "manual_unknown"}

    for record in registry.radii()["records"].values():
        for key, value in record.items():
            if key.endswith("source_id") and value is not None:
                assert value not in forbidden
