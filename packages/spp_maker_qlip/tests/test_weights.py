"""Tests for distance band-pass weighting."""

from __future__ import annotations

import numpy as np
import pytest

from spp_maker.weights import BandpassParams, bandpass_weight, sigmoid, validate_params


def test_validate_params_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        validate_params(BandpassParams(d_lo=0.0, d_hi=6.0, sigma_lo=0.1, sigma_hi=0.5))
    with pytest.raises(ValueError):
        validate_params(BandpassParams(d_lo=1.0, d_hi=1.0, sigma_lo=0.1, sigma_hi=0.5))
    with pytest.raises(ValueError):
        validate_params(BandpassParams(d_lo=1.0, d_hi=2.0, sigma_lo=0.0, sigma_hi=0.5))
    with pytest.raises(ValueError):
        validate_params(BandpassParams(d_lo=1.0, d_hi=2.0, sigma_lo=0.1, sigma_hi=0.0))


def test_bandpass_weight_scalar_limits() -> None:
    params = BandpassParams.defaults()

    below = bandpass_weight(params.d_lo - 10.0 * params.sigma_lo, params)
    mid = bandpass_weight((params.d_lo + params.d_hi) / 2.0, params)
    above = bandpass_weight(params.d_hi + 10.0 * params.sigma_hi, params)

    assert below < 1e-3
    assert mid > 0.5
    assert above < 1e-3


def test_bandpass_weight_vectorized_shape() -> None:
    params = BandpassParams.defaults()
    d = np.array([0.5, 1.0, 2.0, 4.0, 8.0], dtype=np.float64)

    w = bandpass_weight(d, params)

    assert isinstance(w, np.ndarray)
    assert w.shape == d.shape
    assert np.all(w >= 0.0)
    assert np.all(w <= 1.0)


def test_sigmoid_monotonic() -> None:
    x = np.array([-4.0, -1.0, 0.0, 1.0, 4.0], dtype=np.float64)
    y = sigmoid(x)

    assert isinstance(y, np.ndarray)
    assert np.all(np.diff(y) > 0.0)
