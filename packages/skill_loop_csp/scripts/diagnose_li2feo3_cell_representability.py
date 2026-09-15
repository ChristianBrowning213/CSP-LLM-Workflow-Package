"""Controlled A/B/C Li2FeO3 search-cell representability diagnostic.

This script consumes only the frozen, portable ``layered_007`` row bundle.  It
does not retrieve structures, fit SPPs, change the production cell policy, or
write inside the source row.  The only scientific variable between A/B/C is
the orthogonal lattice geometry supplied to the same 4x4x4 native QLIP search.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import statistics
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pyomo.environ as pyo
from ase import Atoms
from pymatgen.core import Structure


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROW_DEFAULT = REPO_ROOT / "outputs" / "paper_50_50_csv_workflow_v1" / "layered_007"
OUTPUT_ROOT_DEFAULT = REPO_ROOT / "outputs" / "li2feo3_cell_representability_v1"
FORMULA = "Li2FeO3"
REQUEST = "Generate a plausible layered battery oxide crystal structure for Li2FeO3."
HELD_OUT_REFERENCE = "mp-aaabwiyp"
GRID_DENSITY = 4
OLD_CUBE_EDGE_A = 4.761
EXPANSION_FACTOR = 1.10
MAX_SCALE_EXPANSION = 2.0
BINARY_SEARCH_AXIS_TOLERANCE_A = 0.001
EDGE_SAFETY_MARGIN = 1.01


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tree_hashes(root: Path) -> dict[str, str]:
    root = Path(root).resolve()
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower())
        if path.is_file()
    }


def normalized_lattice_ratios(lengths: Sequence[float]) -> tuple[float, float, float]:
    """Sort three positive lengths and normalize their product to one."""
    if len(lengths) != 3:
        raise ValueError("exactly three lattice lengths are required")
    ordered = sorted(float(value) for value in lengths)
    if any(not math.isfinite(value) or value <= 0.0 for value in ordered):
        raise ValueError("lattice lengths must be finite and positive")
    geometric_mean = math.prod(ordered) ** (1.0 / 3.0)
    return tuple(value / geometric_mean for value in ordered)  # type: ignore[return-value]


def aggregate_median_shape(ratios: Iterable[Sequence[float]]) -> tuple[float, float, float]:
    """Take component medians, restore unit product, and assign the longest to c."""
    rows = [tuple(float(value) for value in row) for row in ratios]
    if not rows or any(len(row) != 3 for row in rows):
        raise ValueError("one or more ratio triplets are required")
    medians = [statistics.median(row[index] for row in rows) for index in range(3)]
    normalizer = math.prod(medians) ** (1.0 / 3.0)
    return tuple(sorted(value / normalizer for value in medians))  # type: ignore[return-value]


def scale_shape_to_volume(shape: Sequence[float], volume_A3: float) -> tuple[float, float, float]:
    """Uniformly scale a positive length shape to an exact orthogonal volume."""
    if len(shape) != 3 or volume_A3 <= 0.0:
        raise ValueError("a positive volume and three shape ratios are required")
    product = math.prod(float(value) for value in shape)
    if product <= 0.0:
        raise ValueError("shape ratios must be positive")
    factor = (float(volume_A3) / product) ** (1.0 / 3.0)
    return tuple(float(value) * factor for value in shape)  # type: ignore[return-value]


def uniformly_scaled(lengths: Sequence[float], factor: float) -> tuple[float, float, float]:
    if len(lengths) != 3 or factor <= 0.0:
        raise ValueError("three lengths and a positive scale factor are required")
    return tuple(float(value) * float(factor) for value in lengths)  # type: ignore[return-value]


def lattice_payload(lengths: Sequence[float]) -> dict[str, float]:
    a, b, c = (float(value) for value in lengths)
    return {"a": a, "b": b, "c": c, "alpha": 90.0, "beta": 90.0, "gamma": 90.0}


class _ZeroCost:
    include_diagonal_pair_terms = False

    def __call__(self, _pair: tuple[str, str], distances: np.ndarray) -> np.ndarray:
        return np.zeros_like(distances, dtype=float)


def hard_geometry_feasibility(
    formula: str,
    lengths: Sequence[float],
    *,
    grid_density: int = GRID_DENSITY,
    time_limit_s: int = 60,
    proximity_scale: float = 1.0,
) -> dict[str, Any]:
    """Run the real QLIP hard occupation model for an orthogonal A/B/C cell."""
    from qlip.allocation import Allocation
    from qlip.core.solve import _build_positions
    from qlip.plugins.registry import ConstraintRegistry

    cell = lattice_payload(lengths)
    design_space = {
        "template": {"name": "orthogonal_diagnostic", "lattice": cell | {"units": "angstrom"}},
        "sites": {"mode": "uniform_grid", "uniform_grid": {"density": int(grid_density)}},
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
        raise RuntimeError("Gurobi solver is unavailable for diagnostic feasibility")
    solver.options.update({"TimeLimit": int(time_limit_s), "MIPGap": 0.0, "Threads": 1})
    started = time.perf_counter()
    result = solver.solve(allocation.m, tee=False)
    runtime_s = time.perf_counter() - started
    termination = result.solver.termination_condition
    feasible = termination in {pyo.TerminationCondition.optimal, pyo.TerminationCondition.feasible}
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
        "runtime_s": runtime_s,
        "lattice": cell,
        "volume_A3": math.prod(float(value) for value in lengths),
        "grid_density": int(grid_density),
        "candidate_site_count": int(grid_density) ** 3,
        "hard_constraint_source": (
            "QLIP Allocation.encode + proximity.atomic_radii"
            f"(scale={float(proximity_scale):g})"
        ),
        "proximity_scale": float(proximity_scale),
        "spp_objective_used": False,
    }


FeasibilityChecker = Callable[[Sequence[float]], Mapping[str, Any]]


def expand_anisotropic_to_feasible(
    initial_lengths: Sequence[float],
    checker: FeasibilityChecker,
    *,
    expansion_factor: float = EXPANSION_FACTOR,
    maximum_scale: float = MAX_SCALE_EXPANSION,
    axis_tolerance_A: float = BINARY_SEARCH_AXIS_TOLERANCE_A,
    safety_margin: float = EDGE_SAFETY_MARGIN,
) -> tuple[tuple[float, float, float], dict[str, Any]]:
    """Preserve aspect ratios while applying the production-style expansion search."""
    initial = tuple(float(value) for value in initial_lengths)
    checks: list[dict[str, Any]] = []

    def check(scale: float) -> dict[str, Any]:
        lengths = uniformly_scaled(initial, scale)
        result = dict(checker(lengths))
        result["edge_scale_factor"] = scale
        result["lengths_A"] = list(lengths)
        checks.append(result)
        if result.get("status") == "UNKNOWN":
            raise RuntimeError(f"hard-geometry feasibility undecided at scale {scale:.12g}")
        return result

    initial_result = check(1.0)
    if bool(initial_result.get("feasible")):
        return initial, {
            "expansion_required": False,
            "initial_lengths_A": list(initial),
            "final_lengths_A": list(initial),
            "edge_scale_factor": 1.0,
            "volume_increase_A3": 0.0,
            "feasibility_checks": checks,
        }

    lower = 1.0
    upper = 1.0
    upper_result = initial_result
    while not bool(upper_result.get("feasible")) and upper < maximum_scale:
        lower = upper
        upper = min(upper * expansion_factor, maximum_scale)
        upper_result = check(upper)
    if not bool(upper_result.get("feasible")):
        raise RuntimeError(
            "GEOMETRY_NOT_FEASIBLE_WITHIN_BOUND: anisotropic cell remained infeasible "
            f"through {maximum_scale}x initial axes"
        )
    scale_tolerance = axis_tolerance_A / max(initial)
    while upper - lower > scale_tolerance:
        midpoint = (lower + upper) / 2.0
        if bool(check(midpoint).get("feasible")):
            upper = midpoint
        else:
            lower = midpoint
    minimum_feasible_scale = upper
    final_scale = minimum_feasible_scale * safety_margin
    final_result = check(final_scale)
    if not bool(final_result.get("feasible")):
        raise RuntimeError("fixed safety margin did not produce a feasible anisotropic cell")
    final = uniformly_scaled(initial, final_scale)
    return final, {
        "expansion_required": True,
        "initial_lengths_A": list(initial),
        "minimum_feasible_scale_upper_bound": minimum_feasible_scale,
        "last_infeasible_scale_lower_bound": lower,
        "edge_safety_margin": safety_margin,
        "final_lengths_A": list(final),
        "edge_scale_factor": final_scale,
        "initial_volume_A3": math.prod(initial),
        "final_volume_A3": math.prod(final),
        "volume_increase_A3": math.prod(final) - math.prod(initial),
        "feasibility_checks": checks,
    }


def retrieval_shape_prior(source_row: Path) -> dict[str, Any]:
    """Derive length-only anisotropy from the exact persisted VPA-included cohort."""
    prior = read_json(source_row / "cell" / "retrieval_volume_prior.json")
    portable = read_json(source_row / "retrieval" / "retrieval_manifest.json")
    portable_by_id = {str(row["structure_id"]): row for row in portable["selected"]}
    observations: list[dict[str, Any]] = []
    for record in prior["records"]:
        if not record.get("included"):
            continue
        structure_id = str(record["retrieved_record_id"])
        row = portable_by_id[structure_id]
        cif_path = source_row / str(row["portable_cif_path"])
        actual_hash = sha256_file(cif_path)
        expected_hash = str(record["cif_sha256"])
        if actual_hash != expected_hash or actual_hash != str(row["cif_sha256"]):
            raise RuntimeError(f"portable retrieval CIF hash mismatch for {structure_id}")
        structure = Structure.from_file(cif_path)
        lengths = tuple(float(value) for value in structure.lattice.abc)
        ratios = normalized_lattice_ratios(lengths)
        observations.append({
            "retrieval_rank": int(record["retrieval_rank"]),
            "structure_id": structure_id,
            "formula": structure.composition.reduced_formula,
            "portable_cif_path": cif_path.relative_to(source_row).as_posix(),
            "cif_sha256": actual_hash,
            "lattice_lengths_A": list(lengths),
            "sorted_lattice_lengths_A": sorted(lengths),
            "geometric_mean_A": math.prod(lengths) ** (1.0 / 3.0),
            "normalized_sorted_ratios": list(ratios),
        })
    expected_count = int(prior["valid_observation_count"])
    if len(observations) != expected_count:
        raise RuntimeError(
            f"retrieval shape cohort count {len(observations)} != persisted VPA count {expected_count}"
        )
    shape = aggregate_median_shape(row["normalized_sorted_ratios"] for row in observations)
    component_medians = [
        statistics.median(row["normalized_sorted_ratios"][index] for row in observations)
        for index in range(3)
    ]
    return {
        "schema_version": "li2feo3_retrieval_length_shape_prior.v1",
        "source_policy": prior["policy_version"],
        "cohort_definition": "records included by frozen retrieval_volume_prior.json",
        "observation_count": len(observations),
        "component_medians_before_unit_product_renormalization": component_medians,
        "median_normalized_ratios": list(shape),
        "unit_product": math.prod(shape),
        "orientation_rule": "sorted ascending; longest assigned to c",
        "angles_degrees": [90.0, 90.0, 90.0],
        "observations": observations,
    }


def assert_fresh_output_root(output_root: Path, source_row: Path) -> None:
    output = Path(output_root).resolve()
    source = Path(source_row).resolve()
    if output == source or source in output.parents or output in source.parents:
        raise ValueError("diagnostic output must not be inside or contain the frozen source row")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing diagnostic output: {output}")


def scientific_invariants(
    *, request: str, formula: str, task: Mapping[str, Any], effective: Mapping[str, Any],
    request_spp: Mapping[str, Any], retrieval_hashes: Mapping[str, str], pot_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "request": request,
        "formula": formula,
        "structured_task_except_cell": dict(task),
        "retrieval_bundle_hashes": dict(retrieval_hashes),
        "spp_pot_hashes": dict(pot_hashes),
        "pair_manifest": request_spp["quality"]["request_pair_results"],
        "spp_contract": effective["spp_contract"],
        "cutoff_angstrom": effective["cutoff_angstrom"],
        "qlip_objective": "spp_energy",
        "solver": {
            "name": "gurobi",
            "time_limit_s": effective["solver_time_limit_s"],
            "threads": effective["solver_threads"],
            "mip_gap": effective["solver_mip_gap"],
            "requested_seed": effective["random_seed"],
            "effective_seed_behaviour": (
                "QLIP 0.3.0 truthiness guard does not forward integer zero to Gurobi"
                if int(effective["random_seed"]) == 0
                else "QLIP forwards nonzero integer Seed to Gurobi"
            ),
            "parameters": {"NonConvex": 2},
        },
        "proximity": {"plugin": "proximity.atomic_radii", "scale": effective["proximity_scale"]},
        "grid": {"mode": "uniform_grid", "dimensions": [GRID_DENSITY] * 3, "sites": 64},
        "scaffold": None,
        "excluded_structure_ids": [HELD_OUT_REFERENCE],
    }


def audit_variant_invariants(variants: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Assert that every variant differs only in its declared lattice geometry."""
    hashes = {name: canonical_hash(payload["invariants"]) for name, payload in variants.items()}
    passed = len(set(hashes.values())) == 1
    result = {
        "status": "PASS" if passed else "FAIL",
        "allowed_difference": "lattice_geometry_only",
        "variant_invariant_hashes": hashes,
        "identical_request": len({payload["invariants"]["request"] for payload in variants.values()}) == 1,
        "identical_formula": len({payload["invariants"]["formula"] for payload in variants.values()}) == 1,
        "identical_retrieval_bundle_hashes": len({canonical_hash(payload["invariants"]["retrieval_bundle_hashes"]) for payload in variants.values()}) == 1,
        "identical_spp_pot_hashes": len({canonical_hash(payload["invariants"]["spp_pot_hashes"]) for payload in variants.values()}) == 1,
        "identical_pair_manifest": len({canonical_hash(payload["invariants"]["pair_manifest"]) for payload in variants.values()}) == 1,
        "identical_qlip_settings": len({canonical_hash(payload["invariants"]["solver"]) for payload in variants.values()}) == 1,
        "identical_proximity": len({canonical_hash(payload["invariants"]["proximity"]) for payload in variants.values()}) == 1,
        "identical_grid": len({canonical_hash(payload["invariants"]["grid"]) for payload in variants.values()}) == 1,
    }
    if not passed:
        raise RuntimeError(f"scientific invariant audit failed: {result}")
    return result


