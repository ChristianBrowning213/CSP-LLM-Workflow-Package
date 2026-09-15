"""Schemas for literature-replication benchmark protocols."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkProtocol:
    protocol_id: str
    paper_name: str
    benchmark_family: str
    metric_name: str
    comparator_value: float
    direction: str
    unit: str | None
    dataset_scope: str
    attempts: int | None
    required_inputs: tuple[str, ...]
    required_evaluators: tuple[str, ...]
    protocol_match_requirements: str
    source_label: str
    notes: str | None = None

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["required_inputs"] = ",".join(self.required_inputs)
        row["required_evaluators"] = ",".join(self.required_evaluators)
        return row


@dataclass(frozen=True)
class MetricResult:
    benchmark_family: str
    metric_name: str
    our_value: float | None
    n_total: int
    n_computable: int
    n_not_computable: int
    unit: str | None = None
    required_inputs_missing: tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True)
class ComparatorResult:
    benchmark_family: str
    metric_name: str
    our_value: float | None
    paper_value: float
    paper_name: str
    comparator_name: str
    direction: str
    unit: str | None
    beats_paper: bool | None
    delta: float | None
    dataset_scope: str
    protocol_match_level: str
    n_total: int
    n_computable: int
    n_not_computable: int
    required_inputs_missing: str
    notes: str | None

