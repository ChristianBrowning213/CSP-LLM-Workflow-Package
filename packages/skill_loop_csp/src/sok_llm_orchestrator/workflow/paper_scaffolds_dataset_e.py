"""Development-derived, target-blind ordered scaffolds for Dataset E.

Fractional topology and cell shape are taken only from the hash-frozen
development roster.  Absolute cell volume is selected from target-excluded
retrieval evidence using the unchanged v2 VPA policy.  Final reference
coordinates and lattice constants are never accepted by this module.
"""

from __future__ import annotations

from collections import Counter
import itertools
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from pymatgen.core import Composition, Lattice, Structure

from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import (
    ScaffoldAlternative,
    cell_vpa_candidates,
)
from sok_llm_orchestrator.workflow.scaffold_ablation import count_orbit_assignments


SCAFFOLD_LIBRARY_VERSION = "dataset_e.complex_ordered_scaffolds.v1"
SUPPORTED_SUBTYPES = {
    "NASICON_R3_PHOSPHATE",
    "RP_N1",
    "RP_N2",
    "GARNET_IA3D",
    "GARNET_I41ACD",
    "ARGYRODITE_F43M",
    "ARGYRODITE_PNA21",
    "ARGYRODITE_CC",
}
_REPO = Path(__file__).resolve().parents[3]
_ARTIFACT = (
    _REPO
    / "artifacts"
    / "Paper_scaffolds_september"
    / "Dataset_E_complex_topology_showcase"
)
_TEMPLATES = _ARTIFACT / "DEVELOPMENT_SCAFFOLD_TEMPLATES.json"
_FREEZE = _ARTIFACT / "DEVELOPMENT_ROSTER_FREEZE.json"

_CHALCOGEN = {"O", "S", "Se", "Te"}
_HALIDE = {"F", "Cl", "Br", "I"}


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_templates() -> tuple[dict[str, Any], ...]:
    freeze = json.loads(_FREEZE.read_text(encoding="utf-8"))
    if _sha256(_TEMPLATES) != freeze["templates_sha256"]:
        raise RuntimeError("Dataset E development template hash mismatch")
    payload = json.loads(_TEMPLATES.read_text(encoding="utf-8"))
    return tuple(payload["templates"])


def _role(symbol: str, subtype: str) -> str:
    mobile = (
        (subtype.startswith("ARGYRODITE_") and symbol in {"Li", "Ag", "Cu"})
        or (subtype.startswith("NASICON_") and symbol in {"Li", "Na", "K", "Rb", "Cs"})
        or (subtype == "GARNET_I41ACD" and symbol == "Li")
    )
    if mobile:
        return "mobile_cation"
    tetrahedral = (
        (subtype.startswith("NASICON_") and symbol in {"P", "Si"})
        or (
            subtype.startswith("ARGYRODITE_")
            and symbol in {"B", "Si", "Ge", "Sn", "P", "As"}
        )
    )
    if tetrahedral:
        return "tetrahedral_former"
    if symbol in _CHALCOGEN:
        return "framework_chalcogen"
    if symbol in _HALIDE:
        return "framework_halide"
    return "framework_cation"


def _integer_target_counts(formula: str, site_count: int) -> Counter[str] | None:
    composition = Composition(formula).reduced_composition
    scale = site_count / float(composition.num_atoms)
    counts: Counter[str] = Counter()
    for element, amount in composition.items():
        value = float(amount) * scale
        rounded = round(value)
        if not math.isclose(value, rounded, abs_tol=1e-8):
            return None
        counts[str(element)] = rounded
    return counts if sum(counts.values()) == site_count else None


def _species_mappings(template: Mapping[str, Any], formula: str) -> tuple[dict[str, str], ...]:
    subtype = str(template["subtype"])
    source_counts = Counter(str(value) for value in template["source_species_by_site"])
    target_counts = _integer_target_counts(formula, int(template["site_count"]))
    if target_counts is None or len(source_counts) != len(target_counts):
        return ()
    candidates: list[list[str]] = []
    sources = sorted(source_counts)
    for source in sources:
        candidates.append(
            sorted(
                target
                for target, count in target_counts.items()
                if count == source_counts[source]
                and _role(target, subtype) == _role(source, subtype)
            )
        )
    mappings = []
    for targets in itertools.product(*candidates):
        if len(set(targets)) == len(targets):
            mappings.append(dict(zip(sources, targets, strict=True)))
    return tuple(mappings)


