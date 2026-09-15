"""Input and output helpers for SCA."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from sca.evaluators.cif_parse import parse_cif as parse_cif_new
from sca.schemas import CifMetadata, CrystalEvalRecord, CrystalEvaluationResult


RESULT_FIELDS = list(CrystalEvalRecord.model_fields.keys())


def parse_cif(path: str | Path):
    """Compatibility wrapper returning legacy CIF metadata plus Structure."""

    structure, result = parse_cif_new(path)
    cif_path = Path(path)
    metadata = CifMetadata(
        input_path=str(cif_path),
        file_name=cif_path.name,
        parse_ok=result.parse_ok,
        formula=result.formula,
        reduced_formula=result.reduced_formula,
        n_sites=result.n_sites,
        volume=result.volume,
        density=result.density,
        error_type=result.error_type,
        error_message=result.error_message,
    )
    return metadata, structure


def discover_cif_files(folder: str | Path, recursive: bool = True) -> list[Path]:
    """Return CIF files in a folder, sorted for deterministic batch output."""

    folder_path = Path(folder)
    iterator = folder_path.rglob("*.cif") if recursive else folder_path.glob("*.cif")
    return sorted(path for path in iterator if path.is_file())


def load_manifest(csv_path: str | Path, path_col: str) -> list[Path]:
    """Load CIF paths from a CSV manifest and resolve relative paths."""

    frame = load_manifest_frame(csv_path, path_col)
    return [Path(path) for path in frame[path_col].tolist()]


def load_manifest_frame(csv_path: str | Path, path_col: str) -> pd.DataFrame:
    manifest_path = Path(csv_path)
    frame = pd.read_csv(manifest_path)
    if path_col not in frame.columns:
        available = ", ".join(frame.columns)
        raise ValueError(f"Manifest column '{path_col}' not found. Available columns: {available}")
    frame = frame.copy()
    frame[path_col] = [
        str(resolve_manifest_path(path, manifest_path))
        for path in (Path(str(value)) for value in frame[path_col])
    ]
    return frame


def resolve_manifest_path(path: str | Path, manifest_path: str | Path) -> Path:
    """Resolve manifest paths while preserving repo-root-relative entries.

    Manifest-relative paths remain supported, but paths that already exist from
    the current working directory are treated as intentionally repo-root/current
    working directory relative.
    """

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    return (Path(manifest_path).parent / candidate).resolve()


def write_single_json(result: CrystalEvalRecord | CrystalEvaluationResult, output_path: str | Path) -> None:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


def write_csv(results: Iterable[Any], output_path: str | Path) -> None:
    rows = [_to_row(result) for result in results]
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        pd.DataFrame(columns=RESULT_FIELDS).to_csv(out, index=False)
        return
    pd.DataFrame(rows).to_csv(out, index=False)


def write_jsonl(results: Iterable[Any], output_path: str | Path) -> None:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(_to_row(result), ensure_ascii=False) + "\n")


def write_summary_csv(rows: Iterable[Any], output_path: str | Path) -> None:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([_to_row(row) for row in rows]).to_csv(out, index=False)


def _to_row(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_row"):
        return result.to_row()
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if isinstance(result, dict):
        return result
    return dict(result)
