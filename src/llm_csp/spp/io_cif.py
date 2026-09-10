"""Thin CIF loading adapter built on ASE."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Union

import ase
import numpy as np
from ase.io import read


@dataclass(frozen=True)
class LoadedCIF:
    """Normalized CIF payload used by downstream pipeline stages."""

    path: str
    atoms: "ase.Atoms"
    symbols: tuple[str, ...]
    positions: "np.ndarray"
    cell: "np.ndarray"
    pbc: tuple[bool, bool, bool]


def _coerce_pbc(pbc_like: object) -> tuple[bool, bool, bool]:
    pbc_array = np.asarray(pbc_like, dtype=bool)
    if pbc_array.ndim == 0:
        value = bool(pbc_array.item())
        return (value, value, value)

    flat = pbc_array.reshape(-1)
    if flat.size == 1:
        value = bool(flat.item())
        return (value, value, value)
    if flat.size == 3:
        return tuple(bool(x) for x in flat.tolist())
    raise ValueError(f"Invalid pbc shape {tuple(pbc_array.shape)}; expected scalar or 3 values.")


def _coerce_cell(cell_like: object) -> np.ndarray:
    cell = np.asarray(cell_like, dtype=float)
    if cell.shape == (3, 3):
        return cell
    if cell.ndim == 1 and cell.size == 3:
        return np.diag(cell)
    if cell.ndim == 1 and cell.size == 9:
        return cell.reshape(3, 3)
    raise ValueError(f"Invalid cell shape {tuple(cell.shape)}; expected (3, 3).")


def _coerce_positions(positions_like: object, expected_atoms: int) -> np.ndarray:
    positions = np.asarray(positions_like, dtype=float)
    if positions.ndim == 1:
        if positions.size == 0 and expected_atoms == 0:
            return positions.reshape(0, 3)
        if positions.size % 3 != 0:
            raise ValueError(
                f"Invalid positions length {positions.size}; cannot reshape to (N, 3)."
            )
        positions = positions.reshape((-1, 3))

    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError(f"Invalid positions shape {tuple(positions.shape)}; expected (N, 3).")
    if positions.shape[0] != expected_atoms:
        raise ValueError(
            "Mismatch between positions and atom symbols: "
            f"{positions.shape[0]} vs {expected_atoms}."
        )
    return positions


def load_cif(path: Union[str, Path], *, primitive: bool = False) -> LoadedCIF:
    """
    Load one CIF file into a normalized ASE atoms payload.

    Raises:
        ValueError: If the file cannot be loaded or normalized.
    """
    path_obj = Path(path)
    _ = primitive  # Reserved for future reader configuration.

    try:
        if not path_obj.is_file():
            raise FileNotFoundError(f"Path is not a file: {path_obj}")

        atoms = read(path_obj)
        symbols = tuple(str(sym) for sym in atoms.get_chemical_symbols())

        positions = _coerce_positions(atoms.get_positions(), expected_atoms=len(symbols))
        cell = _coerce_cell(atoms.cell.array)
        pbc = _coerce_pbc(atoms.get_pbc())

        atoms.set_positions(positions)
        atoms.set_cell(cell)
        atoms.set_pbc(pbc)

        return LoadedCIF(
            path=str(path_obj),
            atoms=atoms,
            symbols=symbols,
            positions=positions,
            cell=cell,
            pbc=pbc,
        )
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise ValueError(f"Failed to load CIF '{path_obj}': {exc}") from exc


def load_cifs_from_dir(cif_dir: Union[str, Path]) -> list[LoadedCIF]:
    """
    Load all `*.cif` files from a directory in deterministic filename order.

    Matching is case-insensitive and non-recursive.
    """
    cif_dir_path = Path(cif_dir)
    if not cif_dir_path.is_dir():
        raise ValueError(f"Expected CIF directory, got: {cif_dir_path}")

    cif_paths = sorted(
        (
            entry
            for entry in cif_dir_path.iterdir()
            if entry.is_file() and entry.suffix.lower() == ".cif"
        ),
        key=lambda entry: entry.name.lower(),
    )
    return [load_cif(path) for path in cif_paths]
