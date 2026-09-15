from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "freeze_paper1_spp_ablation.py"
SPEC = importlib.util.spec_from_file_location("paper1_ablation_freezer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
freezer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = freezer
SPEC.loader.exec_module(freezer)


def test_balanced_selection_is_deterministic_and_result_blind() -> None:
    targets = [
        {"row_id": f"{family}_{index:03d}", "family": family, "outcome": "ignored"}
        for family in ("rocksalt_b1", "cscl_b2")
        for index in range(8, 0, -1)
    ]
    selected = freezer.select_balanced(targets, per_family=3)
    assert [row["row_id"] for row in selected] == [
        "cscl_b2_001", "cscl_b2_002", "cscl_b2_003",
        "rocksalt_b1_001", "rocksalt_b1_002", "rocksalt_b1_003",
    ]


def test_canonical_hash_is_order_independent() -> None:
    assert freezer.canonical_hash({"b": 2, "a": 1}) == freezer.canonical_hash({"a": 1, "b": 2})