def _scaled_lattice(matrix: list[list[float]], vpa: float, site_count: int) -> Lattice:
    base = Lattice(matrix)
    factor = ((vpa * site_count) / base.volume) ** (1.0 / 3.0)
    return Lattice(base.matrix * factor)


def _ordered_orbits(
    template: Mapping[str, Any], mapping: Mapping[str, str]
) -> tuple[dict[str, Any], ...]:
    result = []
    for source in template["orbits"]:
        species = mapping[str(source["source_species"])]
        result.append(
            {
                "orbit_id": str(source["orbit_id"]),
                "site_indices": [int(index) for index in source["site_indices"]],
                "allowed_species": [species],
                "fixed_species": species,
                "required_occupancy": True,
                "vacancy_allowed": False,
                "allow_partial_occupation": False,
                "occupation_mode": "FIXED_FULL_ORBIT",
                "topology_role": _role(
                    str(source["source_species"]), str(template["subtype"])
                ),
            }
        )
    return tuple(result)


def build_dataset_e_alternatives(
    task: Mapping[str, Any], *, evidence_records: Iterable[Mapping[str, Any]] = ()
) -> tuple[ScaffoldAlternative, ...]:
    """Build exact-composition alternatives without consulting a final reference."""
    formula = str(task["formula"])
    subtype = str(task.get("topology_subclass") or "").upper()
    if subtype not in SUPPORTED_SUBTYPES:
        raise ValueError(f"unsupported Dataset E topology subtype: {subtype!r}")
    vpas, cell_provenance = cell_vpa_candidates(formula, evidence_records)
    alternatives: list[ScaffoldAlternative] = []
    for template in _load_templates():
        if template["subtype"] != subtype:
            continue
        for mapping_index, mapping in enumerate(_species_mappings(template, formula)):
            orbits = _ordered_orbits(template, mapping)
            for vpa_index, vpa in enumerate(vpas):
                lattice = _scaled_lattice(
                    template["lattice_matrix"], float(vpa), int(template["site_count"])
                )
                species = [mapping[str(value)] for value in template["source_species_by_site"]]
                structure = Structure(lattice, species, template["fractional_coordinates"])
                feasible = count_orbit_assignments(formula, len(structure), list(orbits))
                if feasible != 1:
                    raise ValueError(
                        f"{subtype} template {template['template_id']} did not give one exact ordered state"
                    )
                alternative_id = (
                    f"{subtype.lower()}_{template['development_structure_id']}_"
                    f"m{mapping_index}_vpa{vpa_index}"
                )
                provenance = {
                    "scaffold_library_version": SCAFFOLD_LIBRARY_VERSION,
                    "family_policy": str(task.get("family") or ""),
                    "topology_subclass": subtype,
                    "development_template_id": template["template_id"],
                    "development_structure_id": template["development_structure_id"],
                    "development_template_hash": _sha256(_TEMPLATES),
                    "species_role_mapping": dict(mapping),
                    "vpa_A3_per_atom": float(vpa),
                    "cell_evidence": cell_provenance,
                    "fractional_topology_source": "hash_frozen_development_roster",
                    "cell_shape_source": "hash_frozen_development_roster",
                    "absolute_volume_source": cell_provenance["source"],
                    "ordered_only": True,
                    "partial_occupancy_allowed": False,
                    "target_coordinates_consumed": False,
                    "target_lattice_consumed": False,
                }
                alternatives.append(
                    ScaffoldAlternative(
                        alternative_id=alternative_id,
                        scaffold_id=f"dataset_e_{alternative_id}_v1",
                        family_policy=str(task.get("family") or "").upper(),
                        geometry_class=f"{subtype}_DEVELOPMENT_DERIVED",
                        structure=structure,
                        ordered_orbits=orbits,
                        feasible_state_count=feasible,
                        provenance=provenance,
                    )
                )
    if not alternatives:
        raise ValueError(f"no development-derived {subtype} scaffold represents {formula}")
    return tuple(alternatives)


__all__ = [
    "SCAFFOLD_LIBRARY_VERSION",
    "SUPPORTED_SUBTYPES",
    "build_dataset_e_alternatives",
]
