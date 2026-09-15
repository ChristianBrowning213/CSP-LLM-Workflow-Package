"""Flexible, discrete topology scaffolds for Paper_scaffolds_september.

V2 never reads target/reference coordinates.  It exposes only alternatives that
QLIP can represent without changing its objective: ordered site-class choices
inside one fixed geometry, plus a finite outer set of provenance-controlled
cell/internal-coordinate geometries to be solved and compared independently.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

from pymatgen.core import Composition, Lattice, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.workflow.cell_strategy import GLOBAL_VPA_PROVENANCE
from sok_llm_orchestrator.workflow.scaffold_ablation import count_orbit_assignments


SCAFFOLD_LIBRARY_VERSION = "paper_scaffolds_library.v2"
SUPPORTED_POLICIES = {"ROCKSALT", "SPINEL", "LAYERED_O3", "OLIVINE"}
_ANIONS = {"O", "S", "Se", "Te", "N", "F", "Cl", "Br", "I"}
# Ordered specialist-corpus subclasses: borate, silicate, germanate,
# phosphate, arsenate, and vanadate. V is admitted specifically as the
# tetrahedral former in the frozen olivine-vanadate subclass.
_TETRAHEDRAL = {"B", "Si", "Ge", "P", "As", "V"}
_GLOBAL_VPA_CANDIDATES = (
    float(GLOBAL_VPA_PROVENANCE["vpa_q1_A3_per_atom"]),
    17.986899303180298,
    float(GLOBAL_VPA_PROVENANCE["vpa_q3_A3_per_atom"]),
)
_INVERSE_OCT_A = (8, 9, 11, 14, 16, 17, 19, 22)


@dataclass(frozen=True, slots=True)
class ScaffoldAlternative:
    alternative_id: str
    scaffold_id: str
    family_policy: str
    geometry_class: str
    structure: Structure
    ordered_orbits: tuple[dict[str, Any], ...]
    feasible_state_count: int
    provenance: dict[str, Any]

    def canonical_hash(self) -> str:
        payload = {
            "alternative_id": self.alternative_id,
            "lattice": self.structure.lattice.matrix.tolist(),
            "fractional_coordinates": self.structure.frac_coords.tolist(),
            "orbits": self.ordered_orbits,
            "provenance": self.provenance,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()


def resolve_policy(family: str, topology_subclass: str | None = None) -> str | None:
    value = str(family).strip().lower().replace("-", "_").replace(" ", "_")
    if value == "rocksalt":
        return "ROCKSALT"
    if value in {"spinel", "spinel_oxide"}:
        return "SPINEL"
    if value in {"olivine", "olivine_phosphate"}:
        return "OLIVINE"
    if value in {"layered_oxide", "layered_battery_oxide", "layered_o3", "o3"}:
        subclass = str(topology_subclass or "O3").strip().upper()
        return "LAYERED_O3" if subclass == "O3" else None
    return None


def _species(formula: str) -> tuple[str, list[str], list[str]]:
    composition = Composition(formula)
    anions = [str(element) for element in composition.elements if str(element) in _ANIONS]
    if len(anions) != 1:
        raise ValueError(f"v2 requires exactly one ordered framework anion; got {anions}")
    anion = anions[0]
    cations = [str(element) for element in composition.elements if str(element) != anion]
    tetrahedral = [element for element in cations if element in _TETRAHEDRAL]
    return anion, cations, tetrahedral


def _evidence_vpas(formula: str, records: Iterable[Mapping[str, Any]]) -> tuple[list[float], list[str]]:
    target = Composition(formula).reduced_composition
    values: list[float] = []
    ids: list[str] = []
    for record in records:
        record_formula = record.get("formula")
        if record_formula and Composition(str(record_formula)).reduced_composition == target:
            continue
        value = record.get("vpa_A3_per_atom", record.get("volume_per_atom_A3"))
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            values.append(number)
            ids.append(str(record.get("structure_id") or record.get("source_id") or "unspecified"))
    return values, ids


def _nearest_rank(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def cell_vpa_candidates(
    formula: str, evidence_records: Iterable[Mapping[str, Any]] = ()
) -> tuple[tuple[float, ...], dict[str, Any]]:
    values, ids = _evidence_vpas(formula, evidence_records)
    if len(values) >= 3:
        candidates = tuple(dict.fromkeys(_nearest_rank(values, q) for q in (0.25, 0.5, 0.75)))
        source = "leakage_filtered_request_retrieval_vpa_quartiles"
    else:
        candidates = _GLOBAL_VPA_CANDIDATES
        source = "frozen_broad_corpus_vpa_quartiles"
    return candidates, {
        "source": source,
        "evidence_record_ids": ids,
        "valid_evidence_count": len(values),
        "target_composition_records_excluded": True,
        "target_coordinates_consumed": False,
        "target_lattice_consumed": False,
    }


def _orbits(groups: list[tuple[str, list[int], list[str], str]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "orbit_id": orbit_id,
            "site_indices": indices,
            "allowed_species": allowed,
            "required_occupancy": True,
            "vacancy_allowed": False,
            "allow_partial_occupation": False,
            "occupation_mode": "VARIABLE_FULL_ORBIT" if len(allowed) > 1 else "FIXED_FULL_ORBIT",
            "topology_role": role,
        }
        for orbit_id, indices, allowed, role in groups
    )


def _scaled_lattice(base: Lattice, vpa: float, site_count: int) -> Lattice:
    factor = ((vpa * site_count) / base.volume) ** (1.0 / 3.0)
    return Lattice(base.matrix * factor)


def _build_geometry(policy: str, vpa: float, parameter: float | None) -> tuple[Structure, tuple[dict[str, Any], ...], str]:
    if policy == "ROCKSALT":
        base = Lattice.cubic(4.2)
        lattice = _scaled_lattice(base, vpa, 8)
        structure = Structure.from_spacegroup("Fm-3m", lattice, ["Na", "Cl"], [[0, 0, 0], [.5, .5, .5]])
        groups = _orbits([("cation_4a", list(range(4)), [], "octahedral_cation"), ("anion_4b", list(range(4, 8)), [], "anion_framework")])
        return structure, groups, "B1_Fm-3m"
    if policy == "SPINEL":
        u = float(parameter)
        base = Lattice.cubic(8.44)
        lattice = _scaled_lattice(base, vpa, 56)
        structure = Structure.from_spacegroup("Fd-3m", lattice, ["Zn", "Fe", "O"], [[0, 0, 0], [.625, .625, .625], [u, u, u]])
        oct_b = [index for index in range(8, 24) if index not in _INVERSE_OCT_A]
        groups = _orbits([
            ("tet_8a", list(range(8)), [], "tetrahedral_cation"),
            ("oct_ordered_a", list(_INVERSE_OCT_A), [], "octahedral_cation_suborbit"),
            ("oct_ordered_b", oct_b, [], "octahedral_cation_suborbit"),
            ("anion_32e", list(range(24, 56)), [], "anion_framework"),
        ])
        return structure, groups, f"spinel_network_u_{u:.3f}"
    if policy == "LAYERED_O3":
        z = float(parameter)
        base = Lattice.hexagonal(2.815, 14.05)
        lattice = _scaled_lattice(base, vpa, 12)
        structure = Structure.from_spacegroup("R-3m", lattice, ["Li", "Co", "O"], [[0, 0, 0], [0, 0, .5], [0, 0, z]])
        groups = _orbits([("alkali_3a", list(range(3)), [], "o3_alkali_layer"), ("tm_3b", list(range(3, 6)), [], "o3_tm_layer"), ("anion_6c", list(range(6, 12)), [], "o3_oxygen_layer")])
        return structure, groups, f"O3_R-3m_z_{z:.3f}"
    if policy == "OLIVINE":
        base = Lattice.orthorhombic(10.33, 6.01, 4.69)
        lattice = _scaled_lattice(base, vpa, 28)
        structure = Structure.from_spacegroup(
            "Pnma", lattice, ["Li", "Fe", "P", "O", "O", "O"],
            [[0, 0, 0], [.282, .25, .974], [.094, .25, .418], [.097, .25, .742], [.454, .25, .207], [.166, .046, .284]],
        )
        groups = _orbits([("m1_4a", list(range(4)), [], "olivine_m1"), ("m2_4c", list(range(4, 8)), [], "olivine_m2"), ("t_4c", list(range(8, 12)), [], "olivine_tetrahedral_former"), ("o1_4c", list(range(12, 16)), [], "anion_framework"), ("o2_4c", list(range(16, 20)), [], "anion_framework"), ("o3_8d", list(range(20, 28)), [], "anion_framework")])
        return structure, groups, "Pnma_olivine_framework"
    raise ValueError(f"unsupported v2 policy: {policy}")


def _apply_species(policy: str, formula: str, orbits: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    anion, cations, tetrahedral = _species(formula)
    if policy == "ROCKSALT" and len(cations) != 1:
        raise ValueError("ROCKSALT v2 requires an ordered binary AB composition")
    if policy == "SPINEL" and len(cations) != 2:
        raise ValueError("SPINEL v2 requires exactly two cation species in AB2X4/A2BX4")
    if policy == "LAYERED_O3" and len(cations) != 2:
        raise ValueError("LAYERED_O3 v2 requires exactly two cation species in ABX2")
    if policy == "OLIVINE" and not tetrahedral:
        raise ValueError("OLIVINE v2 requires an unambiguous B/Si/Ge/P/As tetrahedral former")
    framework = [item for item in cations if item not in tetrahedral]
    updated = []
    for orbit in orbits:
        row = dict(orbit)
        role = str(row["topology_role"])
        if "anion" in role or "oxygen" in role:
            allowed = [anion]
        elif role == "olivine_tetrahedral_former":
            allowed = tetrahedral
        elif policy == "OLIVINE":
            allowed = framework
        else:
            allowed = cations
        row["allowed_species"] = sorted(allowed)
        row["occupation_mode"] = "VARIABLE_FULL_ORBIT" if len(allowed) > 1 else "FIXED_FULL_ORBIT"
        if len(allowed) == 1:
            row["fixed_species"] = allowed[0]
        updated.append(row)
    return tuple(updated)


def build_family_scaffold_alternatives(
    task: Mapping[str, Any], *, evidence_records: Iterable[Mapping[str, Any]] = ()
) -> tuple[ScaffoldAlternative, ...]:
    formula = str(task["formula"])
    policy = resolve_policy(str(task.get("family") or ""), task.get("topology_subclass"))
    if policy not in SUPPORTED_POLICIES:
        raise ValueError(f"paper_scaffolds_library.v2 has no supported topology for {task.get('family')!r}/{task.get('topology_subclass')!r}")
    vpas, cell_provenance = cell_vpa_candidates(formula, evidence_records)
    parameters: tuple[float | None, ...] = {
        "SPINEL": (0.375, 0.386, 0.397),
        "LAYERED_O3": (0.235, 0.241, 0.247),
    }.get(policy, (None,))
    alternatives = []
    for vpa_index, vpa in enumerate(vpas):
        for parameter_index, parameter in enumerate(parameters):
            structure, bare_orbits, geometry = _build_geometry(policy, vpa, parameter)
            orbits = _apply_species(policy, formula, bare_orbits)
            feasible = count_orbit_assignments(formula, len(structure), list(orbits))
            if feasible < 1:
                raise ValueError(f"{policy} v2 cannot represent exact composition {formula}")
            detected = SpacegroupAnalyzer(structure, symprec=.05).get_space_group_symbol()
            alternative_id = f"{policy.lower()}_vpa{vpa_index}_g{parameter_index}"
            provenance = {
                "scaffold_library_version": SCAFFOLD_LIBRARY_VERSION,
                "family_policy": policy,
                "topology_subclass": "O3" if policy == "LAYERED_O3" else policy,
                "geometry_class": geometry,
                "vpa_A3_per_atom": vpa,
                "cell_evidence": cell_provenance,
                "internal_parameter": parameter,
                "internal_parameter_source": "frozen_family_generic_discrete_grid" if parameter is not None else "not_applicable",
                "prototype_detected_space_group": detected,
                "ordered_only": True,
                "partial_occupancy_allowed": False,
                "target_coordinates_consumed": False,
                "target_lattice_consumed": False,
            }
            scaffold_id = f"paper_scaffolds_{policy.lower()}_{alternative_id}_v2"
            alternatives.append(ScaffoldAlternative(alternative_id, scaffold_id, policy, geometry, structure, orbits, feasible, provenance))
    return tuple(alternatives)


def select_objective_minimum(results: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    rows = list(results)
    if not rows:
        raise ValueError("no solved v2 alternatives were supplied")
    invalid = [row for row in rows if row.get("solver_status") not in {"OPTIMAL", "FEASIBLE"}]
    if invalid:
        raise ValueError("all v2 alternatives must have an authoritative feasible solver result")
    for row in rows:
        solver = float(row["solver_objective"])
        scorer = float(row["independent_objective"])
        if abs(solver - scorer) > 1e-6:
            raise ValueError(f"solver/scorer disagreement for {row.get('alternative_id')}")
    return min(rows, key=lambda row: (float(row["solver_objective"]), str(row["alternative_id"])))


__all__ = ["SCAFFOLD_LIBRARY_VERSION", "ScaffoldAlternative", "build_family_scaffold_alternatives", "cell_vpa_candidates", "resolve_policy", "select_objective_minimum"]
