from __future__ import annotations

from sok_llm_orchestrator.baselines.template_baseline import run_template_baseline


def test_template_baseline_placeholder() -> None:
    out = run_template_baseline("case-1", "TiO2")
    assert out["status"] == "placeholder"
