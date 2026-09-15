from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.contracts.phase3_external_predictors import (
    Phase3ExternalPredictorEntry,
    list_phase3_external_predictors,
    normalize_phase3_external_predictor_requests,
    resolve_phase3_external_predictor_request,
)
from sok_llm_orchestrator.external_predictors.megnet_loader import (
    get_config_path,
    get_model_path,
    load_megnet_model,
)


class MEGNetAdapterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StructureHandoff:
    ok: bool
    source: str | None
    cif_path: str | None
    structure_type: str | None
    formula: str | None
    site_count: int | None
    lattice_volume: float | None
    error_code: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "source": self.source,
            "cif_path": self.cif_path,
            "structure_type": self.structure_type,
            "formula": self.formula,
            "site_count": self.site_count,
            "lattice_volume": self.lattice_volume,
            "error_code": self.error_code,
            "error": self.error,
        }


class MEGNetStructureInputError(MEGNetAdapterError):
    def __init__(self, *, code: str, message: str, handoff: StructureHandoff) -> None:
        super().__init__(message)
        self.code = code
        self.handoff = handoff


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def _entry_by_id() -> dict[str, Phase3ExternalPredictorEntry]:
    return {
        item.id: item
        for item in list_phase3_external_predictors(include_nonimplemented=True)
    }


def _structure_formula(structure: Any) -> str | None:
    composition = getattr(structure, "composition", None)
    formula = getattr(composition, "reduced_formula", None)
    return str(formula) if isinstance(formula, str) and formula else None


def _structure_type_name(structure: Any) -> str:
    return f"{type(structure).__module__}.{type(structure).__name__}"


def _raise_structure_input_error(
    *,
    code: str,
    message: str,
    source: str | None,
    cif_path: str | None,
    structure: Any | None = None,
) -> None:
    formula = _structure_formula(structure) if structure is not None else None
    site_count = None
    lattice_volume = None
    if structure is not None:
        try:
            site_count = int(len(structure))
        except Exception:  # noqa: BLE001
            site_count = None
        try:
            lattice_volume = float(structure.lattice.volume)
        except Exception:  # noqa: BLE001
            lattice_volume = None
    handoff = StructureHandoff(
        ok=False,
        source=source,
        cif_path=cif_path,
        structure_type=_structure_type_name(structure) if structure is not None else None,
        formula=formula,
        site_count=site_count,
        lattice_volume=lattice_volume,
        error_code=code,
        error=message,
    )
    raise MEGNetStructureInputError(code=code, message=message, handoff=handoff)


def _validate_structure_object(structure: Any, *, source: str, cif_path: str | None) -> tuple[Any, StructureHandoff]:
    try:
        from pymatgen.core import Structure as PymatgenStructure
    except Exception as exc:  # pragma: no cover - optional dependency import failure
        _raise_structure_input_error(
            code="MEGNET_PYMATGEN_UNAVAILABLE",
            message=f"pymatgen is required for MEGNet structure input validation: {exc}",
            source=source,
            cif_path=cif_path,
        )
    if not isinstance(structure, PymatgenStructure):
        _raise_structure_input_error(
            code="MEGNET_STRUCTURE_OBJECT_INVALID",
            message=f"MEGNet predictors require a pymatgen.Structure, got {_structure_type_name(structure)}",
            source=source,
            cif_path=cif_path,
            structure=structure,
        )
    try:
        site_count = int(len(structure))
    except Exception as exc:  # noqa: BLE001
        _raise_structure_input_error(
            code="MEGNET_STRUCTURE_OBJECT_INVALID",
            message=f"Could not determine structure site count: {exc}",
            source=source,
            cif_path=cif_path,
            structure=structure,
        )
    if site_count <= 0:
        _raise_structure_input_error(
            code="MEGNET_STRUCTURE_INCOMPLETE",
            message="MEGNet structure input has no atomic sites.",
            source=source,
            cif_path=cif_path,
            structure=structure,
        )
    try:
        lattice_volume = float(structure.lattice.volume)
    except Exception as exc:  # noqa: BLE001
        _raise_structure_input_error(
            code="MEGNET_STRUCTURE_OBJECT_INVALID",
            message=f"Could not inspect structure lattice: {exc}",
            source=source,
            cif_path=cif_path,
            structure=structure,
        )
    if lattice_volume <= 0.0:
        _raise_structure_input_error(
            code="MEGNET_STRUCTURE_INCOMPLETE",
            message="MEGNet structure input has non-positive lattice volume.",
            source=source,
            cif_path=cif_path,
            structure=structure,
        )
    formula = _structure_formula(structure)
    if formula is None:
        _raise_structure_input_error(
            code="MEGNET_STRUCTURE_INCOMPLETE",
            message="MEGNet structure input has no reduced_formula.",
            source=source,
            cif_path=cif_path,
            structure=structure,
        )
    return structure, StructureHandoff(
        ok=True,
        source=source,
        cif_path=cif_path,
        structure_type=_structure_type_name(structure),
        formula=formula,
        site_count=site_count,
        lattice_volume=lattice_volume,
    )


