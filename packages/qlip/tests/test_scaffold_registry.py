from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import qlip.scaffolds.registry as registry
from qlip.scaffolds import (
    ScaffoldCorpusConfigurationError,
    get_scaffold,
    list_scaffolds,
    resolve_scaffold_corpus_root,
    validate_scaffold,
)


def _empty_valid_corpus(root: Path) -> Path:
    dataset = root / registry.CORPUS_DATASET_NAME
    (dataset / "cifs").mkdir(parents=True)
    (dataset / "manifest.jsonl").write_text("", encoding="utf-8")
    return root


def test_explicit_argument_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    explicit = _empty_valid_corpus(tmp_path / "explicit")
    environment = _empty_valid_corpus(tmp_path / "environment")
    monkeypatch.setenv(registry.CORPUS_ENVIRONMENT_VARIABLE, str(environment))
    resolved = resolve_scaffold_corpus_root(explicit)
    assert resolved.resolution_method == "explicit_argument"
    assert Path(resolved.corpus_root) == explicit.resolve()
    assert resolved.attempted_paths == (str(explicit.resolve()),)


def test_environment_variable_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    environment = _empty_valid_corpus(tmp_path / "environment")
    fake_repo = tmp_path / "GitHub" / "qlip"
    fake_repo.mkdir(parents=True)
    monkeypatch.setenv(registry.CORPUS_ENVIRONMENT_VARIABLE, str(environment))
    monkeypatch.setattr(registry, "_find_qlip_repo_root", lambda start=None: fake_repo)
    resolved = resolve_scaffold_corpus_root()
    assert resolved.resolution_method == "environment_variable"
    assert Path(resolved.corpus_root) == environment.resolve()


def test_sibling_repository_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qlip_root = tmp_path / "Documents" / "GitHub" / "qlip"
    qlip_root.mkdir(parents=True)
    corpus = _empty_valid_corpus(qlip_root.parent / "Skill-Loop-CSP" / "data" / "corpora")
    monkeypatch.delenv(registry.CORPUS_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(registry, "_find_qlip_repo_root", lambda start=None: qlip_root)
    resolved = resolve_scaffold_corpus_root()
    assert resolved.resolution_method == "sibling_repository"
    assert Path(resolved.qlip_repo_root or "") == qlip_root
    assert Path(resolved.skill_loop_repo_root or "") == qlip_root.parent / "Skill-Loop-CSP"
    assert Path(resolved.corpus_root) == corpus


def test_discovery_never_drops_github_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(registry.CORPUS_ENVIRONMENT_VARIABLE, raising=False)
    resolved = resolve_scaffold_corpus_root()
    qlip_root = Path(resolved.qlip_repo_root or "")
    incorrect = qlip_root.parent.parent / "Skill-Loop-CSP" / "data" / "corpora"
    assert Path(resolved.corpus_root) != incorrect
    assert Path(resolved.corpus_root) == qlip_root.parent / "Skill-Loop-CSP" / "data" / "corpora"


def test_structured_missing_root_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qlip_root = tmp_path / "GitHub" / "qlip"
    qlip_root.mkdir(parents=True)
    monkeypatch.delenv(registry.CORPUS_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(registry, "_find_qlip_repo_root", lambda start=None: qlip_root)
    monkeypatch.setattr(registry, "__file__", str(tmp_path / "installed" / "registry.py"))
    with pytest.raises(ScaffoldCorpusConfigurationError) as caught:
        resolve_scaffold_corpus_root()
    error = caught.value
    assert error.resolution_method == "configuration_error"
    assert error.qlip_repo_root == str(qlip_root)
    assert error.corpus_root is None
    assert len(error.attempted_paths) == 2
    assert "No valid scaffold corpus" in str(error)


def test_registry_exposes_seven_hash_verified_versioned_scaffolds() -> None:
    records = list_scaffolds()
    assert len(records) == 7
    assert len({record.scaffold_id for record in records}) == 7
    assert all(record.scaffold_version == "1.0.0" for record in records)
    assert all(validate_scaffold(record).valid for record in records)


def test_all_source_cif_hashes_match_registry() -> None:
    for record in list_scaffolds():
        source = Path(record.source_cif_path)
        assert source.is_file()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == record.source_cif_sha256


def test_registry_contains_required_materially_distinct_families() -> None:
    records = list_scaffolds()
    families = {record.family for record in records}
    assert any("rhombohedral" in family for family in families)
    assert any("monoclinic ordered" in family for family in families)
    assert any("phosphate-only" in family for family in families)
    assert any("LiZr2" in family for family in families)
    assert any("Ti" in family for family in families)
    assert any("Hf" in family for family in families)
    signatures = {
        (
            tuple(round(record.lattice[key], 6) for key in ("a", "b", "c", "alpha", "beta", "gamma")),
            tuple(tuple(round(value, 6) for value in site) for site in record.fractional_candidate_sites),
            tuple(sorted(record.orbit_multiplicities.items())),
        )
        for record in records
    }
    assert len(signatures) == len(records)


def test_duplicate_scaffold_id_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = dict(registry._SOURCES[0])
    monkeypatch.setattr(registry, "_SOURCES", registry._SOURCES + (duplicate,))
    registry._records.cache_clear()
    try:
        with pytest.raises(ValueError, match="duplicate scaffold_id"):
            list_scaffolds()
    finally:
        registry._records.cache_clear()


def test_get_scaffold_and_orbit_partition() -> None:
    record = get_scaffold("nasicon_na3zr2si2po12_c2_ordered")
    assert record.source_formula == "Na3Zr2Si2PO12"
    assert record.source_space_group == "C2"
    assert sum(record.orbit_multiplicities.values()) == len(record.fractional_candidate_sites)
    assert set(record.orbit_coordination_roles) == set(record.orbit_multiplicities)
