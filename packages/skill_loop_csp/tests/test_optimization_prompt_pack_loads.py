from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.llm.prompts import load_optimization_prompt_pack


def test_optimization_prompt_pack_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    pack = load_optimization_prompt_pack(root / "prompts")
    assert "optimization_system.md" in pack
    assert "optimization_clarification_examples.md" in pack
    assert "optimization_midloop_examples.md" in pack

