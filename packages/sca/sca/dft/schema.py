"""Versioned, engine-neutral schemas for external DFT calculations."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CalculationType(str, Enum):
    RELAX = "RELAX"
    STATIC = "STATIC"


class DFTStatus(str, Enum):
    PREPARED = "PREPARED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    NOT_CONVERGED = "NOT_CONVERGED"
    UNKNOWN = "UNKNOWN"


class DFTFailureType(str, Enum):
    SCF_NOT_CONVERGED = "SCF_NOT_CONVERGED"
    IONIC_NOT_CONVERGED = "IONIC_NOT_CONVERGED"
    WALLTIME = "WALLTIME"
    ENGINE_CRASH = "ENGINE_CRASH"
    MISSING_OUTPUT = "MISSING_OUTPUT"
    BAD_PSEUDOPOTENTIAL = "BAD_PSEUDOPOTENTIAL"
    MEMORY = "MEMORY"
    STRUCTURE_COLLAPSE = "STRUCTURE_COLLAPSE"
    PARSER_ERROR = "PARSER_ERROR"
    UNKNOWN = "UNKNOWN"


class CompatibilityStatus(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class DFTCompatibilityFingerprint(BaseModel):
    """Scientific settings that must agree before physical energies are combined."""

    model_config = ConfigDict(extra="forbid")

    engine_family: str | None = None
    energy_convention: str | None = None
    xc_functional: str | None = None
    pseudopotential_family: str | None = None
    hubbard_u: dict[str, float] = Field(default_factory=dict)
    dispersion: str | None = None
    correction_scheme: str | None = None

    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DFTCalculationSpec(BaseModel):
    """Complete reproducible scientific input contract for one DFT calculation."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    schema_version: str = "sca.dft.calculation.v1"
    calculation_id: str
    candidate_id: str
    input_cif_path: str
    input_cif_sha256: str
    engine: str
    calculation_type: CalculationType
    xc_functional: str
    dispersion: str | None = None
    pseudopotential_family: str
    cutoff_energy: float
    kpoint_scheme: str = "monkhorst-pack"
    kpoint_spacing: float
    spin_polarized: bool = False
    initial_magnetic_moments: dict[str, float] = Field(default_factory=dict)
    hubbard_u: dict[str, float] = Field(default_factory=dict)
    energy_tolerance: float
    force_tolerance: float | None = None
    stress_tolerance: float | None = None
    max_steps: int
    charge: float = 0.0
    smearing: dict[str, Any] = Field(default_factory=dict)
    parent_calculation_id: str | None = None
    changed_parameters: dict[str, Any] = Field(default_factory=dict)
    change_reason: str | None = None
    correction_scheme: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_retry_provenance(self):
        if self.parent_calculation_id and not self.change_reason:
            raise ValueError("A retry with parent_calculation_id requires change_reason")
        if self.changed_parameters and not self.parent_calculation_id:
            raise ValueError("changed_parameters requires parent_calculation_id")
        return self

    @property
    def compatibility_fingerprint(self) -> DFTCompatibilityFingerprint:
        return DFTCompatibilityFingerprint(
            engine_family=self.engine.lower(),
            energy_convention="periodic_dft_total_energy",
            xc_functional=self.xc_functional,
            pseudopotential_family=self.pseudopotential_family,
            hubbard_u=self.hubbard_u,
            dispersion=self.dispersion,
            correction_scheme=self.correction_scheme,
        )


class DFTResult(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    schema_version: str = "sca.dft.result.v1"
    calculation_id: str
    candidate_id: str
    status: DFTStatus
    converged: bool
    failure_type: DFTFailureType | None = None
    failure_message: str | None = None
    initial_cif: str | None = None
    relaxed_cif: str | None = None
    total_energy_eV: float | None = None
    energy_per_atom_eV: float | None = None
    max_force_eV_A: float | None = None
    stress: list[list[float]] | None = None
    num_ionic_steps: int | None = None
    num_scf_iterations: int | None = None
    final_volume: float | None = None
    runtime_seconds: float | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    engine_version: str | None = None
    compatibility_fingerprint: DFTCompatibilityFingerprint | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DFTExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    schema_version: str = "sca.dft.execution.v1"
    calculation_id: str
    calculation_dir: str
    status: DFTStatus = DFTStatus.PREPARED
    slurm_job_id: str | None = None
    submit_time_utc: str | None = None
    status_checked_utc: str | None = None
    submit_command: list[str] = Field(default_factory=list)
    message: str | None = None

