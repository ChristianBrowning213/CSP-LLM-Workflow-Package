"""Retrieval-informed, hard-feasibility-aware cubic search-cell sizing."""

from __future__ import annotations

import hashlib
import math
import statistics
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pyomo.environ as pyo
from ase import Atoms
from pymatgen.core import Composition, Structure

from sok_llm_orchestrator.workflow.cell_strategy import (
    GLOBAL_VPA_A3_PER_ATOM,
    NATIVE_GRID_DENSITY,
    ResolvedCell,
    n_target_atoms,
)


POLICY_VERSION = "retrieval_feasible_cell_v1"
MIN_VOLUME_OBSERVATIONS = 5
EXPANSION_FACTOR = 1.10
MAX_EDGE_EXPANSION = 2.0
MIN_EDGE_BOUND_A = 0.5
BINARY_SEARCH_TOLERANCE_A = 0.001
EDGE_SAFETY_MARGIN = 1.01
FEASIBILITY_TIME_LIMIT_S = 60


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def retrieval_volume_prior(
    formula: str,
    evidence_selected: Iterable[Any],
    *,
    minimum_observations: int = MIN_VOLUME_OBSERVATIONS,
    excluded_cif_hashes: Iterable[str] = (),
) -> dict[str, Any]:
    """Build an auditable VPA prior from the existing ranked evidence cohort.

    Exact target-composition records, caller-declared reference hashes, duplicate
    CIF hashes, missing/invalid structures, and nonphysical volumes are excluded.
    The input order is retained so duplicate handling is deterministic.
    """
    if minimum_observations < 1:
        raise ValueError("minimum_observations must be positive")
    target = Composition(formula).reduced_composition
    excluded_hashes = {str(value).lower() for value in excluded_cif_hashes}
    seen_hashes: set[str] = set()
    records: list[dict[str, Any]] = []
    included_values: list[float] = []
    for rank, item in enumerate(evidence_selected, start=1):
        path = Path(str(_value(item, "cif_path", "")))
        declared_hash = str(_value(item, "cif_sha256", "")).lower()
        record: dict[str, Any] = {
            "retrieval_rank": int(_value(item, "retrieval_rank", rank)),
            "retrieved_record_id": str(_value(item, "structure_id", "")),
            "cif_path": str(path),
            "cif_sha256": declared_hash,
            "formula": None,
            "volume_A3": None,
            "atom_count": None,
            "volume_per_atom_A3": None,
            "included": False,
            "exclusion_reason": "",
        }
        if not path.is_file():
            record["exclusion_reason"] = "CIF_MISSING"
            records.append(record)
            continue
        actual_hash = _sha256(path)
        record["cif_sha256"] = actual_hash
        if declared_hash and declared_hash != actual_hash:
            record["exclusion_reason"] = "CIF_HASH_MISMATCH"
            records.append(record)
            continue
        if actual_hash in excluded_hashes:
            record["exclusion_reason"] = "DECLARED_TARGET_OR_REFERENCE_HASH"
            records.append(record)
            continue
        if actual_hash in seen_hashes:
            record["exclusion_reason"] = "DUPLICATE_CIF_HASH"
            records.append(record)
            continue
        seen_hashes.add(actual_hash)
        try:
            structure = Structure.from_file(path)
        except Exception as exc:
            record["exclusion_reason"] = f"CIF_PARSE_ERROR:{type(exc).__name__}"
            records.append(record)
            continue
        record["formula"] = structure.composition.reduced_formula
        if structure.composition.reduced_composition == target:
            record["exclusion_reason"] = "TARGET_REDUCED_COMPOSITION"
            records.append(record)
            continue
        volume = float(structure.volume)
        atom_count = len(structure)
        record["volume_A3"] = volume
        record["atom_count"] = atom_count
        if atom_count <= 0:
            record["exclusion_reason"] = "EMPTY_STRUCTURE"
            records.append(record)
            continue
        if not math.isfinite(volume) or volume <= 0.0:
            record["exclusion_reason"] = "NONPOSITIVE_OR_NONFINITE_VOLUME"
            records.append(record)
            continue
        vpa = volume / atom_count
        record["volume_per_atom_A3"] = vpa
        record["included"] = True
        included_values.append(vpa)
        records.append(record)

    usable = len(included_values) >= minimum_observations
    if usable:
        vpa = float(statistics.median(sorted(included_values)))
        status = "RETRIEVAL_VOLUME_USABLE"
        source = "leakage_filtered_retrieval_median"
    else:
        vpa = GLOBAL_VPA_A3_PER_ATOM
        status = "GLOBAL_VOLUME_FALLBACK"
        source = "frozen_global_corpus_median_fallback"
    atoms = n_target_atoms(formula)
    return {
        "policy_version": POLICY_VERSION,
        "formula": formula,
        "status": status,
        "retrieval_volume_status": (
            "RETRIEVAL_VOLUME_USABLE" if usable else "RETRIEVAL_VOLUME_INSUFFICIENT"
        ),
        "minimum_valid_observations": minimum_observations,
        "valid_observation_count": len(included_values),
        "excluded_observation_count": len(records) - len(included_values),
        "vpa_source": source,
        "median_volume_per_atom_A3": vpa,
        "V_prior_A3": atoms * vpa,
        "a_prior_A": (atoms * vpa) ** (1.0 / 3.0),
        "records": records,
    }


