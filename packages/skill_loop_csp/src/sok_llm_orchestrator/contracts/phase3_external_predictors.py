from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass
from typing import Any

from sok_llm_orchestrator.external_predictors.megnet_loader import megnet_loader_report

_IMPLEMENTATION_STATUS = {"implemented_now", "not_implemented", "adapter_scaffold"}
_OPTIMIZATION_DIRECTIONS = {"minimize", "maximize", "bounded", "feasibility"}
_INPUT_TYPES = {"structure"}
_PREDICTION_TYPES = {"property_surrogate"}
_REQUEST_USES = {"reporting", "selection_metric", "ranking"}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


class Phase3ExternalPredictorResolutionError(ValueError):
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


class Phase3ExternalPredictorBenchmarkModeError(ValueError):
    def __init__(self, *, requested: str, cause: Phase3ExternalPredictorResolutionError) -> None:
        self.requested = str(requested)
        self.cause = cause
        self.code = f"PHASE3_BENCHMARK_REJECTED_{cause.code}"
        super().__init__(f"{self.code}: {cause.detail}")


@dataclass(frozen=True, slots=True)
class Phase3ExternalPredictorEntry:
    id: str
    display_name: str
    backend: str
    backend_version: str
    backend_model_id: str
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
    unit: str
    value_state: str
    raw_output_semantics: str
    dft_label_provenance_note: str
    modulus_semantics: dict[str, Any] | None
    notes: str
    request_aliases: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "backend": self.backend,
            "backend_version": self.backend_version,
            "backend_model_id": self.backend_model_id,
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
            "unit": self.unit,
            "value_state": self.value_state,
            "raw_output_semantics": self.raw_output_semantics,
            "dft_label_provenance_note": self.dft_label_provenance_note,
            "modulus_semantics": dict(self.modulus_semantics) if self.modulus_semantics else None,
            "notes": self.notes,
            "request_aliases": list(self.request_aliases or []),
        }


_COMMON_PROVENANCE_REQUIREMENTS = [
    "backend",
    "backend_version",
    "predictor_id",
    "backend_model_id",
    "resolved_model_path",
    "resolved_config_path",
    "adapter_name",
    "input_structure",
    "target",
    "unit",
    "value_state",
    "raw_output_semantics",
    "transform_applied",
    "dft_label_provenance_note",
    "calibration_status",
    "validation_status",
    "benchmark_approval_flag",
    "exploratory_status",
]


def _megnet_entry(
    *,
    predictor_id: str,
    display_name: str,
    backend_model_id: str,
    target: str,
    unit: str,
    value_state: str,
    optimization_direction: str,
    raw_output_semantics: str,
    dft_label_provenance_note: str,
    modulus_semantics: dict[str, Any] | None,
    request_aliases: list[str],
    notes: str,
) -> Phase3ExternalPredictorEntry:
    return Phase3ExternalPredictorEntry(
        id=predictor_id,
        display_name=display_name,
        backend="megnet",
        backend_version=f"megnet={_version('megnet')}; tensorflow={_version('tensorflow')}",
        backend_model_id=backend_model_id,
        input_type="structure",
        prediction_type="property_surrogate",
        optimization_direction=optimization_direction,
        implementation_status="implemented_now",
        provenance_requirements=list(_COMMON_PROVENANCE_REQUIREMENTS),
        calibration_status="not_calibrated",
        validation_status="not_validated",
        known_domain_limits=[
            "Pretrained MEGNet model trained on Materials Project data.",
            "Requires a structure input; composition-only requests are rejected.",
            "No project-specific calibration is applied.",
            "No repository-local benchmark validation has been completed.",
            "Use as an external surrogate/reporting signal, not as a native Phase 1 objective.",
        ],
        benchmark_approved=False,
        exploratory_only=True,
        supported_targets=[target],
        unit=unit,
        value_state=value_state,
        raw_output_semantics=raw_output_semantics,
        dft_label_provenance_note=dft_label_provenance_note,
        modulus_semantics=modulus_semantics,
        request_aliases=request_aliases,
        notes=notes,
    )


