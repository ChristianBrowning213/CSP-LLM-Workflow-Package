from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass
from typing import Any


_IMPLEMENTATION_STATUS = {"implemented_now", "not_implemented", "adapter_scaffold"}
_OPTIMIZATION_DIRECTIONS = {"minimize", "maximize", "bounded", "feasibility"}
_INPUT_TYPES = {"formula", "structure", "composition_or_structure"}
_PREDICTION_TYPES = {"composition_descriptor_scalar", "formation_energy_surrogate"}
_REQUEST_USES = {"reporting", "selection_metric", "ranking"}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


class Phase2ExternalPredictorResolutionError(ValueError):
    def __init__(
        self,
        *,
        code: str,
        requested: str,
        detail: str,
        suggestions: list[str] | None = None,
    ) -> None:
        self.code = str(code)
        self.requested = str(requested)
        self.detail = str(detail)
        self.suggestions = [str(item) for item in (suggestions or []) if str(item).strip()]
        message = self.detail
        if self.suggestions:
            message = f"{self.detail} Supported: {', '.join(self.suggestions)}"
        super().__init__(message)


class Phase2ExternalPredictorBenchmarkModeError(ValueError):
    def __init__(self, *, requested: str, cause: Phase2ExternalPredictorResolutionError) -> None:
        self.requested = str(requested)
        self.cause = cause
        self.code = f"PHASE2_BENCHMARK_REJECTED_{cause.code}"
        super().__init__(f"{self.code}: {cause.detail}")


@dataclass(frozen=True, slots=True)
class Phase2ExternalPredictorEntry:
    id: str
    display_name: str
    backend: str
    backend_version: str
    input_type: str
    prediction_type: str
    optimization_direction: str
    implementation_status: str
    provenance_requirements: list[str]
    calibration_status: str
    validation_status: str
    known_domain_limits: list[str]
    benchmark_approved: bool
    exploratory_only: bool
    supported_targets: list[str]
    notes: str
    request_aliases: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "backend": self.backend,
            "backend_version": self.backend_version,
            "input_type": self.input_type,
            "prediction_type": self.prediction_type,
            "optimization_direction": self.optimization_direction,
            "implementation_status": self.implementation_status,
            "provenance_requirements": list(self.provenance_requirements),
            "calibration_status": self.calibration_status,
            "validation_status": self.validation_status,
            "known_domain_limits": list(self.known_domain_limits),
            "benchmark_approved": bool(self.benchmark_approved),
            "exploratory_only": bool(self.exploratory_only),
            "supported_targets": list(self.supported_targets),
            "notes": self.notes,
            "request_aliases": list(self.request_aliases or []),
        }


def _registry() -> list[Phase2ExternalPredictorEntry]:
    return [
        Phase2ExternalPredictorEntry(
            id="phase2.external.pymatgen_composition_descriptor",
            display_name="Pymatgen Composition Descriptor Predictor",
            backend="pymatgen",
            backend_version=_version("pymatgen"),
            input_type="formula",
            prediction_type="composition_descriptor_scalar",
            optimization_direction="maximize",
            implementation_status="implemented_now",
            provenance_requirements=[
                "backend",
                "backend_version",
                "predictor_id",
                "adapter_name",
                "input_formula",
                "target",
                "value_state",
                "calibration_applied",
            ],
            calibration_status="uncalibrated_exploratory",
            validation_status="not_validated_for_benchmark",
            known_domain_limits=[
                "formula-only descriptor; no structure relaxation, oxidation state, or site-ordering information",
                "not a trained materials-property model",
                "not benchmark-approved for paper claims",
            ],
            benchmark_approved=False,
            exploratory_only=True,
            supported_targets=["mean_atomic_number", "mean_atomic_mass", "mean_electronegativity"],
            request_aliases=[
                "pymatgen_composition_descriptor",
                "composition_descriptor",
                "external_descriptor",
                "mean_atomic_number",
                "mean_atomic_mass",
                "mean_electronegativity",
            ],
            notes=(
                "Implemented local adapter around off-the-shelf pymatgen composition data. "
                "Values are raw exploratory descriptors, not native QLIP objectives and not calibrated predictors."
            ),
        ),
        Phase2ExternalPredictorEntry(
            id="phase2.external.matminer_formation_energy_rf",
            display_name="Matminer Formation-Energy Surrogate Scaffold",
            backend="matminer/sklearn",
            backend_version=f"matminer={_version('matminer')}; sklearn={_version('scikit-learn')}",
            input_type="composition_or_structure",
            prediction_type="formation_energy_surrogate",
            optimization_direction="minimize",
            implementation_status="not_implemented",
            provenance_requirements=[
                "backend",
                "backend_version",
                "predictor_id",
                "model_version",
                "training_data_identifier",
                "calibration_applied",
            ],
            calibration_status="not_available",
            validation_status="not_validated",
            known_domain_limits=["adapter scaffold only; dependencies/model are not bundled"],
            benchmark_approved=False,
            exploratory_only=True,
            supported_targets=["formation_energy"],
            request_aliases=["matminer_formation_energy", "formation_energy_predictor"],
            notes="Canonical placeholder for a future trained external predictor; not runnable in this tranche.",
        ),
    ]


