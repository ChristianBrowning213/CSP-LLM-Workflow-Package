"""Optional CHGNet relaxation evaluator for benchmark manifests."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.io.cif import CifWriter

from sca.evaluators.chgnet import (
    _extract_energy_per_atom,
    _extract_forces_max,
    _load_chgnet_model,
)
from sca.evaluators.cif_parse import parse_cif
from sca.schemas import BenchmarkEvaluatorResult


class ChgnetRelaxBenchmarkEvaluator:
    name = "chgnet_relax"
    description = "Optional CHGNet relaxation with before/after force, energy, and reference-match metrics."

    def __init__(
        self,
        fmax: float | None = None,
        steps: int | None = None,
        relax_cell: bool | None = None,
        out_dir: str | Path | None = None,
    ) -> None:
        self.fmax = fmax if fmax is not None else _float_env("SCA_CHGNET_RELAX_FMAX", 0.1)
        self.steps = steps if steps is not None else _int_env("SCA_CHGNET_RELAX_STEPS", 200)
        self.relax_cell = (
            relax_cell if relax_cell is not None else _bool_env("SCA_CHGNET_RELAX_CELL", True)
        )
        self.out_dir = Path(out_dir or os.environ.get("SCA_CHGNET_RELAX_OUT_DIR", "reports/chgnet_relaxed"))

    def evaluate_item(self, item: dict[str, Any]) -> BenchmarkEvaluatorResult:
        candidate_path = Path(item["path"])
        target_path = item.get("target_cif_path")
        reference_id = item.get("reference_id")
        mode = str(item.get("structure_match_mode") or "both").lower()

        if not target_path:
            return _result(
                ok=False,
                skipped=True,
                summary="no reference CIF",
                error_message="target_cif_path/reference_cif_path was not provided",
            )
        if mode not in {"exact", "anonymous", "both"}:
            return _result(
                ok=False,
                summary="invalid mode",
                error_type="ValueError",
                error_message=f"Unsupported structure match mode '{mode}'",
            )

        candidate, candidate_parse = parse_cif(candidate_path)
        if candidate is None:
            return _result(
                ok=False,
                summary="candidate parse failed",
                error_type=candidate_parse.error_type,
                error_message=candidate_parse.error_message,
            )
        target, target_parse = parse_cif(target_path)
        if target is None:
            return _result(
                ok=False,
                summary="reference parse failed",
                error_type=target_parse.error_type,
                error_message=target_parse.error_message,
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
            before_prediction = model.predict_structure(candidate)
            energy_before = _extract_energy_per_atom(before_prediction, len(candidate))
            force_before = _extract_forces_max(before_prediction)

            relaxed = _relax_structure(
                model=model,
                structure=candidate,
                fmax=self.fmax,
                steps=self.steps,
                relax_cell=self.relax_cell,
            )
            after_prediction = model.predict_structure(relaxed)
            energy_after = _extract_energy_per_atom(after_prediction, len(relaxed))
            force_after = _extract_forces_max(after_prediction)

            relaxed_path = self._write_relaxed_cif(candidate_path, item, relaxed)
            before_match = _match_metrics(candidate, target, mode)
            after_match = _match_metrics(relaxed, target, mode)
        except Exception as exc:
            return _result(
                ok=False,
                summary="failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        energy_drop = (
            energy_before - energy_after
            if energy_before is not None and energy_after is not None
            else None
        )
        relax_ok = force_after is not None and force_after <= self.fmax
        return _result(
            ok=bool(relax_ok),
            summary="relaxed" if relax_ok else "relaxed above force threshold",
            model=getattr(model, "__class__", type(model)).__name__,
            metrics={
                "relax_ok": bool(relax_ok),
                "relaxed_cif_path": str(relaxed_path),
                "relax_model": getattr(model, "__class__", type(model)).__name__,
                "relax_fmax": self.fmax,
                "relax_steps": self.steps,
                "relax_cell": self.relax_cell,
                "energy_before_per_atom": energy_before,
                "energy_after_per_atom": energy_after,
                "energy_drop_per_atom": energy_drop,
                "max_force_before": force_before,
                "max_force_after": force_after,
                "rms_dist_before": before_match["rms_dist"],
                "rms_dist_after": after_match["rms_dist"],
                "relaxed_rms_dist": after_match["rms_dist"],
                "max_dist_before": before_match["max_dist"],
                "max_dist_after": after_match["max_dist"],
                "structure_match_before": before_match["match"],
                "structure_match_after": after_match["match"],
                "relax_error": None,
            },
            flags={"relax_ok": bool(relax_ok), "structure_match_after": after_match["match"]},
            details={
                "reference_cif_path": str(target_path),
                "reference_id": reference_id,
                "mode": mode,
            },
        )

    def _write_relaxed_cif(self, candidate_path: Path, item: dict[str, Any], structure) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        label = item.get("benchmark_id") or candidate_path.stem
        attempt = item.get("attempt_id")
        suffix = f"_{attempt}" if attempt is not None and str(attempt).strip() else ""
        path = self.out_dir / f"{_safe_name(str(label))}{suffix}_chgnet_relaxed.cif"
        CifWriter(structure, symprec=0.1).write_file(path)
        return path


def _relax_structure(model, structure, fmax: float, steps: int, relax_cell: bool):
    from chgnet.model.dynamics import StructOptimizer

    relaxer = StructOptimizer(model=model)
    result = relaxer.relax(
        structure,
        fmax=fmax,
        steps=steps,
        relax_cell=relax_cell,
        verbose=False,
    )
    relaxed = result.get("final_structure") or result.get("structure")
    if relaxed is None:
        raise RuntimeError("CHGNet relaxation did not return a final structure")
    return relaxed


def _match_metrics(candidate, target, mode: str) -> dict[str, float | bool | None]:
    matcher = StructureMatcher(
        ltol=0.2,
        stol=0.3,
        angle_tol=5,
        primitive_cell=True,
        scale=True,
        attempt_supercell=True,
    )
    exact_match = matcher.fit(candidate, target) if mode in {"exact", "both"} else None
    anonymous_match = matcher.fit_anonymous(candidate, target) if mode in {"anonymous", "both"} else None
    matched = exact_match if mode == "exact" else anonymous_match if mode == "anonymous" else bool(exact_match or anonymous_match)
    rms_dist = None
    max_dist = None
    if matched:
        distances = matcher.get_rms_dist(candidate, target)
        if distances is not None:
            rms_dist, max_dist = distances
    return {
        "match": bool(matched),
        "rms_dist": float(rms_dist) if rms_dist is not None else None,
        "max_dist": float(max_dist) if max_dist is not None else None,
    }


def _result(
    ok: bool,
    summary: str,
    model: str | None = None,
    metrics: dict[str, Any] | None = None,
    flags: dict[str, bool | None] | None = None,
    details: dict[str, Any] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    skipped: bool = False,
) -> BenchmarkEvaluatorResult:
    base_metrics = {
        "relax_ok": ok if not skipped else False,
        "relax_error": error_message,
    }
    if metrics:
        base_metrics.update(metrics)
    return BenchmarkEvaluatorResult(
        name=ChgnetRelaxBenchmarkEvaluator.name,
        ok=ok,
        skipped=skipped,
        model=model,
        summary=summary,
        metrics=base_metrics,
        flags=flags or {"relax_ok": ok if not skipped else False},
        details=details or {},
        error_type=error_type,
        error_message=error_message,
    )


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "relaxed"


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
