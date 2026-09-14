"""Utilities for dumping g(r) and exp(-phi) curves as CSV files."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence, Tuple

import numpy as np

from spp_maker.fit_hist import canonical_pair
from spp_maker.pot_io import bin_centers

PairKey = Tuple[str, str]


def parse_pair_values(values: Sequence[str] | None) -> list[PairKey] | None:
    """Parse pair tokens like `Na-Cl` or `Na,Cl` into canonical pair keys."""
    if not values:
        return None

    parsed: list[PairKey] = []
    seen: set[PairKey] = set()
    for raw in values:
        token = str(raw).strip()
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
        elif "," in token:
            left, right = token.split(",", 1)
        else:
            raise ValueError(f"Invalid pair token '{token}'. Use A-B (e.g. Na-Cl).")
        key = canonical_pair(left.strip(), right.strip())
        if key not in seen:
            seen.add(key)
            parsed.append(key)

    if not parsed:
        raise ValueError("No valid pairs parsed.")
    return parsed


def dump_gr_csv(
    *,
    out_dir: Path,
    edges: np.ndarray,
    pairs: Sequence[PairKey],
    g_rows: np.ndarray,
    phi_rows: np.ndarray,
    selected_pairs: Iterable[PairKey] | None = None,
) -> list[Path]:
    """
    Write one CSV per selected pair with columns: r, g, exp_minus_phi.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    edges_arr = np.asarray(edges, dtype=np.float64)
    r = bin_centers(edges_arr)
    g_arr = np.asarray(g_rows, dtype=np.float64)
    phi_arr = np.asarray(phi_rows, dtype=np.float64)
    if g_arr.shape != phi_arr.shape:
        raise ValueError(f"g_rows and phi_rows shape mismatch: {g_arr.shape} vs {phi_arr.shape}.")
    if g_arr.ndim != 2:
        raise ValueError(f"g_rows and phi_rows must be 2D, got ndim={g_arr.ndim}.")
    if g_arr.shape[1] != r.size:
        raise ValueError(
            f"Row width must match number of bins ({r.size}), got {g_arr.shape[1]}."
        )
    if len(pairs) != g_arr.shape[0]:
        raise ValueError(
            f"pairs length must match row count ({g_arr.shape[0]}), got {len(pairs)}."
        )

    index_by_pair = {pair: idx for idx, pair in enumerate(pairs)}
    if selected_pairs is None:
        use_pairs = list(pairs)
    else:
        use_pairs = []
        for pair in selected_pairs:
            if pair not in index_by_pair:
                raise ValueError(f"Requested pair not found: {pair}")
            use_pairs.append(pair)

    written: list[Path] = []
    for pair in use_pairs:
        row_idx = index_by_pair[pair]
        a, b = pair
        path = out_dir / f"{a}-{b}.csv"
        exp_minus_phi = np.exp(-phi_arr[row_idx])
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            writer = csv.writer(handle)
            writer.writerow(("r", "g", "exp_minus_phi"))
            for r_i, g_i, e_i in zip(r, g_arr[row_idx], exp_minus_phi):
                writer.writerow((f"{float(r_i):.8f}", f"{float(g_i):.8e}", f"{float(e_i):.8e}"))
        written.append(path)

    return written
