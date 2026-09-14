"""Explicit MCP tool contracts for the SPP maker server."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DeterministicModel(BaseModel):
    """Base model with strict field handling for contract stability."""

    model_config = ConfigDict(extra="forbid")


class WarningObject(DeterministicModel):
    code: str
    message: str
    path: str | None = None
    dropped_keys: list[str] = Field(default_factory=list)


class StructuredErrorDetail(DeterministicModel):
    path: str
    message: str
    expected: str | None = None
    received: str | None = None


class StructuredError(DeterministicModel):
    type: str
    message: str
    code: str | None = None
    details: list[StructuredErrorDetail] = Field(default_factory=list)


class ProvenanceBlock(DeterministicModel):
    git_sha: str | None = None
    tool: str
    tool_version: str
    params_hash: str | None = None
    content_hash: str | None = None


class ToolEnvelope(DeterministicModel):
    ok: bool
    trace_id: str
    tool_name: str
    result: dict[str, Any] | None
    error: StructuredError | None
    warnings: list[WarningObject] = Field(default_factory=list)


class MCPServerConfig(DeterministicModel):
    allowed_read_roots: list[str] = Field(default_factory=list)
    allowed_write_roots: list[str] = Field(default_factory=list)
    max_cif_count: int = 5000
    max_runtime_seconds: int = 7200
    max_output_bytes: int = 2_000_000_000

    @model_validator(mode="after")
    def _validate_caps(self) -> "MCPServerConfig":
        if self.max_cif_count <= 0:
            raise ValueError("max_cif_count must be > 0")
        if self.max_runtime_seconds <= 0:
            raise ValueError("max_runtime_seconds must be > 0")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be > 0")
        return self


class RunFitParams(DeterministicModel):
    fit_method: Literal["neighbors", "supercell_gr"] = "neighbors"
    r_cut: float | None = None
    knn: int | None = None
    min_d: float | None = None
    d_min: float = 0.5
    d_max: float = 8.0
    alpha: float = 1e-3
    supercell_target_len: float = 20.0
    r_max: float = 10.0
    bin_width: float = 0.05
    sigma: float = 0.1
    truncate_sigma: float = 3.0
    gr_eps: float = 1e-12
    max_pairs: int | None = None


class RunCovalentParams(DeterministicModel):
    enabled: bool = False
    rules_path: str | None = None


class RunCalibrationBandpass(DeterministicModel):
    enabled: bool = True
    d_lo: float | None = None
    d_hi: float | None = None
    sigma_lo: float | None = None
    sigma_hi: float | None = None


class RunCalibrationParams(DeterministicModel):
    score_method: Literal["neighbors", "supercell_gr"] = "neighbors"
    mode: Literal["structure_median", "edge_median", "quantile"] = "structure_median"
    target: float
    q: float = 0.5
    max_calib: int | None = None
    convention: Literal["reward", "penalty"] = "reward"
    min_lambda: float = 0.0
    max_lambda: float = 1e9
    bandpass: RunCalibrationBandpass = Field(default_factory=RunCalibrationBandpass)


class RunFilterParams(DeterministicModel):
    meta_csv: str | None = None
    property_filter: str | None = None
    property_mode: Literal["include", "exclude"] = "include"


class RunPublishParams(DeterministicModel):
    publish_to: str | None = None


class RunPipelineRequest(DeterministicModel):
    trace_id: str | None = None
    cif_dir: str
    out_dir: str
    name: str
    material_system: str | None = None
    formula: str | None = None
    required_pairs: list[str] = Field(default_factory=list)
    qlip_pair_mode: Literal["neighbors", "required_pairs"] = "neighbors"
    qlip_pair_cutoff: float = 6.0
    runtime_profile: Literal["probe", "demo", "production"] = "demo"
    max_cifs: int | None = None
    max_distances_per_pair: int | None = None
    max_pairs_per_pair: int | None = None
    allow_fallback_precompiled: bool | None = None
    fit: RunFitParams = Field(default_factory=RunFitParams)
    covalent: RunCovalentParams = Field(default_factory=RunCovalentParams)
    calibration: RunCalibrationParams
    filters: RunFilterParams = Field(default_factory=RunFilterParams)
    publish: RunPublishParams = Field(default_factory=RunPublishParams)
    timeout_seconds: int | None = None
    dry_run: bool = False
    debug: bool = False


class RunPipelinePaths(DeterministicModel):
    fit_spp_root: str
    calibration_json: str
    scaled_spp_root: str
    package_json: str


class RunPipelineResult(DeterministicModel):
    run_id: str
    run_root: str
    final_bundle: str
    spp_run_root: str | None = None
    final_bundle_path: str | None = None
    calibration_json: str | None = None
    guidance_package_path: str | None = None
    package_json_path: str | None = None
    compatibility: dict[str, Any] = Field(default_factory=dict)
    qlip_solve_compatible: bool = False
    qlip_package: dict[str, Any] = Field(default_factory=dict)
    runtime_profile: str = "demo"
    runtime_stages: list[dict[str, Any]] = Field(default_factory=list)
    content_hash: str
    paths: RunPipelinePaths
    published: dict[str, str] | None = None
    provenance: ProvenanceBlock
    log_path: str | None = None
    dry_run: bool = False
    cif_count: int
    output_bytes: int | None = None


class CheckCompatRequest(DeterministicModel):
    trace_id: str | None = None
    spp_root: str
    strict: bool = False
    debug: bool = False


class CompatFailure(DeterministicModel):
    path: str
    reason: str
    line_no: int | None = None


class CheckCompatResult(DeterministicModel):
    ok: bool
    files_checked: int
    failed_count: int
    failures: list[CompatFailure] = Field(default_factory=list)


class PackageForQLIPRequest(DeterministicModel):
    trace_id: str | None = None
    run_root: str | None = None
    spp_root: str | None = None
    calibration_json: str | None = None
    out_dir: str
    name: str
    include_registry_snapshot: bool = False
    debug: bool = False

    @model_validator(mode="after")
    def _validate_inputs(self) -> "PackageForQLIPRequest":
        if self.run_root is not None:
            if self.spp_root is not None or self.calibration_json is not None:
                raise ValueError(
                    "Provide either run_root OR (spp_root + calibration_json), not both."
                )
            return self
        if self.spp_root is None or self.calibration_json is None:
            raise ValueError("When run_root is omitted, spp_root and calibration_json are required.")
        return self


class PackageForQLIPResult(DeterministicModel):
    run_id: str
    final_bundle_path: str
    package_json_path: str
    contents: list[str]
    provenance: ProvenanceBlock
    output_bytes: int


class PublishToQLIPOutputsRequest(DeterministicModel):
    trace_id: str | None = None
    kind: Literal["spp", "guidance", "package", "constraint"]
    artifact_root: str
    qlip_outputs_path: str
    name: str
    overwrite: bool = False
    strict_compat: bool = True
    copy_mode: Literal["copy", "symlink"] = "copy"
    set_latest: bool = True
    debug: bool = False


class PublishToQLIPOutputsResult(DeterministicModel):
    published_run_id: str
    published_path: str
    index_json_path: str
    latest_pointer_path: str
    latest_pointer_value: str
    provenance: ProvenanceBlock


TOOL_REQUEST_MODELS: dict[str, type[DeterministicModel]] = {
    "spp.run_pipeline": RunPipelineRequest,
    "spp.check_compat": CheckCompatRequest,
    "spp.package_for_qlip": PackageForQLIPRequest,
    "spp.publish_to_qlip_outputs": PublishToQLIPOutputsRequest,
}

TOOL_RESULT_MODELS: dict[str, type[DeterministicModel]] = {
    "spp.run_pipeline": RunPipelineResult,
    "spp.check_compat": CheckCompatResult,
    "spp.package_for_qlip": PackageForQLIPResult,
    "spp.publish_to_qlip_outputs": PublishToQLIPOutputsResult,
}


def stable_json_dumps(payload: Any) -> str:
    """Return deterministic JSON text for hashes/snapshots."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(payload: Any) -> str:
    """Return SHA-256 hash over deterministic JSON encoding."""
    return hashlib.sha256(stable_json_dumps(payload).encode("utf-8")).hexdigest()


def canonical_schema_for_model(model: type[BaseModel]) -> dict[str, Any]:
    """Return schema with stable key ordering."""
    schema = model.model_json_schema()
    return json.loads(stable_json_dumps(schema))


def build_tool_schemas() -> dict[str, dict[str, Any]]:
    """Return canonical request/result schemas for all exported tools."""
    out: dict[str, dict[str, Any]] = {}
    for tool_name in sorted(TOOL_REQUEST_MODELS):
        out[tool_name] = {
            "request": canonical_schema_for_model(TOOL_REQUEST_MODELS[tool_name]),
            "result": canonical_schema_for_model(TOOL_RESULT_MODELS[tool_name]),
            "envelope": canonical_schema_for_model(ToolEnvelope),
        }
    return out
