"""Pydantic schemas for SCA pre-DFT evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CifParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parse_ok: bool
    chemical_species_valid: bool | None = None
    species: list[str] = Field(default_factory=list)
    invalid_species: list[str] = Field(default_factory=list)
    formula: str | None = None
    reduced_formula: str | None = None
    n_sites: int | None = None
    volume: float | None = None
    density: float | None = None
    density_error: str | None = None
    lattice_a: float | None = None
    lattice_b: float | None = None
    lattice_c: float | None = None
    lattice_alpha: float | None = None
    lattice_beta: float | None = None
    lattice_gamma: float | None = None
    error_type: str | None = None
    error_message: str | None = None


class CompositionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_formula: str | None = None
    formula: str | None = None
    reduced_formula: str | None = None
    target_reduced_formula: str | None = None
    target_formula_match: bool | None = None
    composition_error: str | None = None


class SymmetryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    declared_space_group: str | None = None
    declared_space_group_number: int | None = None
    detected_space_group: str | None = None
    detected_space_group_number: int | None = None
    target_space_group: str | None = None
    space_group_consistent: bool | None = None
    symprec_used: float | None = None
    angle_tolerance_used: float | None = None
    symmetry_error: str | None = None


class MultiplicityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    multiplicity_checked: bool
    multiplicity_consistent: bool | None = None
    declared_atom_count: int | None = None
    expanded_atom_count: int | None = None
    site_count: int | None = None
    multiplicity_error: str | None = None


class BondResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bond_reasonableness_score: float | None = None
    bond_lengths_reasonable: bool | None = None
    min_distance: float | None = None
    min_distance_pair: str | None = None
    num_bad_contacts: int = 0
    bad_contact_pairs: list[str] = Field(default_factory=list)
    bond_error: str | None = None


class GeometryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geometry_ok: bool | None = None
    volume: float | None = None
    volume_per_atom: float | None = None
    density: float | None = None
    density_error: str | None = None
    geometry_warning_count: int = 0
    geometry_warnings: list[str] = Field(default_factory=list)
    geometry_error: str | None = None


class UniquenessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duplicate_group_id: str | None = None
    is_duplicate: bool | None = None
    is_unique_representative: bool | None = None
    num_duplicates_in_group: int | None = None


class NoveltyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novelty_checked: bool
    nearest_reference_id: str | None = None
    known_match: bool | None = None
    novel_by_structure_matcher: bool | None = None
    novelty_error: str | None = None


class AlignnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alignn_ok: bool
    alignn_model: str | None = None
    formation_energy_per_atom: float | None = None
    alignn_error: str | None = None


class CrystalEvalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    method: str | None = None
    query_id: str | None = None
    input_path: str
    file_name: str
    parse_ok: bool
    chemical_species_valid: bool | None = None
    species: list[str] = Field(default_factory=list)
    invalid_species: list[str] = Field(default_factory=list)
    formula: str | None = None
    reduced_formula: str | None = None
    target_formula: str | None = None
    target_formula_match: bool | None = None
    declared_space_group: str | None = None
    detected_space_group: str | None = None
    target_space_group: str | None = None
    space_group_consistent: bool | None = None
    multiplicity_checked: bool = False
    multiplicity_consistent: bool | None = None
    bond_reasonableness_score: float | None = None
    bond_lengths_reasonable: bool | None = None
    min_distance: float | None = None
    min_distance_pair: str | None = None
    num_bad_contacts: int = 0
    volume: float | None = None
    volume_per_atom: float | None = None
    density: float | None = None
    density_error: str | None = None
    geometry_ok: bool | None = None
    geometry_warning_count: int = 0
    duplicate_group_id: str | None = None
    is_duplicate: bool | None = None
    is_unique_representative: bool | None = None
    novelty_checked: bool = False
    nearest_reference_id: str | None = None
    known_match: bool | None = None
    novel_by_structure_matcher: bool | None = None
    novelty_error: str | None = None
    alignn_ok: bool = False
    alignn_model: str | None = None
    formation_energy_per_atom: float | None = None
    pre_dft_valid: bool = False
    pre_dft_rank_score: float = 1_000_000.0
    selected_for_dft: bool = False
    error_type: str | None = None
    error_message: str | None = None

    def to_row(self) -> dict[str, Any]:
        return self.model_dump()


class BenchmarkEvaluatorResult(BaseModel):
    """Generic output envelope for one benchmark evaluator."""

    model_config = ConfigDict(extra="forbid")

    name: str
    ok: bool
    skipped: bool = False
    model: str | None = None
    version: str | None = None
    summary: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    flags: dict[str, bool | None] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None


class BenchmarkRecord(BaseModel):
    """Container record for reusable crystal-generation benchmarks."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    method: str | None = None
    query_id: str | None = None
    input_path: str
    file_name: str
    evaluator_outputs: dict[str, BenchmarkEvaluatorResult] = Field(default_factory=dict)
    flattened: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None

    def to_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "run_id": self.run_id,
            "method": self.method,
            "query_id": self.query_id,
            "input_path": self.input_path,
            "file_name": self.file_name,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }
        row.update(self.flattened)
        for name, result in self.evaluator_outputs.items():
            prefix = f"evaluator_{name}"
            row[f"{prefix}_ok"] = result.ok
            row[f"{prefix}_skipped"] = result.skipped
            row[f"{prefix}_summary"] = result.summary
            row[f"{prefix}_error_type"] = result.error_type
            row[f"{prefix}_error_message"] = result.error_message
            row[f"{prefix}_details"] = result.details
        return row


class AggregateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_value: str | None = None
    num_generated: int
    parse_valid_rate: float | None = None
    target_formula_match_rate: float | None = None
    space_group_consistency_rate: float | None = None
    multiplicity_consistency_rate: float | None = None
    bond_reasonable_rate: float | None = None
    geometry_ok_rate: float | None = None
    pre_dft_valid_rate: float | None = None
    unique_valid_count: int
    duplicate_rate: float | None = None
    novelty_checked_count: int
    novel_rate: float | None = None
    known_match_rate: float | None = None
    median_alignn_formation_energy: float | None = None
    best_alignn_formation_energy: float | None = None


# Compatibility schemas retained for the original ALIGNN-only API/tests.
class CifMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_path: str
    file_name: str
    parse_ok: bool = False
    formula: str | None = None
    reduced_formula: str | None = None
    n_sites: int | None = None
    volume: float | None = None
    density: float | None = None
    error_type: str | None = None
    error_message: str | None = None

    @classmethod
    def for_path(cls, path: Path) -> "CifMetadata":
        return cls(input_path=str(path), file_name=path.name)


class EvaluatorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    model: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None


class CrystalEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_path: str
    file_name: str
    parse_ok: bool
    formula: str | None = None
    reduced_formula: str | None = None
    n_sites: int | None = None
    volume: float | None = None
    density: float | None = None
    alignn_ok: bool = False
    alignn_model: str | None = None
    formation_energy_per_atom: float | None = None
    error_type: str | None = None
    error_message: str | None = None

    @classmethod
    def from_parts(
        cls,
        cif: CifMetadata,
        alignn: EvaluatorResult | None = None,
    ) -> "CrystalEvaluationResult":
        alignn = alignn or EvaluatorResult()
        return cls(
            input_path=cif.input_path,
            file_name=cif.file_name,
            parse_ok=cif.parse_ok,
            formula=cif.formula,
            reduced_formula=cif.reduced_formula,
            n_sites=cif.n_sites,
            volume=cif.volume,
            density=cif.density,
            alignn_ok=alignn.ok,
            alignn_model=alignn.model,
            formation_energy_per_atom=alignn.values.get("formation_energy_per_atom"),
            error_type=alignn.error_type or cif.error_type,
            error_message=alignn.error_message or cif.error_message,
        )

    def to_row(self) -> dict[str, Any]:
        return self.model_dump()
