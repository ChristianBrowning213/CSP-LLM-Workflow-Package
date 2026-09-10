"""Export utilities for QLIP-compatible SPP directory layout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

import numpy as np

from .fit_phi import PhiResult
from .pot_io import bin_centers, write_pot

OobRecommendation = Literal["max", "clamp", "zero"]
MissingPairRecommendation = Literal["max_global", "error", "zero"]

_VALID_OOB_RECOMMENDATIONS: set[str] = {"max", "clamp", "zero"}
_VALID_MISSING_PAIR_RECOMMENDATIONS: set[str] = {"max_global", "error", "zero"}


def _validate_phi_result(phi_res: PhiResult) -> None:
    nbins = phi_res.binning.nbins
    npairs = len(phi_res.pairs)

    if phi_res.p.shape != (npairs, nbins):
        raise ValueError(f"phi_res.p must have shape ({npairs}, {nbins}), got {phi_res.p.shape}.")
    if phi_res.phi.shape != (npairs, nbins):
        raise ValueError(
            f"phi_res.phi must have shape ({npairs}, {nbins}), got {phi_res.phi.shape}."
        )
    if phi_res.counts.shape != (npairs, nbins):
        raise ValueError(
            f"phi_res.counts must have shape ({npairs}, {nbins}), got {phi_res.counts.shape}."
        )
    if not np.all(np.isfinite(phi_res.phi)):
        raise ValueError("phi_res.phi must be finite.")


def _resolve_guardrail_indices(
    *,
    r: np.ndarray,
    short_distance_bins: int | None,
    short_distance_r_max: float | None,
    manifest_extra: Optional[dict],
) -> np.ndarray:
    if short_distance_bins is not None:
        end = min(short_distance_bins, r.size)
        return np.arange(end, dtype=np.int64)

    if short_distance_r_max is not None:
        return np.nonzero(r <= short_distance_r_max)[0].astype(np.int64, copy=False)

    d_lo_from_manifest = None
    if manifest_extra is not None:
        bandpass = manifest_extra.get("bandpass")
        if isinstance(bandpass, dict):
            candidate = bandpass.get("d_lo")
            if isinstance(candidate, (int, float)) and np.isfinite(candidate):
                d_lo_from_manifest = float(candidate)

    if d_lo_from_manifest is not None:
        idx = np.nonzero(r <= d_lo_from_manifest)[0].astype(np.int64, copy=False)
        if idx.size > 0:
            return idx

    return np.array([0], dtype=np.int64)


def export_spp_root(
    out_root: Path,
    phi_res: PhiResult,
    *,
    name: str = "spp_run",
    write_manifest: bool = True,
    manifest_extra: Optional[dict] = None,
    oob_recommendation: OobRecommendation = "max",
    missing_pair_recommendation: MissingPairRecommendation = "max_global",
    short_distance_floor: Optional[float] = None,
    short_distance_bins: Optional[int] = None,
    short_distance_r_max: Optional[float] = None,
) -> Path:
    """
    Export `PhiResult` to a QLIP-compatible SPP root directory.

    Each pair `(A, B)` is written to:
      `<out_root>/<A>-<B>/<A>-<B>.POT`
    """
    _validate_phi_result(phi_res)
    if oob_recommendation not in _VALID_OOB_RECOMMENDATIONS:
        raise ValueError(
            "Invalid oob_recommendation "
            f"{oob_recommendation!r}; expected one of {sorted(_VALID_OOB_RECOMMENDATIONS)}."
        )
    if missing_pair_recommendation not in _VALID_MISSING_PAIR_RECOMMENDATIONS:
        raise ValueError(
            "Invalid missing_pair_recommendation "
            f"{missing_pair_recommendation!r}; expected one of "
            f"{sorted(_VALID_MISSING_PAIR_RECOMMENDATIONS)}."
        )
    if short_distance_bins is not None and short_distance_r_max is not None:
        raise ValueError("short_distance_bins and short_distance_r_max are mutually exclusive.")
    if short_distance_floor is None:
        if short_distance_bins is not None or short_distance_r_max is not None:
            raise ValueError(
                "short_distance_bins/short_distance_r_max require short_distance_floor."
            )
    else:
        if not np.isfinite(short_distance_floor) or short_distance_floor < 0:
            raise ValueError(
                f"short_distance_floor must be finite and >= 0, got {short_distance_floor}."
            )
        if short_distance_bins is not None and short_distance_bins <= 0:
            raise ValueError(
                f"short_distance_bins must be > 0, got {short_distance_bins}."
            )
        if short_distance_r_max is not None and not np.isfinite(short_distance_r_max):
            raise ValueError(
                f"short_distance_r_max must be finite, got {short_distance_r_max}."
            )

    out_root.mkdir(parents=True, exist_ok=True)

    edges = np.asarray(phi_res.binning.edges, dtype=np.float64)
    r = bin_centers(edges)
    guardrail_indices = (
        _resolve_guardrail_indices(
            r=r,
            short_distance_bins=short_distance_bins,
            short_distance_r_max=short_distance_r_max,
            manifest_extra=manifest_extra,
        )
        if short_distance_floor is not None
        else np.array([], dtype=np.int64)
    )

    manifest_pairs: list[dict[str, str]] = []
    for row_idx, (a, b) in enumerate(phi_res.pairs):
        pair_dirname = f"{a}-{b}"
        rel_path = f"{pair_dirname}/{pair_dirname}.POT"
        pot_path = out_root / rel_path
        u_vals = np.asarray(phi_res.phi[row_idx], dtype=np.float64).copy()
        if short_distance_floor is not None and guardrail_indices.size > 0:
            u_vals[guardrail_indices] = np.maximum(
                u_vals[guardrail_indices], float(short_distance_floor)
            )

        header_lines = [
            f"pair: {a}-{b}",
            f"alpha: {phi_res.alpha}",
            f"shifted: {phi_res.shifted}",
            f"nbins: {phi_res.binning.nbins}",
            f"d_min: {edges[0]}",
            f"d_max: {edges[-1]}",
            f"oob_recommendation: {oob_recommendation}",
            f"missing_pair_recommendation: {missing_pair_recommendation}",
        ]
        if short_distance_floor is not None:
            if short_distance_bins is not None:
                guard_spec = f"bins=0..{max(short_distance_bins - 1, 0)}"
            elif short_distance_r_max is not None:
                guard_spec = f"r<={short_distance_r_max}"
            else:
                guard_spec = (
                    "r<=bandpass.d_lo-or-first-bin"
                    if guardrail_indices.size > 0
                    else "none"
                )
            header_lines.append(
                f"short_distance_floor: {short_distance_floor} ({guard_spec})"
            )
        write_pot(
            pot_path,
            r=r,
            u=u_vals,
            header_lines=header_lines,
        )
        manifest_pairs.append({"A": a, "B": b, "path": rel_path})

    if write_manifest:
        manifest_data: dict = {
            "name": name,
            "alpha": float(phi_res.alpha),
            "shifted": bool(phi_res.shifted),
            "nbins": int(phi_res.binning.nbins),
            "edges": edges.tolist(),
            "pairs": manifest_pairs,
            "oob_recommendation": oob_recommendation,
            "missing_pair_recommendation": missing_pair_recommendation,
            "short_distance_floor": short_distance_floor,
            "short_distance_bins": short_distance_bins,
            "short_distance_r_max": short_distance_r_max,
        }
        if manifest_extra:
            manifest_data.update(manifest_extra)

        manifest_path = out_root / "manifest.json"
        with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest_data, handle, indent=2, sort_keys=True)
            handle.write("\n")

    return out_root
