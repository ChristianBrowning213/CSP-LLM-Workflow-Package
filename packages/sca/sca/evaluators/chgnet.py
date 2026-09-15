"""Optional CHGNet static-energy benchmark evaluator."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from sca.evaluators.cif_parse import parse_cif
from sca.schemas import BenchmarkEvaluatorResult


class ChgnetStaticBenchmarkEvaluator:
    name = "chgnet_static"
    description = "Optional CHGNet static surrogate-energy prediction."

    def evaluate_path(self, cif_path: str | Path) -> BenchmarkEvaluatorResult:
        structure, parse = parse_cif(cif_path)
        if structure is None:
            return _result(
                ok=False,
                summary="parse failed",
                error_type=parse.error_type,
                error_message=parse.error_message,
            )

        try:
            model = _load_chgnet_model()
        except Exception as exc:
            return _result(
                ok=False,
                skipped=True,
                summary="unavailable",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        try:
            prediction = model.predict_structure(structure)
            energy_per_atom = _extract_energy_per_atom(prediction, len(structure))
            forces_max = _extract_forces_max(prediction)
            forces_mean = _extract_forces_mean(prediction)
            stress_norm = _extract_stress_norm(prediction)
        except Exception as exc:
            return _result(
                ok=False,
                summary="failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        return _result(
            ok=True,
            summary="ok",
            model=getattr(model, "__class__", type(model)).__name__,
            energy_per_atom=energy_per_atom,
            forces_max=forces_max,
            forces_mean=forces_mean,
            stress_norm=stress_norm,
        )


def _load_chgnet_model():
    try:
        from chgnet.model.model import CHGNet
    except Exception as exc:
        raise RuntimeError("CHGNet is unavailable. Install chgnet to use chgnet_static.") from exc
    return CHGNet.load()


def _result(
    ok: bool,
    summary: str,
    model: str | None = None,
    energy_per_atom: float | None = None,
    forces_max: float | None = None,
    forces_mean: float | None = None,
    stress_norm: float | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    skipped: bool = False,
) -> BenchmarkEvaluatorResult:
    return BenchmarkEvaluatorResult(
        name=ChgnetStaticBenchmarkEvaluator.name,
        ok=ok,
        skipped=skipped,
        model=model,
        summary=summary,
        metrics={
            "chgnet_ok": ok,
            "chgnet_model": model,
            "chgnet_energy_per_atom": energy_per_atom,
            "chgnet_forces_max": forces_max,
            "chgnet_forces_mean": forces_mean,
            "chgnet_stress_norm": stress_norm,
            "chgnet_error": error_message,
        },
        flags={"chgnet_ok": ok},
        error_type=error_type,
        error_message=error_message,
    )


def _extract_energy_per_atom(prediction: Any, n_sites: int) -> float | None:
    value = _lookup(prediction, ("energy_per_atom", "e", "energy"))
    if value is None:
        return None
    scalar = _as_float(value)
    if scalar is None:
        return None
    if _has_key(prediction, "energy_per_atom") or _has_key(prediction, "e"):
        return scalar
    return scalar / n_sites if n_sites else scalar


def _extract_forces_max(prediction: Any) -> float | None:
    forces = _lookup(prediction, ("f", "forces"))
    if forces is None:
        return None
    rows = _to_rows(forces)
    if not rows:
        return None
    norms = [
        math.sqrt(sum(component * component for component in row))
        for row in rows
        if row
    ]
    return max(norms) if norms else None


def _extract_forces_mean(prediction: Any) -> float | None:
    forces = _lookup(prediction, ("f", "forces"))
    rows = _to_rows(forces) if forces is not None else []
    norms = [math.sqrt(sum(component * component for component in row)) for row in rows if row]
    return sum(norms) / len(norms) if norms else None


def _extract_stress_norm(prediction: Any) -> float | None:
    stress = _lookup(prediction, ("s", "stress"))
    if stress is None:
        return None
    if hasattr(stress, "detach"):
        stress = stress.detach()
    if hasattr(stress, "cpu"):
        stress = stress.cpu()
    if hasattr(stress, "tolist"):
        stress = stress.tolist()
    values = []
    for value in stress:
        if isinstance(value, list | tuple):
            values.extend(float(component) for component in value)
        else:
            values.append(float(value))
    return math.sqrt(sum(value * value for value in values)) if values else None


def _lookup(prediction: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(prediction, dict):
        for key in keys:
            if key in prediction:
                return prediction[key]
    for key in keys:
        if hasattr(prediction, key):
            return getattr(prediction, key)
    return None


def _has_key(prediction: Any, key: str) -> bool:
    if isinstance(prediction, dict):
        return key in prediction
    return hasattr(prediction, key)


def _as_float(value: Any) -> float | None:
    if hasattr(value, "item"):
        value = value.item()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_rows(value: Any) -> list[list[float]]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    rows = []
    for row in value:
        if hasattr(row, "tolist"):
            row = row.tolist()
        try:
            rows.append([float(component) for component in row])
        except TypeError:
            continue
    return rows
