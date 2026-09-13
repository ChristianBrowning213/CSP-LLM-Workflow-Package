from __future__ import annotations

from typing import Any

import pytest

from llm_csp.agentic.model import AgentModelError, FakeAgentModel, ModelErrorCode, ModelMetadata


def test_fake_model_returns_sequence_and_records_sanitized_requests() -> None:
    model = FakeAgentModel([{"n": 1}, {"n": 2}])
    first = model.generate_structured(task="plan", input_payload={"goal": "x"}, output_schema=dict)
    second = model.generate_structured(task="correct", input_payload={"goal": "x"}, output_schema=dict)
    assert first.output == {"n": 1}
    assert second.output == {"n": 2}
    assert first.metadata.provider == "fake"
    assert first.metadata.request_id == "fake-request-1"
    assert [call["task"] for call in model.calls] == ["plan", "correct"]


def test_fake_model_can_return_malformed_data_and_raise_typed_error() -> None:
    malformed = FakeAgentModel("not structured")
    assert malformed.generate_structured(task="x", input_payload={}, output_schema=dict).output == "not structured"

    unavailable = AgentModelError(ModelErrorCode.MODEL_UNAVAILABLE, "offline")
    with pytest.raises(AgentModelError) as caught:
        FakeAgentModel(unavailable).generate_structured(task="x", input_payload={}, output_schema=dict)
    assert caught.value.code is ModelErrorCode.MODEL_UNAVAILABLE


def test_model_metadata_requires_utc_and_contains_no_secret_field() -> None:
    with pytest.raises(ValueError, match="UTC"):
        ModelMetadata("provider", "model", "1", "2026-01-01T00:00:00")
    metadata = ModelMetadata("provider", "model", "1", "2026-01-01T00:00:00Z", "request")
    assert set(metadata.to_dict()) == {"provider", "model_id", "adapter_version", "timestamp", "request_id"}
    assert "api_key" not in metadata.to_dict()


def test_model_protocol_has_no_provider_specific_arguments() -> None:
    from llm_csp.agentic.model import AgentModel

    annotations: dict[str, Any] = AgentModel.generate_structured.__annotations__
    assert "api_key" not in annotations
    assert "temperature" not in annotations
