from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("pymatgen")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_sca_topology_calibration.py"
SPEC = importlib.util.spec_from_file_location("audit_sca_topology_calibration", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_hash_sorted_is_deterministic_and_not_outcome_dependent() -> None:
    records = [
        {"record_id": "c", "cif_sha256": "ff"},
        {"record_id": "a", "cif_sha256": "0a"},
        {"record_id": "b", "cif_sha256": "0a"},
    ]
    ordered = mod._hash_sorted(records)
    assert [r["record_id"] for r in ordered] == ["a", "b", "c"]
    # order depends only on (cif_sha256, record_id), never on any SCA field
    assert mod._hash_sorted(list(reversed(records))) == ordered


def test_summarise_policy_strict_vs_lenient_and_false_pass() -> None:
    per_row = [
        {"policy": "ROCKSALT", "role": "positive", "topology_status": "PASS"},
        {"policy": "ROCKSALT", "role": "positive", "topology_status": "PASS"},
        {"policy": "ROCKSALT", "role": "positive", "topology_status": "PARTIAL"},
        {"policy": "ROCKSALT", "role": "positive", "topology_status": "FAIL"},
        {"policy": "ROCKSALT", "role": "negative", "topology_status": "PARTIAL"},
        {"policy": "ROCKSALT", "role": "negative", "topology_status": "PASS"},
        {"policy": "ROCKSALT", "role": "negative", "topology_status": "FAIL"},
        {"policy": "ROCKSALT", "role": "negative", "topology_status": "FAIL"},
    ]
    summary = mod.summarise_policy("ROCKSALT", per_row)
    assert summary["positive_n"] == 4
    assert summary["strict_sensitivity"] == 0.5  # 2 PASS / 4
    assert summary["lenient_sensitivity"] == 0.75  # (2 PASS + 1 PARTIAL) / 4
    assert summary["negative_n"] == 4
    assert summary["neg_false_pass"] == 1
    assert summary["strict_false_pass_rate"] == 0.25
    assert summary["strict_specificity"] == 0.75


def test_classify_policy_detail_categories() -> None:
    def summ(**kw):
        base = dict(
            policy="X", positive_n=20, pos_partial=0, strict_sensitivity=1.0,
            lenient_sensitivity=1.0, strict_false_pass_rate=0.0,
        )
        base.update(kw)
        return base

    assert mod._classify_policy_detail(summ(), [], [])[0] == "WELL CALIBRATED"
    assert mod._classify_policy_detail(summ(strict_sensitivity=0.5), [], [])[0] == "OVERLY STRICT"
    assert mod._classify_policy_detail(summ(strict_false_pass_rate=0.5), [], [])[0] == "OVERLY PERMISSIVE"
    assert mod._classify_policy_detail(summ(positive_n=3), [], [])[0] == "INCONCLUSIVE"
    verdict, caveats = mod._classify_policy_detail(summ(strict_false_pass_rate=0.05), [], [])
    assert verdict == "WELL CALIBRATED"
    assert any("permissive" in c for c in caveats)


def test_classify_policy_detail_flags_brittleness() -> None:
    summary = dict(
        policy="X", positive_n=20, pos_partial=0, strict_sensitivity=1.0,
        lenient_sensitivity=1.0, strict_false_pass_rate=0.0,
    )
    rep_rows = [{"policy": "X", "representation_stable": False} for _ in range(10)]
    assert mod._classify_policy_detail(summary, rep_rows, [])[0] == "BRITTLE"


def test_perturb_coords_is_seeded_and_deterministic() -> None:
    from pymatgen.core import Lattice, Structure

    structure = Structure(Lattice.cubic(4.0), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    a = mod._perturb_coords(structure, 0.005, seed=12345)
    b = mod._perturb_coords(structure, 0.005, seed=12345)
    c = mod._perturb_coords(structure, 0.005, seed=999)
    assert a == b
    assert a != c
    assert a.composition == structure.composition  # composition never altered


def test_perturb_scale_preserves_composition_and_changes_volume() -> None:
    from pymatgen.core import Lattice, Structure

    structure = Structure(Lattice.cubic(4.0), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    scaled = mod._perturb_scale(structure, 1.02)
    assert scaled.composition == structure.composition
    assert scaled.volume > structure.volume
    assert abs(scaled.volume / structure.volume - 1.02**3) < 1e-6


def test_policy_controls_negatives_are_structurally_different_a_priori() -> None:
    for policy, spec in mod.POLICY_CONTROLS.items():
        assert spec["positive"] not in spec["negatives"], policy
        assert spec["negatives"], policy
