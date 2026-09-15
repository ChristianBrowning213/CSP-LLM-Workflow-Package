from __future__ import annotations

from dataclasses import dataclass

from sok_llm_orchestrator.orchestrator.clarification_policy import apply_noncritical_defaults, classify_missing_fields
from sok_llm_orchestrator.orchestrator.task_spec import TaskSpec, task_spec_from_query


@dataclass(slots=True)
class OptimizationPreflight:
    ready: bool
    unresolved_critical_fields: list[str]
    questions: list[str]
    defaults_used: list[str]
    task_spec: TaskSpec

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "unresolved_critical_fields": list(self.unresolved_critical_fields),
            "questions": list(self.questions),
            "defaults_used": list(self.defaults_used),
            "task_spec": self.task_spec.to_dict(),
        }


def run_optimization_preflight(spec: TaskSpec) -> OptimizationPreflight:
    decision = classify_missing_fields(spec)
    spec = apply_noncritical_defaults(spec)
    unresolved = list(decision.hard_required)
    questions = list(decision.prompts)

    if spec.symmetry_request.space_group and spec.symmetry_request.hardness not in {"hard", "soft"}:
        unresolved.append("symmetry_request.hardness")
        questions.append("Should the requested symmetry be hard, soft, or optional?")

    return OptimizationPreflight(
        ready=not unresolved,
        unresolved_critical_fields=unresolved,
        questions=questions,
        defaults_used=list(spec.defaults_used),
        task_spec=spec,
    )


def preflight_from_query(query: str) -> OptimizationPreflight:
    return run_optimization_preflight(task_spec_from_query(query))

