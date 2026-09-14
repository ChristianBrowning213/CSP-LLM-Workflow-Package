"""Metadata CSV parsing and matching helpers for property-conditioned fitting."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import numpy as np

from spp_maker.io_cif import LoadedCIF


@dataclass(frozen=True)
class MetaRow:
    """One metadata row keyed by CIF path or CIF filename."""

    row_index: int
    key_type: Literal["cif_path", "cif_name"]
    key: str
    property_label: str
    weight: float | None


@dataclass(frozen=True)
class MetaMap:
    """Parsed metadata table."""

    csv_path: Path
    has_weight_column: bool
    rows: tuple[MetaRow, ...]


@dataclass(frozen=True)
class MetaMatch:
    """Metadata rows matched to loaded CIFs in loaded order."""

    labels: tuple[str | None, ...]
    weights: tuple[float | None, ...]
    unmatched_meta_rows: int
    missing_meta_for_cifs: int


def _parse_optional_weight(raw: str, *, row_index: int) -> float | None:
    raw = raw.strip()
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid weight at metadata CSV row {row_index}: {raw!r}.") from exc
    if not np.isfinite(value):
        raise ValueError(f"Metadata weight at row {row_index} must be finite, got {value}.")
    if value < 0:
        raise ValueError(f"Metadata weight at row {row_index} must be >= 0, got {value}.")
    return value


def load_meta_map(meta_csv_path: Path) -> MetaMap:
    """
    Load metadata CSV.

    Required columns:
    - `property_label`
    - one of `cif_path` or `cif_name`

    Optional:
    - `weight`
    """
    meta_csv_path = meta_csv_path.resolve()
    if not meta_csv_path.is_file():
        raise ValueError(f"meta_csv is not a file: {meta_csv_path}")

    rows: list[MetaRow] = []
    with meta_csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        has_cif_path = "cif_path" in fieldnames
        has_cif_name = "cif_name" in fieldnames
        has_property_label = "property_label" in fieldnames
        has_weight = "weight" in fieldnames

        if not has_property_label:
            raise ValueError("meta_csv must include a 'property_label' column.")
        if not has_cif_path and not has_cif_name:
            raise ValueError("meta_csv must include either 'cif_path' or 'cif_name' column.")

        seen_keys: set[tuple[str, str]] = set()
        for row_index, row in enumerate(reader, start=2):
            label = (row.get("property_label") or "").strip()
            if label == "":
                raise ValueError(f"property_label is required at metadata CSV row {row_index}.")

            weight = _parse_optional_weight((row.get("weight") or ""), row_index=row_index)

            raw_path = (row.get("cif_path") or "").strip() if has_cif_path else ""
            raw_name = (row.get("cif_name") or "").strip() if has_cif_name else ""

            if raw_path != "":
                path_key = Path(raw_path)
                if not path_key.is_absolute():
                    path_key = (meta_csv_path.parent / path_key).resolve()
                else:
                    path_key = path_key.resolve()
                key_type: Literal["cif_path", "cif_name"] = "cif_path"
                key = str(path_key)
            elif raw_name != "":
                key_type = "cif_name"
                key = raw_name
            else:
                raise ValueError(
                    "Each metadata row must provide cif_path or cif_name; "
                    f"missing at row {row_index}."
                )

            uniq = (key_type, key)
            if uniq in seen_keys:
                raise ValueError(f"Duplicate metadata key at row {row_index}: {key_type}={key!r}.")
            seen_keys.add(uniq)

            rows.append(
                MetaRow(
                    row_index=row_index,
                    key_type=key_type,
                    key=key,
                    property_label=label,
                    weight=weight,
                )
            )

    return MetaMap(
        csv_path=meta_csv_path,
        has_weight_column=has_weight,
        rows=tuple(rows),
    )


def match_meta_rows(
    loaded_cifs: Sequence[LoadedCIF],
    meta_map: MetaMap,
) -> MetaMatch:
    """
    Match metadata rows onto loaded CIFs.

    Matching rules:
    - `cif_path` rows match on resolved absolute path.
    - `cif_name` rows match on filename.
    """
    index_by_path = {str(Path(item.path).resolve()): idx for idx, item in enumerate(loaded_cifs)}
    index_by_name = {Path(item.path).name: idx for idx, item in enumerate(loaded_cifs)}

    labels: list[str | None] = [None] * len(loaded_cifs)
    weights: list[float | None] = [None] * len(loaded_cifs)
    matched_indices: set[int] = set()
    unmatched_meta_rows = 0

    for row in meta_map.rows:
        if row.key_type == "cif_path":
            idx = index_by_path.get(row.key)
        else:
            idx = index_by_name.get(row.key)

        if idx is None:
            unmatched_meta_rows += 1
            continue

        if idx in matched_indices:
            raise ValueError(
                "Multiple metadata rows matched the same CIF: "
                f"{Path(loaded_cifs[idx].path).name!r}."
            )
        matched_indices.add(idx)

        labels[idx] = row.property_label
        weights[idx] = row.weight

    missing_meta_for_cifs = sum(1 for label in labels if label is None)
    return MetaMatch(
        labels=tuple(labels),
        weights=tuple(weights),
        unmatched_meta_rows=unmatched_meta_rows,
        missing_meta_for_cifs=missing_meta_for_cifs,
    )
