"""QLIP-targeted required-pair SPP extraction from periodic CIF geometry."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from .compat import check_pot_root, render_compat_report
from .export import export_spp_root
from .fit_hist import HistAccumulator, canonical_pair, make_uniform_binning
from .fit_phi import build_phi_from_hist
from .io_cif import load_cifs_from_dir


def _pair_label(pair: tuple[str, str]) -> str:
    return f"{pair[0]}-{pair[1]}"


def parse_formula_elements(formula: str) -> list[str]:
    """Return unique element symbols in formula order."""
    if not isinstance(formula, str) or not formula.strip():
        return []
    elements: list[str] = []
    for match in re.finditer(r"([A-Z][a-z]?)(?:[0-9]+(?:\.[0-9]+)?)?", formula):
        element = match.group(1)
        if element not in elements:
            elements.append(element)
    return elements


def derive_required_pairs(elements: list[str]) -> list[str]:
    """Return canonical unordered self/cross pairs for formula elements."""
    cleaned: list[str] = []
    for element in elements:
        symbol = str(element).strip().title()
        if symbol and symbol not in cleaned:
            cleaned.append(symbol)
    pairs = {
        _pair_label(canonical_pair(cleaned[i], cleaned[j]))
        for i in range(len(cleaned))
        for j in range(i, len(cleaned))
    }
    return sorted(pairs, key=str.lower)


def _auto_supercell(cell: np.ndarray, cutoff: float) -> tuple[int, int, int]:
    reps: list[int] = []
    for axis in range(3):
        length = float(np.linalg.norm(cell[axis]))
        if length <= 0 or not np.isfinite(length):
            reps.append(1)
        else:
            reps.append(max(1, int(math.ceil(float(cutoff) / length))))
    return tuple(reps)  # type: ignore[return-value]


def _periodic_required_distances(
    atoms: Any,
    *,
    required_pairs: set[str],
    cutoff: float,
    supercell: tuple[int, int, int],
    max_distances_per_pair: int | None = None,
) -> dict[str, list[float]]:
    symbols = tuple(str(symbol) for symbol in atoms.get_chemical_symbols())
    positions = np.asarray(atoms.get_positions(), dtype=np.float64)
    cell = np.asarray(atoms.cell.array, dtype=np.float64)
    out: dict[str, list[float]] = {pair: [] for pair in required_pairs}

    for i, symbol_i in enumerate(symbols):
        pos_i = positions[i]
        for j, symbol_j in enumerate(symbols):
            pair = _pair_label(canonical_pair(symbol_i, symbol_j))
            if pair not in required_pairs:
                continue
            pos_j = positions[j]
            for tx in range(-supercell[0], supercell[0] + 1):
                for ty in range(-supercell[1], supercell[1] + 1):
                    for tz in range(-supercell[2], supercell[2] + 1):
                        if i == j and tx == 0 and ty == 0 and tz == 0:
                            continue
                        image_pos = pos_j + tx * cell[0] + ty * cell[1] + tz * cell[2]
                        distance = float(np.linalg.norm(image_pos - pos_i))
                        if 0.0 < distance <= float(cutoff) + 1e-12:
                            if max_distances_per_pair is None or len(out[pair]) < int(max_distances_per_pair):
                                out[pair].append(distance)
    return out


def collect_required_pair_distances(
    cif_dir: Path,
    formula: str,
    cutoff: float,
    supercell: tuple[int, int, int] | None = None,
    max_distances_per_pair: int | None = None,
) -> dict[str, Any]:
    """Collect periodic distances for every formula-required pair."""
    formula_elements = parse_formula_elements(formula)
    required_pairs = derive_required_pairs(formula_elements)
    required_pair_set = set(required_pairs)
    loaded = load_cifs_from_dir(cif_dir)
    pair_distances: dict[str, list[float]] = {pair: [] for pair in required_pairs}
    cifs: list[dict[str, Any]] = []

    for item in loaded:
        cell = np.asarray(item.atoms.cell.array, dtype=np.float64)
        reps = supercell if supercell is not None else _auto_supercell(cell, float(cutoff))
        distances = _periodic_required_distances(
            item.atoms,
            required_pairs=required_pair_set,
            cutoff=float(cutoff),
            supercell=reps,
            max_distances_per_pair=max_distances_per_pair,
        )
        detected_pairs: dict[str, dict[str, float | int]] = {}
        for pair, values in distances.items():
            if values:
                pair_distances[pair].extend(values)
                detected_pairs[pair] = {
                    "count": int(len(values)),
                    "min_distance": float(min(values)),
                    "max_distance": float(max(values)),
                }
        cifs.append(
            {
                "file": str(Path(item.path)),
                "detected_formula": str(item.atoms.get_chemical_formula()),
                "supercell": list(reps),
                "geometric_pairs_within_cutoff": detected_pairs,
            }
        )

    pair_stats: dict[str, dict[str, float | int | None]] = {}
    missing_pairs: list[str] = []
    sparse_pairs: list[str] = []
    for pair in required_pairs:
        values = pair_distances[pair]
        if not values:
            missing_pairs.append(pair)
            pair_stats[pair] = {"count": 0, "min_distance": None, "max_distance": None}
        else:
            pair_stats[pair] = {
                "count": int(len(values)),
                "min_distance": float(min(values)),
                "max_distance": float(max(values)),
            }

    return {
        "formula": formula,
        "elements": formula_elements,
        "required_pairs": required_pairs,
        "pair_histograms": {pair: list(pair_distances[pair]) for pair in required_pairs},
        "pair_stats": pair_stats,
        "missing_pairs": missing_pairs,
        "sparse_pairs": sparse_pairs,
        "cutoff": float(cutoff),
        "max_distances_per_pair": max_distances_per_pair,
        "corpus_cif_count": len(loaded),
        "corpus_cif_files": [str(Path(item.path)) for item in loaded],
        "cifs": cifs,
    }


def export_required_pair_spp_root(
    *,
    cif_dir: Path,
    formula: str,
    out_root: Path,
    name: str,
    cutoff: float = 6.0,
    supercell: tuple[int, int, int] | None = None,
    alpha: float = 1e-3,
    d_min: float = 0.5,
    bin_width: float = 0.05,
    max_distances_per_pair: int | None = None,
    max_cap_fraction_threshold: float = 0.5,
) -> dict[str, Any]:
    """Export a fresh QLIP-required-pair SPP root using existing POT writer."""
    from .corpus_quality import audit_corpus_for_formula

    corpus_quality = audit_corpus_for_formula(cif_dir=Path(cif_dir), formula=formula, cutoff=float(cutoff))
    out_root.mkdir(parents=True, exist_ok=True)
    quality_status = str(corpus_quality.get("corpus_quality_status") or "unknown")
    quality_errors = [
        item for item in corpus_quality.get("corpus_quality_errors", [])
        if isinstance(item, dict)
    ]
    quality_warnings: list[dict[str, Any]] = []
    if quality_status == "weak":
        quality_warnings.append(
            {
                "code": "corpus_weak_for_spp",
                "message": "Retrieved CIF corpus is chemically related but weak for complete formula-required SPP coverage.",
                "details": corpus_quality,
            }
        )
    corpus_unsuitable_error: dict[str, Any] | None = None
    if quality_status == "unsuitable":
        corpus_unsuitable_error = {
            "code": "corpus_unsuitable_for_spp",
            "message": (
                "Retrieved CIF corpus is unsuitable for complete formula-required SPP generation; "
                "supported-pair POTs will still be exported when pair distances are available."
            ),
            "details": corpus_quality,
            "path": str(out_root),
        }

    diagnostics = collect_required_pair_distances(
        cif_dir=Path(cif_dir),
        formula=formula,
        cutoff=float(cutoff),
        supercell=supercell,
        max_distances_per_pair=max_distances_per_pair,
    )
    missing_pairs = list(diagnostics["missing_pairs"])
    sparse_pairs = list(diagnostics["sparse_pairs"])
    fitted_pairs = [
        pair
        for pair in diagnostics["required_pairs"]
        if pair not in set(missing_pairs) and pair not in set(sparse_pairs)
    ]

    manifest_extra = {
        "source": "fresh_corpus",
        "extraction_mode": "qlip_required_pairs",
        "formula": formula,
        "required_pairs": diagnostics["required_pairs"],
        "fitted_pairs": fitted_pairs,
        "available_pairs": fitted_pairs,
        "missing_pairs": missing_pairs,
        "sparse_pairs": sparse_pairs,
        "pair_stats": diagnostics["pair_stats"],
        "cutoff": float(cutoff),
        "max_distances_per_pair": max_distances_per_pair,
        "corpus_cif_count": diagnostics["corpus_cif_count"],
        "corpus_cif_files": diagnostics["corpus_cif_files"],
        "corpus_quality": corpus_quality,
    }

    errors: list[dict[str, Any]] = []
    if corpus_unsuitable_error is not None:
        errors.append(corpus_unsuitable_error)
    errors.extend(quality_errors)
    pot_quality: dict[str, Any] | None = None
    if fitted_pairs:
        binning = make_uniform_binning(d_min=float(d_min), d_max=max(float(cutoff), float(d_min) + float(bin_width)), bin_width=float(bin_width))
        hist = HistAccumulator(binning=binning, counts={}, total_pairs_seen=0, total_weighted_pairs_seen=0.0)
        for pair in fitted_pairs:
            left, right = pair.split("-", 1)
            for distance in diagnostics["pair_histograms"][pair]:
                hist.add_sample(left, right, float(distance), 1.0)
        try:
            phi_res = build_phi_from_hist(hist, alpha=float(alpha), shifted=True)
            export_spp_root(out_root, phi_res, name=name, manifest_extra=manifest_extra)
            compat = check_pot_root(out_root, strict=True)
            (out_root.parent / "compat_report_required_pairs.txt").write_text(
                render_compat_report(compat) + "\n",
                encoding="utf-8",
            )
            if not compat.ok:
                errors.append(
                    {
                        "code": "required_pair_pot_export_failed",
                        "message": "Required-pair POT export failed compatibility checks.",
                        "path": str(out_root),
                    }
                )
            from .quality import audit_pot_root

            pot_quality = audit_pot_root(
                out_root,
                required_pairs=list(diagnostics["required_pairs"]),
                max_cap_fraction_threshold=float(max_cap_fraction_threshold),
                out_json=out_root.parent / "spp_pot_quality.json",
                out_csv=out_root.parent / "spp_pot_quality.csv",
            )
            if pot_quality.get("spp_pot_quality_status") != "usable":
                errors.append(
                    {
                        "code": "capped_pot_detected",
                        "message": "Generated POT root failed pair-level POT quality gate and is diagnostic-only.",
                        "spp_pot_quality": pot_quality,
                        "path": str(out_root),
                    }
                )
        except Exception as exc:
            errors.append(
                {
                    "code": "required_pair_pot_export_failed",
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                    "path": str(out_root),
                }
            )
    else:
        (out_root / "manifest.json").write_text(
            json.dumps({"name": name, "pairs": [], **manifest_extra}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    pair_export_diagnostics: list[dict[str, Any]] = []
    for pair in diagnostics["required_pairs"]:
        pot_path = out_root / pair / f"{pair}.POT"
        has_evidence = pair in fitted_pairs
        exported = pot_path.is_file()
        failure_reason = None
        if not has_evidence:
            failure_reason = "missing_pair_distances"
        elif not exported:
            failure_reason = "pot_export_failed"
        pair_export_diagnostics.append(
            {
                "pair": pair,
                "evidence_status": "supported" if has_evidence else "missing",
                "pot_export_status": "exported" if exported else "not_exported",
                "pot_path": str(pot_path) if exported else None,
                "failure_reason": failure_reason,
            }
        )
    manifest_path = out_root / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest_payload = {"name": name}
    else:
        manifest_payload = {"name": name, "pairs": []}
    manifest_payload.update({**manifest_extra, "pair_export_diagnostics": pair_export_diagnostics})
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if missing_pairs:
        errors.append(
            {
                "code": "fresh_pair_coverage_incomplete",
                "message": "Fresh required-pair SPP generation did not cover every formula-required pair.",
                "missing_pairs": missing_pairs,
                "required_pairs": diagnostics["required_pairs"],
                "corpus_quality": corpus_quality,
                "path": str(out_root),
            }
        )
        errors.append(
            {
                "code": "required_pair_distances_missing",
                "message": "No periodic distances were found for one or more formula-required pairs.",
                "missing_pairs": missing_pairs,
                "required_pairs": diagnostics["required_pairs"],
                "path": str(out_root),
            }
        )

    return {
        "attempted": True,
        "extraction_mode": "qlip_required_pairs",
        "formula": formula,
        "corpus_cif_count": diagnostics["corpus_cif_count"],
        "corpus_cif_files": diagnostics["corpus_cif_files"],
        "corpus_quality": corpus_quality,
        "spp_pot_quality": pot_quality or {},
        "pair_stats": diagnostics["pair_stats"],
        "required_pairs": diagnostics["required_pairs"],
        "available_pairs": fitted_pairs,
        "fitted_pairs": fitted_pairs,
        "pair_export_diagnostics": pair_export_diagnostics,
        "missing_pairs": missing_pairs,
        "sparse_pairs": sparse_pairs,
        "cutoff": float(cutoff),
        "spp_root": str(out_root),
        "warnings": quality_warnings,
        "errors": errors,
        "ok": not errors,
    }
