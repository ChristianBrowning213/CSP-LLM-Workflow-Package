from __future__ import annotations

from sok_llm_orchestrator.orchestrator.iteration_controller import apply_delta, propose_delta
from sok_llm_orchestrator.orchestrator.plan_schema import RunPlan
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query
from sok_llm_orchestrator.verification.diagnostic_schema import DiagnosticReport


def test_iteration_controller_applies_delta() -> None:
    spec = task_spec_from_query("TiO2")
    plan = RunPlan(
        retrieval_mode="metadata",
        use_spp=True,
        corpus_strategy="composition_tight",
        guidance_mode="guidance_only",
        verification_preset="benchmark",
    )
    diag = DiagnosticReport(
        failure_type="infeasible",
        probable_cause="guidance_too_strong",
        evidence=["spp_term dominates"],
        suggested_deltas=["broaden_corpus"],
    )
    delta = propose_delta(diag)
    spec2, plan2 = apply_delta(spec, plan, delta)
    assert spec2.retrieval_strictness == "broad"
    assert plan2.corpus_strategy == "top_k"
