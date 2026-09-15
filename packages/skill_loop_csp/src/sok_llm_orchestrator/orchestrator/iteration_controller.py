from __future__ import annotations

from dataclasses import dataclass

from sok_llm_orchestrator.orchestrator.plan_schema import RunPlan
from sok_llm_orchestrator.orchestrator.task_spec import TaskSpec
from sok_llm_orchestrator.verification.diagnostic_schema import DiagnosticReport

ALLOWED_DELTAS = {
    "reduce_guidance",
    "remove_guidance",
    "broaden_corpus",
    "relax_symmetry",
    "change_cell_candidates",
    "recalibrate_spp",
}


@dataclass(slots=True)
class IterationDelta:
    delta_type: str
    rationale: str


@dataclass(slots=True)
class IterationState:
    max_iterations: int
    iteration_index: int = 0

    @property
    def can_iterate(self) -> bool:
        return self.iteration_index < self.max_iterations


def propose_delta(report: DiagnosticReport) -> IterationDelta:
    for delta in report.suggested_deltas:
        if delta in ALLOWED_DELTAS:
            return IterationDelta(delta_type=delta, rationale=report.probable_cause)
    return IterationDelta(delta_type="reduce_guidance", rationale="fallback")


def apply_delta(task_spec: TaskSpec, plan: RunPlan, delta: IterationDelta) -> tuple[TaskSpec, RunPlan]:
    if delta.delta_type == "remove_guidance":
        plan.guidance_mode = "none"
    elif delta.delta_type == "reduce_guidance":
        plan.guidance_mode = "guidance_only"
    elif delta.delta_type == "broaden_corpus":
        task_spec.retrieval_strictness = "broad"
        plan.corpus_strategy = "top_k"
    elif delta.delta_type == "relax_symmetry":
        task_spec.symmetry_request.hardness = "soft"
    elif delta.delta_type == "recalibrate_spp":
        task_spec.defaults_used.append("delta:recalibrate_spp")
    elif delta.delta_type == "change_cell_candidates":
        task_spec.defaults_used.append("delta:change_cell_candidates")
    return task_spec, plan