@dataclass(frozen=True)
class Variant:
    key: str
    directory: str
    label: str
    lengths_A: tuple[float, float, float]
    feasibility: dict[str, Any]
    feasibility_trace: dict[str, Any]


def cell_record(variant: Variant, atom_count: int = 6) -> dict[str, Any]:
    a, b, c = variant.lengths_A
    volume = a * b * c
    shortest = min(a, b, c)
    return {
        "variant": variant.key,
        "label": variant.label,
        **lattice_payload(variant.lengths_A),
        "volume_A3": volume,
        "volume_per_atom_A3": volume / atom_count,
        "aspect_ratios_a_b_c_over_a": [a / shortest, b / shortest, c / shortest],
        "grid_density": GRID_DENSITY,
        "grid_spacings_A": [a / GRID_DENSITY, b / GRID_DENSITY, c / GRID_DENSITY],
        "hard_feasibility": variant.feasibility,
        "feasibility_expansion": variant.feasibility_trace,
    }


def dynamic_cell_payload(cell: Mapping[str, Any], variant: Variant) -> dict[str, Any]:
    payload = dict(cell)
    a, b, c = variant.lengths_A
    payload.update({
        **lattice_payload(variant.lengths_A),
        "grid_density": GRID_DENSITY,
        "grid_spacing_A": min(a, b, c) / GRID_DENSITY,
        "cell_volume_A3": a * b * c,
        "vpa_value_A3_per_atom": a * b * c / int(payload["n_target_atoms"]),
        "provenance": {
            "diagnostic_only": True,
            "variant": variant.key,
            "only_changed_variable": "lattice_geometry",
            "source_frozen_cell": cell,
            "feasibility": variant.feasibility,
            "feasibility_trace": variant.feasibility_trace,
        },
    })
    return payload


