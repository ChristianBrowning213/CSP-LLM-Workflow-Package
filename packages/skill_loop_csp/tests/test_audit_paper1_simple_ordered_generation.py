from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_paper1_simple_ordered_generation.py"
SPEC = importlib.util.spec_from_file_location("paper1_generation_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
auditor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = auditor
SPEC.loader.exec_module(auditor)


def test_classifies_valid_incumbents_as_candidates() -> None:
    for status in ("OPTIMAL", "FEASIBLE_TIME_LIMIT"):
        assert auditor.classify(
            {"generation_state": "GENERATED", "solver_status": status}, "EXECUTABLE", True,
        ) == status


def test_preflight_coverage_failure_remains_separate_from_technical_failure() -> None:
    assert auditor.classify(
        {"generation_state": "TECHNICAL_FAILURE"},
        "SCIENTIFIC_SPP_PAIR_COVERAGE_FAILURE", False,
    ) == "PREFLIGHT_SPP_PAIR_COVERAGE_FAILURE"


def test_summary_uses_full_frozen_denominator() -> None:
    rows = [
        {"outcome": "OPTIMAL", "candidate_present": True},
        {"outcome": "FEASIBLE_TIME_LIMIT", "candidate_present": True},
        {"outcome": "PREFLIGHT_SPP_PAIR_COVERAGE_FAILURE", "candidate_present": False},
    ]
    result = auditor._summary(rows)
    assert result["attempted"] == 3
    assert result["candidates"] == 2
    assert result["generation_rate"] == 2 / 3
