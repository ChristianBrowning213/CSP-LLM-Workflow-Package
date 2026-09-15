from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_csp_case_schema_valid_example() -> None:
    root = Path(__file__).resolve().parents[1]
    schema_path = root / "docs" / "branch" / "benchmark_cases" / "csp_case.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = {
        "case_id": "case-1",
        "case_class": "easy-improvement",
        "composition": "TiO2",
        "symmetry_preference": "P42/mnm",
        "retrieval_mode": "metadata",
        "property_bias": "property_x",
        "allowed_corpora": ["composition_tight"],
        "cell_candidate_policy": "fixed_benchmark",
        "expected_analogue_family": "rutile",
        "evaluation_preset": "rediscovery_check",
    }
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(payload)) == []