def sca_summary(raw: Mapping[str, Any], candidate_hash: str, variant: str) -> dict[str, Any]:
    parse = bool(raw.get("parse_ok"))
    composition = bool(raw.get("target_formula_match"))
    geometry = raw.get("geometry_ok") is True
    contacts = int(raw.get("num_bad_contacts") or 0)
    topology = str(raw.get("topology_status") or "NOT_EVALUATED")
    outcome = (
        "PASS"
        if parse and composition and geometry and contacts == 0 and topology in {"PASS", "NOT_EVALUATED"}
        else "PARTIAL"
        if parse and composition
        else "FAIL"
    )
    return {
        "variant": variant,
        "sca_status": outcome,
        "source_candidate_sha256": candidate_hash,
        "candidate_sha256_after": candidate_hash,
        "parse_ok": raw.get("parse_ok"),
        "composition_match": raw.get("target_formula_match"),
        "detected_space_group": raw.get("detected_space_group"),
        "requested_space_group": raw.get("target_space_group"),
        "space_group_match": raw.get("space_group_consistent"),
        "topology_result": topology,
        "geometry_valid": raw.get("geometry_ok"),
        "bad_contacts": contacts,
        "minimum_distance_angstrom": raw.get("min_distance"),
        "minimum_distance_species_pair": raw.get("min_distance_pair"),
        "structure_match_result": raw.get("novel_by_structure_matcher"),
    }


