from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from scripts.validate_full_100_manifest import EXPECTED_MODE_COUNTS, validate_manifest


MANIFEST = Path("benchmarks/full_100_seeded_20260626/full_100_skill_loop_manifest.csv")


def _rows() -> list[dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_full_100_manifest_validation_passes() -> None:
    assert validate_manifest(MANIFEST) == []


def test_full_100_manifest_mode_distribution() -> None:
    rows = _rows()

    assert Counter(row["benchmark_mode"] for row in rows) == EXPECTED_MODE_COUNTS


def test_full_100_manifest_prompt_ids_unique() -> None:
    rows = _rows()
    prompt_ids = [row["prompt_id"] for row in rows]

    assert len(prompt_ids) == len(set(prompt_ids))


def test_full_100_manifest_adversarial_rows_marked_infeasible() -> None:
    adversarial_rows = [
        row for row in _rows() if row["benchmark_mode"] == "adversarial_or_infeasible"
    ]

    assert len(adversarial_rows) == 10
    assert {row["expected_solver_status"] for row in adversarial_rows} == {
        "infeasible_or_invalid"
    }
