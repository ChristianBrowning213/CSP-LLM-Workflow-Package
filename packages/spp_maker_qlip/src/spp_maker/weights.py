"""Distance band-pass weighting utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import numpy as np

ArrayLike = Union[float, np.ndarray]

_SIGMOID_CLIP = 60.0


@dataclass(frozen=True)
class BandpassParams:
    """Parameters controlling smooth short- and long-range suppression."""

    d_lo: float
    d_hi: float
    sigma_lo: float
    sigma_hi: float

    @staticmethod
    def defaults() -> "BandpassParams":
        """
        Provide conservative defaults suitable for inorganic solids.
        These are starting points and expected to be tuned.
        """
        return BandpassParams(d_lo=1.2, d_hi=6.0, sigma_lo=0.15, sigma_hi=0.50)


def validate_params(params: BandpassParams) -> None:
    """
    Raise ValueError for invalid band-pass parameters.

    Requirements:
    - d_lo > 0
    - d_hi > d_lo
    - sigma_lo > 0
    - sigma_hi > 0
    """
    if params.d_lo <= 0:
        raise ValueError(f"d_lo must be > 0, got {params.d_lo}.")
    if params.d_hi <= params.d_lo:
        raise ValueError(
            f"d_hi must be > d_lo, got d_hi={params.d_hi} and d_lo={params.d_lo}."
        )
    if params.sigma_lo <= 0:
        raise ValueError(f"sigma_lo must be > 0, got {params.sigma_lo}.")
    if params.sigma_hi <= 0:
        raise ValueError(f"sigma_hi must be > 0, got {params.sigma_hi}.")


def sigmoid(x: ArrayLike) -> ArrayLike:
    """
    Numerically stable logistic sigmoid.

    For array input, returns `np.ndarray`.
    For scalar input, returns `float`.
    """
    x_array = np.asarray(x)
    if np.issubdtype(x_array.dtype, np.floating):
        dtype = x_array.dtype
    else:
        dtype = np.float64

    clipped = np.clip(x_array.astype(dtype, copy=False), -_SIGMOID_CLIP, _SIGMOID_CLIP)
    result = 1.0 / (1.0 + np.exp(-clipped))

    if np.isscalar(x):
        return float(result)
    return result


def bandpass_weight(d: ArrayLike, params: BandpassParams) -> ArrayLike:
    """
    Smooth band-pass weighting:
      w(d) = sigmoid((d - d_lo)/sigma_lo) * sigmoid((d_hi - d)/sigma_hi)

    Properties:
    - w(d) ~ 0 for d << d_lo
    - w(d) ~ 1 for d_lo << d << d_hi (approximately)
    - w(d) ~ 0 for d >> d_hi
    """
    validate_params(params)

    d_array = np.asarray(d)
    if np.issubdtype(d_array.dtype, np.floating):
        dtype = d_array.dtype
    else:
        dtype = np.float64
    d_float = d_array.astype(dtype, copy=False)

    lo_gate = sigmoid((d_float - params.d_lo) / params.sigma_lo)
    hi_gate = sigmoid((params.d_hi - d_float) / params.sigma_hi)

    weights = np.asarray(lo_gate) * np.asarray(hi_gate)
    if np.isscalar(d):
        return float(weights)
    return weights
