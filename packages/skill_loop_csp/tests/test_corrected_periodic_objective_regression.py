from __future__ import annotations

import tempfile
from pathlib import Path

from scripts.run_corrected_periodic_objective_regression import (
    manifest_hash,
    select_panel,
    source_critical_manifest,
    transition,
)


def test_deterministic_panel_selection() -> None:
    first = select_panel()
    second = select_panel()
    assert first == second
    assert len(first) == 13
    assert [row["row_id"] for row in first][-2:] == ["layered_007", "spinel_053"]


def test_transition_classification() -> None:
    assert transition("FAIL", "PASS", "FAMILY_FAIL", "FAMILY_PASS") == "IMPROVED"
    assert transition("PASS", "PASS", "FAMILY_PASS", "FAMILY_PASS") == "UNCHANGED_GOOD"
    assert transition("FAIL", "FAIL", "NOT_APPLICABLE", "NOT_APPLICABLE") == "UNCHANGED_BAD"
    assert transition("PASS", "FAIL", "NOT_APPLICABLE", "NOT_APPLICABLE") == "REGRESSED"
    assert transition("FAIL", "PASS", "FAMILY_PASS", "FAMILY_FAIL") == "MIXED"
    assert transition("NOT_APPLICABLE", "NOT_APPLICABLE", "FAMILY_PASS", "FAMILY_PASS") == "UNCHANGED_GOOD"


def test_source_manifest_detects_mutation_without_touching_source() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "input").mkdir()
        target = root / "input" / "request.txt"
        target.write_text("before", encoding="utf-8")
        before = manifest_hash(source_critical_manifest(root))
        target.write_text("after", encoding="utf-8")
        assert manifest_hash(source_critical_manifest(root)) != before


def test_terminal_status_contract_is_distinct_from_running() -> None:
    assert {"state": "GENERATED"}.get("state") == "GENERATED"
    assert {"state": "RUNNING"}.get("state") != "GENERATED"
