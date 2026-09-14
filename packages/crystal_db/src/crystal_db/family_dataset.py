"""Versioned, auditable dataset helpers for specialised oxide families."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Structure
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


DATASET_SCHEMA_VERSION = "mp_oxide_family_dataset.v1"
EXCLUDED_LAYERED_ELEMENTS = frozenset(
    {"B", "C", "N", "F", "Si", "P", "S", "Cl", "As", "Se", "Br", "I"}
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def spinel_stoichiometry_compatible(formula: str) -> bool:
    try:
        reduced = Composition(formula).reduced_composition
    except Exception:
        return False
    counts = sorted(round(float(amount), 8) for amount in reduced.values())
    return round(float(reduced.get("O", 0)), 8) == 4.0 and counts in (
        [1.0, 2.0, 4.0],
        [3.0, 4.0],
    )


def layered_oxide_candidate_reason(formula: str, working_ion: str) -> str | None:
    if working_ion not in {"Li", "Na"}:
        return "WRONG_WORKING_ION"
    try:
        composition = Composition(formula)
    except Exception:
        return "INVALID_FORMULA"
    elements = {element.symbol for element in composition.elements}
    if working_ion not in elements:
        return "WORKING_ION_ABSENT"
    if "O" not in elements:
        return "NOT_OXIDE"
    if elements & EXCLUDED_LAYERED_ELEMENTS:
        return "OUT_OF_SCOPE_POLYANION_OR_HALIDE"
    metals = [
        element.symbol
        for element in composition.elements
        if element.symbol not in {working_ion, "O"} and element.is_metal
    ]
    if not metals:
        return "NO_NON_ALKALI_METAL"
    return None


def canonical_structure_forms(structure: Structure) -> dict[str, Structure]:
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01)
    try:
        primitive = analyzer.get_primitive_standard_structure()
    except Exception:
        primitive = structure.get_primitive_structure()
    try:
        conventional = analyzer.get_conventional_standard_structure()
    except Exception:
        conventional = structure.copy()
    return {
        "source": structure.copy(),
        "primitive": primitive,
        "conventional": conventional,
    }


def write_structure_bundle(root: Path, material_id: str, structure: Structure) -> dict[str, Any]:
    forms = canonical_structure_forms(structure)
    paths: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for name, form in forms.items():
        text = str(CifWriter(form))
        path = root / name / f"{material_id}.cif"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
        paths[name] = str(path)
        hashes[name] = sha256_text(text)
    return {
        "paths": paths,
        "sha256": hashes,
        "site_counts": {name: len(form) for name, form in forms.items()},
    }


def structure_bundle_complete(bundle: dict[str, Any]) -> bool:
    paths = bundle.get("paths") or {}
    hashes = bundle.get("sha256") or {}
    for name in ("source", "primitive", "conventional"):
        path = Path(str(paths.get(name) or ""))
        if not path.is_file() or hashes.get(name) != sha256_text(path.read_text(encoding="utf-8")):
            return False
    return True


__all__ = [
    "DATASET_SCHEMA_VERSION",
    "EXCLUDED_LAYERED_ELEMENTS",
    "canonical_structure_forms",
    "json_safe",
    "layered_oxide_candidate_reason",
    "sha256_text",
    "spinel_stoichiometry_compatible",
    "structure_bundle_complete",
    "write_json_atomic",
    "write_structure_bundle",
]
