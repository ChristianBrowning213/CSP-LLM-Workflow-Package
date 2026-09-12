"""Stable, backend-neutral result envelopes for crystal validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ADAPTER_SCHEMA_VERSION = "llm_csp.validation.v1"
SCA_VALIDATED_REVISION = "3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af"


@dataclass(frozen=True)
class ValidationError:
    """One machine-readable validation failure or backend diagnostic."""

    kind: str
    message: str


@dataclass(frozen=True)
class BackendProvenance:
    """Identity of the backend used, without claiming an unreported version."""

    name: str = "Structured_Crystal_Analyser"
    version: str | None = None
    validated_revision: str = SCA_VALIDATED_REVISION
    adapter_schema: str = ADAPTER_SCHEMA_VERSION


@dataclass(frozen=True)
class ValidationResult:
    """Normalized result from SCA's general CIF evaluation pipeline."""

    status: str
    parseable: bool
    valid: bool | None
    composition: dict[str, Any] = field(default_factory=dict)
    general_metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    errors: tuple[ValidationError, ...] = ()
    backend: BackendProvenance = field(default_factory=BackendProvenance)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopologyValidationResult:
    """Normalized result from SCA's family-topology evaluator."""

    status: str
    family: str
    available: bool
    topology_status: str | None
    matches: bool | None
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    errors: tuple[ValidationError, ...] = ()
    backend: BackendProvenance = field(default_factory=BackendProvenance)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
