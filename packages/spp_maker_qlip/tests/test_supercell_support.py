"""Support-extent tests for supercell g(r) accumulation."""

from __future__ import annotations

import numpy as np
from ase import Atoms

from spp_maker.supercell_gr import build_supercell


def _face_heights(cell: np.ndarray) -> np.ndarray:
    a, b, c = cell[0], cell[1], cell[2]
    volume = float(abs(np.dot(a, np.cross(b, c))))
    return np.asarray(
        [
            volume / np.linalg.norm(np.cross(b, c)),
            volume / np.linalg.norm(np.cross(c, a)),
            volume / np.linalg.norm(np.cross(a, b)),
        ],
        dtype=np.float64,
    )


def test_build_supercell_support_for_skewed_cell() -> None:
    cell = np.asarray(
        [
            [3.1, 0.0, 0.0],
            [1.0, 3.7, 0.0],
            [0.5, 0.8, 4.2],
        ],
        dtype=np.float64,
    )
    atoms = Atoms("LiO", positions=[[0.0, 0.0, 0.0], [1.2, 1.1, 1.3]], cell=cell, pbc=True)

    r_max = 10.0
    sigma = 0.1
    margin = 0.5
    truncate_sigma = 3.0
    required = r_max + truncate_sigma * sigma + margin

    build = build_supercell(
        atoms,
        target_len=20.0,
        r_max=r_max,
        sigma=sigma,
        margin=margin,
        truncate_sigma=truncate_sigma,
    )

    assert build.gr_support_ok
    assert build.min_half_extent >= required

    heights = _face_heights(cell)
    half_extents = 0.5 * np.asarray(build.repeats, dtype=np.float64) * heights
    assert np.all(half_extents >= required - 1e-12)