class _ZeroCost:
    include_diagonal_pair_terms = False

    def __call__(self, _pair: tuple[str, str], distances: np.ndarray) -> np.ndarray:
        return np.zeros_like(distances, dtype=float)


def qlip_hard_geometry_feasibility(
    formula: str,
    edge_A: float,
    *,
    grid_density: int = NATIVE_GRID_DENSITY,
    time_limit_s: int = FEASIBILITY_TIME_LIMIT_S,
    proximity_scale: float = 1.0,
) -> dict[str, Any]:
    """Solve the real QLIP hard occupation model with its objective zeroed."""
    if edge_A <= 0.0:
        raise ValueError("edge_A must be positive")
    if grid_density <= 0:
        raise ValueError("grid_density must be positive")
    if proximity_scale <= 0.0:
        raise ValueError("proximity_scale must be positive")
    from qlip.allocation import Allocation
    from qlip.core.solve import _build_positions
    from qlip.plugins.registry import ConstraintRegistry

    design_space = {
        "template": {
            "name": "cubic",
            "lattice": {
                "a": edge_A,
                "b": edge_A,
                "c": edge_A,
                "alpha": 90.0,
                "beta": 90.0,
                "gamma": 90.0,
                "units": "angstrom",
            },
        },
        "sites": {"mode": "uniform_grid", "uniform_grid": {"density": grid_density}},
    }
    positions = _build_positions(design_space)
    allocation = Allocation(Atoms(symbols=formula), positions=positions, cost=_ZeroCost())
    plugin = ConstraintRegistry.get("proximity.atomic_radii")
    if plugin is None:
        raise RuntimeError("QLIP proximity.atomic_radii plugin is unavailable")
    plugin.apply(allocation, {"scale": float(proximity_scale), "allow_self_overlap": False})
    allocation.encode()
    allocation.m.obj.deactivate()
    allocation.m.hard_feasibility_objective = pyo.Objective(expr=0.0)
    solver = pyo.SolverFactory("gurobi")
    if solver is None or not solver.available(exception_flag=False):
        raise RuntimeError("Gurobi solver is unavailable for dynamic-cell feasibility")
    solver.options.update({"TimeLimit": int(time_limit_s), "MIPGap": 0.0, "Threads": 1})
    result = solver.solve(allocation.m, tee=False)
    termination = result.solver.termination_condition
    feasible = termination in {
        pyo.TerminationCondition.optimal,
        pyo.TerminationCondition.feasible,
    }
    if termination == pyo.TerminationCondition.infeasible:
        status = "INFEASIBLE"
    elif feasible:
        status = "FEASIBLE"
    else:
        status = "UNKNOWN"
    return {
        "status": status,
        "feasible": feasible,
        "termination_condition": str(termination),
        "edge_A": float(edge_A),
        "volume_A3": float(edge_A**3),
        "grid_density": grid_density,
        "candidate_site_count": grid_density**3,
        "hard_constraint_source": (
            "QLIP Allocation.encode + "
            f"proximity.atomic_radii(scale={float(proximity_scale):g})"
        ),
        "proximity_scale": float(proximity_scale),
        "spp_objective_used": False,
    }


