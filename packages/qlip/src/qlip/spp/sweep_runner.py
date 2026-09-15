from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms

from qlip.spp.guidance import SPPGuidance


@dataclass(frozen=True)
class SweepCandidate:
    candidate_id: str
    structure: Atoms
    baseline_cost: float
    source_path: Path


@dataclass(frozen=True)
class SweepTask:
    chemistry_key: str
    candidates: list[SweepCandidate]
    baseline_pref: str | None = None


@dataclass(frozen=True)
class SolveResult:
    status: str
    chosen_candidate_id: str
    chosen_structure: Atoms
    objective_total: float
    decomposition: dict[str, float]
    objective_rows: list[dict[str, Any]]
    spp_score: float


def _pref_rank(candidate_id: str, preferred: str | None) -> int:
    if preferred is None:
        return 1
    return 0 if candidate_id == preferred else 1


def run_once(
    task: SweepTask,
    spp_enabled: bool,
    spp_package_path,
    seed: int = 7,
    max_seconds: int = 60,
) -> SolveResult:
    if not task.candidates:
        raise ValueError(f"Task {task.chemistry_key} has no candidates")

    np.random.seed(int(seed))
    guidance = SPPGuidance.from_package(spp_package_path)
    rows: list[dict[str, Any]] = []
    structures_by_id: dict[str, Atoms] = {}

    for candidate in sorted(task.candidates, key=lambda item: item.candidate_id):
        baseline_term = float(candidate.baseline_cost)
        spp_score = float(guidance.spp_score(candidate.structure))
        decomposition: dict[str, float] = {"baseline": baseline_term}
        spp_term = 0.0
        objective_total = baseline_term
        if spp_enabled:
            spp_term = float(guidance.objective_contribution(candidate.structure))
            decomposition[guidance.objective_term_name] = spp_term
            objective_total += spp_term

        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "baseline_cost": baseline_term,
                "spp_score": spp_score,
                "spp_term": float(spp_term),
                "objective_total": float(objective_total),
                "decomposition": decomposition,
                "source_path": str(candidate.source_path),
                "max_seconds": int(max_seconds),
            }
        )
        structures_by_id[candidate.candidate_id] = candidate.structure

    rows.sort(
        key=lambda row: (
            float(row["objective_total"]),
            _pref_rank(str(row["candidate_id"]), task.baseline_pref),
            str(row["candidate_id"]),
        )
    )
    selected = rows[0]
    return SolveResult(
        status="optimal",
        chosen_candidate_id=str(selected["candidate_id"]),
        chosen_structure=structures_by_id[str(selected["candidate_id"])],
        objective_total=float(selected["objective_total"]),
        decomposition={key: float(value) for key, value in selected["decomposition"].items()},
        objective_rows=rows,
        spp_score=float(selected["spp_score"]),
    )
