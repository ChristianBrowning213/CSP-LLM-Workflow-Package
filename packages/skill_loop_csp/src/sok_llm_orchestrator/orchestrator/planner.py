from __future__ import annotations

from sok_llm_orchestrator.orchestrator.clarification_policy import apply_noncritical_defaults
from sok_llm_orchestrator.orchestrator.plan_schema import RunPlan, validate_run_plan
from sok_llm_orchestrator.orchestrator.task_spec import TaskSpec


def build_run_plan(spec: TaskSpec, deterministic: bool = True) -> RunPlan:
    spec = apply_noncritical_defaults(spec)
    retrieval_mode = "hybrid"
    if spec.retrieval_strictness == "composition_tight":
        retrieval_mode = "metadata"
    elif spec.retrieval_strictness == "prototype_tight":
        retrieval_mode = "fingerprint"

    corpus_strategy = "top_k"
    if spec.property_bias:
        corpus_strategy = "property_biased"
    elif spec.retrieval_strictness == "composition_tight":
        corpus_strategy = "composition_tight"

    use_spp = spec.solve_mode in {"optimize", "rediscovery", "feasibility"}
    if not deterministic and spec.property_bias:
        retrieval_mode = "hybrid"

    guidance_mode = "guidance_only" if use_spp else "none"
    plan = RunPlan(
        retrieval_mode=retrieval_mode,
        use_spp=use_spp,
        corpus_strategy=corpus_strategy,
        guidance_mode=guidance_mode,
        verification_preset="benchmark" if spec.solve_mode != "feasibility" else "baseline_sanity",
        rerun_permissions=[
            "reduce_guidance",
            "broaden_corpus",
            "relax_symmetry",
            "change_cell_candidates",
            "recalibrate_spp",
        ],
    )
    validate_run_plan(plan.to_dict())
    return plan
