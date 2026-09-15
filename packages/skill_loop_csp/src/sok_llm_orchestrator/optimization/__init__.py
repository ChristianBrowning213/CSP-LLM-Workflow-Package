from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sok_llm_orchestrator.optimization.loop import OptimizationEngine, OptimizationRunResult
    from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in {"OptimizationEngine", "OptimizationRunResult"}:
        from sok_llm_orchestrator.optimization.loop import OptimizationEngine, OptimizationRunResult

        return {"OptimizationEngine": OptimizationEngine, "OptimizationRunResult": OptimizationRunResult}[name]
    if name == "OptimizationSession":
        from sok_llm_orchestrator.optimization.session_schema import OptimizationSession

        return OptimizationSession
    raise AttributeError(name)

__all__ = [
    "OptimizationEngine",
    "OptimizationRunResult",
    "OptimizationSession",
]
