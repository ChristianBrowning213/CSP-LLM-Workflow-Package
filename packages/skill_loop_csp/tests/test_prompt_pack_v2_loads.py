from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.llm.prompts import load_prompt_pack_v2


def test_prompt_pack_v2_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    pack = load_prompt_pack_v2(root / "prompts")
    assert "system_orchestrator_v2.md" in pack
    assert "clarification_examples.md" in pack
    assert "planning_examples.md" in pack
