"""Schemas and CSV parsing helpers for paper-comparable benchmark manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


BENCHMARK_GROUPS = {
    "A_validity",
    "B_structure_reproduction",
    "C_mlip_stability",
    "D_relaxation",
    "E_novelty_sun",
}
COMPARATOR_DIRECTIONS = {"higher_is_better", "lower_is_better", "within_tolerance"}


@dataclass(frozen=True)
class PaperComparator:
    metric_name: str
    comparator_name: str
    comparator_value: float
    comparator_direction: str
    unit: str | None = None
    source_label: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class PaperBenchmarkTarget:
    benchmark_id: str
    benchmark_group: str
    paper_source: str | None = None
    paper_name: str | None = None
    target_formula: str | None = None
    target_reduced_formula: str | None = None
    target_structure_family: str | None = None
    target_space_group: str | None = None
    target_space_group_number: str | None = None
    target_crystal_system: str | None = None
    prompt: str | None = None
    reference_cif_path: str | None = None
    reference_id: str | None = None
    reference_source: str | None = None
    generation_attempts: int | None = None
    property_name: str | None = None
    property_target_value: float | None = None
    property_target_unit: str | None = None
    property_tolerance: float | None = None
    hull_reference_path: str | None = None
    target_energy_above_hull: float | None = None
    target_formation_energy_per_atom: float | None = None
    target_band_gap: float | None = None
    priority: str | None = None
    notes: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaperBenchmarkMetric:
    summary_scope: str
    benchmark_group: str
    metric_name: str
    our_value: float | None
    n_total: int
    n_computable: int
    n_not_computable: int
    unit: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class PaperBenchmarkSummary:
    rows: list[dict[str, Any]]
    warnings: list[str]


MANIFEST_COLUMNS = [
    "benchmark_id",
    "benchmark_group",
    "paper_source",
    "paper_name",
    "target_formula",
    "target_reduced_formula",
    "target_structure_family",
    "target_space_group",
    "target_space_group_number",
    "target_crystal_system",
    "prompt",
    "reference_cif_path",
    "reference_id",
    "reference_source",
    "generation_attempts",
    "property_name",
    "property_target_value",
    "property_target_unit",
    "property_tolerance",
    "hull_reference_path",
    "target_energy_above_hull",
    "target_formation_energy_per_atom",
    "target_band_gap",
    "metric_name",
    "comparator_name",
    "comparator_value",
    "comparator_direction",
    "comparator_unit",
    "comparator_source",
    "priority",
    "notes",
]


def load_paper_manifest(path: str | Path) -> tuple[list[PaperBenchmarkTarget], list[PaperComparator], list[str]]:
    frame = pd.read_csv(path, dtype=str).fillna("")
    warnings: list[str] = []
    targets: list[PaperBenchmarkTarget] = []
    comparators: list[PaperComparator] = []
    for row_index, row in frame.iterrows():
        row_number = row_index + 2
        benchmark_id = _cell(row, "benchmark_id")
        benchmark_group = _cell(row, "benchmark_group")
        if not benchmark_id:
            warnings.append(f"row {row_number}: missing required benchmark_id")
            continue
        if not benchmark_group:
            warnings.append(f"row {row_number}: missing required benchmark_group")
            continue
        if benchmark_group not in BENCHMARK_GROUPS:
            warnings.append(f"row {row_number}: unknown benchmark_group '{benchmark_group}'")
        row_warnings = _target_warnings(row, row_number)
        targets.append(
            PaperBenchmarkTarget(
                benchmark_id=benchmark_id,
                benchmark_group=benchmark_group,
                paper_source=_cell(row, "paper_source"),
                paper_name=_cell(row, "paper_name"),
                target_formula=_cell(row, "target_formula"),
                target_reduced_formula=_cell(row, "target_reduced_formula"),
                target_structure_family=_cell(row, "target_structure_family"),
                target_space_group=_cell(row, "target_space_group"),
                target_space_group_number=_cell(row, "target_space_group_number"),
                target_crystal_system=_cell(row, "target_crystal_system"),
                prompt=_cell(row, "prompt"),
                reference_cif_path=_cell(row, "reference_cif_path"),
                reference_id=_cell(row, "reference_id"),
                reference_source=_cell(row, "reference_source"),
                generation_attempts=_int_cell(row, "generation_attempts"),
                property_name=_cell(row, "property_name"),
                property_target_value=_float_cell(row, "property_target_value"),
                property_target_unit=_cell(row, "property_target_unit"),
                property_tolerance=_float_cell(row, "property_tolerance"),
                hull_reference_path=_cell(row, "hull_reference_path"),
                target_energy_above_hull=_float_cell(row, "target_energy_above_hull"),
                target_formation_energy_per_atom=_float_cell(row, "target_formation_energy_per_atom"),
                target_band_gap=_float_cell(row, "target_band_gap"),
                priority=_cell(row, "priority"),
                notes=_cell(row, "notes"),
                warnings=row_warnings,
            )
        )
        warnings.extend(row_warnings)
        comparator = _comparator_from_row(row, row_number, warnings)
        if comparator is not None:
            comparators.append(comparator)
    return targets, comparators, warnings


def load_comparator_csv(path: str | Path) -> tuple[list[PaperComparator], list[str]]:
    frame = pd.read_csv(path, dtype=str).fillna("")
    warnings: list[str] = []
    comparators: list[PaperComparator] = []
    for row_index, row in frame.iterrows():
        comparator = _comparator_from_row(row, row_index + 2, warnings)
        if comparator is not None:
            comparators.append(comparator)
    return comparators, warnings


def _comparator_from_row(row: pd.Series, row_number: int, warnings: list[str]) -> PaperComparator | None:
    metric_name = _cell(row, "metric_name") or _cell(row, "metric")
    comparator_name = _cell(row, "comparator_name")
    comparator_value = _float_cell(row, "comparator_value")
    direction = _cell(row, "comparator_direction") or _cell(row, "direction")
    present = any([metric_name, comparator_name, comparator_value is not None, direction])
    if not present:
        return None
    missing = []
    if not metric_name:
        missing.append("metric_name")
    if not comparator_name:
        missing.append("comparator_name")
    if comparator_value is None:
        missing.append("comparator_value")
    if not direction:
        missing.append("comparator_direction")
    if missing:
        warnings.append(f"row {row_number}: comparator missing required fields: {', '.join(missing)}")
        return None
    if direction not in COMPARATOR_DIRECTIONS:
        warnings.append(f"row {row_number}: unknown comparator_direction '{direction}'")
    return PaperComparator(
        metric_name=str(metric_name),
        comparator_name=str(comparator_name),
        comparator_value=float(comparator_value),
        comparator_direction=str(direction),
        unit=_cell(row, "comparator_unit") or _cell(row, "unit"),
        source_label=_cell(row, "comparator_source") or _cell(row, "source_label"),
        notes=_cell(row, "notes"),
    )


def _target_warnings(row: pd.Series, row_number: int) -> list[str]:
    warnings = []
    group = _cell(row, "benchmark_group")
    if group == "B_structure_reproduction" and not _cell(row, "reference_cif_path"):
        warnings.append(f"row {row_number}: reference-dependent target missing reference_cif_path")
    if group == "C_mlip_stability" and not _cell(row, "hull_reference_path"):
        warnings.append(f"row {row_number}: hull-dependent target missing hull_reference_path")
    return warnings


def _cell(row: pd.Series, key: str) -> str | None:
    if key not in row:
        return None
    value = row[key]
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip()


def _float_cell(row: pd.Series, key: str) -> float | None:
    value = _cell(row, key)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int_cell(row: pd.Series, key: str) -> int | None:
    value = _float_cell(row, key)
    if value is None:
        return None
    return int(value)

