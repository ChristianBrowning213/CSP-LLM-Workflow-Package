"""Benchmark adapter for optional ALIGNN predictions."""

from __future__ import annotations

from pathlib import Path

from sca.evaluators.alignn import DEFAULT_ALIGNN_MODEL, AlignnEvaluator
from sca.evaluators.cif_parse import parse_cif
from sca.schemas import BenchmarkEvaluatorResult


class AlignnBenchmarkEvaluator:
    name = "alignn"
    description = "ALIGNN formation-energy prediction."

    def __init__(self, model_name: str = DEFAULT_ALIGNN_MODEL) -> None:
        self.model_name = model_name
        self._evaluator = AlignnEvaluator(model_name=model_name)

    def evaluate_path(self, cif_path: str | Path) -> BenchmarkEvaluatorResult:
        structure, parse = parse_cif(cif_path)
        if structure is None:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                model=self.model_name,
                summary="parse failed",
                error_type=parse.error_type,
                error_message=parse.error_message,
            )

        result = self._evaluator.evaluate(structure, str(cif_path))
        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=result.ok,
            model=result.model,
            summary="ok" if result.ok else "failed",
            metrics=result.values,
            error_type=result.error_type,
            error_message=result.error_message,
        )

