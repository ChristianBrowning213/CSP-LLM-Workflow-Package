"""Audit SPP objective contributions for a solved CIF.

This diagnostic is deliberately separate from the solver. It enumerates the
same periodic image convention used by qlip.interactions.spp.periodic_spp_sum
and reports whether each contact is backed by an explicit POT, a diagnostic
missing-pair fallback, or no contribution.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np
from ase.io import read

from qlip.interactions.spp import (
    DEFAULT_SPP_CUTOFF,
    SPPCollection,
    ZERO_DISTANCE_TOL,
    _image_depth,
    canonical_pair_key,
    periodic_pair_multiplicity,
    soft_missing_pair_penalty,
)


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return canonical_pair_key(a, b)


def _pair_name(pair: tuple[str, str]) -> str:
    return "-".join(pair)


def _load_supported_pairs(
    pot_root: Path,
    pairs: list[tuple[str, str]],
    cutoff: float,
    *,
    regularisation_spp_dir: Path | None,
    regularisation_weight: float,
) -> SPPCollection:
    collection = SPPCollection(
        pot_root,
        cutoff=cutoff,
        regularisation_spp_dir=regularisation_spp_dir,
        regularisation_weight=regularisation_weight,
    )
    existing: list[tuple[str, str]] = []
    for a, b in pairs:
        try:
            collection._resolve_pot_path(a, b)
        except RuntimeError:
            continue
        existing.append((a, b))
    if existing:
        collection.load(existing)
    return collection


def _all_pairs(symbols: list[str]) -> list[tuple[str, str]]:
    unique = sorted(set(symbols), key=str.lower)
    pairs: list[tuple[str, str]] = []
    for idx, a in enumerate(unique):
        for b in unique[idx:]:
            pairs.append(_pair_key(a, b))
    return pairs


def _fallback_value(collection: SPPCollection, distance: float) -> float:
    values = [float(spp(distance)) for spp in collection.spps.values()]
    return max(values) if values else 0.0


def _missing_pair_value(collection: SPPCollection, distance: float, policy: str) -> float:
    if policy == "soft_repulsive":
        return soft_missing_pair_penalty(distance)
    if policy in {"fallback", "max_global", "soft_generic_repulsive"}:
        return _fallback_value(collection, distance)
    return 0.0


def _enumerate_contributions(
    symbols: list[str],
    frac: np.ndarray,
    cell: np.ndarray,
    collection: SPPCollection,
    *,
    cutoff: float,
    missing_pair_policy: str,
    guidance_weight: float,
) -> list[dict[str, Any]]:
    depth = _image_depth(cell, cutoff)
    rows: list[dict[str, Any]] = []
    n = len(symbols)
    for i in range(n):
        for j in range(i, n):
            pair = _pair_key(symbols[i], symbols[j])
            pair_name = _pair_name(pair)
            spp = collection.spps.get(pair)
            reg_spp = getattr(collection, "regularisation_spps", {}).get(pair)
            regularisation_weight = float(getattr(collection, "regularisation_weight", 0.0) or 0.0)
            interaction_multiplicity = periodic_pair_multiplicity(i == j)
            for sx in range(-depth, depth + 1):
                for sy in range(-depth, depth + 1):
                    for sz in range(-depth, depth + 1):
                        shift = np.array([sx, sy, sz], dtype=float)
                        disp = (frac[j] + shift - frac[i]) @ cell
                        distance = float(np.linalg.norm(disp))
                        if distance <= ZERO_DISTANCE_TOL or distance > cutoff:
                            continue
                        if i == j and (sx, sy, sz) == (0, 0, 0):
                            continue
                        local_raw = (
                            float(spp(distance)) * interaction_multiplicity
                            if spp is not None
                            else 0.0
                        )
                        regularisation_raw = (
                            float(reg_spp(distance)) * interaction_multiplicity
                            if reg_spp is not None
                            else 0.0
                        )
                        regularisation_weighted_raw = regularisation_raw * regularisation_weight
                        if spp is not None and reg_spp is not None:
                            source = "explicit_spp_plus_regularisation"
                        elif spp is not None:
                            source = "explicit_spp"
                        elif reg_spp is not None:
                            source = "regularisation_only"
                        else:
                            source = "none"
                        missing_raw = 0.0
                        if spp is None and reg_spp is None and missing_pair_policy in {"fallback", "max_global", "soft_generic_repulsive", "soft_repulsive"}:
                            missing_raw = (
                                _missing_pair_value(collection, distance, missing_pair_policy)
                                * interaction_multiplicity
                            )
                            source = "missing_pair_fallback" if missing_raw != 0.0 else "none"
                        total_raw = local_raw + regularisation_weighted_raw + missing_raw
                        rows.append(
                            {
                                "site_i": i,
                                "site_j": j,
                                "species_i": symbols[i],
                                "species_j": symbols[j],
                                "pair_key": pair_name,
                                "distance": distance,
                                "image_shift": [int(sx), int(sy), int(sz)],
                                "interaction_multiplicity": interaction_multiplicity,
                                "within_cutoff": True,
                                "spp_supported": spp is not None,
                                "local_spp_supported": spp is not None,
                                "regularisation_supported": reg_spp is not None,
                                "missing_pair_fallback_used": source == "missing_pair_fallback",
                                "missing_pair_policy": missing_pair_policy,
                                "local_raw_contribution": local_raw,
                                "local_weighted_contribution": local_raw * guidance_weight,
                                "regularisation_raw_contribution": regularisation_raw,
                                "regularisation_weight": regularisation_weight,
                                "regularisation_weighted_contribution": regularisation_weighted_raw * guidance_weight,
                                "missing_pair_raw_contribution": missing_raw,
                                "missing_pair_weighted_contribution": missing_raw * guidance_weight,
                                "total_raw_contribution": total_raw,
                                "total_weighted_contribution": total_raw * guidance_weight,
                                "raw_contribution": total_raw,
                                "weighted_contribution": total_raw * guidance_weight,
                                "source": source,
                                "diagonal_self_image": i == j,
                            }
                        )
    return rows


def audit(
    cif_path: Path,
    pot_root: Path,
    *,
    cutoff: float,
    missing_pair_policy: str,
    guidance_weight: float,
    regularisation_spp_dir: Path | None = None,
    regularisation_weight: float = 0.0,
    top_k: int = 10,
) -> dict[str, Any]:
    atoms = read(str(cif_path))
    symbols = atoms.get_chemical_symbols()
    frac = atoms.get_scaled_positions()
    cell = np.asarray(atoms.cell.array, dtype=float)
    all_pairs = _all_pairs(symbols)
    collection = _load_supported_pairs(
        pot_root,
        all_pairs,
        cutoff,
        regularisation_spp_dir=regularisation_spp_dir,
        regularisation_weight=regularisation_weight,
    )
    supported_pairs = sorted(_pair_name(pair) for pair in collection.spps)
    regularisation_pairs = sorted(_pair_name(pair) for pair in getattr(collection, "regularisation_spps", {}))
    missing_pairs = sorted(_pair_name(pair) for pair in all_pairs if pair not in collection.spps)
    contributions = _enumerate_contributions(
        symbols,
        frac,
        cell,
        collection,
        cutoff=cutoff,
        missing_pair_policy=missing_pair_policy,
        guidance_weight=guidance_weight,
    )
    explicit = [row for row in contributions if row["source"] == "explicit_spp"]
    fallback = [row for row in contributions if row["source"] == "missing_pair_fallback"]
    regularisation = [row for row in contributions if row["regularisation_supported"]]
    none = [row for row in contributions if row["source"] == "none"]
    distances = [float(row["distance"]) for row in contributions]
    summary = {
        "cif_path": str(cif_path),
        "pot_root": str(pot_root),
        "cutoff": cutoff,
        "missing_pair_policy": missing_pair_policy,
        "guidance_weight": guidance_weight,
        "regularisation_spp_dir": str(regularisation_spp_dir) if regularisation_spp_dir else None,
        "regularisation_weight": regularisation_weight,
        "regularisation_enabled": float(regularisation_weight or 0.0) > 0.0,
        "regularisation_pairs_loaded": len(regularisation_pairs),
        "regularisation_pair_types_supported": regularisation_pairs,
        "regularisation_load_errors": list(getattr(collection, "regularisation_load_errors", []) or []),
        "atom_count": len(symbols),
        "pair_types_present": sorted(_pair_name(pair) for pair in all_pairs),
        "pair_types_supported_by_spp": supported_pairs,
        "missing_pair_types": missing_pairs,
        "total_spp_score": sum(float(row["raw_contribution"]) for row in contributions),
        "weighted_total_score": sum(float(row["weighted_contribution"]) for row in contributions),
        "contribution_count": len(contributions),
        "explicit_spp_contribution_count": len(explicit),
        "regularisation_contribution_count": len(regularisation),
        "missing_pair_fallback_contribution_count": len(fallback),
        "no_contribution_count": len(none),
        "shortest_contact": min(distances) if distances else None,
        "mean_contact_distance": mean(distances) if distances else None,
        "median_contact_distance": median(distances) if distances else None,
        "diagonal_self_image_contribution_count": sum(1 for row in contributions if row["diagonal_self_image"]),
        "diagonal_self_image_equivalent_pair_count": sum(
            float(row["interaction_multiplicity"])
            for row in contributions
            if row["diagonal_self_image"]
        ),
        "off_diagonal_contribution_count": sum(1 for row in contributions if not row["diagonal_self_image"]),
        "top_worst_pair_contributions": sorted(contributions, key=lambda row: row["weighted_contribution"], reverse=True)[:top_k],
        "top_best_pair_contributions": sorted(contributions, key=lambda row: row["weighted_contribution"])[:top_k],
        "shortest_contacts": sorted(contributions, key=lambda row: row["distance"])[:top_k],
        "note": "This is an SPP objective visibility diagnostic, not physical validation.",
    }
    return {"summary": summary, "contributions": contributions}


def write_outputs(payload: dict[str, Any], out_json: Path, out_csv: Path | None, out_md: Path | None) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows = payload["contributions"]
    if out_csv:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0].keys()) if rows else ["site_i", "site_j", "pair_key"]
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    if out_md:
        s = payload["summary"]
        lines = [
            "# SPP Objective Audit",
            "",
            "This report diagnoses SPP objective visibility and weighting. It is not physical validation.",
            "",
            f"- CIF: `{s['cif_path']}`",
            f"- POT root: `{s['pot_root']}`",
            f"- Cutoff: {s['cutoff']}",
            f"- Missing-pair policy: {s['missing_pair_policy']}",
            f"- Guidance weight: {s['guidance_weight']}",
            f"- Regularisation SPP dir: `{s['regularisation_spp_dir']}`",
            f"- Regularisation weight: {s['regularisation_weight']}",
            f"- Regularisation pairs loaded: {s['regularisation_pairs_loaded']}",
            f"- Total SPP score: {s['total_spp_score']}",
            f"- Weighted total SPP score: {s['weighted_total_score']}",
            f"- Shortest contact: {s['shortest_contact']}",
            f"- Supported pair types: {', '.join(s['pair_types_supported_by_spp']) or 'none'}",
            f"- Missing pair types: {', '.join(s['missing_pair_types']) or 'none'}",
            "",
            "## Shortest Contacts",
            "",
            "| pair | sites | distance | source | raw | weighted |",
            "|---|---|---:|---|---:|---:|",
        ]
        for row in s["shortest_contacts"]:
            lines.append(
                f"| {row['pair_key']} | {row['site_i']}-{row['site_j']} | {row['distance']:.6g} | "
                f"{row['source']} | {row['raw_contribution']:.6g} | {row['weighted_contribution']:.6g} |"
            )
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cif", required=True, type=Path)
    parser.add_argument("--pot-root", required=True, type=Path)
    parser.add_argument("--cutoff", type=float, default=DEFAULT_SPP_CUTOFF)
    parser.add_argument("--missing-pair-policy", default="neutral")
    parser.add_argument("--guidance-weight", type=float, default=1.0)
    parser.add_argument("--regularisation-spp-dir", type=Path)
    parser.add_argument("--regularization-spp-dir", type=Path)
    parser.add_argument("--regularisation-weight", "--regularization-weight", dest="regularisation_weight", type=float, default=0.0)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-csv", type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()
    payload = audit(
        args.cif,
        args.pot_root,
        cutoff=args.cutoff,
        missing_pair_policy=args.missing_pair_policy,
        guidance_weight=args.guidance_weight,
        regularisation_spp_dir=args.regularisation_spp_dir or args.regularization_spp_dir,
        regularisation_weight=args.regularisation_weight,
        top_k=args.top_k,
    )
    write_outputs(payload, args.out_json, args.out_csv, args.out_md)
    print(json.dumps(payload["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
