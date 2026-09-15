"""StructureMatcher target matching for benchmark manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pymatgen.analysis.structure_matcher import StructureMatcher

from sca.evaluators.cif_parse import parse_cif
from sca.schemas import BenchmarkEvaluatorResult


class StructureMatchBenchmarkEvaluator:
    name = "structure_match"
    description = "Match generated structures against a target CIF with StructureMatcher."

    def __init__(
        self,
        ltol: float = 0.2,
        stol: float = 0.3,
        angle_tol: float = 5,
    ) -> None:
        self.ltol = ltol
        self.stol = stol
        self.angle_tol = angle_tol

    def evaluate_item(self, item: dict[str, Any]) -> BenchmarkEvaluatorResult:
        candidate_path = Path(item["path"])
        target_path = item.get("target_cif_path")
        reference_id = item.get("reference_id")
        mode = str(item.get("structure_match_mode") or "both").lower()

        if not target_path:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                skipped=True,
                summary="no target CIF",
                details={"reason": "target_cif_path was not provided"},
            )
        if mode not in {"exact", "anonymous", "both"}:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="invalid mode",
                error_type="ValueError",
                error_message=f"Unsupported structure match mode '{mode}'",
            )

        candidate, candidate_parse = parse_cif(candidate_path)
        if candidate is None:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="candidate parse failed",
                error_type=candidate_parse.error_type,
                error_message=candidate_parse.error_message,
            )

        target, target_parse = parse_cif(target_path)
        if target is None:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="target parse failed",
                error_type=target_parse.error_type,
                error_message=target_parse.error_message,
                details={"target_cif_path": str(target_path)},
            )

        try:
            matcher = self._matcher(attempt_supercell=True)
            no_supercell_matcher = self._matcher(attempt_supercell=False)
            exact_match = matcher.fit(candidate, target) if mode in {"exact", "both"} else None
            anonymous_match = (
                matcher.fit_anonymous(candidate, target)
                if mode in {"anonymous", "both"}
                else None
            )
            no_supercell_exact = (
                no_supercell_matcher.fit(candidate, target)
                if mode in {"exact", "both"}
                else None
            )
            no_supercell_anonymous = (
                no_supercell_matcher.fit_anonymous(candidate, target)
                if mode in {"anonymous", "both"}
                else None
            )
            structure_match = exact_match if mode == "exact" else anonymous_match if mode == "anonymous" else bool(exact_match or anonymous_match)
            rms_dist, max_dist = _distances(matcher, candidate, target) if structure_match else (None, None)
            supercell_match = _supercell_used(
                exact_match=exact_match,
                anonymous_match=anonymous_match,
                no_supercell_exact=no_supercell_exact,
                no_supercell_anonymous=no_supercell_anonymous,
            )
        except Exception as exc:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
                details={"target_cif_path": str(target_path), "mode": mode},
            )

        matched_reference_id = str(reference_id or target_path) if structure_match else None
        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=bool(structure_match),
            summary="matched" if structure_match else "not matched",
            metrics={
                "structure_match": bool(structure_match),
                "rms_dist": rms_dist,
                "max_dist": max_dist,
                "anonymous_match": anonymous_match,
                "supercell_match": supercell_match,
                "matched_reference_id": matched_reference_id,
            },
            flags={
                "structure_match": bool(structure_match),
                "anonymous_match": anonymous_match,
                "supercell_match": supercell_match,
            },
            details={
                "target_cif_path": str(target_path),
                "reference_id": reference_id,
                "mode": mode,
                "target_formula": item.get("target_formula"),
            },
        )

    def _matcher(self, attempt_supercell: bool) -> StructureMatcher:
        return StructureMatcher(
            ltol=self.ltol,
            stol=self.stol,
            angle_tol=self.angle_tol,
            primitive_cell=True,
            scale=True,
            attempt_supercell=attempt_supercell,
        )


def _distances(
    matcher: StructureMatcher,
    candidate,
    target,
) -> tuple[float | None, float | None]:
    distances = matcher.get_rms_dist(candidate, target)
    if distances is None:
        return None, None
    rms_dist, max_dist = distances
    return float(rms_dist), float(max_dist)


def _supercell_used(
    exact_match: bool | None,
    anonymous_match: bool | None,
    no_supercell_exact: bool | None,
    no_supercell_anonymous: bool | None,
) -> bool | None:
    if exact_match is None and anonymous_match is None:
        return None
    matched_with_supercell = bool(exact_match or anonymous_match)
    matched_without_supercell = bool(no_supercell_exact or no_supercell_anonymous)
    return matched_with_supercell and not matched_without_supercell