def _read_cif_text(cif_path: str | None) -> tuple[Path, str]:
    if not isinstance(cif_path, str) or not cif_path.strip():
        _raise_structure_input_error(
            code="MEGNET_STRUCTURE_INPUT_MISSING",
            message="MEGNet predictors require a parseable CIF artifact or a pymatgen.Structure input.",
            source=None,
            cif_path=cif_path,
        )
    path = Path(cif_path)
    if not path.is_file():
        _raise_structure_input_error(
            code="MEGNET_CIF_PATH_MISSING",
            message=f"MEGNet CIF input does not exist: {cif_path}",
            source="cif_path",
            cif_path=cif_path,
        )
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        _raise_structure_input_error(
            code="MEGNET_CIF_READ_FAILED",
            message=f"Could not read MEGNet CIF input: {cif_path}: {exc}",
            source="cif_path",
            cif_path=cif_path,
        )
    return path, text


def _assert_cif_looks_structural(cif_path: str | None, text: str) -> None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    meaningful_lines = [line for line in lines if not line.startswith("#")]
    if not meaningful_lines:
        _raise_structure_input_error(
            code="MEGNET_CIF_PARSE_FAILED",
            message="MEGNet CIF input is empty.",
            source="cif_path",
            cif_path=cif_path,
        )
    if not meaningful_lines[0].lower().startswith("data_"):
        _raise_structure_input_error(
            code="MEGNET_CIF_PARSE_FAILED",
            message="MEGNet CIF input is not CIF-like: missing data_ header.",
            source="cif_path",
            cif_path=cif_path,
        )
    if len(meaningful_lines) == 1 and meaningful_lines[0] == "data_solution":
        _raise_structure_input_error(
            code="MEGNET_CIF_STRUCTURALLY_INCOMPLETE",
            message="MEGNet CIF input is placeholder-only and contains no atomic sites.",
            source="cif_path",
            cif_path=cif_path,
        )
    has_atom_sites = any("_atom_site_" in line.lower() for line in meaningful_lines)
    if not has_atom_sites:
        _raise_structure_input_error(
            code="MEGNET_CIF_STRUCTURALLY_INCOMPLETE",
            message="MEGNet CIF input is missing atom-site fields required for a structure handoff.",
            source="cif_path",
            cif_path=cif_path,
        )


def _structure_from_cif(cif_path: str | None) -> tuple[Any, StructureHandoff]:
    _, text = _read_cif_text(cif_path)
    _assert_cif_looks_structural(cif_path, text)
    try:
        from pymatgen.core import Structure
    except Exception as exc:  # pragma: no cover - optional dependency import failure
        _raise_structure_input_error(
            code="MEGNET_PYMATGEN_UNAVAILABLE",
            message=f"pymatgen is required to parse CIF input: {exc}",
            source="cif_path",
            cif_path=cif_path,
        )
    try:
        structure = Structure.from_file(str(Path(cif_path)))
    except Exception as exc:  # noqa: BLE001
        _raise_structure_input_error(
            code="MEGNET_CIF_PARSE_FAILED",
            message=f"Could not parse CIF as pymatgen Structure: {cif_path}: {exc}",
            source="cif_path",
            cif_path=cif_path,
        )
    return _validate_structure_object(structure, source="cif_path", cif_path=cif_path)