def structure_metrics(raw: Mapping[str, Any]) -> dict[str, Any]:
    details = dict(raw.get("topology_details") or {})
    local = dict(details.get("local_environment") or {})
    records = list(details.get("coordination_records") or local.get("coordination_number_by_site") or [])
    fe_records = [row for row in records if row.get("species") == "Fe"]
    li_records = [row for row in records if row.get("species") == "Li"]
    o_records = [row for row in records if row.get("species") == "O"]

    def summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"site_index": row.get("site_index"), "coordination_number": row.get("coordination_number"),
             "neighbour_species": row.get("neighbour_species", {})}
            for row in rows
        ]

    fe = fe_records[0] if fe_records else {}
    neighbours = dict(fe.get("neighbour_species") or {})
    return {
        "topology_policy": raw.get("topology_policy"),
        "topology_status": raw.get("topology_status"),
        "topology_checks": raw.get("topology_checks", {}),
        "framework_dimensionality": local.get("framework_dimensionality"),
        "fe_coordination_number": fe.get("coordination_number"),
        "fe_neighbour_species_counts": neighbours,
        "fe_o_neighbours": neighbours.get("O"),
        "fe_li_neighbours": neighbours.get("Li"),
        "li_coordination_summary": summaries(li_records),
        "o_coordination_summary": summaries(o_records),
    }


