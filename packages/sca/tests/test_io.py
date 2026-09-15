from pathlib import Path

import pytest

from sca.io import load_manifest, parse_cif


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_tiny_valid_cif() -> None:
    metadata, structure = parse_cif(FIXTURES / "tiny_valid.cif")

    assert metadata.parse_ok is True
    assert structure is not None
    assert metadata.formula == "Na1 Cl1"
    assert metadata.reduced_formula == "NaCl"
    assert metadata.n_sites == 2
    assert metadata.volume is not None
    assert metadata.density is not None
    assert metadata.error_type is None


def test_parse_malformed_cif_returns_structured_error() -> None:
    metadata, structure = parse_cif(FIXTURES / "malformed.cif")

    assert metadata.parse_ok is False
    assert structure is None
    assert metadata.error_type is not None
    assert metadata.error_message is not None


def test_load_manifest_resolves_relative_paths(tmp_path: Path) -> None:
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("cif_path\ncifs/example.cif\n", encoding="utf-8")

    paths = load_manifest(manifest, "cif_path")

    assert paths == [(tmp_path / "cifs" / "example.cif").resolve()]


def test_load_manifest_rejects_missing_path_column(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("other\nx.cif\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cif_path"):
        load_manifest(manifest, "cif_path")
