from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "branch" / "benchmark_cases" / "csp_case.schema.json"


def load_case_set(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        cases = payload.get("cases", [])
    else:
        cases = payload
    if not isinstance(cases, list):
        raise ValueError("Benchmark case file must contain a list of cases or {'cases': [...]} payload.")
    return cases


def validate_case(case: dict[str, Any]) -> None:
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(case), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        pointer = "/" + "/".join(str(x) for x in err.absolute_path)
        raise ValueError(f"{case.get('case_id', '<unknown>')}{pointer}: {err.message}")
