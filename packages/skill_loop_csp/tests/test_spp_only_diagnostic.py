from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from sok_llm_orchestrator.workflow.spp_only_diagnostic import (
    PeriodicKernel,
    assignment_is_native,
    assignment_to_structure,
    deterministic_assignments,
    feasibility_ladder_rows,
    load_effective_spp,
    optimize_assignment,
    score_assignment,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "artifacts" / "Paper_results_scaffold_ablation_2026-08-18_151807"


def _trace(row_id: str) -> dict:
    paths = list((FROZEN / "runs" / "NONE" / row_id).rglob("workflow_trace.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def test_no_scaffold_final_spp_is_nonzero_and_varies() -> None:
    with TemporaryDirectory() as temporary:
        output = Path(temporary) / "audit.json"
        trace = _trace("NASICON-ZR-NONE")
        assert trace["required_pairs"]
        assert trace["unsupported_pair_count"] == 0
        request, regulator, _combined = load_effective_spp(trace)
        assignments = deterministic_assignments("Na3Zr2Si2PO12", 3)
        values = [score_assignment("Na3Zr2Si2PO12", item, request, regulator)["total_effective_objective"] for item in assignments]
        output.write_text(json.dumps(values), encoding="utf-8")
        assert output.is_file()
        assert any(abs(value) > 1e-8 for value in values)
        assert len({round(value, 8) for value in values}) > 1


def test_feasibility_ladder_activates_only_real_none_categories(monkeypatch) -> None:
    with TemporaryDirectory() as temporary:
        monkeypatch.setattr(
            "sok_llm_orchestrator.workflow.spp_only_diagnostic.same_species_capacity",
            lambda species: {
                "species": species, "atomic_radius_A": 1.66, "same_species_exclusion_A": 3.32,
                "maximum_minimum_image_distance_A": 3.3775, "conflict_edge_count": 1,
                "maximum_compatible_sites": 2, "solver_status": 2, "solver": "Gurobi",
                "rule": "AtomicRadii",
            },
        )
        rows, certificate = feasibility_ladder_rows("Na3Zr2Si2PO12", "FROZEN_QLIP_INFEASIBLE")
        path = Path(temporary) / "ladder.json"; path.write_text(json.dumps(rows), encoding="utf-8")
        assert [row["level"] for row in rows] == ["LEVEL_0", "LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_FULL"]
        assert rows[1]["feasible"] == "YES" and rows[2]["feasible"] == "NO"
        assert "proximity.atomic_radii" not in rows[1]["constraint_categories_active"]
        assert "proximity.atomic_radii" in rows[2]["constraint_categories_active"]
        assert "no_native_symmetry_constraints_present" in rows[3]["constraint_categories_active"]
        assert certificate["contradiction"] is True


def test_feasibility_only_ladder_has_no_spp_dependency(monkeypatch) -> None:
    with TemporaryDirectory() as temporary:
        monkeypatch.setattr(
            "sok_llm_orchestrator.workflow.spp_only_diagnostic.same_species_capacity",
            lambda species: {"species": species, "maximum_compatible_sites": 1, "solver_status": 2},
        )
        rows, _ = feasibility_ladder_rows("LiZr2(PO4)3", "INFEASIBLE")
        Path(temporary, "result.txt").write_text(rows[0]["solver_feasibility_status"], encoding="utf-8")
        assert all("SPP" not in row["constraint_categories_active"] for row in rows)


def test_relaxed_native_search_loads_no_scaffold_or_reference_occupation() -> None:
    with TemporaryDirectory() as temporary:
        formula = "LiZr2(PO4)3"
        assignments = deterministic_assignments(formula, 1)
        assert assignment_is_native(formula, assignments[0])
        species = ["Li", "Zr", "P", "O"]
        values = {}
        for left in species:
            for right in species:
                key = tuple(sorted((left, right)))
                values.setdefault(key, np.zeros((8, 8, 8), dtype=float))
        kernel = PeriodicKernel(values)
        assignment, _score, diagnostics = optimize_assignment(formula, kernel, restarts=1, steps=2)
        cif = Path(temporary) / "candidate.cif"
        assignment_to_structure(formula, assignment).to(filename=cif)
        assert cif.is_file()
        assert diagnostics["scaffold_loaded"] is False
        assert diagnostics["reference_or_target_occupation_used"] is False
        assert diagnostics["optimality_claimed"] is False


def test_execution_uses_established_real_validation_backends() -> None:
    with TemporaryDirectory() as temporary:
        source = (ROOT / "scripts" / "run_spp_only_diagnostic.py").read_text(encoding="utf-8")
        evidence = Path(temporary) / "validation_backends.txt"
        evidence.write_text(source, encoding="utf-8")
        assert "ProductionWorkflowStages" in source
        assert "stages.evaluate(cif_path, target)" in source
        assert "run_chgnet_table.py" in source
        assert "SpacegroupAnalyzer" in source
        assert "render_vesta" in source
