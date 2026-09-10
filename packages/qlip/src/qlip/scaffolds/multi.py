"""Independent multi-scaffold attempt coordination with scale-safe selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable

from .occupation import preflight_ordered_occupation
from .registry import get_scaffold
from .schema import ScaffoldRecord


SELECTION_POLICIES = {
    "FIRST_VALID",
    "SHARED_OBJECTIVE_MINIMUM",
    "POST_VALIDATION_RANK",
    "RETURN_ALL_VALID",
}


@dataclass(frozen=True)
class MultiScaffoldResult:
    scaffold_attempt_count: int
    representable_scaffold_count: int
    feasible_scaffold_count: int
    selected_scaffold_id: str | None
    selected_scaffold_ids: tuple[str, ...]
    selection_policy: str
    rejected_scaffolds: tuple[str, ...]
    rejected_reasons: dict[str, str]
    attempts: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_scaffold_hypotheses(
    formula: str,
    scaffold_ids: Iterable[str],
    *,
    selection_policy: str,
    solve_attempt: Callable[[ScaffoldRecord, Any], dict[str, Any]] | None = None,
    common_objective_scale: str | None = None,
    scaffold_loader: Callable[[str], ScaffoldRecord] = get_scaffold,
) -> MultiScaffoldResult:
    policy = str(selection_policy).upper()
    if policy not in SELECTION_POLICIES:
        raise ValueError(f"unknown multi-scaffold selection policy: {selection_policy}")
    ids = [str(value) for value in scaffold_ids]
    if not ids:
        raise ValueError("at least one scaffold ID is required")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scaffold IDs are not independent hypotheses")
    if policy == "SHARED_OBJECTIVE_MINIMUM" and not common_objective_scale:
        raise ValueError("SHARED_OBJECTIVE_MINIMUM requires a documented common_objective_scale")

    attempts: list[dict[str, Any]] = []
    rejected: dict[str, str] = {}
    feasible: list[dict[str, Any]] = []
    representable_count = 0
    for scaffold_id in ids:
        try:
            scaffold = scaffold_loader(scaffold_id)
            occupation = preflight_ordered_occupation(
                formula,
                len(scaffold.fractional_candidate_sites),
                scaffold.symmetry_orbits,
            )
            attempt: dict[str, Any] = {
                "scaffold_id": scaffold_id,
                "scaffold_version": scaffold.scaffold_version,
                "source_structure_id": scaffold.source_structure_id,
                "source_cif_sha256": scaffold.source_cif_sha256,
                "topology_policy": scaffold.topology_policy,
                "representability": occupation.to_dict(),
                "solve_status": "NOT_RUN" if solve_attempt is None else None,
                "certificate": None,
                "artifacts": None,
            }
            if not occupation.stoichiometry_representable:
                reason = occupation.rejection_reason or "stoichiometry not representable"
                rejected[scaffold_id] = reason
                attempt["rejection_reason"] = reason
                attempts.append(attempt)
                continue
            representable_count += 1
            if solve_attempt is None:
                attempts.append(attempt)
                continue
            solve_result = dict(solve_attempt(scaffold, occupation))
            attempt.update(solve_result)
            status = str(solve_result.get("solve_status", "ERROR"))
            if status not in {"OPTIMAL", "FEASIBLE"} or not solve_result.get("validation_passed", False):
                reason = str(solve_result.get("rejection_reason") or f"solve/validation status: {status}")
                rejected[scaffold_id] = reason
                attempt["rejection_reason"] = reason
            else:
                if policy == "SHARED_OBJECTIVE_MINIMUM" and solve_result.get("objective_scale_id") != common_objective_scale:
                    reason = "attempt objective does not use the declared common scale"
                    rejected[scaffold_id] = reason
                    attempt["rejection_reason"] = reason
                else:
                    feasible.append(attempt)
            attempts.append(attempt)
        except Exception as exc:  # noqa: BLE001
            rejected[scaffold_id] = f"{type(exc).__name__}: {exc}"
            attempts.append({"scaffold_id": scaffold_id, "solve_status": "ERROR", "rejection_reason": rejected[scaffold_id]})

    selected: list[dict[str, Any]] = []
    if feasible:
        if policy == "FIRST_VALID":
            selected = [feasible[0]]
        elif policy == "SHARED_OBJECTIVE_MINIMUM":
            selected = [min(feasible, key=lambda row: (float(row["objective"]), str(row["scaffold_id"])))]
        elif policy == "POST_VALIDATION_RANK":
            selected = [min(feasible, key=lambda row: (float(row.get("validation_rank", float("inf"))), str(row["scaffold_id"])))]
        else:
            selected = list(feasible)
    selected_ids = tuple(str(row["scaffold_id"]) for row in selected)
    return MultiScaffoldResult(
        scaffold_attempt_count=len(ids),
        representable_scaffold_count=representable_count,
        feasible_scaffold_count=len(feasible),
        selected_scaffold_id=selected_ids[0] if selected_ids else None,
        selected_scaffold_ids=selected_ids,
        selection_policy=policy,
        rejected_scaffolds=tuple(value for value in ids if value in rejected),
        rejected_reasons=rejected,
        attempts=tuple(attempts),
    )