def _registry() -> list[Phase3ExternalPredictorEntry]:
    return [
        _megnet_entry(
            predictor_id="phase3.external.megnet_formation_energy",
            display_name="MEGNet Formation Energy Predictor",
            backend_model_id="Eform_MP_2018",
            target="formation_energy",
            unit="eV/atom",
            value_state="raw",
            optimization_direction="minimize",
            raw_output_semantics="formation energy per atom in eV/atom",
            dft_label_provenance_note=(
                "MEGNet Eform_MP_2018 pretrained Materials Project formation-energy labels."
            ),
            modulus_semantics=None,
            request_aliases=["megnet_formation_energy", "formation_energy", "eform_mp_2018"],
            notes=(
                "Real adapter for pretrained MEGNet Eform_MP_2018. Output is raw formation "
                "energy per atom in eV/atom; no calibration, normalization, or postprocess transform."
            ),
        ),
        _megnet_entry(
            predictor_id="phase3.external.megnet_band_gap",
            display_name="MEGNet Band Gap Predictor",
            backend_model_id="Bandgap_MP_2018",
            target="band_gap",
            unit="eV",
            value_state="raw",
            optimization_direction="bounded",
            raw_output_semantics="band gap in eV",
            dft_label_provenance_note="MEGNet Bandgap_MP_2018 pretrained Materials Project band-gap labels.",
            modulus_semantics=None,
            request_aliases=["megnet_band_gap", "band_gap", "bandgap_mp_2018"],
            notes=(
                "Real adapter for pretrained MEGNet Bandgap_MP_2018. Output is raw band gap "
                "in eV; no calibration, normalization, or postprocess transform."
            ),
        ),
        _megnet_entry(
            predictor_id="phase3.external.megnet_bulk_modulus",
            display_name="MEGNet Bulk Modulus Predictor",
            backend_model_id="logK_MP_2018",
            target="bulk_modulus",
            unit="log10(GPa)",
            value_state="raw_log10",
            optimization_direction="bounded",
            raw_output_semantics="log10 bulk modulus K with modulus measured in GPa",
            dft_label_provenance_note="MEGNet logK_MP_2018 pretrained Materials Project elasticity labels.",
            modulus_semantics={
                "symbol": "K",
                "quantity": "bulk_modulus",
                "raw_model_output": "log10(K)",
                "linear_unit": "GPa",
                "postprocess_to_linear_gpa_applied": False,
            },
            request_aliases=["megnet_bulk_modulus", "bulk_modulus", "logk_mp_2018"],
            notes=(
                "Real adapter for pretrained MEGNet logK_MP_2018. Output remains raw "
                "log10(K) where K is in GPa; no exponentiation is applied."
            ),
        ),
        _megnet_entry(
            predictor_id="phase3.external.megnet_shear_modulus",
            display_name="MEGNet Shear Modulus Predictor",
            backend_model_id="logG_MP_2018",
            target="shear_modulus",
            unit="log10(GPa)",
            value_state="raw_log10",
            optimization_direction="bounded",
            raw_output_semantics="log10 shear modulus G with modulus measured in GPa",
            dft_label_provenance_note="MEGNet logG_MP_2018 pretrained Materials Project elasticity labels.",
            modulus_semantics={
                "symbol": "G",
                "quantity": "shear_modulus",
                "raw_model_output": "log10(G)",
                "linear_unit": "GPa",
                "postprocess_to_linear_gpa_applied": False,
            },
            request_aliases=["megnet_shear_modulus", "shear_modulus", "logg_mp_2018"],
            notes=(
                "Real adapter for pretrained MEGNet logG_MP_2018. Output remains raw "
                "log10(G) where G is in GPa; no exponentiation is applied."
            ),
        ),
    ]


