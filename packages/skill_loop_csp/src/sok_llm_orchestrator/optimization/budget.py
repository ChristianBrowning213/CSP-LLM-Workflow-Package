from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sok_llm_orchestrator.config import Settings


@dataclass(slots=True)
class OptimizationBudgetConfig:
    max_iterations: int
    max_solver_calls: int
    max_retrieval_calls: int
    max_failed_iterations: int
    max_recovery_attempts: int
    stagnation_window: int
    exploration_rate: float
    allow_midloop_clarification: bool
    selection_metric_view: str = "objective_total"
    max_wall_clock_s: int | None = None
    action_family_limits: dict[str, int] = field(default_factory=dict)
    action_allowlist: list[str] = field(default_factory=list)

    @classmethod
    def from_settings(cls, settings: Settings) -> "OptimizationBudgetConfig":
        max_failed_iterations = int(settings.optimization_max_failed_iterations)
        stagnation_window = int(settings.optimization_stagnation_window)
        return cls(
            max_iterations=int(settings.optimization_max_iterations),
            max_solver_calls=int(settings.optimization_max_solver_calls),
            max_retrieval_calls=int(settings.optimization_max_retrieval_calls),
            max_failed_iterations=max_failed_iterations,
            max_recovery_attempts=max(2, max_failed_iterations + stagnation_window),
            stagnation_window=stagnation_window,
            exploration_rate=float(settings.optimization_exploration_rate),
            allow_midloop_clarification=bool(settings.optimization_allow_midloop_clarification),
            selection_metric_view=str(settings.optimization_selection_metric_view or "objective_total").strip().lower(),
            max_wall_clock_s=settings.optimization_max_wall_clock_s,
            action_family_limits=dict(settings.optimization_action_family_limits),
            action_allowlist=list(settings.optimization_action_allowlist),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_iterations": self.max_iterations,
            "max_solver_calls": self.max_solver_calls,
            "max_retrieval_calls": self.max_retrieval_calls,
            "max_failed_iterations": self.max_failed_iterations,
            "max_recovery_attempts": self.max_recovery_attempts,
            "stagnation_window": self.stagnation_window,
            "exploration_rate": self.exploration_rate,
            "allow_midloop_clarification": self.allow_midloop_clarification,
            "selection_metric_view": self.selection_metric_view,
            "max_wall_clock_s": self.max_wall_clock_s,
            "action_family_limits": dict(self.action_family_limits),
            "action_allowlist": list(self.action_allowlist),
        }


@dataclass(slots=True)
class BudgetTracker:
    config: OptimizationBudgetConfig
    iterations_used: int = 0
    solver_calls_used: int = 0
    retrieval_calls_used: int = 0
    failed_iterations_used: int = 0
    recovery_attempts_used: int = 0
    action_family_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "iterations_used": self.iterations_used,
            "solver_calls_used": self.solver_calls_used,
            "retrieval_calls_used": self.retrieval_calls_used,
            "failed_iterations_used": self.failed_iterations_used,
            "recovery_attempts_used": self.recovery_attempts_used,
            "action_family_counts": dict(self.action_family_counts),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BudgetTracker":
        cfg = payload.get("config", {})
        tracker = cls(
            config=OptimizationBudgetConfig(
                max_iterations=int(cfg["max_iterations"]),
                max_solver_calls=int(cfg["max_solver_calls"]),
                max_retrieval_calls=int(cfg["max_retrieval_calls"]),
                max_failed_iterations=int(cfg["max_failed_iterations"]),
                max_recovery_attempts=int(
                    cfg.get(
                        "max_recovery_attempts",
                        max(2, int(cfg["max_failed_iterations"]) + int(cfg["stagnation_window"])),
                    )
                ),
                stagnation_window=int(cfg["stagnation_window"]),
                exploration_rate=float(cfg["exploration_rate"]),
                allow_midloop_clarification=bool(cfg["allow_midloop_clarification"]),
                selection_metric_view=str(cfg.get("selection_metric_view", "objective_total")).strip().lower(),
                max_wall_clock_s=(int(cfg["max_wall_clock_s"]) if cfg.get("max_wall_clock_s") is not None else None),
                action_family_limits={str(k): int(v) for k, v in (cfg.get("action_family_limits", {}) or {}).items()},
                action_allowlist=[
                    str(item).strip()
                    for item in (cfg.get("action_allowlist", []) or [])
                    if str(item).strip()
                ],
            ),
            iterations_used=int(payload.get("iterations_used", 0)),
            solver_calls_used=int(payload.get("solver_calls_used", 0)),
            retrieval_calls_used=int(payload.get("retrieval_calls_used", 0)),
            failed_iterations_used=int(payload.get("failed_iterations_used", 0)),
            recovery_attempts_used=int(payload.get("recovery_attempts_used", 0)),
            action_family_counts={str(k): int(v) for k, v in (payload.get("action_family_counts", {}) or {}).items()},
        )
        return tracker

    def remaining_iterations(self) -> int:
        return max(0, int(self.config.max_iterations) - int(self.iterations_used))

    def remaining_solver_calls(self) -> int:
        return max(0, int(self.config.max_solver_calls) - int(self.solver_calls_used))

    def remaining_retrieval_calls(self) -> int:
        return max(0, int(self.config.max_retrieval_calls) - int(self.retrieval_calls_used))

    def remaining_recovery_attempts(self) -> int:
        return max(0, int(self.config.max_recovery_attempts) - int(self.recovery_attempts_used))

    def recovery_exhausted(self) -> bool:
        return int(self.recovery_attempts_used) >= int(self.config.max_recovery_attempts)

    def can_take_iteration(self, *, include_failed_limit: bool = True) -> str | None:
        if self.iterations_used >= self.config.max_iterations:
            return "budget_exhausted:max_iterations"
        if self.solver_calls_used >= self.config.max_solver_calls:
            return "budget_exhausted:max_solver_calls"
        if self.retrieval_calls_used >= self.config.max_retrieval_calls:
            return "budget_exhausted:max_retrieval_calls"
        if include_failed_limit and self.failed_iterations_used >= self.config.max_failed_iterations:
            return "budget_exhausted:max_failed_iterations"
        return None

    def is_action_family_allowed(self, family: str) -> bool:
        limit = self.config.action_family_limits.get(family)
        if limit is None:
            return True
        return self.action_family_counts.get(family, 0) < limit

    def is_action_allowed(self, action_id: str) -> bool:
        allowlist = [str(item).strip() for item in self.config.action_allowlist if str(item).strip()]
        if not allowlist:
            return True
        return str(action_id) in set(allowlist)

    def consume(
        self,
        *,
        action_family: str,
        solver_calls: int,
        retrieval_calls: int,
        failed: bool,
        recovery_attempt: bool,
    ) -> None:
        self.iterations_used += 1
        self.solver_calls_used += int(solver_calls)
        self.retrieval_calls_used += int(retrieval_calls)
        if failed:
            self.failed_iterations_used += 1
        if recovery_attempt:
            self.recovery_attempts_used += 1
        self.action_family_counts[action_family] = self.action_family_counts.get(action_family, 0) + 1
