from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_results_extension_v3"


def read(name: str):
    with (OUT / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_factorial_preserves_same_loose_candidate_domain():
    scores = read("03_scaffold_spp/FEASIBLE_ASSIGNMENT_SCORES.csv")
    by_case = {}
    for row in scores:
        by_case.setdefault(row["case_id"], set()).add(row["assignment_id"])
    assert len(by_case) == 7
    assert all(len(assignments) == 2 for assignments in by_case.values())
    for case_id in by_case:
        scaffold = json.loads((OUT / "03_scaffold_spp" / "raw" / case_id / "scaffold_definition.json").read_text(encoding="utf-8"))
        assert scaffold["loose"]["feasible"] == 2
        assert scaffold["loose"]["positions"] == [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]]


def test_neutral_condition_is_not_solver_tie_break_prediction():
    factorial = read("03_scaffold_spp/SCAFFOLD_SPP_FACTORIAL.csv")
    neutral = [r for r in factorial if r["condition"] == "LOOSE_NO_SPP"]
    assert len(neutral) == 7
    assert all(r["solver_status"] == "NO_UNIQUE_PREFERENCE" and r["selected_assignment"] == "NA" for r in neutral)


def test_strict_supplemented_and_excluded_cohorts_are_separate():
    cases = read("03_scaffold_spp/CASE_SELECTION.csv")
    classes = {r["case_id"]: r["SPP_coverage_class"] for r in cases}
    assert sum(v == "STRICT_PRIMARY" for v in classes.values()) == 5
    assert classes["cssnbr3"] == classes["cssni3"] == "SUPPLEMENTED_PAIR_COVERAGE"
    assert classes["srtio3"] == "EXCLUDED_INSUFFICIENT_COVERAGE"


def test_actual_solver_is_optimal_and_matches_independent_objective():
    solver = read("03_scaffold_spp/SOLVER_CONFIRMATION.csv")
    assert len(solver) == 14
    assert all(r["solver_status"] == "OPTIMAL" and r["objective_parity"] == "True" for r in solver)
    assert max(float(r["absolute_objective_difference"]) for r in solver) < 1e-6


def test_grid8_is_preserved_only_as_boundary_and_grid64_absent():
    assert len(read("03_scaffold_spp/boundary_grid8/GRID8_ALL_ASSIGNMENTS.csv")) == 7840
    assert "SUPPLEMENTARY_BOUNDARY_EXPERIMENT" in (OUT / "03_scaffold_spp" / "boundary_grid8" / "README.md").read_text(encoding="utf-8")
    assert not (OUT / "03_scaffold_spp" / "boundary_grid64").exists()
