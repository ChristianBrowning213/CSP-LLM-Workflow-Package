"""Strict ordered-only structural classifiers for specialist crystal families."""

from __future__ import annotations

from typing import Any

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from .ordered_validation import is_fully_ordered_structure


CLASSIFIER_VERSION = "paper_scaffolds.ordered_prototype_match.v2"
OLIVINE_SPACE_GROUPS = {62}
ARGYRODITE_SPACE_GROUPS = {9, 14, 31, 33, 43, 216}
ARGYRODITE_MOBILE = {"Li", "Ag", "Cu"}
ARGYRODITE_FRAMEWORK = {"P", "As", "Ge", "Si", "Sn"}
ARGYRODITE_CHALCOGEN = {"S", "Se", "Te"}
MATCHER = StructureMatcher(
    ltol=0.2,
    stol=0.3,
    angle_tol=5.0,
    primitive_cell=True,
    scale=True,
    attempt_supercell=False,
)


def reduced_amounts(structure: Structure) -> dict[str, int]:
    return {
        str(element): int(round(float(amount)))
        for element, amount in structure.composition.reduced_composition.items()
    }


def olivine_subtype(structure: Structure) -> str:
    amounts = reduced_amounts(structure)
    if amounts.get("Li") == 1 and amounts.get("P") == 1 and amounts.get("O") == 4 and len(amounts) == 4:
        return "OLIVINE_LIMPO4"
    if amounts.get("Si") == 1 and amounts.get("O") == 4:
        return "OLIVINE_SILICATE"
    return "OLIVINE_OTHER"


def argyrodite_subtype(structure: Structure) -> str:
    elements = {element.symbol for element in structure.composition.elements}
    if "Li" in elements:
        return "LI_ARGYRODITE"
    if "Ag" in elements:
        return "AG_ARGYRODITE"
    if "Cu" in elements:
        return "CU_ARGYRODITE"
    return "OTHER_ARGYRODITE"


def is_li6ps5x_parent(structure: Structure) -> bool:
    amounts = reduced_amounts(structure)
    halogen = sum(amounts.get(element, 0) for element in ("F", "Cl", "Br", "I"))
    return (
        amounts.get("Li") == 6
        and amounts.get("P") == 1
        and amounts.get("S") == 5
        and halogen == 1
        and len(amounts) == 4
    )


def _match_reference(
    structure: Structure, references: list[tuple[str, Structure]]
) -> str | None:
    for reference_id, reference in references:
        if MATCHER.fit_anonymous(structure, reference):
            return reference_id
    return None


def classify_ordered_family(
    family: str,
    structure: Structure,
    references: list[tuple[str, Structure]],
) -> dict[str, Any]:
    ordered = is_fully_ordered_structure(structure)
    if not ordered["ordered"]:
        return {
            "accepted": False,
            "decision_reason": "REJECT_DISORDERED_SOURCE",
            "ordered_validation": ordered,
            "family_match": False,
            "matched_prototype": None,
            "subtype": None,
        }
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
    space_group_number = analyzer.get_space_group_number()
    space_group_symbol = analyzer.get_space_group_symbol()
    elements = {element.symbol for element in structure.composition.elements}
    amounts = reduced_amounts(structure)
    matched_reference = _match_reference(structure, references)
    if family == "OLIVINE":
        oxygen = amounts.get("O")
        non_oxygen = sorted(value for element, value in amounts.items() if element != "O")
        chemistry_ok = oxygen == 4 and non_oxygen in ([1, 2], [1, 1, 1])
        symmetry_ok = space_group_number in OLIVINE_SPACE_GROUPS
        subtype = olivine_subtype(structure)
    elif family == "ARGYRODITE":
        chemistry_ok = bool(
            elements & ARGYRODITE_MOBILE
            and elements & ARGYRODITE_FRAMEWORK
            and elements & ARGYRODITE_CHALCOGEN
        )
        symmetry_ok = space_group_number in ARGYRODITE_SPACE_GROUPS
        subtype = argyrodite_subtype(structure)
    else:
        raise ValueError(f"Unsupported ordered family: {family}")
    accepted = bool(matched_reference and chemistry_ok and symmetry_ok)
    if matched_reference is None:
        reason = "REJECT_NOT_FAMILY_PROTOTYPE"
    elif not chemistry_ok:
        reason = "REJECT_FAMILY_CHEMISTRY"
    elif not symmetry_ok:
        reason = "REJECT_FAMILY_SYMMETRY"
    else:
        reason = "ACCEPT_ORDERED_FAMILY"
    return {
        "accepted": accepted,
        "decision_reason": reason,
        "ordered_validation": ordered,
        "family_match": bool(matched_reference),
        "matched_prototype": matched_reference,
        "subtype": subtype if accepted else None,
        "li6ps5x_parent": is_li6ps5x_parent(structure) if family == "ARGYRODITE" else False,
        "space_group_number": space_group_number,
        "space_group_symbol": space_group_symbol,
        "primitive_sites": len(analyzer.get_primitive_standard_structure()),
        "conventional_sites": len(analyzer.get_conventional_standard_structure()),
        "chemistry_ok": chemistry_ok,
        "symmetry_ok": symmetry_ok,
    }
