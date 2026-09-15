"""Compatible DFT convex-hull analysis, separate from surrogate predicted_hull."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pymatgen.analysis.phase_diagram import PDEntry, PhaseDiagram
from pymatgen.core import Composition

from sca.dft.compatibility import compare_energy_set
from sca.dft.schema import CompatibilityStatus, DFTCompatibilityFingerprint


class DFTHullEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chemical_system: str
    material_id: str
    formula: str
    total_energy_eV: float
    energy_per_atom_eV: float | None = None
    formation_energy_eV_atom: float | None = None
    compatibility_fingerprint: DFTCompatibilityFingerprint
    source: str
    provenance: dict = Field(default_factory=dict)


class DFTHullResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hull_status: str
    energy_above_hull_eV_atom: float | None = None
    is_on_hull: bool | None = None
    decomposition_products: dict[str, float] = Field(default_factory=dict)
    decomposition_energy_eV_atom: float | None = None
    hull_reference_count: int = 0
    descriptive_label: str | None = None
    thresholds_eV_atom: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


def calculate_dft_hull(
    candidate: DFTHullEntry,
    references: list[DFTHullEntry],
    *,
    on_hull_tolerance: float = 1e-8,
    near_hull_threshold: float = 0.05,
) -> DFTHullResult:
    relevant = [entry for entry in references if entry.chemical_system == candidate.chemical_system]
    compatible = compare_energy_set(candidate.compatibility_fingerprint, [entry.compatibility_fingerprint for entry in relevant])
    if compatible.status == CompatibilityStatus.INCOMPATIBLE:
        return DFTHullResult(
            hull_status="NOT_COMPUTABLE_INCOMPATIBLE_REFERENCES",
            hull_reference_count=len(relevant),
            reasons=compatible.reasons,
        )
    if compatible.status != CompatibilityStatus.COMPATIBLE:
        return DFTHullResult(hull_status="NOT_COMPUTABLE", hull_reference_count=len(relevant), reasons=compatible.reasons)
    elements = {element.symbol for element in Composition(candidate.formula).elements}
    terminal_elements = {
        next(iter(Composition(entry.formula).elements)).symbol
        for entry in relevant
        if len(Composition(entry.formula).elements) == 1
    }
    missing = sorted(elements - terminal_elements)
    if missing:
        return DFTHullResult(
            hull_status="NOT_COMPUTABLE",
            hull_reference_count=len(relevant),
            reasons=["missing elemental terminal entries: " + ", ".join(missing)],
        )
    try:
        ref_entries = [PDEntry(entry.formula, entry.total_energy_eV, name=entry.material_id) for entry in relevant]
        candidate_entry = PDEntry(candidate.formula, candidate.total_energy_eV, name=candidate.material_id)
        diagram = PhaseDiagram(ref_entries + [candidate_entry])
        decomposition, ehull = diagram.get_decomp_and_e_above_hull(candidate_entry, allow_negative=True)
    except Exception as exc:
        return DFTHullResult(hull_status="NOT_COMPUTABLE", hull_reference_count=len(relevant), reasons=[str(exc)])
    label = "ON_HULL" if ehull <= on_hull_tolerance else "NEAR_HULL" if ehull <= near_hull_threshold else "ABOVE_HULL"
    products = {str(entry.composition.reduced_formula): float(amount) for entry, amount in decomposition.items()}
    return DFTHullResult(
        hull_status="COMPUTABLE",
        energy_above_hull_eV_atom=float(ehull),
        is_on_hull=bool(ehull <= on_hull_tolerance),
        decomposition_products=products,
        decomposition_energy_eV_atom=float(ehull),
        hull_reference_count=len(relevant),
        descriptive_label=label,
        thresholds_eV_atom={"on_hull_tolerance": on_hull_tolerance, "near_hull_threshold": near_hull_threshold},
    )