def validate_phase2_external_predictor_registry() -> None:
    seen_ids: set[str] = set()
    for item in _registry():
        payload = item.to_dict()
        if payload["id"] in seen_ids:
            raise ValueError(f"Duplicate phase2 predictor id: {payload['id']}")
        seen_ids.add(payload["id"])
        if payload["implementation_status"] not in _IMPLEMENTATION_STATUS:
            raise ValueError(f"Invalid implementation_status for {payload['id']}")
        if payload["optimization_direction"] not in _OPTIMIZATION_DIRECTIONS:
            raise ValueError(f"Invalid optimization_direction for {payload['id']}")
        if payload["input_type"] not in _INPUT_TYPES:
            raise ValueError(f"Invalid input_type for {payload['id']}")
        if payload["prediction_type"] not in _PREDICTION_TYPES:
            raise ValueError(f"Invalid prediction_type for {payload['id']}")
        if not payload["provenance_requirements"]:
            raise ValueError(f"provenance_requirements must be non-empty for {payload['id']}")
        if not payload["supported_targets"]:
            raise ValueError(f"supported_targets must be non-empty for {payload['id']}")


def list_phase2_external_predictors(*, include_nonimplemented: bool = True) -> list[Phase2ExternalPredictorEntry]:
    validate_phase2_external_predictor_registry()
    items = _registry()
    if include_nonimplemented:
        return list(items)
    return [item for item in items if item.implementation_status == "implemented_now"]


def phase2_external_predictor_table(*, include_nonimplemented: bool = True) -> list[dict[str, Any]]:
    return [
        item.to_dict()
        for item in list_phase2_external_predictors(include_nonimplemented=include_nonimplemented)
    ]


def phase2_external_predictor_report() -> dict[str, Any]:
    table = phase2_external_predictor_table(include_nonimplemented=True)
    implemented = [row for row in table if row.get("implementation_status") == "implemented_now"]
    nonimplemented = [row for row in table if row.get("implementation_status") != "implemented_now"]
    return {
        "schema_version": "phase2.external_predictor_library.v1",
        "phase1_native_objective_registry": "separate",
        "counts": {
            "total": len(table),
            "implemented_now": len(implemented),
            "not_implemented": sum(1 for row in table if row.get("implementation_status") == "not_implemented"),
            "benchmark_approved": sum(1 for row in table if bool(row.get("benchmark_approved"))),
            "exploratory_only": sum(1 for row in table if bool(row.get("exploratory_only"))),
        },
        "implemented_now": implemented,
        "nonimplemented": nonimplemented,
        "all_entries": table,
    }


def _build_alias_map() -> dict[str, Phase2ExternalPredictorEntry]:
    alias_map: dict[str, Phase2ExternalPredictorEntry] = {}
    for item in list_phase2_external_predictors(include_nonimplemented=True):
        aliases = [item.id, *(item.request_aliases or [])]
        for alias in aliases:
            key = _norm(alias)
            if key:
                alias_map[key] = item
    return alias_map