def _coerce_structure(structure: Any | None, cif_path: str | None) -> tuple[Any, StructureHandoff]:
    if structure is not None:
        return _validate_structure_object(structure, source="pymatgen_structure", cif_path=cif_path)
    return _structure_from_cif(cif_path)


def _as_scalar(value: Any) -> float:
    try:
        item = value.item()
    except AttributeError:
        item = value
    except ValueError:
        item = value
    if isinstance(item, (list, tuple)) and item:
        return _as_scalar(item[0])
    try:
        return float(item)
    except TypeError:
        try:
            return float(value[0])
        except Exception as exc:  # noqa: BLE001
            raise MEGNetAdapterError(f"MEGNet prediction was not scalar: {value!r}") from exc


def _predict_raw(model: Any, structure: Any) -> float:
    if hasattr(model, "predict_structure"):
        return _as_scalar(model.predict_structure(structure))
    prediction = model.predict([structure])
    return _as_scalar(prediction[0])


def _prediction_core(entry: Phase3ExternalPredictorEntry, structure: Any) -> dict[str, Any]:
    model = load_megnet_model(entry.backend_model_id)
    return {
        "value": _predict_raw(model, structure),
        "model_path": get_model_path(entry.backend_model_id),
        "config_path": get_config_path(entry.backend_model_id),
    }


def _build_prediction(
    *,
    request: dict[str, Any],
    entry: Phase3ExternalPredictorEntry,
    structure: Any,
    cif_path: str | None,
    structure_handoff: StructureHandoff,
) -> dict[str, Any]:
    core = _prediction_core(entry, structure)
    transform_applied = None
    input_formula = structure_handoff.formula
    provenance = {
        "backend": entry.backend,
        "backend_version": entry.backend_version,
        "predictor_id": entry.id,
        "backend_model_id": entry.backend_model_id,
        "model_version": entry.backend_model_id,
        "resolved_model_path": str(core["model_path"]),
        "resolved_config_path": str(core["config_path"]),
        "adapter_name": "megnet_graphmodel_structure_adapter",
        "estimate_source": "pretrained_megnet_materials_project_model",
        "target": request["target"],
        "unit": entry.unit,
        "value_state": entry.value_state,
        "raw_output_semantics": entry.raw_output_semantics,
        "calibration_applied": False,
        "normalization_applied": False,
        "transformation_applied": False,
        "transform_applied": transform_applied,
        "dft_label_provenance_note": entry.dft_label_provenance_note,
        "calibration_status": entry.calibration_status,
        "validation_status": entry.validation_status,
        "benchmark_approval_flag": bool(entry.benchmark_approved),
        "exploratory_status": bool(entry.exploratory_only),
        "input_structure_source": structure_handoff.source,
        "input_structure_site_count": structure_handoff.site_count,
        "input_structure_lattice_volume": structure_handoff.lattice_volume,
    }
    return {
        "schema_version": "phase3.external_prediction.v1",
        "predictor_id": entry.id,
        "target": request["target"],
        "value": float(core["value"]),
        "value_state": entry.value_state,
        "unit": entry.unit,
        "prediction_type": entry.prediction_type,
        "optimization_direction": entry.optimization_direction,
        "use": request.get("use", "reporting"),
        "input": {
            "input_type": entry.input_type,
            "formula": input_formula,
            "cif_path": cif_path,
        },
        "structure_handoff": structure_handoff.to_dict(),
        "provenance": provenance,
        "calibration": {
            "calibration_status": entry.calibration_status,
            "validation_status": entry.validation_status,
            "benchmark_approved": bool(entry.benchmark_approved),
            "exploratory_only": bool(entry.exploratory_only),
            "known_domain_limits": list(entry.known_domain_limits),
        },
        "modulus_semantics": dict(entry.modulus_semantics) if entry.modulus_semantics else None,
        "native_phase1_objective": False,
        "model_file": str(core["model_path"]),
        "config_file": str(core["config_path"]),
        "dft_label_provenance": entry.dft_label_provenance_note,
    }


