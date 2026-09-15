"""Build run manifests by mapping generated CIF files to paper target rows."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from pymatgen.core import Composition

from sca.evaluators.cif_parse import parse_cif
from sca.io import discover_cif_files
from sca.paper_benchmarks.schema import PaperBenchmarkTarget, load_paper_manifest


RUN_MANIFEST_COLUMNS = [
    "cif_path",
    "file_name",
    "benchmark_id",
    "benchmark_group",
    "attempt_id",
    "target_formula",
    "target_reduced_formula",
    "target_structure_family",
    "target_space_group",
    "target_space_group_number",
    "target_crystal_system",
    "prompt",
    "target_cif_path",
    "reference_cif_path",
    "reference_id",
    "reference_source",
    "paper_source",
    "paper_name",
    "hull_reference_path",
    "target_energy_above_hull",
    "target_formation_energy_per_atom",
    "target_band_gap",
    "property_name",
    "property_target_value",
    "property_target_unit",
    "property_tolerance",
    "method",
    "priority",
    "mapping_status",
    "mapping_confidence",
    "mapping_reason",
    "generated_reduced_formula",
    "generated_formula",
    "notes",
]


def build_paper_run_manifest(
    targets_csv: str | Path,
    generated_folder: str | Path,
    out_csv: str | Path,
    recursive: bool = True,
    filename_formula_mode: str = "infer",
    default_method: str = "qlip_generated",
    attempt_id_mode: str = "filename",
    copy_reference_fields: bool = True,
    unmatched_out: str | Path | None = None,
    strict: bool = False,
) -> pd.DataFrame:
    if filename_formula_mode not in {"infer", "strict", "none"}:
        raise ValueError("filename_formula_mode must be one of infer, strict, none")
    if attempt_id_mode not in {"filename", "counter"}:
        raise ValueError("attempt_id_mode must be one of filename, counter")
    targets, _, warnings = load_paper_manifest(targets_csv)
    target_extras = _target_extras(targets_csv)
    paths = discover_cif_files(generated_folder, recursive=recursive)
    rows = []
    unmatched_rows = []
    attempt_counts: Counter[str] = Counter()
    target_index = _target_index(targets)
    for path in paths:
        generated = _generated_info(path)
        target, status, confidence, reason = _match_target(
            path,
            generated,
            targets,
            target_index,
            filename_formula_mode=filename_formula_mode,
        )
        benchmark_id = target.benchmark_id if target else _unmapped_benchmark_id(generated, path)
        attempt_counts[benchmark_id] += 1
        attempt_id = (
            _filename_attempt_id(path) if attempt_id_mode == "filename" else None
        ) or attempt_counts[benchmark_id]
        rows.append(
            _manifest_row(
                path=path,
                generated=generated,
                target=target,
                benchmark_id=benchmark_id,
                attempt_id=attempt_id,
                mapping_status=status,
                mapping_confidence=confidence,
                mapping_reason=reason,
                default_method=default_method,
                copy_reference_fields=copy_reference_fields,
                extras=target_extras.get(target.benchmark_id, {}) if target else {},
            )
        )
        if status in {"unmatched", "ambiguous"}:
            unmatched_rows.append(
                {
                    "cif_path": str(path),
                    "file_name": path.name,
                    "generated_formula": generated.get("formula"),
                    "generated_reduced_formula": generated.get("reduced_formula"),
                    "filename_formula_token": _filename_formula_token(path),
                    "mapping_status": status,
                    "mapping_confidence": confidence,
                    "mapping_reason": reason,
                }
            )
    if strict and unmatched_rows:
        reasons = "; ".join(f"{row['file_name']}: {row['mapping_reason']}" for row in unmatched_rows[:10])
        raise RuntimeError(f"Unmatched or ambiguous generated CIFs found: {reasons}")
    frame = pd.DataFrame(rows, columns=RUN_MANIFEST_COLUMNS)
    extra_columns = sorted({key for row in rows for key in row if key not in RUN_MANIFEST_COLUMNS})
    if extra_columns:
        frame = pd.DataFrame(rows, columns=RUN_MANIFEST_COLUMNS + extra_columns)
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_csv, index=False)
    if unmatched_out:
        unmatched_path = Path(unmatched_out)
        unmatched_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            unmatched_rows,
            columns=[
                "cif_path",
                "file_name",
                "generated_formula",
                "generated_reduced_formula",
                "filename_formula_token",
                "mapping_status",
                "mapping_confidence",
                "mapping_reason",
            ],
        ).to_csv(unmatched_path, index=False)
    if warnings:
        warning_path = out_csv.with_suffix(".warnings.txt")
        warning_path.write_text("\n".join(warnings) + "\n", encoding="utf-8")
    return frame


def _target_index(targets: list[PaperBenchmarkTarget]) -> dict[str, list[PaperBenchmarkTarget]]:
    index: dict[str, list[PaperBenchmarkTarget]] = defaultdict(list)
    for target in targets:
        added = set()
        for formula in (target.target_reduced_formula, target.target_formula):
            normalized = _formula_key(formula)
            if normalized and normalized not in added:
                index[normalized].append(target)
                added.add(normalized)
    return index


def _match_target(
    path: Path,
    generated: dict[str, Any],
    targets: list[PaperBenchmarkTarget],
    target_index: dict[str, list[PaperBenchmarkTarget]],
    filename_formula_mode: str,
) -> tuple[PaperBenchmarkTarget | None, str, str, str]:
    formula_key = _formula_key(generated.get("reduced_formula"))
    candidates = target_index.get(formula_key, []) if formula_key else []
    if candidates:
        best, confidence, reason = _resolve_candidates(path.name, candidates, "reduced_formula")
        if best is None:
            return None, "ambiguous", "ambiguous", reason
        return best, "matched", confidence, reason
    if filename_formula_mode == "none":
        return None, "unmatched", "unmatched", "no parsed formula match and filename fallback disabled"
    filename_formula = _filename_formula_token(path)
    filename_key = _formula_key(filename_formula) or _normalize_token(filename_formula)
    filename_candidates = target_index.get(filename_key, []) if filename_key else []
    if filename_candidates:
        best, confidence, reason = _resolve_candidates(path.name, filename_candidates, "filename_formula")
        if best is None:
            return None, "ambiguous", "ambiguous", reason
        return best, "matched", confidence, reason
    if filename_formula_mode == "infer":
        stem = _normalize_token(path.stem)
        contains_candidates = [
            target
            for target in targets
            if _normalize_token(target.target_formula) and _normalize_token(target.target_formula) in stem
        ]
        if contains_candidates:
            best, confidence, reason = _resolve_candidates(path.name, contains_candidates, "filename_formula")
            if best is None:
                return None, "ambiguous", "ambiguous", reason
            return best, "matched", confidence, reason
    return None, "unmatched", "unmatched", "no_matching_target"


def _resolve_candidates(
    file_name: str,
    candidates: list[PaperBenchmarkTarget],
    source: str,
) -> tuple[PaperBenchmarkTarget | None, str, str]:
    if len(candidates) == 1:
        confidence = "filename_formula" if source == "filename_formula" else "reduced_formula"
        return candidates[0], confidence, f"{source} matched exactly one target"
    filename = _normalize_token(file_name)
    family_matches = []
    for target in candidates:
        family = _normalize_token(target.target_structure_family)
        space_group = _normalize_token(target.target_space_group)
        if (family and family in filename) or (space_group and space_group in filename):
            family_matches.append(target)
    if len(family_matches) == 1:
        return family_matches[0], "exact_formula_and_family", f"{source} matched; filename family disambiguated"
    if len(family_matches) > 1:
        ids = ", ".join(target.benchmark_id for target in family_matches)
        return None, "ambiguous", f"ambiguous_formula after family match: {ids}"
    ids = ", ".join(target.benchmark_id for target in candidates)
    return None, "ambiguous", f"ambiguous_formula: {ids}"


def _manifest_row(
    path: Path,
    generated: dict[str, Any],
    target: PaperBenchmarkTarget | None,
    benchmark_id: str,
    attempt_id: int,
    mapping_status: str,
    mapping_confidence: str,
    mapping_reason: str,
    default_method: str,
    copy_reference_fields: bool,
    extras: dict[str, Any],
) -> dict[str, Any]:
    reference_path = target.reference_cif_path if target and copy_reference_fields else None
    row = {
        "cif_path": str(path),
        "file_name": path.name,
        "benchmark_id": benchmark_id,
        "benchmark_group": target.benchmark_group if target else "A_validity",
        "attempt_id": attempt_id,
        "target_formula": target.target_formula if target else generated.get("reduced_formula"),
        "target_reduced_formula": target.target_reduced_formula if target else generated.get("reduced_formula"),
        "target_structure_family": target.target_structure_family if target else None,
        "target_space_group": target.target_space_group if target else None,
        "target_space_group_number": target.target_space_group_number if target else None,
        "target_crystal_system": target.target_crystal_system if target else None,
        "prompt": target.prompt if target else None,
        "target_cif_path": reference_path,
        "reference_cif_path": reference_path,
        "reference_id": target.reference_id if target else None,
        "reference_source": target.reference_source if target else None,
        "paper_source": target.paper_source if target else None,
        "paper_name": target.paper_name if target else None,
        "hull_reference_path": target.hull_reference_path if target else None,
        "target_energy_above_hull": target.target_energy_above_hull if target else None,
        "target_formation_energy_per_atom": target.target_formation_energy_per_atom if target else None,
        "target_band_gap": target.target_band_gap if target else None,
        "property_name": target.property_name if target else None,
        "property_target_value": target.property_target_value if target else None,
        "property_target_unit": target.property_target_unit if target else None,
        "property_tolerance": target.property_tolerance if target else None,
        "method": default_method,
        "priority": target.priority if target else None,
        "mapping_status": mapping_status,
        "mapping_confidence": mapping_confidence,
        "mapping_reason": mapping_reason,
        "generated_reduced_formula": generated.get("reduced_formula"),
        "generated_formula": generated.get("formula"),
        "notes": target.notes if target else "Generated CIF did not map to a paper target row",
    }
    for key, value in extras.items():
        row.setdefault(key, value)
    return row


def _generated_info(path: Path) -> dict[str, Any]:
    structure, parsed = parse_cif(path)
    if structure is None:
        return {"formula": None, "reduced_formula": None, "parse_error": parsed.error_message}
    composition = structure.composition
    return {
        "formula": composition.formula,
        "reduced_formula": composition.reduced_formula,
        "parse_error": None,
    }


def _formula_key(formula: str | None) -> str | None:
    if not formula:
        return None
    try:
        return _normalize_token(Composition(formula).reduced_formula)
    except Exception:
        return _normalize_token(formula)


def _normalize_token(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _unmapped_benchmark_id(generated: dict[str, Any], path: Path) -> str:
    formula = _normalize_token(generated.get("reduced_formula"))
    if formula:
        return f"unmapped_{formula}"
    return f"unmapped_{_normalize_token(path.stem)}"


def _filename_formula_token(path: Path) -> str | None:
    parts = [part for part in re.split(r"[_\-\s]+", path.stem.lower()) if part]
    skip = {"challenge", "solution", "generated", "sample", "attempt", "cif", "proxy"}
    for part in parts:
        if part in skip or part.isdigit():
            continue
        if re.search(r"\d", part):
            return part
    for part in parts:
        if part not in skip and not part.isdigit():
            return part
    return None


def _filename_attempt_id(path: Path) -> int | None:
    match = re.search(r"(?:challenge|attempt|sample)[_\-\s]*(\d+)", path.stem, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _target_extras(targets_csv: str | Path) -> dict[str, dict[str, Any]]:
    frame = pd.read_csv(targets_csv, dtype=str).fillna("")
    known = set(RUN_MANIFEST_COLUMNS) | {
        "metric_name",
        "comparator_name",
        "comparator_value",
        "comparator_direction",
        "comparator_unit",
        "comparator_source",
    }
    extras: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        benchmark_id = str(row.get("benchmark_id", "")).strip()
        if not benchmark_id:
            continue
        values = {}
        for column, value in row.items():
            if column in known or value is None or str(value).strip() == "":
                continue
            values[str(column)] = value
        extras[benchmark_id] = values
    return extras
