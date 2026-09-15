"""Benchmark adapter for local novelty outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sca.evaluators.cif_parse import parse_cif
from sca.evaluators.novelty import evaluate_novelty
from sca.schemas import BenchmarkEvaluatorResult


class NoveltyBenchmarkEvaluator:
    name = "novelty"
    description = "Local novelty check when an in-process reference corpus is supplied."

    def __init__(self, reference_structures: dict[str, Any] | None = None) -> None:
        self.reference_structures = reference_structures

    def evaluate_path(self, cif_path: str | Path) -> BenchmarkEvaluatorResult:
        structure, parsed = parse_cif(cif_path)
        if structure is None:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="parse failed",
                error_type=parsed.error_type,
                error_message=parsed.error_message,
            )
        result = evaluate_novelty(structure, self.reference_structures)
        if not result.novelty_checked:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                skipped=True,
                summary="no reference corpus",
                metrics={
                    "novelty_checked": False,
                    "known_match": None,
                    "novel_by_structure_matcher": None,
                    "nearest_reference_id": None,
                    "novelty_error": None,
                },
                details={"reason": "No reference structures were supplied to the novelty evaluator."},
            )
        ok = result.novelty_error is None
        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=ok,
            summary="novel" if result.novel_by_structure_matcher else "known match" if result.known_match else "checked",
            metrics={
                "novelty_checked": result.novelty_checked,
                "known_match": result.known_match,
                "novel_by_structure_matcher": result.novel_by_structure_matcher,
                "nearest_reference_id": result.nearest_reference_id,
                "novelty_error": result.novelty_error,
            },
            flags={
                "novelty_checked": result.novelty_checked,
                "known_match": result.known_match,
                "novel_by_structure_matcher": result.novel_by_structure_matcher,
            },
            error_type="NoveltyError" if result.novelty_error else None,
            error_message=result.novelty_error,
        )
