"""Formation energy from explicitly compatible elemental chemical potentials."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pymatgen.core import Composition

from sca.dft.compatibility import compare_energy_set
from sca.dft.schema import CompatibilityStatus, DFTCompatibilityFingerprint


class ElementalReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element: str
    reference_phase: str
    reference_energy_eV_per_atom: float
    compatibility_fingerprint: DFTCompatibilityFingerprint
    source: str
    provenance: dict = Field(default_factory=dict)


class FormationEnergyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    formation_energy_eV: float | None = None
    formation_energy_eV_atom: float | None = None
    reference_terms_eV: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


def calculate_formation_energy(
    formula: str,
    total_energy_eV: float,
    candidate_fingerprint: DFTCompatibilityFingerprint,
    references: list[ElementalReference],
) -> FormationEnergyResult:
    composition = Composition(formula)
    by_element = {reference.element: reference for reference in references}
    missing = [element.symbol for element in composition.elements if element.symbol not in by_element]
    if missing:
        return FormationEnergyResult(status="NOT_COMPUTABLE", reasons=["missing elemental references: " + ", ".join(missing)])
    selected = [by_element[element.symbol] for element in composition.elements]
    compatible = compare_energy_set(candidate_fingerprint, [item.compatibility_fingerprint for item in selected])
    if compatible.status != CompatibilityStatus.COMPATIBLE:
        return FormationEnergyResult(status="NOT_COMPUTABLE", reasons=compatible.reasons)
    terms = {
        element.symbol: float(composition[element]) * by_element[element.symbol].reference_energy_eV_per_atom
        for element in composition.elements
    }
    energy = float(total_energy_eV - sum(terms.values()))
    return FormationEnergyResult(
        status="COMPUTABLE",
        formation_energy_eV=energy,
        formation_energy_eV_atom=energy / composition.num_atoms,
        reference_terms_eV=terms,
    )

