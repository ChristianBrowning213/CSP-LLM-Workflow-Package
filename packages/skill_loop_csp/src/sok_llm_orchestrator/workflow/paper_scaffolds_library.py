"""Reusable family-level topology scaffolds for Paper_scaffolds_september Dataset C.

Each entry is a *reusable* structural-family abstraction, not a stored answer for
one composition. A scaffold supplies:

* an idealized prototype structure for the family's higher-order topology, built
  from standard Wyckoff representatives via ``pymatgen`` ``Structure.from_spacegroup``
  (the same idealized coordinates as the project's existing
  ``structures.prototype_scaffold`` definitions), and
* ``ordered_orbits`` that partition every candidate site into symmetry classes
  with an allowed-species list.

QLIP keeps meaningful degrees of freedom: in ``variable`` mode the cation orbits
accept every cation in the target composition, so the solver still chooses the
site/species assignment (e.g. normal vs inverse spinel, M1/M2 cation ordering),
scored by the same request-conditioned SPP objective used without a scaffold.
Exact composition and full occupancy remain enforced by QLIP.

This module deliberately does not read target coordinates or neighbour CIFs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymatgen.core import Composition, Lattice, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


SCAFFOLD_LIBRARY_VERSION = "paper_scaffolds_library.v1"

SUPPORTED_FAMILIES = {
    "rocksalt": "ROCKSALT",
    "spinel": "SPINEL",
    "spinel oxide": "SPINEL",
    "layered oxide": "LAYERED_OXIDE",
    "layered battery oxide": "LAYERED_OXIDE",
    "olivine phosphate": "OLIVINE",
    "olivine": "OLIVINE",
}

# Unambiguous small tetrahedral network-formers only.
_TET_SYMS = {"Si", "P", "As", "Ge", "B"}
_ANION_SYMS = {"O", "S", "Se", "F", "Cl", "Br", "I", "N", "Te"}


@dataclass(frozen=True)
class _OrbitSpec:
    orbit_id: str
    wyckoff: str
    representative: tuple[float, float, float]
    multiplicity: int
    role: str  # framework_cation | tet_cation | anion | spinel_tet_cation | spinel_oct_cation


@dataclass(frozen=True)
class _FamilyPrototype:
    family: str
    topology_policy: str
    space_group: str
    anonymous_formula: str
    lattice: Lattice
    orbits: tuple[_OrbitSpec, ...]
    note: str


_PROTOTYPES: dict[str, _FamilyPrototype] = {
    # Rocksalt AB, Fm-3m #225 — two interpenetrating fcc sublattices, 6+6 octahedral.
    "ROCKSALT": _FamilyPrototype(
        family="rocksalt",
        topology_policy="ROCKSALT",
        space_group="Fm-3m",
        anonymous_formula="AB",
        lattice=Lattice.cubic(4.2),
        orbits=(
            _OrbitSpec("cation_4a", "4a", (0.0, 0.0, 0.0), 4, "framework_cation"),
            _OrbitSpec("anion_4b", "4b", (0.5, 0.5, 0.5), 4, "anion"),
        ),
        note="Idealized rocksalt: A on 4a, anion on 4b; octahedral 6-coordination for both.",
    ),
    # Spinel AB2X4, Fd-3m #227 — tetrahedral 8a + octahedral 16d cation network, 32e anion.
    "SPINEL": _FamilyPrototype(
        family="spinel",
        topology_policy="SPINEL",
        space_group="Fd-3m",
        anonymous_formula="AB2X4",
        lattice=Lattice.cubic(8.44),
        orbits=(
            _OrbitSpec("tet_8a", "8a", (0.0, 0.0, 0.0), 8, "spinel_tet_cation"),
            _OrbitSpec("oct_16d", "16d", (0.625, 0.625, 0.625), 16, "spinel_oct_cation"),
            _OrbitSpec("anion_32e", "32e", (0.386, 0.386, 0.386), 32, "anion"),
        ),
        note="Idealized spinel conventional cell (u=0.386): tetrahedral 8a + octahedral 16d cations, 32e anion.",
    ),
    # Layered oxide ABO2, R-3m #166 — alternating alkali / transition-metal octahedral layers.
    "LAYERED_OXIDE": _FamilyPrototype(
        family="layered oxide",
        topology_policy="LAYERED_OXIDE",
        space_group="R-3m",
        anonymous_formula="ABX2",
        lattice=Lattice.hexagonal(2.815, 14.05),
        orbits=(
            _OrbitSpec("alkali_3a", "3a", (0.0, 0.0, 0.0), 3, "framework_cation"),
            _OrbitSpec("tm_3b", "3b", (0.0, 0.0, 0.5), 3, "framework_cation"),
            _OrbitSpec("anion_6c", "6c", (0.0, 0.0, 0.241), 6, "anion"),
        ),
        note="Idealized O3 layered oxide (LiCoO2 prototype): alkali 3a and transition-metal 3b layers, 6c oxygen.",
    ),
    # Olivine ABXO4, Pnma #62 — octahedral M1/M2 cations, isolated XO4 tetrahedra.
    "OLIVINE": _FamilyPrototype(
        family="olivine phosphate",
        topology_policy="OLIVINE",
        space_group="Pnma",
        anonymous_formula="ABXO4",
        lattice=Lattice.orthorhombic(10.33, 6.01, 4.69),
        orbits=(
            _OrbitSpec("m1_4a", "4a", (0.0, 0.0, 0.0), 4, "framework_cation"),
            _OrbitSpec("m2_4c", "4c", (0.282, 0.25, 0.974), 4, "framework_cation"),
            _OrbitSpec("t_4c", "4c", (0.094, 0.25, 0.418), 4, "tet_cation"),
            _OrbitSpec("o1_4c", "4c", (0.097, 0.25, 0.742), 4, "anion"),
            _OrbitSpec("o2_4c", "4c", (0.454, 0.25, 0.207), 4, "anion"),
            _OrbitSpec("o3_8d", "8d", (0.166, 0.046, 0.284), 8, "anion"),
        ),
        note="Idealized olivine (LiFePO4 prototype): octahedral M1 (4a) and M2 (4c) cations, isolated TO4 tetrahedra, three oxygen orbits.",
    ),
}


def resolve_policy(family: str) -> str | None:
    return SUPPORTED_FAMILIES.get(str(family).strip().lower())


def _species_split(formula: str) -> tuple[list[str], list[str], list[str]]:
    comp = Composition(formula)
    els = [str(e) for e in comp.elements]
    anions = [e for e in els if e in _ANION_SYMS]
    if anions:
        prime = sorted(anions, key=lambda e: (-comp[e], e))[0]
        anions = [prime]
    cations = [e for e in els if e not in anions]
    tet = [e for e in cations if e in _TET_SYMS]
    framework = [e for e in cations if e not in tet] or cations
    return cations, tet, framework


def _build_prototype_structure(proto: _FamilyPrototype) -> tuple[Structure, list[list[int]]]:
    """Build the idealized structure; return it plus per-orbit site-index groups.

    ``Structure.from_spacegroup`` orders generated sites by asymmetric-unit entry,
    so consecutive slices of length ``multiplicity`` correspond to each orbit.
    """
    placeholder = {
        "framework_cation": "Na", "spinel_tet_cation": "Zn", "spinel_oct_cation": "Fe",
        "tet_cation": "Si", "anion": "O",
    }
    species = [placeholder[o.role] for o in proto.orbits]
    coords = [list(o.representative) for o in proto.orbits]
    structure = Structure.from_spacegroup(proto.space_group, proto.lattice, species, coords)
    groups: list[list[int]] = []
    offset = 0
    for spec in proto.orbits:
        groups.append(list(range(offset, offset + spec.multiplicity)))
        offset += spec.multiplicity
    if offset != len(structure):
        raise ValueError(
            f"{proto.space_group} generated {len(structure)} sites; orbit multiplicities sum to {offset}"
        )
    return structure, groups


def build_family_scaffold(
    task: dict[str, Any], mode: str = "variable"
) -> tuple[str, Structure, list[dict[str, Any]], dict[str, Any]]:
    """Build a reusable family scaffold for ``task['formula']``.

    ``mode`` — ``"variable"`` (cation orbits accept every target cation: real QLIP
    assignment DOF) or ``"fixed"`` (each orbit pinned to its ideal species).
    Returns ``(scaffold_id, structure, ordered_orbits, provenance)``.
    """
    family = str(task.get("family") or "")
    policy = resolve_policy(family)
    if policy is None or policy not in _PROTOTYPES:
        raise ValueError(f"paper_scaffolds_library has no reusable scaffold for family {family!r}")
    mode = str(mode).strip().lower()
    if mode not in {"variable", "fixed"}:
        raise ValueError("mode must be 'variable' or 'fixed'")
    proto = _PROTOTYPES[policy]
    formula = str(task["formula"])
    cations, tet, framework = _species_split(formula)
    if not any(str(e) in _ANION_SYMS for e in Composition(formula).elements):
        raise ValueError(f"{formula} has no recognised framework anion for the {policy} scaffold")
    anion = sorted((str(e) for e in Composition(formula).elements if str(e) in _ANION_SYMS),
                   key=lambda e: (-Composition(formula)[e], e))[0]

    structure, groups = _build_prototype_structure(proto)
    comp = Composition(formula)
    scale = round(len(structure) / comp.num_atoms)
    if scale <= 0 or abs(len(structure) / comp.num_atoms - scale) > 1e-6:
        raise ValueError(f"{policy} scaffold has {len(structure)} sites; {formula} does not tile it")
    need = {str(e): int(round(float(a) * scale)) for e, a in comp.get_el_amt_dict().items()}

    ideal_by_role = {
        "spinel_tet_cation": (min(framework, key=lambda e: (comp[e], e)) if mode == "fixed" and framework else None),
        "spinel_oct_cation": (max(framework, key=lambda e: (comp[e], e)) if mode == "fixed" and framework else None),
    }
    if policy == "SPINEL" and tet:
        # a genuine tetrahedral former (Si/Ge in e.g. Co2SiO4) prefers the 8a site
        ideal_by_role["spinel_tet_cation"] = tet[0]

    ordered_orbits: list[dict[str, Any]] = []
    for spec, site_indices in zip(proto.orbits, groups, strict=True):
        if spec.role == "anion":
            allowed = [anion]
        elif spec.role == "tet_cation":
            allowed = list(tet) if tet else list(framework)
        elif spec.role in {"spinel_tet_cation", "spinel_oct_cation"}:
            allowed = list(cations) if mode == "variable" else [ideal_by_role[spec.role] or framework[-1]]
        else:  # framework_cation (octahedral / layer site)
            if mode == "fixed":
                allowed = [framework[0] if spec.orbit_id in {"m1_4a", "alkali_3a"} else framework[-1]]
            else:
                allowed = list(framework)
        ordered_orbits.append(
            {
                "orbit_id": spec.orbit_id,
                "wyckoff": spec.wyckoff,
                "site_indices": [int(i) for i in site_indices],
                "allowed_species": allowed,
                "required_occupancy": True,
                "occupation_mode": "VARIABLE_FULL_ORBIT" if len(allowed) > 1 else "FIXED_FULL_ORBIT",
            }
        )

    if sum(need.values()) != len(structure):
        raise ValueError(f"{policy} scaffold: {formula} does not tile {len(structure)} sites")
    sites_allowing: dict[str, int] = {}
    for orbit in ordered_orbits:
        for sp in orbit["allowed_species"]:
            sites_allowing[sp] = sites_allowing.get(sp, 0) + len(orbit["site_indices"])
    missing = [sp for sp in need if sp not in sites_allowing]
    if missing:
        raise ValueError(f"{policy} scaffold for {formula}: species {missing} have no orbit")
    short = [sp for sp, n in need.items() if sites_allowing.get(sp, 0) < n]
    if short:
        raise ValueError(f"{policy} scaffold for {formula}: species {short} have fewer eligible sites than required")

    from sok_llm_orchestrator.workflow.scaffold_ablation import count_orbit_assignments

    feasible_states = count_orbit_assignments(formula, len(structure), ordered_orbits)

    scaffold_id = f"paper_scaffolds_{policy.lower()}_{proto.space_group.replace('-', '').lower()}_{mode}_v1"
    detected = SpacegroupAnalyzer(structure, symprec=0.05).get_space_group_symbol()
    min_dist = float(structure.distance_matrix[structure.distance_matrix > 0].min())
    provenance = {
        "scaffold_library_version": SCAFFOLD_LIBRARY_VERSION,
        "family": proto.family,
        "topology_policy": proto.topology_policy,
        "prototype_space_group": proto.space_group,
        "prototype_detected_space_group": detected,
        "prototype_min_site_distance_A": round(min_dist, 4),
        "anonymous_formula": proto.anonymous_formula,
        "site_count": len(structure),
        "formula": formula,
        "formula_units": scale,
        "mode": mode,
        "feasible_whole_orbit_state_count": int(feasible_states),
        "cation_orbit_species": sorted(cations),
        "anion": anion,
        "tetrahedral_cation_species": sorted(tet),
        "orbit_summary": [
            {"orbit_id": o["orbit_id"], "sites": len(o["site_indices"]), "allowed": o["allowed_species"],
             "mode": o["occupation_mode"]}
            for o in ordered_orbits
        ],
        "note": proto.note,
        "cell_representation_note": (
            "Scaffold uses the family's idealized crystallographic cell (not the "
            "retrieval_feasible_cell used in the no-scaffold Dataset B run)."
        ),
    }
    return scaffold_id, structure, ordered_orbits, provenance


__all__ = [
    "SCAFFOLD_LIBRARY_VERSION",
    "SUPPORTED_FAMILIES",
    "resolve_policy",
    "build_family_scaffold",
]
