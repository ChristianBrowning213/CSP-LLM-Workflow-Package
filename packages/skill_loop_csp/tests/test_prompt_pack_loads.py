from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.llm.prompts import load_prompt_pack


def test_prompt_pack_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    pack = load_prompt_pack(root / "prompts")
    assert "system_orchestrator.md" in pack
    assert "tool_use_policy.md" in pack
    assert "skills_index.md" in pack
