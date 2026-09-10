"""Export canonical required-pair POT subsets from an explicit external library."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Iterable

from .required_pairs import derive_required_pairs, parse_formula_elements

SOURCE_POT_ROOT_ENV = "SPP_SOURCE_POT_ROOT"


def canonical_pair_label(left: str, right: str) -> str:
    """Return the source-compatible case-insensitive unordered pair label."""
    parts = sorted([left.strip().title(), right.strip().title()], key=str.lower)
    if not all(parts):
        raise ValueError("pair elements must be non-empty")
    return f"{parts[0]}-{parts[1]}"


def resolve_source_pot_root(source_pot_root: str | Path | None = None) -> Path:
    """Resolve an explicit source root, falling back only to SPP_SOURCE_POT_ROOT."""
    configured = source_pot_root if source_pot_root is not None else os.getenv(SOURCE_POT_ROOT_ENV)
    if configured is None or not str(configured).strip():
        raise ValueError(
            "source_pot_root is required; pass it explicitly or set SPP_SOURCE_POT_ROOT"
        )
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"source POT root is not a directory: {root}")
    return root


def _source_candidates(root: Path, pair: str) -> list[Path]:
    left, right = pair.split("-", 1)
    reverse = f"{right}-{left}"
    return [
        root / pair / f"{pair}.POT",
        root / reverse / f"{reverse}.POT",
        root / f"{pair}.POT",
        root / f"{reverse}.POT",
        root / f"{pair.upper()}.POT",
        root / reverse.upper() / f"{reverse.upper()}.POT",
        root / f"{reverse.upper()}.POT",
    ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_required_pot_subset(
    *,
    output_root: str | Path,
    formula: str | None = None,
    elements: Iterable[str] | None = None,
    source_pot_root: str | Path | None = None,
) -> dict[str, Any]:
    """Copy an exact, canonicalized required-pair subset without altering POT bytes."""
    if formula is None and elements is None:
        raise ValueError("formula or elements is required")
    element_list = parse_formula_elements(formula or "") if elements is None else list(elements)
    required_pairs = derive_required_pairs(element_list)
    source_root = resolve_source_pot_root(source_pot_root)
    destination = Path(output_root).expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"output_root must be empty or absent: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for pair in required_pairs:
        source = next((path for path in _source_candidates(source_root, pair) if path.is_file()), None)
        if source is None:
            missing.append(pair)
            continue
        pair_dir = destination / pair
        pair_dir.mkdir(parents=True, exist_ok=True)
        exported = pair_dir / f"{pair}.POT"
        shutil.copyfile(source, exported)
        source_hash = _sha256(source)
        exported_hash = _sha256(exported)
        if source_hash != exported_hash:
            raise RuntimeError(f"POT content hash changed during export: {pair}")
        resolved.append(
            {
                "pair": pair,
                "source_file": str(source),
                "exported_file": str(exported),
                "sha256": exported_hash,
                "source_name_was_reversed": source.stem.lower() != pair.lower(),
            }
        )

    status = "complete" if required_pairs and not missing else "incomplete"
    manifest = {
        "schema_version": "llm_csp.spp.required_pot_subset.v1",
        "status": status,
        "complete": status == "complete",
        "formula": formula,
        "elements": element_list,
        "required_pairs": required_pairs,
        "source_pot_root": str(source_root),
        "output_root": str(destination),
        "resolved_files": resolved,
        "exported_files": [item["exported_file"] for item in resolved],
        "missing_pairs": missing,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
