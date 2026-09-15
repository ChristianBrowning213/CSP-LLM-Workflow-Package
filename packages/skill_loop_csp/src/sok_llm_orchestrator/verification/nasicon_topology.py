"""Geometry-grounded validator for ordered NASICON-like Na-Zr-Si-P oxides."""

from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pymatgen.core import Composition, Structure


DEFAULT_TOLERANCES: dict[str, float] = {
    "zr_o_cutoff_angstrom": 2.55,
    "si_o_cutoff_angstrom": 2.05,
    "p_o_cutoff_angstrom": 2.05,
    "na_o_cutoff_angstrom": 3.30,
    "na_na_channel_cutoff_angstrom": 4.50,
    "na_framework_cation_min_angstrom": 2.50,
    "severe_short_contact_angstrom": 1.00,
}


def _symbol(site: Any) -> str:
    return str(site.specie.symbol)


def _distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    data = np.asarray(list(values), dtype=float)
    if data.size == 0:
        return {"count": 0, "min": None, "mean": None, "max": None, "std": None}
    return {
        "count": int(data.size), "min": float(data.min()), "mean": float(data.mean()),
        "max": float(data.max()), "std": float(data.std()),
    }


def _coordination(structure: Structure, center: str, cutoff: float) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for idx, site in enumerate(structure):
        if _symbol(site) != center:
            continue
        oxygen = [neighbor for neighbor in structure.get_neighbors(site, cutoff) if _symbol(neighbor) == "O"]
        records.append({
            "site_index": idx,
            "coordination_number": len(oxygen),
            "oxygen_indices": sorted({int(neighbor.index) for neighbor in oxygen}),
            "oxygen_images": [
                {"index": int(neighbor.index), "image": [int(v) for v in neighbor.image], "distance": float(neighbor.nn_distance)}
                for neighbor in oxygen
            ],
            "bond_lengths_angstrom": [float(neighbor.nn_distance) for neighbor in oxygen],
        })
    return records


def _angles(structure: Structure, records: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for record in records:
        center = structure[record["site_index"]].coords
        vectors = []
        for oxygen in record["oxygen_images"]:
            frac = structure[oxygen["index"]].frac_coords + np.asarray(oxygen["image"], dtype=float)
            vectors.append(structure.lattice.get_cartesian_coords(frac) - center)
        for left, right in itertools.combinations(vectors, 2):
            cosine = float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))
            values.append(float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))))
    return values


def _periodic_graph_rank(nodes: set[int], edges: list[tuple[int, int, tuple[int, int, int]]]) -> tuple[int, bool, list[list[int]]]:
    adjacency: dict[int, list[tuple[int, np.ndarray]]] = defaultdict(list)
    for left, right, shift in edges:
        vector = np.asarray(shift, dtype=int)
        adjacency[left].append((right, vector))
        adjacency[right].append((left, -vector))
    if not nodes:
        return 0, False, []
    offsets: dict[int, np.ndarray] = {}
    components = 0
    cycles: list[np.ndarray] = []
    for start in sorted(nodes):
        if start in offsets:
            continue
        components += 1
        offsets[start] = np.zeros(3, dtype=int)
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor, shift in adjacency.get(current, []):
                proposed = offsets[current] + shift
                if neighbor not in offsets:
                    offsets[neighbor] = proposed
                    queue.append(neighbor)
                else:
                    cycle = proposed - offsets[neighbor]
                    if np.any(cycle):
                        cycles.append(cycle)
    rank = int(np.linalg.matrix_rank(np.asarray(cycles, dtype=float))) if cycles else 0
    unique_cycles = sorted({tuple(int(v) for v in cycle) for cycle in cycles})
    return rank, components == 1 and len(offsets) == len(nodes), [list(item) for item in unique_cycles]


def _framework_graph(structure: Structure, records: list[dict[str, Any]]) -> tuple[int, bool, list[list[int]]]:
    nodes: set[int] = set()
    edges: list[tuple[int, int, tuple[int, int, int]]] = []
    for record in records:
        center = int(record["site_index"])
        nodes.add(center)
        for oxygen in record["oxygen_images"]:
            ligand = int(oxygen["index"])
            nodes.add(ligand)
            edges.append((center, ligand, tuple(int(v) for v in oxygen["image"])))
    return _periodic_graph_rank(nodes, edges)


