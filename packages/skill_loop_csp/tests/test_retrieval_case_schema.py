from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_retrieval_case_schema_valid_example() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "docs" / "branch" / "benchmark_cases" / "retrieval_case.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    payload = {
        "case_id": "retrieval_tio2_01",
        "query": "TiO2 rutile",
        "retrieval_mode": "metadata",
        "expected_structure_ids": ["mp-1"],
    }
    errors = list(validator.iter_errors(payload))
    assert errors == []
