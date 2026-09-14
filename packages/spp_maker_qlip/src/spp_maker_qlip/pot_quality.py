"""Quality diagnostics for generated QLIP/SPP POT roots."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from spp_maker.pot_io import read_pot_like_qlip


def _pair_name(path: Path) -> str:
    return path.stem if path.stem else path.parent.name


def audit_pot_file(path: Path, *, max_cap_fraction_threshold: float = 0.5) -> dict[str, Any]:
    r_vals, u_vals = read_pot_like_qlip(path)
    pair = _pair_name(Path(path))
    if r_vals.size == 0 or u_vals.size == 0:
        return {
            "pair": pair,
            "pot_file": str(path),
            "x_min": None,
            "x_max": None,
            "y_min": None,
            "y_max": None,
            "raw_point_count": 0,
            "max_cap_value": None,
            "max_cap_fraction": 1.0,
            "nonempty_effective_region_fraction": 0.0,
            "flat_cap_present": True,
            "pot_quality": "missing",
            "pot_quality_reason": "no_numeric_pot_rows",
        }
    finite = np.isfinite(r_vals) & np.isfinite(u_vals)
    r_vals = r_vals[finite]
    u_vals = u_vals[finite]
    if r_vals.size == 0:
        return {
            "pair": pair,
            "pot_file": str(path),
            "x_min": None,
            "x_max": None,
            "y_min": None,
            "y_max": None,
            "raw_point_count": 0,
            "max_cap_value": None,
            "max_cap_fraction": 1.0,
            "nonempty_effective_region_fraction": 0.0,
            "flat_cap_present": True,
            "pot_quality": "degenerate",
            "pot_quality_reason": "no_finite_pot_rows",
        }
    y_max = float(np.max(u_vals))
    y_min = float(np.min(u_vals))
    tolerance = max(1e-9, abs(y_max) * 1e-8)
    max_cap_fraction = float(np.mean(np.abs(u_vals - y_max) <= tolerance))
    nonempty_effective_region_fraction = float(np.mean(np.abs(u_vals - y_max) > tolerance))
    flat_cap_present = max_cap_fraction > float(max_cap_fraction_threshold)
    if flat_cap_present:
        quality = "capped"
        reason = "max_cap_fraction_exceeds_threshold"
    elif np.isclose(y_min, y_max):
        quality = "degenerate"
        reason = "constant_pot_curve"
    else:
        quality = "usable"
        reason = "pot_curve_has_noncap_region"
    return {
        "pair": pair,
        "pot_file": str(path),
        "x_min": float(np.min(r_vals)),
        "x_max": float(np.max(r_vals)),
        "y_min": y_min,
        "y_max": y_max,
        "raw_point_count": int(r_vals.size),
        "max_cap_value": y_max,
        "max_cap_fraction": max_cap_fraction,
        "nonempty_effective_region_fraction": nonempty_effective_region_fraction,
        "flat_cap_present": bool(flat_cap_present),
        "pot_quality": quality,
        "pot_quality_reason": reason,
    }


def audit_pot_root(
    pot_root: Path,
    *,
    required_pairs: list[str] | tuple[str, ...] | None = None,
    max_cap_fraction_threshold: float = 0.5,
    out_json: Path | None = None,
    out_csv: Path | None = None,
) -> dict[str, Any]:
    root = Path(pot_root)
    rows = [
        audit_pot_file(path, max_cap_fraction_threshold=max_cap_fraction_threshold)
        for path in sorted(root.rglob("*.POT"), key=lambda item: str(item).lower())
    ]
    by_pair = {str(row["pair"]): row for row in rows}
    required = list(required_pairs or sorted(by_pair.keys(), key=str.lower))
    missing_pairs = [pair for pair in required if pair not in by_pair]
    unusable_pairs = [
        pair for pair in required
        if pair in by_pair and by_pair[pair].get("pot_quality") != "usable"
    ]
    if missing_pairs:
        status = "missing"
        reason = "required_pair_pot_missing"
    elif unusable_pairs:
        status = "unusable"
        reason = "required_pair_pot_quality_failed"
    else:
        status = "usable"
        reason = "all_required_pair_pots_usable"
    payload = {
        "pot_root": str(root),
        "required_pairs": required,
        "pairs": rows,
        "missing_pairs": missing_pairs,
        "unusable_pairs": unusable_pairs,
        "max_cap_fraction_threshold": float(max_cap_fraction_threshold),
        "spp_pot_quality_status": status,
        "spp_pot_quality_reason": reason,
        "diagnostic_only": status != "usable",
    }
    if out_json is not None:
        Path(out_json).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if out_csv is not None:
        out_csv = Path(out_csv)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "pair",
            "pot_file",
            "x_min",
            "x_max",
            "y_min",
            "y_max",
            "raw_point_count",
            "max_cap_value",
            "max_cap_fraction",
            "nonempty_effective_region_fraction",
            "flat_cap_present",
            "pot_quality",
            "pot_quality_reason",
        ]
        with out_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in fieldnames})
    return payload
