"""Versioned Statistical Pair Potential artifact schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SppPairTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bin_edges: list[float] = Field(min_length=2)
    penalties: list[float] = Field(min_length=1)
    tail_penalty: float | None = None
    weight: float = 1.0
    distance_grid: list[float] | None = None
    interpolation_policy: str = "piecewise_constant"

    @model_validator(mode="after")
    def _check_lengths(self) -> "SppPairTable":
        if len(self.penalties) != len(self.bin_edges) - 1:
            raise ValueError("penalties length must equal len(bin_edges) - 1")
        if sorted(self.bin_edges) != self.bin_edges:
            raise ValueError("bin_edges must be sorted ascending")
        if self.distance_grid is not None:
            if len(self.distance_grid) != len(self.penalties):
                raise ValueError("distance_grid length must equal penalties length")
            if sorted(self.distance_grid) != self.distance_grid:
                raise ValueError("distance_grid must be sorted ascending")
        return self


class SppProvenance(BaseModel):
    model_config = ConfigDict(extra="allow")

    created_by: str | None = None
    source: str | None = None
    notes: str | None = None


class SppCorpusSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    num_structures: int | None = None
    num_pairs: int | None = None
    description: str | None = None


class SppArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: Literal["spp"] = "spp"
    schema_version: Literal["1.0"] = "1.0"
    species_pairs: dict[str, SppPairTable]
    smoothing: dict[str, Any] = Field(default_factory=dict)
    corpus_hash: str | None = None
    cutoff_policy: dict[str, Any] = Field(default_factory=dict)
    weighting_policy: dict[str, Any] = Field(default_factory=dict)
    provenance: SppProvenance = Field(default_factory=SppProvenance)
    corpus_summary: SppCorpusSummary = Field(default_factory=SppCorpusSummary)

    @model_validator(mode="after")
    def _check_pairs(self) -> "SppArtifact":
        if not self.species_pairs:
            raise ValueError("species_pairs must not be empty")
        return self

    @property
    def cutoff(self) -> float:
        value = self.cutoff_policy.get("cutoff")
        return float(value) if value is not None else 8.0


def load_spp_artifact(path: str | Path) -> SppArtifact:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return SppArtifact.model_validate(payload)


def species_pair_key(species_a: str, species_b: str) -> str:
    return "--".join(sorted((species_a, species_b)))
