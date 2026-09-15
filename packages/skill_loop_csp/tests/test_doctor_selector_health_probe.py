from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.cli import _resolve_runtime_llm, _run_action_selector_health_probe
from sok_llm_orchestrator.config import Settings


class _SelectorHealthyClient:
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        _ = messages, tools, max_tokens, temperature
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"action_id":"guided_hybrid_balanced",'
                            '"ranked_action_ids":["guided_hybrid_balanced","baseline_control"],'
                            '"rationale":"valid selector probe"}'
                        )
                    }
                }
            ]
        }


class _SelectorMalformedClient:
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        _ = messages, tools, max_tokens, temperature
        return {"choices": [{"message": {"content": "```bad```"}}]}


def test_action_selector_health_probe_reports_structured_output_failure() -> None:
    check = _run_action_selector_health_probe(_SelectorMalformedClient())  # type: ignore[arg-type]
    assert check["name"] == "action_selector_health"
    assert check["ok"] is False
    assert check["source"] == "fallback_after_invalid_output"
    assert check["error"] == "contains_code_fence"
    telemetry = check.get("telemetry", {})
    assert isinstance(telemetry, dict)
    assert int(telemetry.get("fallback_count", 0)) == 1
    assert int(telemetry.get("parse_failures", 0)) >= 1


def test_resolve_runtime_llm_includes_selector_health_check(monkeypatch) -> None:
    monkeypatch.setattr(
        "sok_llm_orchestrator.cli.resolve_llm_credentials",
        lambda base_url, llm_api_key, llm_model: ("local-key", "probe-model", ["auto_discovered_model:probe-model"]),
    )
    monkeypatch.setattr("sok_llm_orchestrator.cli.smoke_chat_api_v1", lambda base_url, model: (True, "ok"))
    monkeypatch.setattr("sok_llm_orchestrator.cli.LLMClient", lambda **kwargs: _SelectorHealthyClient())

    settings = Settings.from_sources(None)
    ok, checks = _resolve_runtime_llm(settings)
    assert ok is True
    assert [check.get("name") for check in checks] == ["llm_config", "action_selector_health"]
    selector_check = checks[1]
    assert selector_check["ok"] is True
    assert selector_check["source"] == "llm"
