"""Composition checks."""

from __future__ import annotations

from pymatgen.core import Composition, Structure

from sca.schemas import CompositionResult


def evaluate_composition(
    structure: Structure,
    target_formula: str | None,
) -> CompositionResult:
    """Compare a structure composition against an optional target formula."""

    formula = structure.composition.formula
    reduced_formula = structure.composition.reduced_formula
    if not target_formula:
        return CompositionResult(
            target_formula=None,
            formula=formula,
            reduced_formula=reduced_formula,
            target_formula_match=None,
        )

    try:
        target_reduced = Composition(target_formula).reduced_formula
    except Exception as exc:
        return CompositionResult(
            target_formula=target_formula,
            formula=formula,
            reduced_formula=reduced_formula,
            target_formula_match=False,
            composition_error=f"{type(exc).__name__}: {exc}",
        )

    return CompositionResult(
        target_formula=target_formula,
        formula=formula,
        reduced_formula=reduced_formula,
        target_reduced_formula=target_reduced,
        target_formula_match=reduced_formula == target_reduced,
    )
