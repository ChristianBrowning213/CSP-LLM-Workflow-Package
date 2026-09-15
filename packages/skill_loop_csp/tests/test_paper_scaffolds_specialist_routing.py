"""Paper_scaffolds_september specialist family corpus routing.

Confirms the explicit logical-database selectors added for the scaffold-paper
specialist families resolve to the frozen accepted-only Crystal-DB rebuilds and
that the pre-existing general/spinel/layered/nasicon routing is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sok_llm_orchestrator.retrieval.corpus_router import route_corpus


@pytest.fixture()
def registry(workdir: Path) -> Path:
    tmp_path = workdir
    corpora = {
        "mp_stable_10k_v1",
        "mp_spinel_oxides_v1",
        "mp_layered_battery_oxides_v1",
        "nasicon_specialist_v3",
        "nasicon_specialist_all_targets_out_v3",
        "paper_scaffolds_rocksalt_v1",
        "paper_scaffolds_olivine_v2",
        "paper_scaffolds_ruddlesden_popper_v1",
        "paper_scaffolds_garnet_v1",
        "paper_scaffolds_nasicon_v1",
        "paper_scaffolds_argyrodite_v2",
    }
    payload = {"schema_version": "specialist_corpus_registry.v1", "corpora": {}}
    for name in corpora:
        db = tmp_path / f"{name}.db"
        db.write_bytes(b"sqlite-placeholder")
        payload["corpora"][name] = {"database": str(db), "path_base": "repository"}
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("rocksalt", "paper_scaffolds_rocksalt_v1"),
        ("olivine", "paper_scaffolds_olivine_v2"),
        ("ruddlesden_popper", "paper_scaffolds_ruddlesden_popper_v1"),
        ("garnet", "paper_scaffolds_garnet_v1"),
        ("nasicon", "paper_scaffolds_nasicon_v1"),
        ("argyrodite", "paper_scaffolds_argyrodite_v2"),
    ],
)
def test_specialist_selectors_route_to_frozen_rebuilds(registry: Path, selector: str, expected: str) -> None:
    route = route_corpus("Generate a candidate", formula="NaCl", registry_path=registry, logical_selector=selector)
    assert route.corpus_id == expected


def test_existing_selectors_unchanged(registry: Path) -> None:
    assert route_corpus("x", formula="MgO", registry_path=registry, logical_selector="general").corpus_id == "mp_stable_10k_v1"
    assert route_corpus("x", formula="MgAl2O4", registry_path=registry, logical_selector="spinel").corpus_id == "mp_spinel_oxides_v1"
    assert route_corpus("x", formula="LiCoO2", registry_path=registry, logical_selector="layered").corpus_id == "mp_layered_battery_oxides_v1"


def test_unknown_selector_still_rejected(registry: Path) -> None:
    with pytest.raises(ValueError):
        route_corpus("x", formula="MgO", registry_path=registry, logical_selector="not_a_family")
