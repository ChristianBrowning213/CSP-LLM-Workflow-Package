"""Deterministic, side-effect-free structured model for tests and examples."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from .base import ModelMetadata, StructuredModelResponse
from .errors import AgentModelError


class FakeAgentModel:
    def __init__(
        self,
        responses: Any | Iterable[Any],
        *,
        provider: str = "fake",
        model_id: str = "deterministic-fixture",
        adapter_version: str = "1",
        clock: Callable[[], datetime] = lambda: datetime(2000, 1, 1, tzinfo=timezone.utc),
    ) -> None:
        if isinstance(responses, (list, tuple, deque)):
            values = list(responses)
        else:
            values = [responses]
        if not values:
            raise ValueError("at least one fake response is required")
        self._responses = deque(values)
        self.provider = provider
        self.model_id = model_id
        self.adapter_version = adapter_version
        self.clock = clock
        self.calls: list[dict[str, Any]] = []

    def generate_structured(
        self,
        *,
        task: str,
        input_payload: Mapping[str, Any],
        output_schema: type[Any],
    ) -> StructuredModelResponse[Any]:
        self.calls.append({
            "task": task,
            "input_payload": dict(input_payload),
            "output_schema": output_schema.__name__,
        })
        if not self._responses:
            raise AgentModelError(
                "MODEL_REQUEST_FAILED", "fake response sequence exhausted", retryable_format=False
            )
        value = self._responses.popleft()
        if isinstance(value, BaseException):
            raise value
        number = len(self.calls)
        metadata = ModelMetadata(
            self.provider,
            self.model_id,
            self.adapter_version,
            self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            f"fake-request-{number}",
        )
        return StructuredModelResponse(value, metadata)


__all__ = ["FakeAgentModel"]
