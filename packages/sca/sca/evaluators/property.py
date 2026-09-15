"""Property target and predicted-hull benchmark evaluators."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from pymatgen.analysis.phase_diagram import PDEntry, PhaseDiagram
from pymatgen.core import Composition

from sca.evaluators.cif_parse import parse_cif
from sca.schemas import BenchmarkEvaluatorResult


PROPERTY_SOURCE_KEYS = {
    "formation_energy_per_atom": (
        "formation_energy_per_atom",
        "alignn_formation_energy_per_atom",
        "chgnet_energy_per_atom",
        "m3gnet_energy_per_atom",
        "mace_energy_per_atom",
        "sevennet_energy_per_atom",
    ),
    "energy_above_hull": (
        "predicted_energy_above_hull",
    ),
    "band_gap": ("band_gap", "predicted_band_gap"),
}


class PropertyTargetsBenchmarkEvaluator:
    name = "property_targets"
    description = "Compare benchmark rows against target property values from a manifest."

    def evaluate_row(self, row: dict) -> BenchmarkEvaluatorResult:
        metrics: dict[str, Any] = {
            "property_target_ok": False,
            "target_property_name": row.get("target_property_name"),
            "target_property_value": row.get("target_property_value"),
            "predicted_property_value": None,
            "property_error": None,
            "formation_energy_error": None,
            "energy_above_hull_error": None,
            "band_gap_error": None,
        }

        comparisons = []
        comparisons.extend(
            _compare_named_target(
                "formation_energy",
                row.get("target_formation_energy_per_atom"),
                _first_float(row, PROPERTY_SOURCE_KEYS["formation_energy_per_atom"]),
            )
        )
        comparisons.extend(
            _compare_named_target(
                "energy_above_hull",
                row.get("target_energy_above_hull"),
                _first_float(row, PROPERTY_SOURCE_KEYS["energy_above_hull"]),
            )
        )
        comparisons.extend(
            _compare_named_target(
                "band_gap",
                row.get("target_band_gap"),
                _first_float(row, PROPERTY_SOURCE_KEYS["band_gap"]),
            )
        )

        target_name = row.get("target_property_name")
        if target_name:
            target_value = _float_or_none(row.get("target_property_value"))
            predicted_value = _first_float(row, PROPERTY_SOURCE_KEYS.get(str(target_name), (str(target_name),)))
            metrics["predicted_property_value"] = predicted_value
            if target_value is not None and predicted_value is not None:
                error = predicted_value - target_value
                metrics["property_error"] = error
                comparisons.append(("property", target_value, predicted_value, error))

        for name, target, predicted, error in comparisons:
            metrics[f"target_{name}"] = target
            metrics[f"predicted_{name}"] = predicted
            metrics[f"{name}_error"] = error

        ok = any(value is not None for value in (
            metrics.get("property_error"),
            metrics.get("formation_energy_error"),
            metrics.get("energy_above_hull_error"),
            metrics.get("band_gap_error"),
        ))
        metrics["property_target_ok"] = ok
        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=ok,
            skipped=not ok,
            summary="ok" if ok else "no comparable target",
            metrics=metrics,
            flags={"property_target_ok": ok},
        )


class PredictedHullBenchmarkEvaluator:
    name = "predicted_hull"
    description = "Predicted/surrogate energy-above-hull against local phase entries."

    def evaluate_row(self, row: dict) -> BenchmarkEvaluatorResult:
        reference_path = row.get("hull_reference_path")
        if not reference_path:
            return _hull_result(False, "no hull reference", skipped=True, error_message="hull_reference_path was not provided")
        composition = _composition_from_row(row)
        if composition is None:
            return _hull_result(False, "no composition", skipped=True, error_message="No parsed composition available")
        energy_per_atom = _first_float(row, PROPERTY_SOURCE_KEYS["formation_energy_per_atom"])
        if energy_per_atom is None:
            return _hull_result(False, "no predicted energy", skipped=True, error_message="No predicted formation energy per atom available")

        try:
            entries = load_phase_entries(reference_path)
            chemical_system = {element.symbol for element in composition.elements}
            relevant_entries = [
                entry for entry in entries
                if {element.symbol for element in entry.composition.elements}.issubset(chemical_system)
            ]
            if not relevant_entries:
                raise ValueError("No reference entries overlap the generated chemical system")
            generated_entry = PDEntry(
                composition,
                float(energy_per_atom) * composition.num_atoms,
                name="generated_candidate",
            )
            phase_diagram = PhaseDiagram(relevant_entries + [generated_entry])
            decomposition, energy_above_hull = phase_diagram.get_decomp_and_e_above_hull(generated_entry)
        except Exception as exc:
            return _hull_result(False, "failed", error_type=type(exc).__name__, error_message=str(exc))

        products = [
            getattr(entry, "name", entry.composition.reduced_formula)
            for entry in sorted(decomposition, key=lambda entry: entry.composition.reduced_formula)
        ]
        return _hull_result(
            True,
            "ok",
            predicted_energy_above_hull=float(energy_above_hull),
            hull_reference_count=len(relevant_entries),
            decomposition_products=";".join(products),
            energy_source="predicted_surrogate",
        )


@lru_cache(maxsize=8)
def load_phase_entries(path: str | Path) -> tuple[PDEntry, ...]:
    reference_path = Path(path)
    if reference_path.suffix.lower() == ".json":
        payload = json.loads(reference_path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("entries", [])
    else:
        rows = pd.read_csv(reference_path).to_dict(orient="records")
    entries = []
    for index, row in enumerate(rows):
        formula = row.get("formula") or row.get("composition") or row.get("reduced_formula")
        energy = _float_or_none(row.get("formation_energy_per_atom"))
        if formula is None or energy is None:
            continue
        composition = Composition(str(formula))
        name = str(row.get("material_id") or row.get("entry_id") or row.get("id") or formula)
        entries.append(PDEntry(composition, energy * composition.num_atoms, name=name))
    if not entries:
        raise ValueError(f"No phase entries could be loaded from {reference_path}")
    return tuple(entries)


def _compare_named_target(
    name: str,
    target_value: Any,
    predicted_value: float | None,
) -> list[tuple[str, float, float, float]]:
    target = _float_or_none(target_value)
    if target is None or predicted_value is None:
        return []
    return [(name, target, predicted_value, predicted_value - target)]


def _composition_from_row(row: dict) -> Composition | None:
    composition_text = row.get("reduced_formula") or row.get("formula")
    if composition_text:
        return Composition(str(composition_text))
    input_path = row.get("input_path")
    if input_path:
        structure, parsed = parse_cif(input_path)
        if parsed.parse_ok and structure is not None:
            return structure.composition
    return None


def _hull_result(
    ok: bool,
    summary: str,
    skipped: bool = False,
    error_type: str | None = None,
    error_message: str | None = None,
    predicted_energy_above_hull: float | None = None,
    hull_reference_count: int | None = None,
    decomposition_products: str | None = None,
    energy_source: str | None = None,
) -> BenchmarkEvaluatorResult:
    return BenchmarkEvaluatorResult(
        name=PredictedHullBenchmarkEvaluator.name,
        ok=ok,
        skipped=skipped,
        summary=summary,
        metrics={
            "hull_ok": ok,
            "predicted_energy_above_hull": predicted_energy_above_hull,
            "predicted_hull_energy_source": energy_source,
            "hull_reference_count": hull_reference_count,
            "decomposition_products": decomposition_products,
            "hull_error": error_message,
        },
        flags={"hull_ok": ok},
        error_type=error_type,
        error_message=error_message,
    )


def _first_float(row: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _float_or_none(row.get(key))
        if value is not None:
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