FeasibilityChecker = Callable[[str, float], dict[str, Any]]


def resolve_dynamic_cell(
    formula: str,
    evidence_selected: Iterable[Any],
    *,
    grid_density: int = NATIVE_GRID_DENSITY,
    excluded_cif_hashes: Iterable[str] = (),
    feasibility_checker: FeasibilityChecker | None = None,
    proximity_scale: float = 1.0,
) -> tuple[ResolvedCell, dict[str, Any]]:
    """Resolve one deterministic retrieval-feasible cubic QLIP cell."""
    prior = retrieval_volume_prior(
        formula,
        evidence_selected,
        excluded_cif_hashes=excluded_cif_hashes,
    )
    checker = feasibility_checker or (
        lambda target, edge: qlip_hard_geometry_feasibility(
            target, edge, grid_density=grid_density, proximity_scale=proximity_scale
        )
    )
    prior_edge = float(prior["a_prior_A"])
    checks: list[dict[str, Any]] = []

    def check(edge: float) -> dict[str, Any]:
        result = checker(formula, edge)
        checks.append(dict(result))
        if result.get("status") == "UNKNOWN":
            raise RuntimeError(f"hard-geometry feasibility was not decided at edge {edge:.12g} A")
        return result

    prior_result = check(prior_edge)
    if prior_result["feasible"]:
        geometry_status = "GEOMETRY_FEASIBLE_AT_PRIOR"
        upper_edge = prior_edge
        lower_edge = max(prior_edge / EXPANSION_FACTOR, MIN_EDGE_BOUND_A)
        lower_result = check(lower_edge)
        while lower_result["feasible"] and lower_edge > MIN_EDGE_BOUND_A:
            upper_edge = lower_edge
            lower_edge = max(lower_edge / EXPANSION_FACTOR, MIN_EDGE_BOUND_A)
            lower_result = check(lower_edge)
        if lower_result["feasible"]:
            lower_infeasible_edge = None
            geometric_edge = lower_edge
        else:
            lower_infeasible_edge = lower_edge
            while upper_edge - lower_infeasible_edge > BINARY_SEARCH_TOLERANCE_A:
                midpoint = (lower_infeasible_edge + upper_edge) / 2.0
                if check(midpoint)["feasible"]:
                    upper_edge = midpoint
                else:
                    lower_infeasible_edge = midpoint
            geometric_edge = upper_edge
    else:
        geometry_status = "GEOMETRY_EXPANDED_TO_FEASIBLE"
        lower_infeasible_edge = prior_edge
        upper_edge = prior_edge
        upper_result = prior_result
        while not upper_result["feasible"] and upper_edge < prior_edge * MAX_EDGE_EXPANSION:
            lower_infeasible_edge = upper_edge
            upper_edge = min(upper_edge * EXPANSION_FACTOR, prior_edge * MAX_EDGE_EXPANSION)
            upper_result = check(upper_edge)
        if not upper_result["feasible"]:
            raise RuntimeError(
                "GEOMETRY_NOT_FEASIBLE_WITHIN_BOUND: "
                f"{formula} remained infeasible through {MAX_EDGE_EXPANSION}x prior edge"
            )
        while upper_edge - lower_infeasible_edge > BINARY_SEARCH_TOLERANCE_A:
            midpoint = (lower_infeasible_edge + upper_edge) / 2.0
            if check(midpoint)["feasible"]:
                upper_edge = midpoint
            else:
                lower_infeasible_edge = midpoint
        geometric_edge = upper_edge

    base_edge = max(prior_edge, geometric_edge)
    final_edge = base_edge * EDGE_SAFETY_MARGIN
    final_result = check(final_edge)
    if not final_result["feasible"]:
        raise RuntimeError("fixed safety margin did not produce a feasible final dynamic cell")
    atoms = n_target_atoms(formula)
    final_volume = final_edge**3
    provenance = {
        "policy_version": POLICY_VERSION,
        "shape": "cubic",
        "grid_density": grid_density,
        "proximity_scale": float(proximity_scale),
        "retrieval_volume_prior": prior,
        "geometry_status": geometry_status,
        "minimum_feasible_edge_upper_bound_A": geometric_edge,
        "last_infeasible_edge_lower_bound_A": lower_infeasible_edge,
        "expansion_factor": EXPANSION_FACTOR,
        "maximum_edge_expansion": MAX_EDGE_EXPANSION,
        "minimum_edge_bound_A": MIN_EDGE_BOUND_A,
        "binary_search_tolerance_A": BINARY_SEARCH_TOLERANCE_A,
        "edge_safety_margin": EDGE_SAFETY_MARGIN,
        "final_edge_A": final_edge,
        "final_volume_A3": final_volume,
        "final_volume_per_atom_A3": final_volume / atoms,
        "feasibility_checks": checks,
        "final_status": geometry_status,
    }
    cell = ResolvedCell(
        cell_mode=POLICY_VERSION,
        a=final_edge,
        b=final_edge,
        c=final_edge,
        alpha=90.0,
        beta=90.0,
        gamma=90.0,
        grid_density=grid_density,
        grid_spacing_A=final_edge / grid_density,
        n_target_atoms=atoms,
        vpa_source=str(prior["vpa_source"]),
        vpa_value=float(prior["median_volume_per_atom_A3"]),
        cell_volume_A3=final_volume,
        provenance=provenance,
    )
    return cell, provenance