def validate_phase3_external_predictor_registry() -> None:
    seen_ids: set[str] = set()
    for item in _registry():
        payload = item.to_dict()
        if payload["id"] in seen_ids:
            raise ValueError(f"Duplicate phase3 predictor id: {payload['id']}")
        seen_ids.add(payload["id"])
        if payload["implementation_status"] not in _IMPLEMENTATION_STATUS:
            raise ValueError(f"Invalid implementation_status for {payload['id']}")
        if payload["optimization_direction"] not in _OPTIMIZATION_DIRECTIONS:
            raise ValueError(f"Invalid optimization_direction for {payload['id']}")
        if payload["input_type"] not in _INPUT_TYPES:
            raise ValueError(f"Invalid input_type for {payload['id']}")
        if payload["prediction_type"] not in _PREDICTION_TYPES:
            raise ValueError(f"Invalid prediction_type for {payload['id']}")
        if not payload["backend_model_id"]:
            raise ValueError(f"backend_model_id must be non-empty for {payload['id']}")
        if not payload["provenance_requirements"]:
            raise ValueError(f"provenance_requirements must be non-empty for {payload['id']}")
        if not payload["supported_targets"]:
            raise ValueError(f"supported_targets must be non-empty for {payload['id']}")
        if not isinstance(payload["benchmark_approved"], bool):
            raise ValueError(f"benchmark_approved must be boolean for {payload['id']}")
        if not isinstance(payload["exploratory_only"], bool):
            raise ValueError(f"exploratory_only must be boolean for {payload['id']}")


def list_phase3_external_predictors(*, include_nonimplemented: bool = True) -> list[Phase3ExternalPredictorEntry]:
    validate_phase3_external_predictor_registry()
    items = _registry()
    if include_nonimplemented:
        return list(items)
    return [item for item in items if item.implementation_status == "implemented_now"]


def phase3_external_predictor_table(*, include_nonimplemented: bool = True) -> list[dict[str, Any]]:
    return [
        item.to_dict()
        for item in list_phase3_external_predictors(include_nonimplemented=include_nonimplemented)
    ]


def phase3_external_predictor_report() -> dict[str, Any]:
    table = phase3_external_predictor_table(include_nonimplemented=True)
    implemented = [row for row in table if row.get("implementation_status") == "implemented_now"]
    nonimplemented = [row for row in table if row.get("implementation_status") != "implemented_now"]
    return {
        "schema_version": "phase3.external_predictor_library.v1",
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
        "megnet_loader": megnet_loader_report(),
    }


def _build_alias_map() -> dict[str, Phase3ExternalPredictorEntry]:
    alias_map: dict[str, Phase3ExternalPredictorEntry] = {}
    for item in list_phase3_external_predictors(include_nonimplemented=True):
        aliases = [item.id, item.backend_model_id, *(item.request_aliases or [])]
        for alias in aliases:
            key = _norm(alias)
            if key:
                alias_map[key] = item
    return alias_map


def resolve_phase3_external_predictor_request(
    requested: str,
    *,
    allow_nonimplemented: bool = False,
) -> Phase3ExternalPredictorEntry:
    key = _norm(requested)
    item = _build_alias_map().get(key)
    if item is None:
        raise Phase3ExternalPredictorResolutionError(
            code="PHASE3_UNKNOWN_EXTERNAL_PREDICTOR",
            requested=requested,
            detail=f"Unknown Phase 3 external predictor request: {requested}",
            suggestions=[row.id for row in list_phase3_external_predictors(include_nonimplemented=False)],
        )
    if item.implementation_status != "implemented_now" and not allow_nonimplemented:
        raise Phase3ExternalPredictorResolutionError(
            code="PHASE3_EXTERNAL_PREDICTOR_NOT_IMPLEMENTED",
            requested=requested,
            detail=(
                f"Phase 3 external predictor '{requested}' maps to '{item.id}', "
                "which is not implemented in this repository."
            ),
            suggestions=[row.id for row in list_phase3_external_predictors(include_nonimplemented=False)],
        )
    return item


