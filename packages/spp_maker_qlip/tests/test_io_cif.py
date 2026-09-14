"""Tests for CIF loading adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from spp_maker.io_cif import load_cif, load_cifs_from_dir


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cifs"


def test_load_cif_success() -> None:
    loaded = load_cif(FIXTURE_DIR / "nacl.cif")

    assert len(loaded.symbols) > 0
    assert loaded.positions.shape == (len(loaded.symbols), 3)
    assert loaded.cell.shape == (3, 3)
    assert isinstance(loaded.pbc, tuple)
    assert len(loaded.pbc) == 3
    assert all(isinstance(value, bool) for value in loaded.pbc)


def test_load_cifs_from_dir_sorts_and_loads() -> None:
    loaded = load_cifs_from_dir(FIXTURE_DIR)
    names = [Path(item.path).name for item in loaded]

    assert names == sorted(names, key=str.lower)
    assert len(loaded) == 2
    assert names == ["nacl.cif", "sic.cif"]


def test_load_cif_bad_path_raises_value_error(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.cif"

    with pytest.raises(ValueError, match=r"^Failed to load CIF '.*missing\.cif':"):
        load_cif(missing_path)