def resolved_cell_from_dict(payload: Mapping[str, Any]) -> ResolvedCell:
    """Rehydrate a persisted dynamic cell without repeating feasibility work."""
    if payload.get("cell_mode") != POLICY_VERSION:
        raise ValueError(f"persisted cell is not {POLICY_VERSION}")
    return ResolvedCell(
        cell_mode=str(payload["cell_mode"]),
        a=float(payload["a"]),
        b=float(payload["b"]),
        c=float(payload["c"]),
        alpha=float(payload["alpha"]),
        beta=float(payload["beta"]),
        gamma=float(payload["gamma"]),
        grid_density=int(payload["grid_density"]),
        grid_spacing_A=float(payload["grid_spacing_A"]),
        n_target_atoms=int(payload["n_target_atoms"]),
        vpa_source=str(payload["vpa_source"]),
        vpa_value=(
            None
            if payload.get("vpa_value_A3_per_atom") is None
            else float(payload["vpa_value_A3_per_atom"])
        ),
        cell_volume_A3=float(payload["cell_volume_A3"]),
        provenance=dict(payload.get("provenance") or {}),
    )


__all__ = [
    "BINARY_SEARCH_TOLERANCE_A",
    "EDGE_SAFETY_MARGIN",
    "EXPANSION_FACTOR",
    "FEASIBILITY_TIME_LIMIT_S",
    "MAX_EDGE_EXPANSION",
    "MIN_EDGE_BOUND_A",
    "MIN_VOLUME_OBSERVATIONS",
    "POLICY_VERSION",
    "qlip_hard_geometry_feasibility",
    "resolve_dynamic_cell",
    "resolved_cell_from_dict",
    "retrieval_volume_prior",
]