def _sharing(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter()
    relationships: list[dict[str, Any]] = []
    connected_pairs = 0
    for left, right in itertools.combinations(records, 2):
        shared = sorted(set(left["oxygen_indices"]) & set(right["oxygen_indices"]))
        if not shared:
            continue
        connected_pairs += 1
        kind = "corner" if len(shared) == 1 else "edge" if len(shared) == 2 else "face"
        counts[kind] += 1
        relationships.append({
            "center_indices": [left["site_index"], right["site_index"]],
            "shared_oxygen_indices": shared, "sharing": kind,
        })
    corner_fraction = float(counts["corner"] / connected_pairs) if connected_pairs else 0.0
    return {
        "connected_polyhedron_pairs": connected_pairs,
        "corner_sharing_pairs": counts["corner"], "edge_sharing_pairs": counts["edge"],
        "face_sharing_pairs": counts["face"], "corner_sharing_fraction": corner_fraction,
        "relationships": relationships,
    }


def _sodium_channel_proxy(structure: Structure, tolerances: dict[str, float]) -> dict[str, Any]:
    na_indices = {idx for idx, site in enumerate(structure) if _symbol(site) == "Na"}
    edges: list[tuple[int, int, tuple[int, int, int]]] = []
    oxygen_cn: list[int] = []
    framework_contacts: list[dict[str, Any]] = []
    for idx in sorted(na_indices):
        site = structure[idx]
        oxygen_cn.append(sum(_symbol(item) == "O" for item in structure.get_neighbors(site, tolerances["na_o_cutoff_angstrom"])))
        for neighbor in structure.get_neighbors(site, tolerances["na_na_channel_cutoff_angstrom"]):
            if _symbol(neighbor) == "Na" and (idx < int(neighbor.index) or any(int(v) != 0 for v in neighbor.image)):
                edges.append((idx, int(neighbor.index), tuple(int(v) for v in neighbor.image)))
        for neighbor in structure.get_neighbors(site, tolerances["na_framework_cation_min_angstrom"]):
            if _symbol(neighbor) in {"Zr", "Si", "P"}:
                framework_contacts.append({"na_index": idx, "center_index": int(neighbor.index), "distance": float(neighbor.nn_distance)})
    rank, connected, cycles = _periodic_graph_rank(na_indices, edges)
    return {
        "definition": "Na-Na periodic graph at <=4.50 A, with Na excluded from framework-center contacts <2.50 A",
        "na_site_count": len(na_indices), "na_o_coordination": oxygen_cn,
        "mean_na_o_coordination": float(np.mean(oxygen_cn)) if oxygen_cn else None,
        "na_na_edge_count": len(edges), "periodic_rank": rank, "connected": connected,
        "translation_cycles": cycles, "framework_cation_short_contacts": framework_contacts,
        "channel_like": bool(rank >= 1 and not framework_contacts),
    }


def validate_nasicon_topology(
    cif_or_structure: str | Path | Structure,
    *,
    tolerances: dict[str, float] | None = None,
) -> dict[str, Any]:
    limits = {**DEFAULT_TOLERANCES, **(tolerances or {})}
    try:
        structure = cif_or_structure if isinstance(cif_or_structure, Structure) else Structure.from_file(str(cif_or_structure))
    except Exception as exc:
        return {"topology_status": "FAIL", "parseable_cif": False, "error": str(exc), "tolerances": limits}

    expected = Composition("Na3Zr2Si2PO12").reduced_composition
    formula_correct = structure.composition.reduced_composition == expected
    zr = _coordination(structure, "Zr", limits["zr_o_cutoff_angstrom"])
    si = _coordination(structure, "Si", limits["si_o_cutoff_angstrom"])
    phosphorus = _coordination(structure, "P", limits["p_o_cutoff_angstrom"])
    all_polyhedra = zr + si + phosphorus
    fractions = {
        "zr_o6_fraction": sum(item["coordination_number"] == 6 for item in zr) / len(zr) if zr else 0.0,
        "si_o4_fraction": sum(item["coordination_number"] == 4 for item in si) / len(si) if si else 0.0,
        "p_o4_fraction": sum(item["coordination_number"] == 4 for item in phosphorus) / len(phosphorus) if phosphorus else 0.0,
    }
    framework_rank, framework_connected, framework_cycles = _framework_graph(structure, all_polyhedra)
    sharing = _sharing(all_polyhedra)
    sodium = _sodium_channel_proxy(structure, limits)

    distances = np.asarray(structure.distance_matrix, dtype=float)
    distances[distances < 1e-12] = np.inf
    min_contact = float(np.min(distances)) if len(structure) > 1 else math.inf
    severe_short_contact = min_contact < limits["severe_short_contact_angstrom"]
    warnings: list[str] = []
    if not formula_correct:
        warnings.append("reduced_formula_mismatch")
    if framework_rank < 3:
        warnings.append("framework_not_proven_three_dimensional")
    if not framework_connected:
        warnings.append("framework_graph_disconnected")
    if not sodium["channel_like"]:
        warnings.append("sodium_channel_proxy_not_satisfied")
    if severe_short_contact:
        warnings.append("severe_short_contact")

    perfect_coordination = all(value == 1.0 for value in fractions.values())
    if formula_correct and perfect_coordination and framework_connected and framework_rank == 3 and not severe_short_contact:
        status = "PASS" if sodium["channel_like"] else "PARTIAL"
    elif formula_correct and min(fractions.values()) >= 0.5 and framework_rank >= 2 and not severe_short_contact:
        status = "PARTIAL"
    else:
        status = "FAIL"

    bond_lengths = {center: _distribution(itertools.chain.from_iterable(item["bond_lengths_angstrom"] for item in records)) for center, records in (("Zr-O", zr), ("Si-O", si), ("P-O", phosphorus))}
    angle_distributions = {center: _distribution(_angles(structure, records)) for center, records in (("O-Zr-O", zr), ("O-Si-O", si), ("O-P-O", phosphorus))}
    return {
        "schema_version": "nasicon_topology_validation.v1",
        "topology_status": status, "parseable_cif": True,
        "reduced_formula": str(structure.composition.reduced_formula), "formula_correct": formula_correct,
        "site_count": len(structure), "framework_dimensionality": framework_rank,
        "framework_connected": framework_connected, "framework_translation_cycles": framework_cycles,
        **fractions, **sharing, "sodium_channel_proxy": sodium,
        "coordination_records": {"Zr": zr, "Si": si, "P": phosphorus},
        "bond_length_distributions_angstrom": bond_lengths, "bond_angle_distributions_degrees": angle_distributions,
        "minimum_interatomic_distance_angstrom": min_contact, "severe_short_contact": severe_short_contact,
        "tolerances": limits, "warnings": warnings,
        "claim_scope": "geometric NASICON-topology screen; not stability, conductivity, novelty, or realizability evidence",
    }


__all__ = ["DEFAULT_TOLERANCES", "validate_nasicon_topology"]
