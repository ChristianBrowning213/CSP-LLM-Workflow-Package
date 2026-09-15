from __future__ import annotations

from sok_llm_orchestrator.optimization.action_compile import compile_action
from sok_llm_orchestrator.optimization.action_registry import get_action


def test_action_compile_is_deterministic() -> None:
    action = get_action("guided_hybrid_balanced")
    left = compile_action(action).to_dict()
    right = compile_action(action).to_dict()
    assert left == right
    assert left["execution_mode"] == "paired"

