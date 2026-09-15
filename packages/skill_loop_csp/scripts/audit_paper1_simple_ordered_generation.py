"""Create the frozen Paper 1 generation-state audit required before SCA."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


FIELDS = (
    "row_id", "family", "preflight_classification", "generation_state",
    "solver_status", "outcome", "candidate_present", "candidate_sha256",
    "scientific_attempt_count", "technical_attempt_count", "error",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify(status: Mapping[str, Any], preflight_classification: str, candidate_present: bool) -> str:
    if preflight_classification == "SCIENTIFIC_SPP_PAIR_COVERAGE_FAILURE":
        return "PREFLIGHT_SPP_PAIR_COVERAGE_FAILURE"
    solver = str(status.get("solver_status", ""))
    state = str(status.get("generation_state", ""))
    if state == "GENERATED" and candidate_present and solver in {"OPTIMAL", "FEASIBLE_TIME_LIMIT"}:
        return solver
    if solver == "INFEASIBLE" or state == "SCIENTIFIC_FAILURE":
        return "INFEASIBLE"
    if state in {"NOT_STARTED", "RUNNING", ""}:
        return state or "MISSING_STATUS"
    return "TECHNICAL_FAILURE"


def audit_row(row_root: Path, preflight_row: Mapping[str, Any]) -> dict[str, Any]:
    status_path = row_root / "status" / "generation_status.json"
    status = read_json(status_path) if status_path.is_file() else {}
    candidate = row_root / "generated" / "candidate.cif"
    candidate_present = candidate.is_file()
    outcome = classify(status, str(preflight_row["classification"]), candidate_present)
    return {
        "row_id": str(preflight_row["row_id"]),
        "family": str(preflight_row["family"]),
        "preflight_classification": str(preflight_row["classification"]),
        "generation_state": str(status.get("generation_state", "MISSING")),
        "solver_status": str(status.get("solver_status", "")),
        "outcome": outcome,
        "candidate_present": candidate_present,
        "candidate_sha256": str(status.get("candidate_sha256", "")),
        "scientific_attempt_count": int(status.get("scientific_attempt_count", 0)),
        "technical_attempt_count": int(status.get("technical_attempt_count", 0)),
        "error": str(status.get("error", "")),
    }


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    outcomes = Counter(str(row["outcome"]) for row in rows)
    candidates = sum(bool(row["candidate_present"]) for row in rows)
    return {
        "attempted": len(rows),
        "candidates": candidates,
        "generation_rate": candidates / len(rows) if rows else 0.0,
        "OPTIMAL": outcomes["OPTIMAL"],
        "FEASIBLE_TIME_LIMIT": outcomes["FEASIBLE_TIME_LIMIT"],
        "INFEASIBLE": outcomes["INFEASIBLE"],
        "technical_failures": outcomes["TECHNICAL_FAILURE"],
        "preflight_spp_pair_coverage_failures": outcomes["PREFLIGHT_SPP_PAIR_COVERAGE_FAILURE"],
        "not_completed": sum(outcomes[name] for name in ("NOT_STARTED", "RUNNING", "MISSING_STATUS")),
    }


def audit(*, preflight_audit: Path, run_root: Path, output_root: Path) -> dict[str, Any]:
    preflight = read_json(preflight_audit)
    rows = [
        audit_row(run_root / str(row["row_id"]), row)
        for row in preflight["rows"]
    ]
    overall = _summary(rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["family"])].append(row)
    by_family = {family: _summary(items) for family, items in sorted(grouped.items())}
    assertions = {
        "all_frozen_rows_accounted_for": len(rows) == sum(preflight["counts"].values()),
        "all_executable_rows_terminal": all(
            row["outcome"] not in {"NOT_STARTED", "RUNNING", "MISSING_STATUS"}
            for row in rows if row["preflight_classification"] == "EXECUTABLE"
        ),
        "every_generated_state_has_candidate": all(
            row["candidate_present"] for row in rows if row["generation_state"] == "GENERATED"
        ),
        "no_candidate_for_preflight_coverage_failures": all(
            not row["candidate_present"] for row in rows
            if row["preflight_classification"] == "SCIENTIFIC_SPP_PAIR_COVERAGE_FAILURE"
        ),
    }
    result = {
        "schema_version": "paper1_simple_ordered_generation_audit.v1",
        "preflight_audit": str(preflight_audit.resolve()),
        "run_root": str(run_root.resolve()),
        "overall": overall, "by_family": by_family,
        "assertions": assertions, "rows": rows,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "GENERATION_AUDIT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output_root / "GENERATION_AUDIT.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in FIELDS} for row in rows)
    lines = ["# Paper 1 generation-state audit", "", "## Overall", ""]
    lines.extend(f"- {key}: {value}" for key, value in overall.items())
    lines.extend(["", "## By family", "", "| Family | Attempted | Candidates | OPTIMAL | Time-limit | Infeasible | Preflight coverage failure | Technical |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for family, values in by_family.items():
        lines.append(
            f"| {family} | {values['attempted']} | {values['candidates']} | {values['OPTIMAL']} | "
            f"{values['FEASIBLE_TIME_LIMIT']} | {values['INFEASIBLE']} | "
            f"{values['preflight_spp_pair_coverage_failures']} | {values['technical_failures']} |"
        )
    (output_root / "GENERATION_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not all(assertions.values()):
        failed = [name for name, value in assertions.items() if not value]
        raise RuntimeError(f"generation audit failed: {', '.join(failed)}")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--preflight-audit", type=Path,
        default=root / "artifacts" / "paper1_spp_positive_domain" / "preflight" / "PREFLIGHT_AUDIT.json",
    )
    parser.add_argument("--run-root", type=Path, default=root / "outputs" / "paper1_simple_ordered_v1")
    parser.add_argument(
        "--output-root", type=Path,
        default=root / "artifacts" / "paper1_spp_positive_domain" / "generation",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = audit(
        preflight_audit=args.preflight_audit.resolve(), run_root=args.run_root.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps(result["overall"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