def solve_variant(
    variant: Variant, output_root: Path, source_cell: Mapping[str, Any], request_spp: Mapping[str, Any],
    task: Mapping[str, Any], config: Any, stages: Any,
) -> dict[str, Any]:
    variant_root = output_root / variant.directory
    qlip_root = variant_root / "qlip"
    candidate_root = variant_root / "generated"
    sca_root = variant_root / "sca"
    variant_root.mkdir(parents=True, exist_ok=True)
    for path in (qlip_root, candidate_root, sca_root):
        path.mkdir(parents=True, exist_ok=False)
    cell = cell_record(variant)
    write_json(variant_root / "cell.json", cell)
    if variant.key == "C":
        write_json(variant_root / "feasibility_trace.json", variant.feasibility_trace)
    variant_spp = dict(request_spp)
    variant_spp["dynamic_cell"] = dynamic_cell_payload(source_cell, variant)
    write_json(qlip_root / "solver_config.json", {
        "name": "gurobi", "time_limit_s": config.solver_time_limit_s,
        "threads": config.solver_threads, "mip_gap": config.solver_mip_gap,
        "requested_seed": config.solver_seed,
        "effective_seed_behaviour": "not forwarded because QLIP uses a truthiness guard for seed=0",
        "parameters": {"NonConvex": 2}, "proximity_scale": config.proximity_scale,
    })
    started = time.perf_counter()
    try:
        solved = stages.solve(dict(task), variant_spp, config, qlip_root)
    except Exception as exc:
        from sok_llm_orchestrator.workflow.runner import WorkflowStageError

        runtime_s = time.perf_counter() - started
        if isinstance(exc, WorkflowStageError) and str(exc.details.get("qlip_status")) in {
            "INFEASIBLE", "TIME_LIMIT_NO_SOLUTION"
        }:
            result = {
                "status": str(exc.details["qlip_status"]), "runtime_s": runtime_s,
                "candidate_produced": False, "candidate_sha256": None,
                "error": str(exc), "details": exc.details,
            }
            write_json(qlip_root / "solver_result.json", result)
            return {"variant": variant.key, "cell": cell, "qlip": result, "sca": None, "structure": None}
        raise
    runtime_s = time.perf_counter() - started
    candidate = candidate_root / "candidate.cif"
    if candidate.exists():
        raise FileExistsError(f"refusing to overwrite candidate: {candidate}")
    shutil.copy2(Path(solved["cif_path"]), candidate)
    candidate_hash = sha256_file(candidate)
    (candidate_root / "candidate.sha256").write_text(
        f"{candidate_hash}  candidate.cif\n", encoding="ascii"
    )
    diagnostics = dict(solved.get("solver_diagnostics") or {})
    qlip_result = {
        "status": solved["status"], "runtime_s": runtime_s,
        "solver_objective": solved["solver_objective"],
        "solver_summary": solved.get("solver_summary"),
        "solver_diagnostics": diagnostics,
        "search_space": solved.get("search_space"),
        "qlip_adapter": solved.get("qlip_adapter"),
        "objective_absolute_difference": solved.get("difference"),
        "requested_seed": config.solver_seed,
        "effective_seed_behaviour": "Gurobi Seed not set by QLIP because requested integer zero is falsy",
        "candidate_produced": True, "candidate_sha256": candidate_hash,
        "generated_cif_path": "generated/candidate.cif",
    }
    write_json(qlip_root / "solver_result.json", qlip_result)
    write_json(qlip_root / "problem_size.json", dict(diagnostics.get("model_stats") or {}) | {
        "candidate_positions": GRID_DENSITY**3, "auxiliary_linearisation_variables": 0,
    })
    raw = stages.evaluate(candidate, dict(task))
    if sha256_file(candidate) != candidate_hash:
        raise RuntimeError(f"SCA modified immutable diagnostic candidate for {variant.key}")
    summary = sca_summary(raw, candidate_hash, variant.key)
    write_json(sca_root / "config.json", {
        "backend": "sca.pipelines.evaluate_one_cif", "run_alignn": False,
        "source_candidate_sha256": candidate_hash,
    })
    write_json(sca_root / "result.json", raw)
    write_json(sca_root / "summary.json", summary)
    return {
        "variant": variant.key, "cell": cell, "qlip": qlip_result,
        "sca": summary, "structure": structure_metrics(raw),
    }


def comparison_row(result: Mapping[str, Any]) -> dict[str, Any]:
    cell = result["cell"]
    qlip = result["qlip"]
    sca = result.get("sca") or {}
    structure = result.get("structure") or {}
    spacings = cell["grid_spacings_A"]
    return {
        "variant": result["variant"], "a_A": cell["a"], "b_A": cell["b"], "c_A": cell["c"],
        "alpha_deg": cell["alpha"], "beta_deg": cell["beta"], "gamma_deg": cell["gamma"],
        "volume_A3": cell["volume_A3"], "volume_per_atom_A3": cell["volume_per_atom_A3"],
        "grid_dx_A": spacings[0], "grid_dy_A": spacings[1], "grid_dz_A": spacings[2],
        "hard_feasible": cell["hard_feasibility"].get("feasible"),
        "feasibility_expansion_required": cell["feasibility_expansion"].get("expansion_required", False),
        "qlip_status": qlip.get("status"), "qlip_runtime_s": qlip.get("runtime_s"),
        "qlip_objective": qlip.get("solver_objective"),
        "requested_seed": qlip.get("requested_seed", 0),
        "effective_seed_behaviour": qlip.get("effective_seed_behaviour"),
        "variables": (qlip.get("solver_diagnostics") or {}).get("model_stats", {}).get("variables"),
        "constraints": (qlip.get("solver_diagnostics") or {}).get("model_stats", {}).get("constraints"),
        "candidate_produced": qlip.get("candidate_produced"), "candidate_sha256": qlip.get("candidate_sha256"),
        "parse_ok": sca.get("parse_ok"), "composition_match": sca.get("composition_match"),
        "geometry_valid": sca.get("geometry_valid"), "bad_contacts": sca.get("bad_contacts"),
        "min_distance_A": sca.get("minimum_distance_angstrom"),
        "min_distance_pair": sca.get("minimum_distance_species_pair"),
        "detected_space_group": sca.get("detected_space_group"),
        "topology_policy": structure.get("topology_policy"), "topology_status": structure.get("topology_status"),
        "topology_checks": json.dumps(structure.get("topology_checks"), sort_keys=True),
        "framework_dimensionality": structure.get("framework_dimensionality"),
        "fe_coordination_number": structure.get("fe_coordination_number"),
        "fe_o_neighbours": structure.get("fe_o_neighbours"), "fe_li_neighbours": structure.get("fe_li_neighbours"),
        "li_coordination_summary": json.dumps(structure.get("li_coordination_summary"), sort_keys=True),
        "o_coordination_summary": json.dumps(structure.get("o_coordination_summary"), sort_keys=True),
    }


