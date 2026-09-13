"""Small provider-neutral structured-generation protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Mapping, Protocol, TypeVar

from ..models import _non_empty, _utc_timestamp


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    provider: str
    model_id: str
    adapter_version: str
    timestamp: str
    request_id: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.provider, "provider"), (self.model_id, "model_id"),
            (self.adapter_version, "adapter_version"), (self.timestamp, "timestamp"),
        ):
            _non_empty(value, name)
        _utc_timestamp(self.timestamp)
        if self.request_id is not None:
            _non_empty(self.request_id, "request_id")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class StructuredModelResponse(Generic[T]):
    """Untrusted structured output plus operational (not scientific) provenance."""

    output: T | Any
    metadata: ModelMetadata


class AgentModel(Protocol):
    def generate_structured(
        self,
        *,
        task: str,
        input_payload: Mapping[str, Any],
        output_schema: type[T],
    ) -> StructuredModelResponse[T]: ...


__all__ = ["AgentModel", "ModelMetadata", "StructuredModelResponse"]
