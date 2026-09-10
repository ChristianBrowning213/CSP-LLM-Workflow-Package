"""Read/write helpers for QLIP-compatible .POT files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import numpy as np


def bin_centers(edges: np.ndarray) -> np.ndarray:
    """
    Convert bin edges to bin centers.

    `edges` must be 1D, finite, strictly increasing, and length >= 2.
    """
    edges_arr = np.asarray(edges, dtype=np.float64)
    if edges_arr.ndim != 1:
        raise ValueError(f"edges must be 1D, got shape {tuple(edges_arr.shape)}.")
    if edges_arr.size < 2:
        raise ValueError("edges must contain at least two values.")
    if not np.all(np.isfinite(edges_arr)):
        raise ValueError("edges must be finite.")
    if not np.all(np.diff(edges_arr) > 0):
        raise ValueError("edges must be strictly increasing.")
    return 0.5 * (edges_arr[:-1] + edges_arr[1:])


def write_pot(
    path: Path,
    r: np.ndarray,
    u: np.ndarray,
    *,
    header_lines: Optional[Sequence[str]] = None,
    float_fmt: str = "{:.8f}",
) -> None:
    """
    Write a .POT file with optional comment headers and numeric rows.

    Numeric payload rows are formatted as `<r> <u>`.
    """
    r_arr = np.asarray(r, dtype=np.float64)
    u_arr = np.asarray(u, dtype=np.float64)

    if r_arr.ndim != 1 or u_arr.ndim != 1:
        raise ValueError("r and u must be 1D arrays.")
    if r_arr.shape != u_arr.shape:
        raise ValueError(f"r and u shapes must match, got {r_arr.shape} and {u_arr.shape}.")
    if not np.all(np.isfinite(r_arr)):
        raise ValueError("r must be finite.")
    if not np.all(np.isfinite(u_arr)):
        raise ValueError("u must be finite.")

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="\n") as handle:
        if header_lines:
            for line in header_lines:
                safe_line = str(line).replace("\n", " ").strip()
                handle.write(f"# {safe_line}\n")
        for r_i, u_i in zip(r_arr, u_arr):
            handle.write(f"{float_fmt.format(float(r_i))} {float_fmt.format(float(u_i))}\n")


def read_pot_like_qlip(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """
    Parse a .POT file with QLIP-like tolerance:
    skip lines that cannot be parsed as exactly two floats.
    """
    r_vals: list[float] = []
    u_vals: list[float] = []

    # Historical QLIP POT headers may contain Windows-1252 punctuation. Numeric
    # payloads are ASCII, so replacement decoding preserves every parsed value.
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                continue
            try:
                r_i = float(parts[0])
                u_i = float(parts[1])
            except ValueError:
                continue
            r_vals.append(r_i)
            u_vals.append(u_i)

    return np.asarray(r_vals, dtype=np.float64), np.asarray(u_vals, dtype=np.float64)
