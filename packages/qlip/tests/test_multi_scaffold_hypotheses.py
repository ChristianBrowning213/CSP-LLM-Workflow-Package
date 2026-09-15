from __future__ import annotations

from dataclasses import replace

import pytest

from qlip.scaffolds import get_scaffold
from qlip.scaffolds.multi import run_scaffold_hypotheses


BASE = get_scaffold("nzp_nazr2po43_r3c")


def _record(scaffold_id, allowed=("Na", "Zr", "P", "O")):
    allow = set(allowed)
    orbits = tuple({**orbit, "allowed_species": tuple(value for value in orbit["allowed_species"] if value in allow)} for orbit in BASE.symmetry_orbits)
    return replace(BASE, scaffold_id=scaffold_id, symmetry_orbits=orbits)


def _loader(scaffold_id):
    if scaffold_id == "bad":
        return _record("bad", allowed=("Na", "P", "O"))
    return _record(scaffold_id)


def _solve(scaffold, occupation):
    values = {"a": 2.0, "b": 1.0, "c": 3.0}
    return {
        "solve_status": "OPTIMAL", "validation_passed": True,
        "objective": values[scaffold.scaffold_id], "objective_scale_id": "shared-v1",
        "validation_rank": {"a": 3, "b": 2, "c": 1}[scaffold.scaffold_id],
        "certificate": {"scaffold_id": scaffold.scaffold_id},
        "artifacts": {"cif": f"{scaffold.scaffold_id}.cif"},
    }


def test_first_valid_rejects_unrepresentable_scaffold() -> None:
    result = run_scaffold_hypotheses(
        "NaZr2P3O12", ["bad", "a", "b"], selection_policy="FIRST_VALID",
        solve_attempt=_solve, scaffold_loader=_loader,
    )
    assert result.scaffold_attempt_count == 3
    assert result.representable_scaffold_count == 2
    assert result.feasible_scaffold_count == 2
    assert result.selected_scaffold_id == "a"
    assert result.rejected_scaffolds == ("bad",)


def test_shared_objective_minimum_requires_documented_common_scale() -> None:
    with pytest.raises(ValueError, match="common_objective_scale"):
        run_scaffold_hypotheses("NaZr2P3O12", ["a", "b"], selection_policy="SHARED_OBJECTIVE_MINIMUM", scaffold_loader=_loader)


def test_shared_objective_minimum_uses_only_declared_scale() -> None:
    result = run_scaffold_hypotheses(
        "NaZr2P3O12", ["a", "b", "c"], selection_policy="SHARED_OBJECTIVE_MINIMUM",
        common_objective_scale="shared-v1", solve_attempt=_solve, scaffold_loader=_loader,
    )
    assert result.selected_scaffold_id == "b"


def test_post_validation_rank_is_explicit() -> None:
    result = run_scaffold_hypotheses(
        "NaZr2P3O12", ["a", "b", "c"], selection_policy="POST_VALIDATION_RANK",
        solve_attempt=_solve, scaffold_loader=_loader,
    )
    assert result.selected_scaffold_id == "c"
    assert result.selection_policy == "POST_VALIDATION_RANK"


def test_return_all_valid_preserves_separate_attempt_artifacts() -> None:
    result = run_scaffold_hypotheses(
        "NaZr2P3O12", ["a", "b"], selection_policy="RETURN_ALL_VALID",
        solve_attempt=_solve, scaffold_loader=_loader,
    )
    assert result.selected_scaffold_ids == ("a", "b")
    assert [attempt["artifacts"]["cif"] for attempt in result.attempts] == ["a.cif", "b.cif"]