def resolve_phase2_external_predictor_request(
    requested: str,
    *,
    allow_nonimplemented: bool = False,
) -> Phase2ExternalPredictorEntry:
    key = _norm(requested)
    item = _build_alias_map().get(key)
    if item is None:
        raise Phase2ExternalPredictorResolutionError(
            code="PHASE2_UNKNOWN_EXTERNAL_PREDICTOR",
            requested=requested,
            detail=f"Unknown Phase 2 external predictor request: {requested}",
            suggestions=[row.id for row in list_phase2_external_predictors(include_nonimplemented=False)],
        )
    if item.implementation_status != "implemented_now" and not allow_nonimplemented:
        raise Phase2ExternalPredictorResolutionError(
            code="PHASE2_EXTERNAL_PREDICTOR_NOT_IMPLEMENTED",
            requested=requested,
            detail=(
                f"Phase 2 external predictor '{requested}' maps to '{item.id}', "
                "which is not implemented in this repository."
            ),
            suggestions=[row.id for row in list_phase2_external_predictors(include_nonimplemented=False)],
        )
    return item


def normalize_phase2_external_predictor_request(
    payload: str | dict[str, Any],
    *,
    allow_nonimplemented: bool = False,
) -> dict[str, Any]:
    if isinstance(payload, str):
        raw: dict[str, Any] = {"predictor_id": payload}
    elif isinstance(payload, dict):
        raw = dict(payload)
    else:
        raise Phase2ExternalPredictorResolutionError(
            code="PHASE2_MALFORMED_EXTERNAL_PREDICTOR_REQUEST",
            requested=str(payload),
            detail="External predictor request must be a predictor id string or object.",
        )
    predictor_id = raw.get("predictor_id")
    if not isinstance(predictor_id, str) or not predictor_id.strip():
        raise Phase2ExternalPredictorResolutionError(
            code="PHASE2_MALFORMED_EXTERNAL_PREDICTOR_REQUEST",
            requested=str(raw),
            detail="External predictor request requires non-empty predictor_id.",
        )
    entry = resolve_phase2_external_predictor_request(
        predictor_id,
        allow_nonimplemented=allow_nonimplemented,
    )
    target = raw.get("target")
    if target is None:
        target = entry.supported_targets[0]
    if not isinstance(target, str) or target not in entry.supported_targets:
        raise Phase2ExternalPredictorResolutionError(
            code="PHASE2_UNSUPPORTED_EXTERNAL_PREDICTOR_TARGET",
            requested=predictor_id,
            detail=f"Unsupported target for {entry.id}: {target}",
            suggestions=list(entry.supported_targets),
        )
    use = raw.get("use", "reporting")
    if not isinstance(use, str) or use not in _REQUEST_USES:
        raise Phase2ExternalPredictorResolutionError(
            code="PHASE2_MALFORMED_EXTERNAL_PREDICTOR_REQUEST",
            requested=predictor_id,
            detail=f"External predictor use must be one of {sorted(_REQUEST_USES)}.",
        )
    return {
        "schema_version": "phase2.external_predictor_request.v1",
        "predictor_id": entry.id,
        "target": target,
        "use": use,
        "value_state": "raw",
    }


def normalize_phase2_external_predictor_requests(
    payloads: list[Any] | tuple[Any, ...] | None,
    *,
    allow_nonimplemented: bool = False,
) -> list[dict[str, Any]]:
    if payloads is None:
        return []
    if not isinstance(payloads, (list, tuple)):
        raise Phase2ExternalPredictorResolutionError(
            code="PHASE2_MALFORMED_EXTERNAL_PREDICTOR_REQUEST",
            requested=str(payloads),
            detail="external_predictors must be a list.",
        )
    return [
        normalize_phase2_external_predictor_request(
            item,
            allow_nonimplemented=allow_nonimplemented,
        )
        for item in payloads
    ]


def require_phase2_external_predictor_for_benchmark(payload: str | dict[str, Any]) -> dict[str, Any]:
    try:
        return normalize_phase2_external_predictor_request(payload, allow_nonimplemented=False)
    except Phase2ExternalPredictorResolutionError as exc:
        raise Phase2ExternalPredictorBenchmarkModeError(requested=str(payload), cause=exc) from exc
