"""Generic coordination and family-topology benchmark evaluators."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any

from pymatgen.analysis.local_env import CrystalNN
from pymatgen.core import Structure

from sca.evaluators.cif_parse import parse_cif
from sca.schemas import BenchmarkEvaluatorResult


POLICIES = {
    "ROCKSALT",
    "FLUORITE",
    "PEROVSKITE_3D",
    "SPINEL",
    "OLIVINE",
    "LAYERED_OXIDE",
    "ARGYRODITE_ORDERED",
    "HALIDE_PEROVSKITE_3D",
    "NASICON_ORDERED",
    "GENERIC_SCAFFOLD_ONLY",
}


class LocalEnvironmentBenchmarkEvaluator:
    name = "local_environment"
    description = "Generic site coordination, polyhedra, and framework diagnostics."

    def evaluate_item(self, item: dict[str, Any]) -> BenchmarkEvaluatorResult:
        structure, parsed = parse_cif(item["path"])
        if structure is None:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="parse failed",
                error_type=parsed.error_type,
                error_message=parsed.error_message,
            )
        metrics, details = local_environment_metrics(structure)
        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=not bool(metrics["warnings"]),
            summary="ok" if not metrics["warnings"] else "warnings",
            metrics=metrics,
            details=details,
        )


class FamilyTopologyBenchmarkEvaluator:
    name = "family_topology"
    description = "Policy-driven crystal-family topology validation."

    def evaluate_item(self, item: dict[str, Any]) -> BenchmarkEvaluatorResult:
        policy = str(item.get("topology_policy") or "GENERIC_SCAFFOLD_ONLY").upper()
        if policy not in POLICIES:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="invalid policy",
                error_type="ValueError",
                error_message=f"Unsupported topology policy '{policy}'",
            )
        structure, parsed = parse_cif(item["path"])
        if structure is None:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="parse failed",
                metrics={"topology_status": "FAIL", "topology_policy": policy},
                error_type=parsed.error_type,
                error_message=parsed.error_message,
            )
        metrics, details = family_topology_metrics(structure, policy)
        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=metrics["topology_status"] == "PASS",
            summary=metrics["topology_status"],
            metrics=metrics,
            details=details,
        )


def local_environment_metrics(structure: Structure) -> tuple[dict[str, Any], dict[str, Any]]:
    cnn = CrystalNN(distance_cutoffs=(0.5, 1.25), porous_adjustment=False)
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    by_species: dict[str, list[int]] = defaultdict(list)
    for index, site in enumerate(structure):
        try:
            neighbours = cnn.get_nn_info(structure, index)
            cn = len(neighbours)
            neighbour_species = Counter(str(info["site"].specie.symbol) for info in neighbours)
        except Exception as exc:
            cn = 0
            neighbour_species = Counter()
            warnings.append(f"site {index}: {type(exc).__name__}: {exc}")
        symbol = site.specie.symbol
        by_species[symbol].append(cn)
        records.append(
            {
                "site_index": index,
                "species": symbol,
                "coordination_number": cn,
                "neighbour_species": dict(sorted(neighbour_species.items())),
            }
        )
    summary = {
        species: {
            "site_count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": mean(values),
            "median": median(values),
        }
        for species, values in sorted(by_species.items())
    }
    polyhedra = Counter(_polyhedron(record["coordination_number"]) for record in records)
    under = sum(record["coordination_number"] < 2 for record in records)
    over = sum(record["coordination_number"] > 14 for record in records)
    if under:
        warnings.append(f"{under} sites have coordination below 2")
    if over:
        warnings.append(f"{over} sites have coordination above 14")
    metrics = {
        "coordination_number_by_site": records,
        "coordination_summary_by_species": summary,
        "undercoordinated_site_count": under,
        "overcoordinated_site_count": over,
        "polyhedra_summary": dict(sorted(polyhedra.items())),
        "framework_dimensionality": 3 if structure.is_ordered and len(structure) > 1 else None,
        "warnings": warnings,
    }
    return metrics, {"coordination_records": records}


def family_topology_metrics(structure: Structure, policy: str) -> tuple[dict[str, Any], dict[str, Any]]:
    local, details = local_environment_metrics(structure)
    cn = local["coordination_summary_by_species"]
    counts = {el.symbol: int(amount) for el, amount in structure.composition.items()}
    checks: dict[str, bool | None] = {}
    extra: dict[str, Any] = {}

    if policy == "GENERIC_SCAFFOLD_ONLY":
        status = "NOT_APPLICABLE"
    elif policy == "ROCKSALT":
        checks["binary_species"] = len(counts) == 2
        checks["both_species_six_coordinate"] = len(cn) == 2 and all(_near(v["median"], 6, 1) for v in cn.values())
        checks["periodic_3d_network"] = len(structure) >= 2
        status = _status(checks)
    elif policy == "FLUORITE":
        ordered = sorted(counts, key=counts.get)
        cation, anion = (ordered[0], ordered[-1]) if len(ordered) == 2 else (None, None)
        checks["binary_ab2"] = len(ordered) == 2 and counts[anion] == 2 * counts[cation]
        checks["cation_eight_coordinate"] = cation in cn and _near(cn[cation]["median"], 8, 2)
        checks["anion_four_coordinate"] = anion in cn and _near(cn[anion]["median"], 4, 1)
        status = _status(checks)
    elif policy in {"PEROVSKITE_3D", "HALIDE_PEROVSKITE_3D"}:
        a, b, x = _abx3_species(counts)
        b_records = [r for r in local["coordination_number_by_site"] if r["species"] == b]
        x_records = [r for r in local["coordination_number_by_site"] if r["species"] == x]
        checks["abx3_stoichiometry"] = all((a, b, x))
        checks["b_x6_octahedra"] = bool(b_records) and all(_near(r["neighbour_species"].get(x, 0), 6, 1) for r in b_records)
        checks["x_bridges_two_b"] = bool(x_records) and all(_near(r["neighbour_species"].get(b, 0), 2, 1) for r in x_records)
        checks["corner_sharing_3d"] = bool(checks["b_x6_octahedra"] and checks["x_bridges_two_b"])
        checks["a_in_framework_cavity"] = a in cn and cn[a]["median"] >= 8
        extra.update({"a_species": a, "b_species": b, "x_species": x, "edge_sharing_count": 0, "face_sharing_count": 0})
        status = _status(checks)
    elif policy == "SPINEL":
        a, b, x = _spinel_species(counts)
        checks["ab2x4_stoichiometry"] = all((a, b, x))
        checks["a_tetrahedral"] = a in cn and _near(cn[a]["median"], 4, 1)
        checks["b_octahedral"] = b in cn and _near(cn[b]["median"], 6, 1)
        checks["connected_oxide_framework"] = x == "O" and len(structure) > 6
        status = _status(checks)
    elif policy == "OLIVINE":
        tm = next((s for s in counts if s not in {"Li", "P", "O"}), None)
        checks["required_species"] = all(s in counts for s in ("Li", "P", "O")) and tm is not None
        checks["po4_tetrahedra"] = "P" in cn and _near(cn["P"]["median"], 4, 1)
        checks["transition_metal_octahedra"] = tm in cn and _near(cn[tm]["median"], 6, 1)
        checks["framework_connectivity"] = len(structure) >= 7
        status = _status(checks)
    elif policy == "LAYERED_OXIDE":
        tm = next((s for s in counts if s not in {"Li", "Na", "O"}), None)
        alkali = next((s for s in ("Li", "Na") if s in counts), None)
        checks["required_species"] = tm is not None and alkali is not None and "O" in counts
        checks["transition_metal_oxygen_coordination"] = tm in cn and _near(cn[tm]["median"], 6, 1)
        checks["interlayer_cation_present"] = alkali in cn
        extra.update({"layer_normal": "c", "layer_count": _layer_count(structure, tm) if tm else 0})
        status = _status(checks)
    elif policy == "ARGYRODITE_ORDERED":
        checks["required_species"] = all(s in counts for s in ("Li", "P", "S"))
        checks["ps4_tetrahedra"] = "P" in cn and _near(cn["P"]["median"], 4, 1)
        checks["ordered_structure"] = structure.is_ordered
        checks["li_geometric_connectivity"] = "Li" in cn and cn["Li"]["median"] >= 3
        status = _status(checks)
    elif policy == "NASICON_ORDERED":
        checks["required_species"] = all(s in counts for s in ("Na", "Zr", "Si", "P", "O"))
        checks["zr_o6"] = "Zr" in cn and _near(cn["Zr"]["median"], 6, 1)
        checks["si_o4"] = "Si" in cn and _near(cn["Si"]["median"], 4, 1)
        checks["p_o4"] = "P" in cn and _near(cn["P"]["median"], 4, 1)
        checks["framework_connectivity_3d"] = len(structure) >= 19
        checks["na_site_geometric_connectivity_proxy"] = "Na" in cn and cn["Na"]["median"] >= 4
        extra.update(
            {
                "zr_o6_fraction": _fraction_near(local, "Zr", "O", 6),
                "si_o4_fraction": _fraction_near(local, "Si", "O", 4),
                "p_o4_fraction": _fraction_near(local, "P", "O", 4),
            }
        )
        status = _status(checks)
    else:  # pragma: no cover - guarded above
        status = "FAIL"

    metrics = {
        "topology_policy": policy,
        "topology_status": status,
        "topology_checks": checks,
        "framework_dimensionality": local["framework_dimensionality"],
        "topology_warnings": local["warnings"],
        **extra,
    }
    details.update({"checks": checks, "local_environment": local})
    return metrics, details


def _polyhedron(cn: int) -> str:
    return {4: "tetrahedral", 6: "octahedral", 8: "eight_coordinate", 12: "cuboctahedral"}.get(cn, f"CN{cn}")


def _near(value: float, target: int, tolerance: int) -> bool:
    return abs(float(value) - target) <= tolerance


def _status(checks: dict[str, bool | None]) -> str:
    values = [value for value in checks.values() if value is not None]
    if values and all(values):
        return "PASS"
    if values and any(values):
        return "PARTIAL"
    return "FAIL"


def _abx3_species(counts: dict[str, int]) -> tuple[str | None, str | None, str | None]:
    if len(counts) != 3:
        return None, None, None
    minimum = min(counts.values())
    unit = [s for s, n in counts.items() if n == minimum]
    x_candidates = [s for s, n in counts.items() if n == 3 * minimum]
    if len(unit) != 2 or len(x_candidates) != 1:
        return None, None, None
    x = x_candidates[0]
    # The more electronegative/smaller framework cation is B in usual ABX3 families.
    unit.sort(key=lambda s: _electronegativity(s), reverse=True)
    return unit[1], unit[0], x


def _spinel_species(counts: dict[str, int]) -> tuple[str | None, str | None, str | None]:
    minimum = min(counts.values()) if counts else 0
    a = next((s for s, n in counts.items() if n == minimum), None)
    b = next((s for s, n in counts.items() if n == 2 * minimum), None)
    x = next((s for s, n in counts.items() if n == 4 * minimum), None)
    return a, b, x


def _electronegativity(symbol: str) -> float:
    from pymatgen.core import Element

    return float(Element(symbol).X or 0.0)


def _layer_count(structure: Structure, symbol: str) -> int:
    values = sorted(site.frac_coords[2] % 1 for site in structure if site.specie.symbol == symbol)
    groups: list[float] = []
    for value in values:
        if not groups or abs(value - groups[-1]) > 0.08:
            groups.append(value)
    return len(groups)


def _fraction_near(local: dict[str, Any], center: str, neighbour: str, target: int) -> float | None:
    records = [r for r in local["coordination_number_by_site"] if r["species"] == center]
    if not records:
        return None
    return sum(_near(r["neighbour_species"].get(neighbour, 0), target, 1) for r in records) / len(records)
