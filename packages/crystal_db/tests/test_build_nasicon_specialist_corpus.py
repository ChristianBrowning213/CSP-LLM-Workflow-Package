from __future__ import annotations

import importlib.util
from pathlib import Path

from pymatgen.core import Structure


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_nasicon_specialist_corpus.py"
SPEC = importlib.util.spec_from_file_location("build_nasicon_specialist_corpus", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


# Relocation-only change: the source test reached into a sibling Skill-Loop
# worktree. The exact fixture is archived locally so this suite is standalone.
REFERENCE = Path(__file__).resolve().parent / "fixtures" / "nasicon" / "reference.cif"


def test_required_target_pairs_are_all_15_unordered_pairs():
    pairs = builder.required_pairs()
    assert len(pairs) == 15
    assert len(set(pairs)) == 15
    assert {"Na-Zr", "P-Si", "Zr-Zr"} <= set(pairs)


def test_pair_coverage_preserves_supporter_ids_and_reports_missing():
    records = [
        {"internal_id": "framework", "elements": ["Na", "Zr", "O"]},
        {"internal_id": "tetra", "elements": ["Si", "P", "O"]},
    ]
    rows = {row["pair"]: row for row in builder.pair_coverage(records)}
    assert rows["Na-Zr"]["covered"] is True
    assert rows["Na-Zr"]["supporting_internal_ids"] == "framework"
    assert rows["P-Si"]["covered"] is True
    assert rows["Na-P"]["covered"] is False


def test_selected_reference_satisfies_tier_1_framework_proxy():
    metrics = builder.framework_metrics(Structure.from_file(REFERENCE))
    assert metrics["coordination_all_expected"] is True
    assert metrics["framework_components"] == 1
    assert metrics["framework_dimensionality"] == 3
