"""Tests for POT read/write helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from spp_maker.pot_io import read_pot_like_qlip, write_pot


def test_write_and_read_pot_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "Na-Cl" / "Na-Cl.POT"
    r = np.array([1.25, 1.75, 2.25], dtype=np.float64)
    u = np.array([0.2, 0.5, 1.1], dtype=np.float64)

    write_pot(
        path,
        r,
        u,
        header_lines=["pair: Na-Cl", "nbins: 3"],
    )

    r_read, u_read = read_pot_like_qlip(path)
    assert r_read.shape == r.shape
    assert u_read.shape == u.shape
    assert np.allclose(r_read, r, atol=1e-8)
    assert np.allclose(u_read, u, atol=1e-8)
