"""Deterministic intent-satisfaction evaluator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pymatgen.analysis.local_env import CrystalNN
from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sca.evaluators.cif_parse import parse_cif
from sca.evaluators.geometry import evaluate_geometry
from sca.schemas import BenchmarkEvaluatorResult


NOT_COMPUTABLE = "not_computable"


class IntentSatisfactionBenchmarkEvaluator:
    name = "intent_satisfaction"
    description = "Deterministically checks whether a generated CIF satisfies manifest intent constraints."

    def evaluate_row(self, row: dict[str, Any]) -> BenchmarkEvaluatorResult:
        metrics = {key: NOT_COMPUTABLE for key in _metric_keys()}
        metrics["intent_failure_reasons"] = ""
        metrics["intent_satisfaction_error"] = None
        try:
            structure, parse_result = parse_cif(_input_path(row))
            constraints = _constraints(row)
            expected_status = str(constraints.get("expected_solver_status") or "").strip()
            if structure is None:
                status_ok = _expected_invalid_ok(expected_status, row)
                metrics.update(
                    {
                        "intent_formula_satisfied": False,
                        "intent_expected_solver_status_satisfied": status_ok,
                        "intent_satisfaction_rate": 1.0 if status_ok else 0.0,
                        "intent_satisfaction_score": 1.0 if status_ok else 0.0,
                        "intent_failure_reasons": "invalid_or_missing_cif" if not status_ok else "",
                        "intent_satisfaction_error": parse_result.error_message,
                    }
                )
                return _result(metrics)

            formula_ok = _formula_matches(structure, _target(row, constraints, "formula", "target_formula"))
            family_ok = _family_matches(row, constraints)
            sg_ok, system_ok = _space_group_matches(structure, row, constraints)
            motif_ok, coordination_ok, connectivity_ok = _motif_checks(structure, row, constraints)
            min_ok, forbidden_ok = _distance_checks(structure, row, constraints)
            solver_ok = _solver_status_ok(expected_status, row, has_cif=True)
            metrics.update(
                {
                    "intent_formula_satisfied": formula_ok,
                    "intent_family_satisfied": family_ok,
                    "intent_space_group_satisfied": sg_ok,
                    "intent_crystal_system_satisfied": system_ok,
                    "intent_motif_satisfied": motif_ok,
                    "intent_coordination_satisfied": coordination_ok,
                    "intent_connectivity_satisfied": connectivity_ok,
                    "intent_min_distance_satisfied": min_ok,
                    "intent_forbidden_contacts_satisfied": forbidden_ok,
                    "intent_expected_solver_status_satisfied": solver_ok,
                }
            )
            score, rate, reasons = _score(metrics)
            metrics["intent_satisfaction_rate"] = rate
            metrics["intent_satisfaction_score"] = score
            metrics["intent_failure_reasons"] = "; ".join(reasons)
        except Exception as exc:
            metrics["intent_satisfaction_error"] = f"{type(exc).__name__}: {exc}"
            metrics["intent_satisfaction_score"] = 0.0
            metrics["intent_satisfaction_rate"] = 0.0
            return BenchmarkEvaluatorResult(name=self.name, ok=False, summary="failed", metrics=metrics, error_type=type(exc).__name__, error_message=str(exc))
        return _result(metrics)


class CifParseBenchmarkEvaluator:
    name = "cif_parse"
    description = "Standalone CIF parse evaluator alias for benchmark-cif-set."

    def evaluate_item(self, item: dict[str, Any]) -> BenchmarkEvaluatorResult:
        _, result = parse_cif(item["path"])
        metrics = result.model_dump()
        return BenchmarkEvaluatorResult(name=self.name, ok=bool(result.parse_ok), summary="parsed" if result.parse_ok else "parse_failed", metrics=metrics)


class GeometryBenchmarkEvaluator:
    name = "geometry"
    description = "Standalone basic geometry evaluator alias for benchmark-cif-set."

    def evaluate_item(self, item: dict[str, Any]) -> BenchmarkEvaluatorResult:
        structure, parse_result = parse_cif(item["path"])
        if structure is None:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="not_computable",
                metrics={"geometry_ok": NOT_COMPUTABLE, "geometry_error": parse_result.error_message},
            )
        result = evaluate_geometry(structure)
        return BenchmarkEvaluatorResult(name=self.name, ok=bool(result.geometry_ok), summary="ok" if result.geometry_ok else "failed", metrics=result.model_dump())


def _metric_keys() -> list[str]:
    return [
        "intent_formula_satisfied",
        "intent_family_satisfied",
        "intent_space_group_satisfied",
        "intent_crystal_system_satisfied",
        "intent_motif_satisfied",
        "intent_coordination_satisfied",
        "intent_connectivity_satisfied",
        "intent_min_distance_satisfied",
        "intent_forbidden_contacts_satisfied",
        "intent_expected_solver_status_satisfied",
        "intent_satisfaction_rate",
        "intent_satisfaction_score",
    ]


def _input_path(row: dict[str, Any]) -> str:
    return str(row.get("input_path") or row.get("cif_path") or "")


def _constraints(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("intent_constraints_json")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return {}


def _target(row: dict[str, Any], constraints: dict[str, Any], constraint_key: str, row_key: str) -> str:
    return str(constraints.get(constraint_key) or row.get(row_key) or "").strip()


def _formula_matches(structure: Structure, target: str) -> bool | str:
    if not target:
        return NOT_COMPUTABLE
    try:
        observed = structure.composition.reduced_composition
        expected = Composition(target).reduced_composition
        return observed.almost_equals(expected)
    except Exception:
        return NOT_COMPUTABLE


def _family_matches(row: dict[str, Any], constraints: dict[str, Any]) -> bool | str:
    target = _target(row, constraints, "structure_family", "target_structure_family").lower()
    if not target:
        return NOT_COMPUTABLE
    text = " ".join(
        str(row.get(key) or "")
        for key in ("target_structure_family", "input_text", "expected_family_terms", "expected_motifs_or_priors")
    ).lower()
    aliases = {
        "halide perovskite": "perovskite",
        "oxide perovskite": "perovskite",
        "olivine phosphate": "olivine",
        "layered oxide": "layered",
    }
    needle = aliases.get(target, target)
    return needle in text or target in text


def _space_group_matches(structure: Structure, row: dict[str, Any], constraints: dict[str, Any]) -> tuple[bool | str, bool | str]:
    try:
        analyzer = SpacegroupAnalyzer(structure, symprec=0.1)
        symbol = analyzer.get_space_group_symbol()
        system = analyzer.get_crystal_system()
    except Exception:
        return NOT_COMPUTABLE, NOT_COMPUTABLE
    target_sg = _target(row, constraints, "space_group", "target_space_group").lower()
    target_system = _target(row, constraints, "crystal_system", "target_crystal_system").lower()
    sg_ok: bool | str = NOT_COMPUTABLE
    system_ok: bool | str = NOT_COMPUTABLE
    if target_sg:
        normalized_target = target_sg.replace(" ", "")
        normalized_symbol = symbol.lower().replace(" ", "")
        sg_ok = normalized_symbol in normalized_target or "subgroup" in target_sg
    if target_system:
        system_ok = system.lower() in target_system
    return sg_ok, system_ok


def _motif_checks(structure: Structure, row: dict[str, Any], constraints: dict[str, Any]) -> tuple[bool | str, bool | str, bool | str]:
    required = constraints.get("required_motifs") or []
    expected_motifs = " ".join(required if isinstance(required, list) else [str(required)]).lower()
    expected_coord = str(row.get("expected_coordination_terms") or "").lower()
    expected_connectivity = str(row.get("expected_connectivity_terms") or "").lower()
    if not expected_motifs and not expected_coord and not expected_connectivity:
        return NOT_COMPUTABLE, NOT_COMPUTABLE, NOT_COMPUTABLE
    elements = {str(element) for element in structure.composition.elements}
    motif_ok: bool | str = True
    if "dumbbell" in expected_motifs:
        motif_ok = any(element in elements for element in ("S", "Se", "Te"))
    coordination_ok: bool | str = NOT_COMPUTABLE
    try:
        cnn = CrystalNN()
        coords = [len(cnn.get_nn_info(structure, i)) for i in range(len(structure))]
        if "octa" in expected_coord or "6" in expected_coord:
            coordination_ok = any(value >= 5 for value in coords)
        elif "tetra" in expected_coord or "4" in expected_coord:
            coordination_ok = any(3 <= value <= 5 for value in coords)
    except Exception:
        coordination_ok = NOT_COMPUTABLE
    connectivity_ok: bool | str = True if expected_connectivity else NOT_COMPUTABLE
    return motif_ok, coordination_ok, connectivity_ok


def _distance_checks(structure: Structure, row: dict[str, Any], constraints: dict[str, Any]) -> tuple[bool | str, bool | str]:
    min_rules = constraints.get("min_distance_rules") or []
    forbidden = constraints.get("forbidden_contacts") or []
    distances = [distance for _, distance in structure.distance_matrix_as_dict().items()] if hasattr(structure, "distance_matrix_as_dict") else []
    if not distances:
        matrix = structure.distance_matrix
        distances = [float(matrix[i, j]) for i in range(len(structure)) for j in range(i + 1, len(structure))]
    min_distance = min(distances) if distances else None
    min_ok: bool | str = NOT_COMPUTABLE
    if min_rules:
        thresholds = [_float(rule.get("min_distance") or rule.get("distance") or rule.get("threshold")) for rule in min_rules if isinstance(rule, dict)]
        thresholds = [value for value in thresholds if value is not None]
        min_ok = min_distance is not None and (not thresholds or all(min_distance >= threshold for threshold in thresholds))
    elif row.get("min_distance") not in (None, ""):
        min_ok = _float(row.get("min_distance")) is not None
    forbidden_ok: bool | str = True if not forbidden else NOT_COMPUTABLE
    bad_contacts = row.get("num_bad_contacts") or row.get("bad_contact_count")
    if bad_contacts not in (None, ""):
        forbidden_ok = (_float(bad_contacts) or 0.0) == 0.0
    return min_ok, forbidden_ok


def _solver_status_ok(expected_status: str, row: dict[str, Any], *, has_cif: bool) -> bool | str:
    if not expected_status:
        return NOT_COMPUTABLE
    if expected_status == "expected_valid":
        return has_cif
    if expected_status == "expected_solver_backed_candidate":
        text = " ".join(str(row.get(key) or "") for key in ("solver_status", "raw_run_dir", "run_dir")).lower()
        return has_cif and ("solver" in text or text == "")
    if expected_status == "infeasible_or_invalid":
        return not has_cif or _expected_invalid_ok(expected_status, row)
    return NOT_COMPUTABLE


def _expected_invalid_ok(expected_status: str, row: dict[str, Any]) -> bool:
    if expected_status != "infeasible_or_invalid":
        return False
    run_dir = row.get("raw_run_dir") or row.get("run_dir")
    if run_dir and Path(str(run_dir)).exists():
        for path in Path(str(run_dir)).rglob("*.json"):
            try:
                text = path.read_text(encoding="utf-8").lower()
            except Exception:
                continue
            if "infeasible" in text or "invalid" in text:
                return True
    return False


def _score(metrics: dict[str, Any]) -> tuple[float, float, list[str]]:
    groups = [
        (0.30, ["intent_formula_satisfied"], "formula"),
        (0.20, ["intent_family_satisfied"], "family"),
        (0.15, ["intent_space_group_satisfied", "intent_crystal_system_satisfied"], "space_group_or_system"),
        (0.15, ["intent_motif_satisfied", "intent_coordination_satisfied", "intent_connectivity_satisfied"], "motif_coordination_connectivity"),
        (0.10, ["intent_min_distance_satisfied", "intent_forbidden_contacts_satisfied"], "distances_contacts"),
        (0.10, ["intent_expected_solver_status_satisfied"], "solver_status"),
    ]
    earned = 0.0
    denominator = 0.0
    checked = 0
    passed = 0
    reasons = []
    for weight, keys, label in groups:
        values = [metrics.get(key) for key in keys if metrics.get(key) != NOT_COMPUTABLE]
        if not values:
            reasons.append(f"{label}:not_computable")
            continue
        value = sum(1.0 if item is True else 0.0 for item in values) / len(values)
        earned += weight * value
        denominator += weight
        checked += len(values)
        passed += sum(1 for item in values if item is True)
        if value < 1.0:
            reasons.append(f"{label}:failed")
    score = earned / denominator if denominator else 0.0
    rate = passed / checked if checked else 0.0
    return float(score), float(rate), reasons


def _result(metrics: dict[str, Any]) -> BenchmarkEvaluatorResult:
    score = _float(metrics.get("intent_satisfaction_score")) or 0.0
    return BenchmarkEvaluatorResult(
        name="intent_satisfaction",
        ok=score >= 0.5,
        summary=f"score={score:.3f}",
        metrics=metrics,
    )


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
