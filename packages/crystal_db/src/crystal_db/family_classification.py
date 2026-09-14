"""Deterministic family classifiers for specialised Materials Project corpora."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any

from pymatgen.analysis.local_env import CrystalNN
from pymatgen.core import Element, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


CLASSIFIER_VERSION = "mp_oxide_family.v1"
LAYERED_FAMILY = "layered_battery_oxide"
SPINEL_FAMILY = "spinel_oxide"
ALKALI = {"Li", "Na"}
POLYANION_CENTRES = {"B", "C", "N", "P", "S", "Si", "As", "Se"}
LAYERED_TERMS = (
    "layered", "layers of", "layer of", "two-dimensional", "2-dimensional",
    "alpha-nafeo2", "caswellsilverite", "o3-type", "o2-type", "p2-type", "p3-type",
)
WRONG_LAYERED_TERMS = (
    "spinel", "olivine", "nasicon", "nzp", "tunnel structure", "molecular",
)
SPINEL_TERMS = ("spinel", "spinel-like", "spinel derived", "spinel-derived")


@dataclass(frozen=True, slots=True)
class FamilyDecision:
    family: str
    accepted: bool
    status: str
    reason_codes: tuple[str, ...]
    evidence: dict[str, Any] = field(default_factory=dict)
    classifier_version: str = CLASSIFIER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _primitive(structure: Structure) -> Structure:
    try:
        return SpacegroupAnalyzer(structure, symprec=0.01).get_primitive_standard_structure()
    except Exception:
        return structure.get_primitive_structure()


def _text(description: str | None, condensed: dict[str, Any] | None) -> str:
    structured = json.dumps(condensed or {}, sort_keys=True, default=str)
    return f"{description or ''} {structured}".lower()


def _common_rejection(
    structure: Structure,
    *,
    family: str,
    max_primitive_sites: int,
) -> FamilyDecision | None:
    primitive_sites = len(_primitive(structure))
    evidence = {
        "ordered": bool(structure.is_ordered),
        "primitive_site_count": primitive_sites,
        "max_primitive_sites": int(max_primitive_sites),
        "elements": sorted(element.symbol for element in structure.composition.elements),
    }
    if not structure.is_ordered:
        return FamilyDecision(family, False, "REJECTED", ("DISORDERED",), evidence)
    if primitive_sites > max_primitive_sites:
        return FamilyDecision(family, False, "REJECTED", ("TOO_LARGE",), evidence)
    if "O" not in evidence["elements"]:
        return FamilyDecision(family, False, "REJECTED", ("NOT_OXIDE",), evidence)
    return None


def _is_non_alkali_metal(symbol: str) -> bool:
    if symbol in ALKALI or symbol == "O":
        return False
    try:
        return bool(Element(symbol).is_metal)
    except Exception:
        return False


def _coordination_by_species(structure: Structure) -> dict[str, list[int]]:
    cnn = CrystalNN(distance_cutoffs=(0.5, 1.25), porous_adjustment=False)
    result: dict[str, list[int]] = {}
    for index, site in enumerate(structure):
        symbol = site.specie.symbol
        if symbol == "O":
            continue
        try:
            oxygen_neighbours = sum(
                info["site"].specie.symbol == "O" for info in cnn.get_nn_info(structure, index)
            )
        except Exception:
            continue
        result.setdefault(symbol, []).append(int(oxygen_neighbours))
    return result


def _layer_plane_count(structure: Structure, symbols: set[str]) -> int:
    values = sorted(
        float(site.frac_coords[2] % 1.0)
        for site in structure
        if site.specie.symbol in symbols
    )
    groups: list[float] = []
    for value in values:
        if not groups or min(abs(value - groups[-1]), 1.0 - abs(value - groups[-1])) > 0.08:
            groups.append(value)
    return len(groups)


def classify_layered_battery_oxide(
    structure: Structure,
    *,
    working_ion: str | None,
    robocrys_description: str | None,
    robocrys_condensed: dict[str, Any] | None = None,
    max_primitive_sites: int = 24,
) -> FamilyDecision:
    common = _common_rejection(
        structure, family=LAYERED_FAMILY, max_primitive_sites=max_primitive_sites
    )
    if common:
        return common
    elements = {element.symbol for element in structure.composition.elements}
    text = _text(robocrys_description, robocrys_condensed)
    evidence: dict[str, Any] = {
        "working_ion": working_ion,
        "elements": sorted(elements),
        "robocrys_layered_signal": any(term in text for term in LAYERED_TERMS),
        "robocrys_wrong_family_terms": [term for term in WRONG_LAYERED_TERMS if term in text],
        "space_group_number": SpacegroupAnalyzer(structure, symprec=0.01).get_space_group_number(),
    }
    if working_ion not in ALKALI or working_ion not in elements:
        return FamilyDecision(
            LAYERED_FAMILY, False, "REJECTED", ("WRONG_WORKING_ION",), evidence
        )
    metals = {symbol for symbol in elements if _is_non_alkali_metal(symbol)}
    evidence["non_alkali_metals"] = sorted(metals)
    if not metals:
        return FamilyDecision(LAYERED_FAMILY, False, "REJECTED", ("NO_TRANSITION_METAL",), evidence)
    polyanions = sorted((elements - ALKALI - metals - {"O"}) & POLYANION_CENTRES)
    evidence["polyanion_centres"] = polyanions
    if polyanions:
        return FamilyDecision(LAYERED_FAMILY, False, "REJECTED", ("OUT_OF_SCOPE_POLYANION",), evidence)
    if evidence["robocrys_wrong_family_terms"]:
        return FamilyDecision(LAYERED_FAMILY, False, "REJECTED", ("WRONG_FAMILY",), evidence)

    coordination = _coordination_by_species(structure)
    metal_octahedral = any(
        values and sum(abs(value - 6) <= 1 for value in values) / len(values) >= 0.5
        for symbol, values in coordination.items()
        if symbol in metals
    )
    plane_count = _layer_plane_count(structure, metals)
    evidence.update(
        {
            "oxygen_coordination_by_cation": coordination,
            "transition_metal_octahedral_signal": metal_octahedral,
            "transition_metal_layer_count": plane_count,
        }
    )
    structural_signal = bool(metal_octahedral and plane_count >= 1)
    if evidence["robocrys_layered_signal"] and structural_signal:
        return FamilyDecision(LAYERED_FAMILY, True, "ACCEPTED", ("LAYERED_EVIDENCE",), evidence)
    return FamilyDecision(
        LAYERED_FAMILY, False, "QUARANTINED", ("CLASSIFICATION_UNCERTAIN",), evidence
    )


def _spinel_formula_compatible(structure: Structure) -> bool:
    reduced = structure.composition.reduced_composition
    counts = sorted(round(float(amount), 8) for amount in reduced.values())
    return counts in ([1.0, 2.0, 4.0], [3.0, 4.0]) and reduced[Element("O")] == 4


def classify_spinel_oxide(
    structure: Structure,
    *,
    robocrys_description: str | None,
    robocrys_condensed: dict[str, Any] | None = None,
    max_primitive_sites: int = 28,
) -> FamilyDecision:
    common = _common_rejection(
        structure, family=SPINEL_FAMILY, max_primitive_sites=max_primitive_sites
    )
    if common:
        return common
    text = _text(robocrys_description, robocrys_condensed)
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01)
    formula_compatible = _spinel_formula_compatible(structure)
    evidence: dict[str, Any] = {
        "formula_compatible": formula_compatible,
        "space_group_number": analyzer.get_space_group_number(),
        "robocrys_spinel_signal": any(term in text for term in SPINEL_TERMS),
    }
    if not formula_compatible:
        return FamilyDecision(SPINEL_FAMILY, False, "REJECTED", ("WRONG_STOICHIOMETRY",), evidence)
    coordination = _coordination_by_species(structure)
    cation_values = [value for symbol, values in coordination.items() if symbol != "O" for value in values]
    tetrahedral = any(abs(value - 4) <= 1 for value in cation_values)
    octahedral = any(abs(value - 6) <= 1 for value in cation_values)
    evidence.update(
        {
            "oxygen_coordination_by_cation": coordination,
            "tetrahedral_cation_signal": tetrahedral,
            "octahedral_cation_signal": octahedral,
            "space_group_227_signal": evidence["space_group_number"] == 227,
        }
    )
    structural_signal = tetrahedral and octahedral
    if evidence["robocrys_spinel_signal"] and structural_signal:
        subtype = "mixed_valence_or_unresolved" if len(structure.composition.elements) == 2 else "normal_or_inverse_unresolved"
        evidence["spinel_subtype"] = subtype
        return FamilyDecision(SPINEL_FAMILY, True, "ACCEPTED", ("SPINEL_EVIDENCE",), evidence)
    return FamilyDecision(
        SPINEL_FAMILY, False, "QUARANTINED", ("CLASSIFICATION_UNCERTAIN",), evidence
    )


__all__ = [
    "CLASSIFIER_VERSION",
    "FamilyDecision",
    "LAYERED_FAMILY",
    "SPINEL_FAMILY",
    "classify_layered_battery_oxide",
    "classify_spinel_oxide",
]
