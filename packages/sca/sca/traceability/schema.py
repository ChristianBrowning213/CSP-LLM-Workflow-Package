"""Schemas for auditable text-to-crystal CSP run bundles."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TraceArtifact(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    errors: list[str] = Field(default_factory=list)
    notes: str | None = None


class StructuredIntent(TraceArtifact):
    formula: str | None = None
    chemical_system: str | None = None
    space_group: str | int | None = None
    crystal_system: str | None = None
    prototype_family: str | None = None
    constraints: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    evidence_id: str
    formula: str | None = None
    chemical_system: str | None = None
    family: str | None = None
    space_group: str | int | None = None
    cif_path: str | None = None
    score: float | None = None
    citation: str | None = None
    parseable: bool | None = None


class RetrievalTrace(TraceArtifact):
    query: str | None = None
    mode: str | None = None
    retrieved: list[EvidenceItem] = Field(default_factory=list)


class ConstraintTrace(TraceArtifact):
    constraints: list[dict[str, Any]] = Field(default_factory=list)


class SPPTrace(TraceArtifact):
    pairs: list[dict[str, Any]] = Field(default_factory=list)


class SolverTrace(TraceArtifact):
    backend: str | None = None
    solver_status: str | None = None
    objective_value: float | None = None
    num_variables: int | None = None
    num_constraints: int | None = None
    solve_time_seconds: float | None = None
    infeasibility_explanation: str | None = None


class GeneratedCandidateTrace(TraceArtifact):
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class ValidationTrace(TraceArtifact):
    report_path: str | None = None
    pre_dft_valid: bool | None = None


class RelaxationTrace(TraceArtifact):
    report_path: str | None = None
    relax_ok: bool | None = None


class DiagnosticsTrace(TraceArtifact):
    report_path: str | None = None
    failure_type: str | None = None


class FinalDecisionTrace(TraceArtifact):
    decision: str | None = None
    explanation: str | None = None
    citations: list[str] = Field(default_factory=list)


class TraceableRunBundle(BaseModel):
    """Complete audit trail for a text-to-crystal CSP run."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    prompt_id: str | None = None
    input_text: str
    timestamp: str | None = None
    run_dir: str | None = None
    manifest_row: dict[str, Any] = Field(default_factory=dict)
    files: dict[str, str] = Field(default_factory=dict)
    checksums: dict[str, str] = Field(default_factory=dict)
    status: str | None = None
    errors: list[str] = Field(default_factory=list)
    notes: str | None = None
    structured_intent: StructuredIntent | None = None
    retrieval_trace: RetrievalTrace | None = None
    constraint_trace: ConstraintTrace | None = None
    spp_trace: SPPTrace | None = None
    solver_trace: SolverTrace | None = None
    generated_candidates: GeneratedCandidateTrace | None = None
    validation_trace: ValidationTrace | None = None
    relaxation_trace: RelaxationTrace | None = None
    diagnostics_trace: DiagnosticsTrace | None = None
    final_decision: FinalDecisionTrace | None = None


class BundleInspectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    prompt_id: str | None = None
    run_dir: str
    bundle_valid: bool
    missing_artifacts: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    crosslink_errors: list[str] = Field(default_factory=list)
    artifact_presence: dict[str, bool] = Field(default_factory=dict)
    reproducibility_metadata_present: bool = False
    missing_reproducibility_fields: list[str] = Field(default_factory=list)
    bundle: TraceableRunBundle | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "prompt_id": self.prompt_id,
            "run_dir": self.run_dir,
            "bundle_valid": self.bundle_valid,
            "missing_artifact_count": len(self.missing_artifacts),
            "missing_artifacts": ";".join(self.missing_artifacts),
            "parse_errors": ";".join(self.parse_errors),
            "crosslink_errors": ";".join(self.crosslink_errors),
            "reproducibility_metadata_present": self.reproducibility_metadata_present,
            "missing_reproducibility_fields": ";".join(self.missing_reproducibility_fields),
            **{f"artifact_{key}_present": value for key, value in self.artifact_presence.items()},
        }