def normalize_phase3_external_predictor_request(
    payload: str | dict[str, Any],
    *,
    allow_nonimplemented: bool = False,
) -> dict[str, Any]:
    if isinstance(payload, str):
        raw: dict[str, Any] = {"predictor_id": payload}
    elif isinstance(payload, dict):
        raw = dict(payload)
    else:
        raise Phase3ExternalPredictorResolutionError(
            code="PHASE3_MALFORMED_EXTERNAL_PREDICTOR_REQUEST",
            requested=str(payload),
            detail="External predictor request must be a predictor id string or object.",
        )
    predictor_id = raw.get("predictor_id")
    if not isinstance(predictor_id, str) or not predictor_id.strip():
        raise Phase3ExternalPredictorResolutionError(
            code="PHASE3_MALFORMED_EXTERNAL_PREDICTOR_REQUEST",
            requested=str(raw),
            detail="External predictor request requires non-empty predictor_id.",
        )
    entry = resolve_phase3_external_predictor_request(
        predictor_id,
        allow_nonimplemented=allow_nonimplemented,
    )
    target = raw.get("target")
    if target is None:
        target = entry.supported_targets[0]
    if not isinstance(target, str) or target not in entry.supported_targets:
        raise Phase3ExternalPredictorResolutionError(
            code="PHASE3_UNSUPPORTED_EXTERNAL_PREDICTOR_TARGET",
            requested=predictor_id,
            detail=f"Unsupported target for {entry.id}: {target}",
            suggestions=list(entry.supported_targets),
        )
    use = raw.get("use", "reporting")
    if not isinstance(use, str) or use not in _REQUEST_USES:
        raise Phase3ExternalPredictorResolutionError(
            code="PHASE3_MALFORMED_EXTERNAL_PREDICTOR_REQUEST",
            requested=predictor_id,
            detail=f"External predictor use must be one of {sorted(_REQUEST_USES)}.",
        )
    return {
        "schema_version": "phase3.external_predictor_request.v1",
        "predictor_id": entry.id,
        "target": target,
        "use": use,
        "value_state": entry.value_state,
    }


def normalize_phase3_external_predictor_requests(
    payloads: list[Any] | tuple[Any, ...] | None,
    *,
    allow_nonimplemented: bool = False,
) -> list[dict[str, Any]]:
    if payloads is None:
        return []
    if not isinstance(payloads, (list, tuple)):
        raise Phase3ExternalPredictorResolutionError(
            code="PHASE3_MALFORMED_EXTERNAL_PREDICTOR_REQUEST",
            requested=str(payloads),
            detail="external_predictors must be a list.",
        )
    return [
        normalize_phase3_external_predictor_request(
            item,
            allow_nonimplemented=allow_nonimplemented,
        )
        for item in payloads
    ]


def require_phase3_external_predictor_for_benchmark(payload: str | dict[str, Any]) -> dict[str, Any]:
    try:
        return normalize_phase3_external_predictor_request(payload, allow_nonimplemented=False)
    except Phase3ExternalPredictorResolutionError as exc:
        raise Phase3ExternalPredictorBenchmarkModeError(requested=str(payload), cause=exc) from exc


def _adapter_result(function_name: str, structure: Any) -> dict[str, Any]:
    from sok_llm_orchestrator.external_predictors import megnet_adapters

    func = getattr(megnet_adapters, function_name)
    return func(structure)


def megnet_formation_energy(structure: Any) -> dict[str, Any]:
    return _adapter_result("megnet_formation_energy", structure)


def megnet_band_gap(structure: Any) -> dict[str, Any]:
    return _adapter_result("megnet_band_gap", structure)


def megnet_bulk_modulus(structure: Any) -> dict[str, Any]:
    return _adapter_result("megnet_bulk_modulus", structure)


def megnet_shear_modulus(structure: Any) -> dict[str, Any]:
    return _adapter_result("megnet_shear_modulus", structure)


__all__ = [
    "Phase3ExternalPredictorEntry",
    "Phase3ExternalPredictorResolutionError",
    "Phase3ExternalPredictorBenchmarkModeError",
    "validate_phase3_external_predictor_registry",
    "list_phase3_external_predictors",
    "phase3_external_predictor_table",
    "phase3_external_predictor_report",
    "resolve_phase3_external_predictor_request",
    "normalize_phase3_external_predictor_request",
    "normalize_phase3_external_predictor_requests",
    "require_phase3_external_predictor_for_benchmark",
    "megnet_formation_energy",
    "megnet_band_gap",
    "megnet_bulk_modulus",
    "megnet_shear_modulus",
]
