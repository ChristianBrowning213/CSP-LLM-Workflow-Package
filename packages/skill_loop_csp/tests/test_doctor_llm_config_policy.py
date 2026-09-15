from __future__ import annotations

from sok_llm_orchestrator.llm.discovery import resolve_llm_credentials


def test_resolve_llm_credentials_fills_local_key() -> None:
    api_key, model, notes = resolve_llm_credentials(
        base_url="http://localhost:1234/v1",
        llm_api_key=None,
        llm_model="zai-org/glm-4.7-flash",
    )
    assert api_key == "local-key"
    assert model == "zai-org/glm-4.7-flash"
    assert any(note.startswith("auto_filled_api_key:") for note in notes)


def test_resolve_llm_credentials_non_local_keeps_missing_key() -> None:
    api_key, model, _ = resolve_llm_credentials(
        base_url="https://example.com/v1",
        llm_api_key=None,
        llm_model="m",
    )
    assert api_key is None
    assert model == "m"
