"""Post-relaxation crystallographic and intent-retention evaluator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sca.evaluators.bonds import evaluate_bonds
from sca.evaluators.geometry import evaluate_geometry
from sca.evaluators.topology import family_topology_metrics
from sca.schemas import BenchmarkEvaluatorResult
from sca.structure_transition import analyse_structure_transition


FAMILY_POLICIES = {
    "rocksalt": "ROCKSALT",
    "nitride": "ROCKSALT",
    "fluorite": "FLUORITE",
    "perovskite": "PEROVSKITE_3D",
    "halide perovskite": "HALIDE_PEROVSKITE_3D",
    "spinel": "SPINEL",
    "olivine phosphate": "OLIVINE",
    "layered oxide": "LAYERED_OXIDE",
    "layered": "LAYERED_OXIDE",
    "argyrodite": "ARGYRODITE_ORDERED",
}


class RelaxationIntentRetentionEvaluator:
    name = "relaxation_intent_retention"
    description = "Generated-to-relaxed structural change and crystallographic intent retention."

    def evaluate_item(self, item: dict[str, Any]) -> BenchmarkEvaluatorResult:
        initial_path = Path(item.get("initial_cif_path") or item.get("path") or item.get("cif_path") or "")
        relaxed_raw = item.get("relaxed_cif_path") or item.get("final_cif_path")
        if not relaxed_raw:
            return _result("NOT_EVALUATED", {}, skipped=True, error="relaxed_cif_path was not provided")
        relaxed_path = Path(relaxed_raw)
        if not initial_path.is_file() or not relaxed_path.is_file():
            return _result("FAILED_RELAXATION", {}, error="initial or relaxed CIF does not exist")
        try:
            initial = Structure.from_file(initial_path)
            relaxed = Structure.from_file(relaxed_path)
            transition = analyse_structure_transition(initial_path, relaxed_path)
            initial_symmetry = SpacegroupAnalyzer(initial)
            relaxed_symmetry = SpacegroupAnalyzer(relaxed)
            initial_sg = initial_symmetry.get_space_group_symbol()
            relaxed_sg = relaxed_symmetry.get_space_group_symbol()
            requested = _optional(item.get("target_space_group"))
            require_sg = _as_bool(item.get("require_space_group")) is True
            target_family = _optional(item.get("target_family") or item.get("target_structure_family"))
            policy = _optional(item.get("topology_policy")) or FAMILY_POLICIES.get((target_family or "").lower())
            if policy:
                initial_family, _ = family_topology_metrics(initial, policy)
                relaxed_family, _ = family_topology_metrics(relaxed, policy)
                initial_family_status = initial_family["topology_status"]
                relaxed_family_status = relaxed_family["topology_status"]
                family_retained = initial_family_status == "PASS" and relaxed_family_status == "PASS"
            else:
                initial_family_status = relaxed_family_status = "NOT_EVALUATED"
                family_retained = None
            geometry = evaluate_geometry(relaxed)
            bonds = evaluate_bonds(relaxed)
            composition_retained = initial.composition == relaxed.composition
            site_count_retained = len(initial) == len(relaxed)
            sg_retained = initial_sg == relaxed_sg
            severe_contacts = bonds.num_bad_contacts > 0
            volume_pathological = transition.volume_change_pct is not None and abs(transition.volume_change_pct) > float(item.get("collapse_volume_change_pct", 35.0))
            core_valid = composition_retained and site_count_retained and geometry.geometry_ok is True and not severe_contacts
            topology_lost = family_retained is False
            if not core_valid or topology_lost or volume_pathological or not transition.mapping_succeeded:
                overall = "COLLAPSED"
            elif family_retained in {True, None} and (sg_retained or not require_sg):
                overall = "ROBUST"
            else:
                overall = "MODIFIED_BUT_VALID"
            metrics = {
                "composition_retained": composition_retained,
                "site_count_retained": site_count_retained,
                "requested_space_group": requested,
                "initial_space_group": initial_sg,
                "relaxed_space_group": relaxed_sg,
                "space_group_retained": sg_retained,
                "target_family": target_family,
                "initial_family_status": initial_family_status,
                "relaxed_family_status": relaxed_family_status,
                "family_retained": family_retained,
                "geometry_valid_after": geometry.geometry_ok,
                "bad_contacts_after": bonds.num_bad_contacts,
                "minimum_distance_after": bonds.min_distance,
                "overall_relaxation_status": overall,
                **transition.model_dump(),
            }
            return _result(overall, metrics)
        except Exception as exc:
            return _result("NOT_EVALUATED", {}, error=f"{type(exc).__name__}: {exc}")


def _result(status: str, metrics: dict[str, Any], skipped: bool = False, error: str | None = None) -> BenchmarkEvaluatorResult:
    metrics = {"overall_relaxation_status": status, **metrics}
    return BenchmarkEvaluatorResult(
        name="relaxation_intent_retention",
        ok=status in {"ROBUST", "MODIFIED_BUT_VALID"},
        skipped=skipped,
        summary=status,
        metrics=metrics,
        error_type="RelaxationRetentionError" if error else None,
        error_message=error,
    )


def _optional(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None

