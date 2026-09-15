from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from typing import Any

from sok_llm_orchestrator.contracts.phase2_external_predictors import (
    Phase2ExternalPredictorResolutionError,
    Phase2ExternalPredictorEntry,
    list_phase2_external_predictors,
    normalize_phase2_external_predictor_request,
)
from sok_llm_orchestrator.contracts.phase3_external_predictors import (
    Phase3ExternalPredictorResolutionError,
    normalize_phase3_external_predictor_request,
)
from sok_llm_orchestrator.external_predictors.megnet_adapters import run_external_megnet_predictors


class ExternalPredictorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExternalPredictionContext:
    formula: str | None
    cif_path: str | None = None


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def _entry_by_id() -> dict[str, Phase2ExternalPredictorEntry]:
    return {
        item.id: item
        for item in list_phase2_external_predictors(include_nonimplemented=True)
    }


def normalize_external_predictor_request(
    payload: str | dict[str, Any],
    *,
    allow_nonimplemented: bool = False,
) -> dict[str, Any]:
    if isinstance(payload, str):
        predictor_id: Any = payload
    elif isinstance(payload, dict):
        predictor_id = payload.get("predictor_id")
    else:
        predictor_id = None
    if isinstance(predictor_id, str):
        if predictor_id.startswith("phase3."):
            return normalize_phase3_external_predictor_request(
                payload,
                allow_nonimplemented=allow_nonimplemented,
            )
        if predictor_id.startswith("phase2."):
            return normalize_phase2_external_predictor_request(
                payload,
                allow_nonimplemented=allow_nonimplemented,
            )
    phase2_error: Exception | None = None
    try:
        return normalize_phase2_external_predictor_request(
            payload,
            allow_nonimplemented=allow_nonimplemented,
        )
    except Phase2ExternalPredictorResolutionError as exc:
        phase2_error = exc
    try:
        return normalize_phase3_external_predictor_request(
            payload,
            allow_nonimplemented=allow_nonimplemented,
        )
    except Phase3ExternalPredictorResolutionError:
        if phase2_error is not None:
            raise phase2_error
        raise


def normalize_external_predictor_requests(
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
        normalize_external_predictor_request(
            item,
            allow_nonimplemented=allow_nonimplemented,
        )
        for item in payloads
    ]


def _pymatgen_composition_descriptor(
    request: dict[str, Any],
    context: ExternalPredictionContext,
    entry: Phase2ExternalPredictorEntry,
) -> dict[str, Any]:
    if not isinstance(context.formula, str) or not context.formula.strip():
        raise ExternalPredictorError("pymatgen composition descriptor requires a formula input.")
    try:
        from pymatgen.core import Composition, Element
    except Exception as exc:  # pragma: no cover - exercised only when environment changes
        raise ExternalPredictorError(f"pymatgen is not available: {exc}") from exc

    composition = Composition(context.formula)
    total_atoms = float(sum(composition.get_el_amt_dict().values()))
    if total_atoms <= 0.0:
        raise ExternalPredictorError(f"formula has no atoms: {context.formula}")

    target = str(request["target"])
    weighted = 0.0
    for symbol, amount in composition.get_el_amt_dict().items():
        element = Element(symbol)
        weight = float(amount) / total_atoms
        if target == "mean_atomic_number":
            component = float(element.Z)
        elif target == "mean_atomic_mass":
            component = float(element.atomic_mass)
        elif target == "mean_electronegativity":
            component = float(element.X) if element.X is not None else 0.0
        else:
            raise ExternalPredictorError(f"unsupported pymatgen descriptor target: {target}")
        weighted += weight * component

    return {
        "schema_version": "phase2.external_prediction.v1",
        "predictor_id": entry.id,
        "target": target,
        "value": float(weighted),
        "value_state": "raw",
        "unit": None,
        "prediction_type": entry.prediction_type,
        "optimization_direction": entry.optimization_direction,
        "use": request.get("use", "reporting"),
        "input": {
            "input_type": entry.input_type,
            "formula": context.formula,
            "cif_path": context.cif_path,
        },
        "provenance": {
            "backend": entry.backend,
            "backend_version": _package_version("pymatgen"),
            "predictor_id": entry.id,
            "model_version": "pymatgen-element-data",
            "adapter_name": "pymatgen_composition_descriptor",
            "estimate_source": "local_off_the_shelf_library",
            "target": target,
            "value_state": "raw",
            "calibration_applied": False,
            "normalization_applied": False,
            "transformation_applied": False,
        },
        "calibration": {
            "calibration_status": entry.calibration_status,
            "validation_status": entry.validation_status,
            "benchmark_approved": bool(entry.benchmark_approved),
            "exploratory_only": bool(entry.exploratory_only),
            "known_domain_limits": list(entry.known_domain_limits),
        },
        "native_phase1_objective": False,
    }


def run_external_predictors(
    requests: list[Any] | tuple[Any, ...] | None,
    *,
    formula: str | None,
    cif_path: str | None = None,
    structure: Any | None = None,
) -> dict[str, Any]:
    normalized = normalize_external_predictor_requests(requests)
    phase2_requests = [
        item
        for item in normalized
        if isinstance(item.get("schema_version"), str)
        and item["schema_version"].startswith("phase2.")
    ]
    phase3_requests = [
        item
        for item in normalized
        if isinstance(item.get("schema_version"), str)
        and item["schema_version"].startswith("phase3.")
    ]
    context = ExternalPredictionContext(formula=formula, cif_path=cif_path)
    entries = _entry_by_id()
    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for request in phase2_requests:
        predictor_id = str(request["predictor_id"])
        entry = entries[predictor_id]
        try:
            if predictor_id == "phase2.external.pymatgen_composition_descriptor":
                predictions.append(_pymatgen_composition_descriptor(request, context, entry))
            else:
                raise ExternalPredictorError(f"No adapter registered for {predictor_id}")
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "predictor_id": predictor_id,
                    "target": request.get("target"),
                    "error": str(exc),
                }
            )
    phase3_result = run_external_megnet_predictors(
        phase3_requests,
        structure=structure,
        cif_path=cif_path,
    )
    predictions.extend(
        item
        for item in phase3_result.get("predictions", [])
        if isinstance(item, dict)
    )
    errors.extend(
        item
        for item in phase3_result.get("errors", [])
        if isinstance(item, dict)
    )
    if phase2_requests and phase3_requests:
        schema_version = "external_predictions.v1"
    elif phase3_requests:
        schema_version = "phase3.external_predictions.v1"
    else:
        schema_version = "phase2.external_predictions.v1"
    payload = {
        "schema_version": schema_version,
        "native_phase1_objective": False,
        "requests": normalized,
        "predictions": predictions,
        "errors": errors,
        "ok": not errors,
    }
    if isinstance(phase3_result.get("structure_handoff"), dict):
        payload["phase3_structure_handoff"] = dict(phase3_result["structure_handoff"])
    return payload
