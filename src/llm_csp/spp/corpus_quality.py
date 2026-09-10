"""Corpus suitability diagnostics for formula-targeted SPP generation."""

from __future__ import annotations

import math
import re
from functools import reduce
from pathlib import Path
from typing import Any

import numpy as np

from .fit_hist import canonical_pair
from .io_cif import load_cifs_from_dir

from .required_pairs import derive_required_pairs, parse_formula_elements


def _pair_label(left: str, right: str) -> str:
    pair = canonical_pair(str(left), str(right))
    return f"{pair[0]}-{pair[1]}"


def _formula_counts(formula: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in re.finditer(r"([A-Z][a-z]?)([0-9]*)", formula or ""):
        element = match.group(1)
        amount = int(match.group(2) or "1")
        counts[element] = counts.get(element, 0) + amount
    return counts


def _reduced_counts(counts: dict[str, int]) -> dict[str, int]:
    values = [int(value) for value in counts.values() if int(value) > 0]
    if not values:
        return {}
    divisor = reduce(math.gcd, values)
    return {key: int(value // divisor) for key, value in sorted(counts.items())}


def _auto_supercell(cell: np.ndarray, cutoff: float) -> tuple[int, int, int]:
    reps: list[int] = []
    for axis in range(3):
        length = float(np.linalg.norm(cell[axis]))
        reps.append(1 if length <= 0 or not np.isfinite(length) else max(1, int(math.ceil(float(cutoff) / length))))
    return tuple(reps)  # type: ignore[return-value]


def _file_pair_distances(atoms: Any, required_pairs: set[str], cutoff: float) -> dict[str, list[float]]:
    symbols = tuple(str(symbol) for symbol in atoms.get_chemical_symbols())
    positions = np.asarray(atoms.get_positions(), dtype=np.float64)
    cell = np.asarray(atoms.cell.array, dtype=np.float64)
    reps = _auto_supercell(cell, cutoff)
    out: dict[str, list[float]] = {pair: [] for pair in required_pairs}
    for i, symbol_i in enumerate(symbols):
        pos_i = positions[i]
        for j, symbol_j in enumerate(symbols):
            pair = _pair_label(symbol_i, symbol_j)
            if pair not in required_pairs:
                continue
            pos_j = positions[j]
            for tx in range(-reps[0], reps[0] + 1):
                for ty in range(-reps[1], reps[1] + 1):
                    for tz in range(-reps[2], reps[2] + 1):
                        if i == j and tx == 0 and ty == 0 and tz == 0:
                            continue
                        distance = float(np.linalg.norm((pos_j + tx * cell[0] + ty * cell[1] + tz * cell[2]) - pos_i))
                        if 0.0 < distance <= float(cutoff) + 1e-12:
                            out[pair].append(distance)
    return out


def audit_corpus_for_formula(cif_dir: str | Path, formula: str, cutoff: float = 6.0) -> dict[str, Any]:
    """Return deterministic diagnostics for whether a CIF corpus supports formula-required SPP pairs."""
    target_elements = parse_formula_elements(formula)
    target_element_set = set(target_elements)
    required_pairs = derive_required_pairs(target_elements)
    cross_pairs = [pair for pair in required_pairs if len(set(pair.split("-", 1))) == 2]
    target_reduced = _reduced_counts(_formula_counts(formula))
    loaded = load_cifs_from_dir(Path(cif_dir))

    detected_formulas: list[str] = []
    detected_elements_by_file: dict[str, list[str]] = {}
    files_with_all_target_elements: list[str] = []
    files_with_exact_or_reduced_formula_match: list[str] = []
    files_with_target_cross_pairs: list[str] = []
    geometric_pair_counts: dict[str, int] = {pair: 0 for pair in required_pairs}
    min_distances: dict[str, float | None] = {pair: None for pair in required_pairs}
    direct_support_files: dict[str, list[str]] = {pair: [] for pair in required_pairs}

    for item in loaded:
        path_text = str(Path(item.path))
        symbols = [str(symbol) for symbol in item.atoms.get_chemical_symbols()]
        elements = sorted(set(symbols))
        detected_formula = str(item.atoms.get_chemical_formula())
        detected_formulas.append(detected_formula)
        detected_elements_by_file[path_text] = elements
        if target_element_set and target_element_set.issubset(set(elements)):
            files_with_all_target_elements.append(path_text)

        detected_counts: dict[str, int] = {}
        for symbol in symbols:
            detected_counts[symbol] = detected_counts.get(symbol, 0) + 1
        if target_reduced and _reduced_counts(detected_counts) == target_reduced:
            files_with_exact_or_reduced_formula_match.append(path_text)

        file_distances = _file_pair_distances(item.atoms, set(required_pairs), float(cutoff))
        if any(file_distances.get(pair) for pair in cross_pairs):
            files_with_target_cross_pairs.append(path_text)
        for pair, values in file_distances.items():
            if not values:
                continue
            direct_support_files[pair].append(path_text)
            geometric_pair_counts[pair] += len(values)
            observed_min = float(min(values))
            current_min = min_distances[pair]
            min_distances[pair] = observed_min if current_min is None else min(float(current_min), observed_min)

    errors: list[dict[str, Any]] = []
    if target_elements and not files_with_all_target_elements:
        errors.append(
            {
                "code": "target_elements_absent",
                "message": "No CIF in the retrieved corpus contains all target elements; pair-level evidence may still be usable if all required pairs are supported.",
            }
        )
    missing_cross_pairs = [pair for pair in cross_pairs if geometric_pair_counts.get(pair, 0) == 0]
    for pair in missing_cross_pairs:
        errors.append(
            {
                "code": "target_cross_pair_absent",
                "message": f"No CIF in the retrieved corpus contains geometric {pair} distances under cutoff.",
                "pair": pair,
            }
        )

    missing_required_pairs = [pair for pair in required_pairs if geometric_pair_counts.get(pair, 0) == 0]
    pair_evidence_summary = []
    for pair in required_pairs:
        count = int(geometric_pair_counts.get(pair, 0))
        pair_evidence_summary.append(
            {
                "required_pair": pair,
                "direct_support_candidate_ids": sorted(dict.fromkeys(direct_support_files.get(pair, []))),
                "analogue_support_candidate_ids": [],
                "semantic_only_candidate_ids": [],
                "direct_observation_count": count,
                "analogue_observation_count": 0,
                "total_weighted_observation_count": float(count),
                "nonempty_histogram_bin_fraction": None,
                "pair_quality": "usable" if count > 0 else "missing",
                "pair_quality_reason": "direct_pair_distances_found" if count > 0 else "no_direct_pair_distances_found",
            }
        )

    blocking_errors = [
        item for item in errors
        if item.get("code") in {"target_cross_pair_absent"}
    ]
    if missing_required_pairs:
        status = "unsuitable"
        recommendation = "expand_pair_level_spp_corpus"
    elif missing_required_pairs or not files_with_exact_or_reduced_formula_match:
        status = "weak"
        recommendation = "prefer_exact_formula_corpus_or_increase_structural_coverage"
        if not files_with_exact_or_reduced_formula_match:
            errors.append(
                {
                    "code": "exact_or_reduced_formula_absent",
                    "message": "No CIF has an exact or reduced formula match to the target formula.",
                }
            )
    else:
        status = "suitable"
        recommendation = "proceed_with_fresh_required_pair_spp"
    if blocking_errors:
        status = "unsuitable"
        recommendation = "expand_pair_level_spp_corpus"

    return {
        "formula": formula,
        "target_elements": target_elements,
        "required_pairs": required_pairs,
        "cif_count": len(loaded),
        "cif_files": [str(Path(item.path)) for item in loaded],
        "detected_formulas": sorted(dict.fromkeys(detected_formulas)),
        "detected_elements_by_file": detected_elements_by_file,
        "files_with_all_target_elements": files_with_all_target_elements,
        "files_with_exact_or_reduced_formula_match": files_with_exact_or_reduced_formula_match,
        "files_with_target_cross_pairs": sorted(dict.fromkeys(files_with_target_cross_pairs)),
        "geometric_pair_counts": geometric_pair_counts,
        "geometric_pair_min_distances": min_distances,
        "missing_pairs": missing_required_pairs,
        "missing_cross_pairs": missing_cross_pairs,
        "pair_evidence_summary": pair_evidence_summary,
        "spp_quality": "usable" if not missing_required_pairs and status in {"suitable", "weak"} else "missing_required_pair_evidence",
        "corpus_quality_status": status,
        "corpus_quality_errors": errors,
        "recommendation": recommendation,
        "corpus_dir": str(Path(cif_dir)),
        "cutoff": float(cutoff),
    }
