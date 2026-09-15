"""Frozen, independent family-topology validation for Dataset E."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Lattice, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


VALIDATOR_VERSION = "dataset_e.anonymous_development_topology_matcher.v1"
MATCHER_SETTINGS = {
    "ltol": 0.2,
    "stol": 0.3,
    "angle_tol": 5.0,
    "primitive_cell": True,
    "scale": True,
    "attempt_supercell": False,
}
SYMMETRY_TOLERANCE = 0.05
_REPO = Path(__file__).resolve().parents[3]
_TEMPLATES = (
    _REPO
    / "artifacts"
    / "Paper_scaffolds_september"
    / "Dataset_E_complex_topology_showcase"
    / "DEVELOPMENT_SCAFFOLD_TEMPLATES.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_development_references(subtype: str) -> tuple[tuple[str, Structure], ...]:
    payload = json.loads(_TEMPLATES.read_text(encoding="utf-8"))
    result = []
    for item in payload["templates"]:
        if item["subtype"] != subtype:
            continue
        structure = Structure(
            Lattice(item["lattice_matrix"]),
            item["source_species_by_site"],
            item["fractional_coordinates"],
        )
        result.append((str(item["development_structure_id"]), structure))
    if not result:
        raise ValueError(f"no frozen development references for {subtype!r}")
    return tuple(result)


def validate_dataset_e_topology(structure: Structure, subtype: str) -> dict[str, Any]:
    """Return PASS only for an anonymous match to the frozen subtype references."""
    matcher = StructureMatcher(**MATCHER_SETTINGS)
    matches = [
        reference_id
        for reference_id, reference in load_development_references(subtype)
        if matcher.fit_anonymous(structure, reference)
    ]
    ordered = bool(structure.is_ordered)
    status = "PASS" if ordered and matches else "FAIL"
    analyzer = SpacegroupAnalyzer(structure, symprec=SYMMETRY_TOLERANCE)
    return {
        "validator_version": VALIDATOR_VERSION,
        "status": status,
        "ordered": ordered,
        "subtype": subtype,
        "anonymous_development_reference_matches": matches,
        "match_count": len(matches),
        "detected_space_group_symbol": analyzer.get_space_group_symbol(),
        "detected_space_group_number": analyzer.get_space_group_number(),
        "matcher_settings": dict(MATCHER_SETTINGS),
        "symmetry_tolerance": SYMMETRY_TOLERANCE,
        "development_templates_sha256": _sha256(_TEMPLATES),
        "criterion": "ordered AND anonymous StructureMatcher match to same-subtype development reference",
    }


__all__ = [
    "MATCHER_SETTINGS",
    "SYMMETRY_TOLERANCE",
    "VALIDATOR_VERSION",
    "load_development_references",
    "validate_dataset_e_topology",
]