def _single_adapter_result(predictor_id: str, structure: Any) -> dict[str, Any]:
    entry = resolve_phase3_external_predictor_request(predictor_id)
    validated_structure, structure_handoff = _validate_structure_object(
        structure,
        source="pymatgen_structure",
        cif_path=None,
    )
    request = {
        "schema_version": "phase3.external_predictor_request.v1",
        "predictor_id": entry.id,
        "target": entry.supported_targets[0],
        "use": "reporting",
        "value_state": entry.value_state,
    }
    prediction = _build_prediction(
        request=request,
        entry=entry,
        structure=validated_structure,
        cif_path=None,
        structure_handoff=structure_handoff,
    )
    return {
        "value": prediction["value"],
        "provenance": prediction["provenance"],
        "unit": prediction["unit"],
        "value_state": prediction["value_state"],
        "modulus_semantics": prediction["modulus_semantics"],
    }


def megnet_formation_energy(structure: Any) -> dict[str, Any]:
    return _single_adapter_result("phase3.external.megnet_formation_energy", structure)


def megnet_band_gap(structure: Any) -> dict[str, Any]:
    return _single_adapter_result("phase3.external.megnet_band_gap", structure)


def megnet_bulk_modulus(structure: Any) -> dict[str, Any]:
    return _single_adapter_result("phase3.external.megnet_bulk_modulus", structure)


def megnet_shear_modulus(structure: Any) -> dict[str, Any]:
    return _single_adapter_result("phase3.external.megnet_shear_modulus", structure)


def run_external_megnet_predictors(
    requests: list[Any] | tuple[Any, ...] | None,
    *,
    structure: Any | None = None,
    cif_path: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_phase3_external_predictor_requests(requests)
    structure_handoff = StructureHandoff(
        ok=True,
        source=None,
        cif_path=cif_path,
        structure_type=None,
        formula=None,
        site_count=None,
        lattice_volume=None,
    )
    context_structure = structure
    if normalized:
        try:
            context_structure, structure_handoff = _coerce_structure(structure, cif_path)
        except MEGNetStructureInputError as exc:
            return {
                "schema_version": "phase3.external_predictions.v1",
                "native_phase1_objective": False,
                "requests": normalized,
                "structure_handoff": exc.handoff.to_dict(),
                "predictions": [],
                "errors": [
                    {
                        "predictor_id": str(request.get("predictor_id")),
                        "target": request.get("target"),
                        "error_code": exc.code,
                        "error": str(exc),
                        "structure_handoff": exc.handoff.to_dict(),
                    }
                    for request in normalized
                ],
                "ok": False,
            }
    entries = _entry_by_id()
    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for request in normalized:
        predictor_id = str(request["predictor_id"])
        entry = entries[predictor_id]
        try:
            predictions.append(
                _build_prediction(
                    request=request,
                    entry=entry,
                    structure=context_structure,
                    cif_path=cif_path,
                    structure_handoff=structure_handoff,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "predictor_id": predictor_id,
                    "target": request.get("target"),
                    "error_code": exc.code if hasattr(exc, "code") else "MEGNET_PREDICTION_FAILED",
                    "error": str(exc),
                    "structure_handoff": structure_handoff.to_dict(),
                }
            )
    return {
        "schema_version": "phase3.external_predictions.v1",
        "native_phase1_objective": False,
        "requests": normalized,
        "structure_handoff": structure_handoff.to_dict(),
        "predictions": predictions,
        "errors": errors,
        "ok": not errors,
    }


__all__ = [
    "MEGNetAdapterError",
    "megnet_band_gap",
    "megnet_bulk_modulus",
    "megnet_formation_energy",
    "megnet_shear_modulus",
    "run_external_megnet_predictors",
]