def write_comparison(output_root: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0])
    with (output_root / "COMPARISON.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    by_variant = {row["variant"]: row for row in rows}
    metrics = [
        ("a Å", "a_A"), ("b Å", "b_A"), ("c Å", "c_A"), ("volume Å³", "volume_A3"),
        ("grid dx/dy/dz Å", None), ("QLIP status", "qlip_status"), ("runtime s", "qlip_runtime_s"),
        ("objective", "qlip_objective"), ("min distance Å", "min_distance_A"),
        ("Fe CN", "fe_coordination_number"), ("Fe-O neighbours", "fe_o_neighbours"),
        ("Fe-Li neighbours", "fe_li_neighbours"), ("framework dimensionality", "framework_dimensionality"),
        ("topology", "topology_status"), ("detected SG", "detected_space_group"),
    ]
    lines = [
        "# Li2FeO3 cell representability comparison", "",
        "| Metric | A current cube | B old 4.761 cube | C retrieval anisotropic |",
        "|---|---:|---:|---:|",
    ]
    for label, field in metrics:
        values = []
        for key in ("A", "B", "C"):
            row = by_variant[key]
            value = (
                f"{row['grid_dx_A']:.6f} / {row['grid_dy_A']:.6f} / {row['grid_dz_A']:.6f}"
                if field is None else row.get(field)
            )
            values.append("" if value is None else str(value))
        lines.append(f"| {label} | {values[0]} | {values[1]} | {values[2]} |")
    (output_root / "COMPARISON.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def interpretation_case(rows: list[dict[str, Any]], original: Mapping[str, Any]) -> tuple[str, str, bool]:
    by = {row["variant"]: row for row in rows}
    statuses = {key: str(by[key].get("topology_status")) for key in ("A", "B", "C")}

    def pass_status(value: str) -> bool:
        return value == "PASS"

    def nonpass(value: str) -> bool:
        return value in {"PARTIAL", "FAIL"}
    if nonpass(statuses["A"]) and pass_status(statuses["B"]) and pass_status(statuses["C"]):
        case, explanation = "CASE 1", "Current cubic representability is implicated; both larger scale and retrieval-informed anisotropy repair topology."
    elif nonpass(statuses["A"]) and pass_status(statuses["B"]) and nonpass(statuses["C"]):
        case, explanation = "CASE 2", "Physical scale/volume is more important than same-volume anisotropy alone."
    elif nonpass(statuses["A"]) and nonpass(statuses["B"]) and pass_status(statuses["C"]):
        case, explanation = "CASE 3", "The retrieval-derived shape prior is specifically supported."
    elif all(nonpass(statuses[key]) for key in ("A", "B", "C")):
        case, explanation = "CASE 4", "Cell geometry alone is insufficient; pairwise SPP or missing higher-order topology is the stronger explanation."
    else:
        case, explanation = "UNCLASSIFIED", f"Observed topology pattern {statuses} does not match Cases 1-4."
    fresh_a_reproduced = (
        by["A"].get("qlip_status") == original.get("status")
        and by["A"].get("candidate_sha256") == original.get("generated_cif_sha256")
        and by["A"].get("topology_status") == original.get("topology_status")
    )
    if not fresh_a_reproduced:
        case = "CASE 5 / " + case
        explanation = "Fresh A differs materially from frozen A, so solver reproducibility is a confounder. " + explanation
    return case, explanation, fresh_a_reproduced


def run(source_row: Path, output_root: Path) -> dict[str, Any]:
    source_row = Path(source_row).resolve()
    output_root = Path(output_root).resolve()
    assert_fresh_output_root(output_root, source_row)
    required = [
        source_row / "cell" / "dynamic_cell.json", source_row / "spp" / "request_spp_cache.json",
        source_row / "retrieval" / "retrieval_manifest.json", source_row / "generated" / "candidate.cif",
        source_row / "sca" / "result.json", source_row / "qlip" / "solver_result.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"frozen row is incomplete: {missing}")
    protected_before = tree_hashes(source_row)
    request = (source_row / "input" / "request.txt").read_text(encoding="utf-8")
    task = read_json(source_row / "structured_task" / "structured_task.json")
    effective = read_json(source_row / "input" / "effective_config.json")
    if request != REQUEST or task.get("formula") != FORMULA:
        raise RuntimeError("frozen row request/formula does not match the controlled diagnostic")
    if not effective.get("exclude_target_reference") or effective.get("target_reference_id") != HELD_OUT_REFERENCE:
        raise RuntimeError("held-out reference exclusion is not frozen as required")
    retrieval_manifest = read_json(source_row / "retrieval" / "retrieval_manifest.json")
    retrieved_ids = {str(row.get("structure_id")) for row in retrieval_manifest["selected"]}
    if HELD_OUT_REFERENCE in retrieved_ids:
        raise RuntimeError("held-out reference appears in the persisted retrieval bundle")

    from sok_llm_orchestrator.workflow.component_paths import ComponentRoots
    from sok_llm_orchestrator.workflow.csv_workflow import BatchRow, _workflow_config
    from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages

    roots = ComponentRoots.load(REPO_ROOT)
    roots.activate_imports(include_sca=True)
    source_row_data = read_json(source_row / "input" / "input_row.json")
    batch_row = BatchRow(
        row_id="layered_007", csv_row_number=int(source_row_data.get("csv_row_number", 0) or 0),
        request_text=request, source_row=source_row_data, effective_config=effective, structured_task=task,
    )
    config = _workflow_config(batch_row, source_row, roots)
    config = replace(config, output_root=output_root)
    request_spp = read_json(source_row / "spp" / "request_spp_cache.json")
    source_cell = read_json(source_row / "cell" / "dynamic_cell.json")
    retrieval_hashes = {
        path.relative_to(source_row).as_posix(): sha256_file(path)
        for path in [
            source_row / "retrieval" / "retrieval_manifest.json",
            source_row / "retrieval" / "neighbour_hashes.csv",
            *sorted((source_row / "retrieval" / "neighbours").glob("*.cif")),
        ]
    }
    pot_hashes = {
        path.relative_to(source_row).as_posix(): sha256_file(path)
        for path in sorted((source_row / "spp" / "potentials").rglob("*.POT"))
    }
    persisted_pot_hashes = dict(request_spp.get("request_spp_hashes") or {})
    actual_relative_pot_hashes = {
        path.relative_to(source_row / "spp" / "potentials").as_posix(): digest
        for path, digest in [
            (source_row / key, value) for key, value in pot_hashes.items()
        ]
    }
    if actual_relative_pot_hashes != persisted_pot_hashes:
        raise RuntimeError("portable SPP POT hashes differ from request_spp_cache.json")

    output_root.mkdir(parents=True, exist_ok=False)
    write_json(output_root / "protected_row_hashes.before.json", protected_before)
    shape_prior = retrieval_shape_prior(source_row)
    write_json(output_root / "retrieval_shape_prior.json", shape_prior)

    a_lengths = (float(source_cell["a"]), float(source_cell["b"]), float(source_cell["c"]))
    b_lengths = (OLD_CUBE_EDGE_A,) * 3
    c_initial = scale_shape_to_volume(shape_prior["median_normalized_ratios"], math.prod(a_lengths))
    def checker(lengths: Sequence[float]) -> dict[str, Any]:
        return hard_geometry_feasibility(
            FORMULA, lengths, grid_density=GRID_DENSITY,
            proximity_scale=float(effective["proximity_scale"]),
        )
    a_feasible = dict(checker(a_lengths))
    b_feasible = dict(checker(b_lengths))
    if not a_feasible.get("feasible") or not b_feasible.get("feasible"):
        raise RuntimeError(f"required A/B hard-feasibility gate failed: A={a_feasible}, B={b_feasible}")
    c_lengths, c_trace = expand_anisotropic_to_feasible(c_initial, checker)
    c_feasible = dict(c_trace["feasibility_checks"][-1])
    variants = {
        "A": Variant("A", "A_current_cube", "current cube", a_lengths, a_feasible, {"expansion_required": False}),
        "B": Variant("B", "B_old_4p761_cube", "old 4.761 Å cube", b_lengths, b_feasible, {"expansion_required": False}),
        "C": Variant("C", "C_retrieval_anisotropic", "retrieval anisotropic", c_lengths, c_feasible, c_trace),
    }
    common = scientific_invariants(
        request=request, formula=FORMULA, task=task, effective=effective,
        request_spp=request_spp, retrieval_hashes=retrieval_hashes, pot_hashes=pot_hashes,
    )
    variant_audit_inputs = {
        key: {"invariants": common, "lattice_geometry": lattice_payload(value.lengths_A)}
        for key, value in variants.items()
    }
    invariant_audit = audit_variant_invariants(variant_audit_inputs)
    invariant_audit.update({
        "held_out_reference": HELD_OUT_REFERENCE,
        "held_out_reference_excluded": HELD_OUT_REFERENCE not in retrieved_ids,
        "source_candidate_or_reference_used_to_construct_B": False,
        "source_candidate_or_reference_used_to_construct_C": False,
        "protected_file_count": len(protected_before),
        "pre_solve_protected_tree_hash": canonical_hash(protected_before),
    })
    write_json(output_root / "invariant_audit.json", invariant_audit)
    write_json(output_root / "experiment_config.json", {
        "schema_version": "li2feo3_cell_representability_experiment.v1",
        "purpose": "isolated diagnostic; not a benchmark and not a production policy change",
        "source_row": str(source_row), "output_root": str(output_root),
        "request": request, "formula": FORMULA, "held_out_reference": HELD_OUT_REFERENCE,
        "variants": {key: cell_record(value) for key, value in variants.items()},
        "invariants": common, "component_roots": roots.as_dict(),
    })
    write_json(output_root / "C_retrieval_anisotropic" / "shape_prior.json", {
        "median_normalized_ratios": shape_prior["median_normalized_ratios"],
        "initial_same_volume_cell_A": list(c_initial),
        "initial_volume_A3": math.prod(c_initial),
        "final_feasible_cell_A": list(c_lengths),
        "final_volume_A3": math.prod(c_lengths),
    })

    stages = ProductionWorkflowStages()
    results = [
        solve_variant(variants[key], output_root, source_cell, request_spp, task, config, stages)
        for key in ("A", "B", "C")
    ]
    rows = [comparison_row(result) for result in results]
    write_comparison(output_root, rows)
    original_solver = read_json(source_row / "qlip" / "solver_result.json")
    original_sca = read_json(source_row / "sca" / "result.json")
    original = {
        "status": original_solver.get("status"),
        "generated_cif_sha256": original_solver.get("generated_cif_sha256"),
        "solver_objective": original_solver.get("solver_objective"),
        "topology_status": original_sca.get("topology_status"),
        "detected_space_group": original_sca.get("detected_space_group"),
    }
    case, explanation, fresh_a_reproduced = interpretation_case(rows, original)
    fresh_a = next(row for row in rows if row["variant"] == "A")
    original_a_comparison = {
        "frozen_A": original,
        "fresh_A": {
            "status": fresh_a["qlip_status"],
            "generated_cif_sha256": fresh_a["candidate_sha256"],
            "solver_objective": fresh_a["qlip_objective"],
            "topology_status": fresh_a["topology_status"],
            "detected_space_group": fresh_a["detected_space_group"],
        },
        "status_equal": fresh_a["qlip_status"] == original["status"],
        "objective_equal": fresh_a["qlip_objective"] == original["solver_objective"],
        "candidate_sha256_equal": fresh_a["candidate_sha256"] == original["generated_cif_sha256"],
        "topology_status_equal": fresh_a["topology_status"] == original["topology_status"],
        "detected_space_group_equal": fresh_a["detected_space_group"] == original["detected_space_group"],
        "materially_reproduced": fresh_a_reproduced,
    }
    write_json(output_root / "ORIGINAL_A_COMPARISON.json", original_a_comparison)
    policy_judgment = (
        "The evidence does not justify a retrieval-informed anisotropic policy by itself: "
        "same-volume C remained PARTIAL while larger-volume B passed. A separately frozen "
        "volume/physical-spacing diagnostic would be required before any production change."
        if case.endswith("CASE 2")
        else "Any production-policy decision requires a separate review of this diagnostic evidence."
    )
    report = [
        "# Li2FeO3 cell representability diagnostic", "",
        "This is an isolated diagnostic over the frozen portable `layered_007` evidence bundle. It does not alter `csv_workflow_v1`.", "",
        "## Outcome", "", f"- Interpretation: **{case}**", f"- {explanation}",
        f"- Fresh A reproduced frozen A exactly by status, candidate hash, and topology: **{fresh_a_reproduced}**",
        f"- Future-policy judgment: {policy_judgment}",
        "", "## Frozen A versus fresh A", "",
        f"- Solver status: `{original['status']}` versus `{fresh_a['qlip_status']}`.",
        f"- Objective: `{original['solver_objective']}` versus `{fresh_a['qlip_objective']}`.",
        f"- Candidate SHA-256: `{original['generated_cif_sha256']}` versus `{fresh_a['candidate_sha256']}`.",
        f"- Topology: `{original['topology_status']}` versus `{fresh_a['topology_status']}`.",
        f"- Detected space group: `{original['detected_space_group']}` versus `{fresh_a['detected_space_group']}`.",
        "", "## Cell conditions", "",
        f"- A: `{list(a_lengths)}` Å; volume `{math.prod(a_lengths):.9f}` Å³.",
        f"- B: `{list(b_lengths)}` Å; volume `{math.prod(b_lengths):.9f}` Å³.",
        f"- C initial: `{list(c_initial)}` Å; volume `{math.prod(c_initial):.9f}` Å³.",
        f"- C final: `{list(c_lengths)}` Å; volume `{math.prod(c_lengths):.9f}` Å³; expansion required: `{c_trace['expansion_required']}`.",
        "", "## Retrieval anisotropy", "",
        f"- Included observations: `{shape_prior['observation_count']}`.",
        f"- Median unit-product ratios: `{shape_prior['median_normalized_ratios']}`.",
        "- Ratios use sorted lattice lengths; the longest dimension is assigned to c; all diagnostic angles remain 90°.",
        "", "## Invariants", "",
        f"- Invariant audit: **{invariant_audit['status']}**.",
        f"- Held-out reference `{HELD_OUT_REFERENCE}` remained excluded.",
        "- Retrieval, POTs, pair manifest, objective, proximity, grid, and solver settings are identical across A/B/C.",
        "- Requested seed is 0; installed QLIP does not forward zero through its truthiness guard, so no Gurobi Seed=0 claim is made.",
        "", "## Comparison", "", (output_root / "COMPARISON.md").read_text(encoding="utf-8"),
    ]
    (output_root / "DIAGNOSTIC_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    protected_after = tree_hashes(source_row)
    write_json(output_root / "protected_row_hashes.after.json", protected_after)
    protected_unchanged = protected_before == protected_after
    invariant_audit.update({
        "post_solve_protected_tree_hash": canonical_hash(protected_after),
        "raw_benchmark_row_unchanged": protected_unchanged,
    })
    write_json(output_root / "invariant_audit.json", invariant_audit)
    if not protected_unchanged:
        changed = sorted(set(protected_before) | set(protected_after))
        changed = [name for name in changed if protected_before.get(name) != protected_after.get(name)]
        raise RuntimeError(f"frozen benchmark row changed during diagnostic: {changed}")
    return {
        "status": "COMPLETE", "interpretation_case": case,
        "fresh_a_reproduced": fresh_a_reproduced,
        "raw_benchmark_row_unchanged": True, "output_root": str(output_root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-row", type=Path, default=SOURCE_ROW_DEFAULT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT_DEFAULT)
    args = parser.parse_args()
    if str(REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "src"))
    print(json.dumps(run(args.source_row, args.output_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
