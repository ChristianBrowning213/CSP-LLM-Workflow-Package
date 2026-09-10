"""Convert pairwise distance histograms into smoothed SPP penalty curves."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

from .fit_hist import Binning, HistAccumulator, PairKey


@dataclass(frozen=True)
class PhiResult:
    """Stacked probabilities and phi curves for canonical species pairs."""

    binning: Binning
    alpha: float
    shifted: bool
    pairs: tuple[PairKey, ...]
    p: np.ndarray
    phi: np.ndarray
    counts: np.ndarray

    def index_of(self, key: PairKey) -> int:
        """Return row index for `key` or raise ValueError if it is absent."""
        try:
            return self.pairs.index(key)
        except ValueError as exc:
            raise ValueError(f"Pair key not present: {key}") from exc


def compute_probabilities(counts: np.ndarray, *, alpha: float) -> np.ndarray:
    """
    Compute Laplace-smoothed probabilities along the last axis.

    Formula:
      p = (counts + alpha) / (sum(counts) + alpha * nbins)
    """
    if not np.isfinite(alpha):
        raise ValueError(f"alpha must be finite, got {alpha}.")
    if alpha <= 0:
        raise ValueError(f"alpha must be > 0, got {alpha}.")

    counts_arr = np.asarray(counts, dtype=np.float64)
    if counts_arr.ndim < 1:
        raise ValueError("counts must have at least one dimension.")
    if counts_arr.shape[-1] < 1:
        raise ValueError("counts last dimension (nbins) must be >= 1.")
    if not np.all(np.isfinite(counts_arr)):
        raise ValueError("counts must be finite.")
    if np.any(counts_arr < 0):
        raise ValueError("counts must be >= 0.")

    nbins = counts_arr.shape[-1]
    numer = counts_arr + float(alpha)
    denom = np.sum(counts_arr, axis=-1, keepdims=True) + float(alpha) * nbins
    p = numer / denom
    return p.astype(np.float64, copy=False)


def compute_phi(p: np.ndarray) -> np.ndarray:
    """Return `-log(p)` after validating probability bounds."""
    p_arr = np.asarray(p, dtype=np.float64)
    if p_arr.ndim < 1:
        raise ValueError("p must have at least one dimension.")
    if p_arr.shape[-1] < 1:
        raise ValueError("p last dimension (nbins) must be >= 1.")
    if not np.all(np.isfinite(p_arr)):
        raise ValueError("p must be finite.")
    if np.any(p_arr <= 0):
        raise ValueError("p must be strictly positive.")
    if np.any(p_arr > 1.0):
        raise ValueError("p must be <= 1.")

    return -np.log(p_arr)


def shift_phi_min_zero(phi: np.ndarray) -> np.ndarray:
    """Shift each row along the last axis so the row minimum is exactly zero."""
    phi_arr = np.asarray(phi, dtype=np.float64)
    if phi_arr.ndim < 1:
        raise ValueError("phi must have at least one dimension.")
    if phi_arr.shape[-1] < 1:
        raise ValueError("phi last dimension (nbins) must be >= 1.")
    if not np.all(np.isfinite(phi_arr)):
        raise ValueError("phi must be finite.")
    return phi_arr - np.min(phi_arr, axis=-1, keepdims=True)


def _validate_hist_counts(
    hist: HistAccumulator,
    ordered_pairs: tuple[PairKey, ...],
) -> np.ndarray:
    nbins = hist.binning.nbins
    rows = []
    for key in ordered_pairs:
        values = np.asarray(hist.counts[key], dtype=np.float64)
        if values.shape != (nbins,):
            raise ValueError(
                f"Histogram counts for pair {key} must have shape ({nbins},), got {values.shape}."
            )
        if not np.all(np.isfinite(values)):
            raise ValueError(f"Histogram counts for pair {key} must be finite.")
        if np.any(values < 0):
            raise ValueError(f"Histogram counts for pair {key} must be >= 0.")
        rows.append(values)

    if not rows:
        return np.zeros((0, nbins), dtype=np.float64)
    return np.vstack(rows).astype(np.float64, copy=False)


def build_phi_from_hist(
    hist: HistAccumulator,
    *,
    alpha: float = 1e-3,
    shifted: bool = True,
    include_zero_pairs: bool = False,
) -> PhiResult:
    """
    Convert histogram counts into smoothed probabilities and phi penalty curves.

    Pair ordering is lexicographic for deterministic row layout.
    """
    # Re-validate edges to guard against externally mutated/constructed objects.
    binning = Binning(edges=np.array(hist.binning.edges, dtype=np.float64, copy=True))
    _ = include_zero_pairs  # Placeholder for future pair-universe support.

    ordered_pairs: tuple[PairKey, ...] = tuple(sorted(hist.counts.keys()))
    counts = _validate_hist_counts(hist, ordered_pairs)

    p = compute_probabilities(counts, alpha=alpha)
    phi = compute_phi(p)
    if shifted:
        phi = shift_phi_min_zero(phi)

    return PhiResult(
        binning=binning,
        alpha=float(alpha),
        shifted=bool(shifted),
        pairs=ordered_pairs,
        p=p,
        phi=phi,
        counts=counts,
    )
