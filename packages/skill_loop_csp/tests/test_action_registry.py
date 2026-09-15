from __future__ import annotations

from sok_llm_orchestrator.optimization.action_registry import get_action, legal_action_families, list_registered_actions


def test_registry_has_actions_and_families() -> None:
    actions = list_registered_actions()
    assert actions
    families = legal_action_families()
    assert "guided_exploit" in families
    assert get_action(actions[0].action_id).action_id == actions[0].action_id

