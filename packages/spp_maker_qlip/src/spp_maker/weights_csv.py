"""CSV utilities for optional per-structure weighting."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence

import numpy as np

from spp_maker.io_cif import LoadedCIF


def _parse_weight(raw: str, *, row_index: int) -> float:
    try:
        weight = float(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid weight at CSV row {row_index}: {raw!r}.") from exc
    if not np.isfinite(weight):
        raise ValueError(f"Weight at CSV row {row_index} must be finite, got {weight}.")
    if weight < 0:
        raise ValueError(f"Weight at CSV row {row_index} must be >= 0, got {weight}.")
    return weight


def load_structure_weights(
    *,
    weights_csv: Path,
    loaded_cifs: Sequence[LoadedCIF],
) -> list[float]:
    """
    Load structure weights from CSV.

    Supported CSV columns:
    - `cif_name` (filename only)
    - `cif_path` (relative/absolute path; preferred if column exists)
    - `weight` (nonnegative finite float)

    Returns one weight per item in `loaded_cifs`, defaulting to 1.0 when missing.
    """
    if not weights_csv.is_file():
        raise ValueError(f"weights_csv is not a file: {weights_csv}")

    with weights_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        has_path = "cif_path" in fieldnames
        has_name = "cif_name" in fieldnames
        has_weight = "weight" in fieldnames

        if not has_weight:
            raise ValueError("weights_csv must include a 'weight' column.")
        if not has_path and not has_name:
            raise ValueError("weights_csv must include either 'cif_path' or 'cif_name' column.")

        use_path = has_path
        by_path: dict[Path, float] = {}
        by_name: dict[str, float] = {}

        for row_index, row in enumerate(reader, start=2):
            raw_weight = (row.get("weight") or "").strip()
            if raw_weight == "":
                raise ValueError(f"Missing weight at CSV row {row_index}.")
            weight = _parse_weight(raw_weight, row_index=row_index)

            if use_path:
                raw_path = (row.get("cif_path") or "").strip()
                if raw_path == "":
                    raise ValueError(
                        "Missing cif_path at CSV row "
                        f"{row_index} while 'cif_path' column is in use."
                    )
                key_path = Path(raw_path)
                if not key_path.is_absolute():
                    key_path = (weights_csv.parent / key_path).resolve()
                else:
                    key_path = key_path.resolve()
                if key_path in by_path:
                    raise ValueError(f"Duplicate cif_path in weights_csv: {key_path}")
                by_path[key_path] = weight
            else:
                raw_name = (row.get("cif_name") or "").strip()
                if raw_name == "":
                    raise ValueError(
                        "Missing cif_name at CSV row "
                        f"{row_index} while 'cif_name' column is in use."
                    )
                if raw_name in by_name:
                    raise ValueError(f"Duplicate cif_name in weights_csv: {raw_name}")
                by_name[raw_name] = weight

    resolved_paths = [Path(item.path).resolve() for item in loaded_cifs]
    names = [Path(item.path).name for item in loaded_cifs]

    weights: list[float] = []
    for path_key, name_key in zip(resolved_paths, names):
        if use_path and path_key in by_path:
            weights.append(by_path[path_key])
        elif (not use_path) and name_key in by_name:
            weights.append(by_name[name_key])
        else:
            weights.append(1.0)

    return weights
