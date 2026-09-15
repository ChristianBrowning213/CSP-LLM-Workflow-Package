"""Validate the seeded 100-run Skill-Loop-CSP benchmark manifest."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


EXPECTED_SEED = "20260626"
EXPECTED_NUM_ROWS = 100
EXPECTED_MODE_COUNTS = {
    "loose_design_intent": 40,
    "motif_specific": 25,
    "retrieval_evidence_grounded": 15,
    "solver_constraint_heavy": 10,
    "adversarial_or_infeasible": 10,
}


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_json_rows(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]
    if isinstance(payload, list):
        return payload
    raise ValueError(f"{path} must contain a JSON list or an object with a rows list")


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_manifest(csv_path: Path) -> list[str]:
    rows = _load_csv(csv_path)
    errors: list[str] = []

    _require(len(rows) == EXPECTED_NUM_ROWS, f"expected 100 CSV rows, found {len(rows)}", errors)

    run_indices: list[int] = []
    for row_number, row in enumerate(rows, start=2):
        value = (row.get("run_index") or "").strip()
        try:
            run_indices.append(int(value))
        except ValueError:
            errors.append(f"row {row_number}: run_index is not an integer: {value!r}")

    if len(run_indices) == len(rows):
        _require(
            run_indices == list(range(1, EXPECTED_NUM_ROWS + 1)),
            "run_index must be exactly 1..100",
            errors,
        )

    seeds = {(row.get("seed") or "").strip() for row in rows}
    _require(seeds == {EXPECTED_SEED}, f"all rows must use seed {EXPECTED_SEED}; found {seeds}", errors)

    prompt_ids = [(row.get("prompt_id") or "").strip() for row in rows]
    _require(
        len(prompt_ids) == len(set(prompt_ids)),
        "prompt_id values must be unique",
        errors,
    )
    _require(all(prompt_ids), "prompt_id values must not be blank", errors)

    modes = Counter((row.get("benchmark_mode") or "").strip() for row in rows)
    _require(
        dict(modes) == EXPECTED_MODE_COUNTS,
        f"benchmark_mode distribution mismatch: expected {EXPECTED_MODE_COUNTS}, found {dict(modes)}",
        errors,
    )

    blank_inputs = [row.get("run_index", "?") for row in rows if not (row.get("input_text") or "").strip()]
    _require(not blank_inputs, f"input_text is blank for run_index values {blank_inputs}", errors)

    missing_formula = [
        row.get("run_index", "?")
        for row in rows
        if (row.get("benchmark_mode") or "").strip() != "adversarial_or_infeasible"
        and not (row.get("target_formula") or "").strip()
    ]
    _require(
        not missing_formula,
        f"target_formula is required for non-adversarial rows: {missing_formula}",
        errors,
    )

    archive_dirs = [(row.get("run_archive_dir") or "").strip() for row in rows]
    _require(all(archive_dirs), "run_archive_dir values must not be blank", errors)
    _require(
        len(archive_dirs) == len(set(archive_dirs)),
        "run_archive_dir values must be unique",
        errors,
    )

    json_path = csv_path.with_suffix(".json")
    _require(json_path.exists(), f"matching JSON manifest does not exist: {json_path}", errors)
    if json_path.exists():
        try:
            json_rows = _load_json_rows(json_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"could not read JSON manifest {json_path}: {exc}")
        else:
            _require(
                len(json_rows) == len(rows),
                f"JSON row count {len(json_rows)} does not match CSV row count {len(rows)}",
                errors,
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_csv", type=Path)
    args = parser.parse_args()

    errors = validate_manifest(args.manifest_csv)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"Manifest validation passed: {args.manifest_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
