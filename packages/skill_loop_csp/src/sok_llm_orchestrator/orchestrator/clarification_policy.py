from __future__ import annotations

from dataclasses import dataclass

from sok_llm_orchestrator.orchestrator.task_spec import TaskSpec

HARD_REQUIRED_FIELDS = ("composition_target", "solve_mode")
IMPORTANT_DEFAULTABLE_FIELDS = ("symmetry_request", "retrieval_strictness", "iteration_budget")
OPTIONAL_FIELDS = ("motif_prior", "property_bias")


@dataclass(slots=True)
class ClarificationDecision:
    hard_required: list[str]
    important_defaultable: list[str]
    optional: list[str]
    prompts: list[str]


def classify_missing_fields(spec: TaskSpec) -> ClarificationDecision:
    hard_required: list[str] = []
    important_defaultable: list[str] = []
    optional: list[str] = []
    prompts: list[str] = []

    if not spec.composition_target:
        hard_required.append("composition_target")
        prompts.append("Please provide a fixed composition target (for example: TiO2).")
    if not spec.solve_mode:
        hard_required.append("solve_mode")
        prompts.append("Should this run prioritize feasibility, optimization, or rediscovery?")

    if spec.symmetry_request.space_group is None:
        important_defaultable.append("symmetry_request.space_group")
        prompts.append("Do you have a preferred space group, or should I keep symmetry unconstrained?")
    if spec.iteration_budget < 0:
        important_defaultable.append("iteration_budget")
        prompts.append("Please provide a non-negative iteration budget.")

    if spec.motif_prior is None:
        optional.append("motif_prior")
    if spec.property_bias is None:
        optional.append("property_bias")

    return ClarificationDecision(
        hard_required=hard_required,
        important_defaultable=important_defaultable,
        optional=optional,
        prompts=prompts,
    )


def apply_noncritical_defaults(spec: TaskSpec) -> TaskSpec:
    if spec.symmetry_request.hardness not in {"hard", "soft", "none"}:
        spec.symmetry_request.hardness = "none"
        spec.defaults_used.append("symmetry_request.hardness:none")
    if spec.iteration_budget == 0 and spec.solve_mode == "optimize":
        spec.iteration_budget = 1
        spec.defaults_used.append("iteration_budget:1")
    return spec
