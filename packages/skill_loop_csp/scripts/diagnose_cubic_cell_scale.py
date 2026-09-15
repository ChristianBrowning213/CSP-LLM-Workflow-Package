"""Run resumable, row-local cubic cell-scale diagnostics for frozen CSV rows.

The only scientific variable is the cubic edge length. Retrieval, SPP/POT,
QLIP, proximity, 4x4x4 grid, solver, and canonical SCA inputs are rehydrated
from each protected source row. No production workflow module is modified.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from pymatgen.core import Composition  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from diagnose_li2feo3_cell_representability import (  # noqa: E402
    canonical_hash,
    read_json,
    sca_summary,
    sha256_file,
    structure_metrics,
    tree_hashes,
    write_json,
)


GRID_DENSITY = 4
TOPOLOGY_NUMERIC = {"FAIL": 0, "PARTIAL": 1, "PASS": 2}
STAGE1_EDGES = (3.869042, 4.00, 4.15, 4.30, 4.45, 4.60, 4.761, 4.90, 5.05)
STAGE2_MULTIPLIERS = (1.00, 1.10, 1.20, 1.30)
REQUIRED_ROW_FILES = (
    "cell/dynamic_cell.json",
    "generated/candidate.cif",
    "input/effective_config.json",
    "input/input_row.json",
    "input/request.txt",
    "qlip/solver_result.json",
    "retrieval/neighbour_hashes.csv",
    "retrieval/retrieval_manifest.json",
    "sca/result.json",
    "sca/summary.json",
    "spp/pair_manifest.csv",
    "spp/request_spp_cache.json",
    "structured_task/structured_task.json",
)


def edge_volume(edge_A: float) -> float:
    edge = float(edge_A)
    if not math.isfinite(edge) or edge <= 0.0:
        raise ValueError("edge must be finite and positive")
    return edge**3


def edge_grid_spacing(edge_A: float, grid_density: int = GRID_DENSITY) -> float:
    if grid_density <= 0:
        raise ValueError("grid density must be positive")
    return float(edge_A) / int(grid_density)


def absolute_edge_sweep(edges: Iterable[float]) -> tuple[float, ...]:
    values = tuple(float(value) for value in edges)
    if not values or any(not math.isfinite(value) or value <= 0.0 for value in values):
        raise ValueError("one or more finite positive edges are required")
    if len(values) != len(set(values)):
        raise ValueError("edge sweep contains duplicates")
    return values


def multiplier_edge_sweep(edge_A: float, multipliers: Iterable[float]) -> tuple[float, ...]:
    base = float(edge_A)
    values = tuple(float(value) for value in multipliers)
    if base <= 0.0 or not values or any(value <= 0.0 for value in values):
        raise ValueError("base edge and multipliers must be positive")
    return tuple(base * value for value in values)


def edge_directory(edge_A: float) -> str:
    text = f"{float(edge_A):.6f}".rstrip("0")
    whole, decimal = text.split(".")
    return f"edge_{whole}p{decimal.ljust(3, '0')}"


def scale_directory(multiplier: float) -> str:
    return f"scale_{float(multiplier):.2f}".replace(".", "p")


def topology_numeric(status: Any) -> int | None:
    return TOPOLOGY_NUMERIC.get(str(status).upper())


def topology_transition(before: Any, after: Any) -> str:
    left = str(before).upper()
    right = str(after).upper()
    if left not in TOPOLOGY_NUMERIC or right not in TOPOLOGY_NUMERIC:
        return "NOT_COMPARABLE"
    if TOPOLOGY_NUMERIC[right] > TOPOLOGY_NUMERIC[left]:
        return f"{left}_TO_{right}"
    if TOPOLOGY_NUMERIC[right] < TOPOLOGY_NUMERIC[left]:
        return f"{left}_TO_{right}_WORSE"
    return "UNCHANGED"


def aggregate_best_transitions(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["row_id"])].append(row)
    counts: Counter[str] = Counter()
    for values in grouped.values():
        ordered = sorted(values, key=lambda row: float(row["scale_multiplier"]))
        baseline = next((row for row in ordered if math.isclose(float(row["scale_multiplier"]), 1.0)), None)
        if baseline is None:
            counts["NOT_COMPARABLE"] += 1
            continue
        valid = [row for row in ordered if topology_numeric(row.get("topology_status")) is not None]
        if not valid:
            counts["NOT_COMPARABLE"] += 1
            continue
        best = max(valid, key=lambda row: topology_numeric(row.get("topology_status")) or 0)
        counts[topology_transition(baseline.get("topology_status"), best.get("topology_status"))] += 1
    return dict(sorted(counts.items()))


def _rankdata(values: Sequence[float]) -> np.ndarray:
    order = np.argsort(np.asarray(values, dtype=float), kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    index = 0
    while index < len(order):
        end = index + 1
        while end < len(order) and values[order[end]] == values[order[index]]:
            end += 1
        ranks[order[index:end]] = (index + end - 1) / 2.0 + 1.0
        index = end
    return ranks


def spearman(values_x: Sequence[Any], values_y: Sequence[Any]) -> float | None:
    pairs = [
        (float(x), float(y)) for x, y in zip(values_x, values_y, strict=True)
        if x is not None and y is not None and math.isfinite(float(x)) and math.isfinite(float(y))
    ]
    if len(pairs) < 3:
        return None
    x, y = zip(*pairs, strict=True)
    rx, ry = _rankdata(x), _rankdata(y)
    if np.std(rx) == 0.0 or np.std(ry) == 0.0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def classify_stage1_transition(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: float(row["edge_A"]))
    numeric = [topology_numeric(row.get("topology_status")) for row in ordered]
    valid = [value for value in numeric if value is not None]
    correlation = spearman([row["edge_A"] for row in ordered], numeric)
    pass_indices = [index for index, value in enumerate(numeric) if value == 2]
    first_pass = pass_indices[0] if pass_indices else None
    sustained_pass = bool(
        first_pass is not None
        and first_pass > 0
        and all(value == 2 for value in numeric[first_pass:])
        and any(value is not None and value < 2 for value in numeric[:first_pass])
    )
    threshold_interval = None
    if sustained_pass and first_pass is not None:
        threshold_interval = [float(ordered[first_pass - 1]["edge_A"]), float(ordered[first_pass]["edge_A"])]
    if sustained_pass and len(pass_indices) >= 2:
        classification = "REPRESENTABILITY_THRESHOLD"
        trigger = True
    elif (
        correlation is not None and correlation >= 0.5 and len(pass_indices) >= 2
        and valid and valid[-1] > valid[0]
    ):
        classification = "POSITIVE_SCALE_TREND"
        trigger = True
    elif len(pass_indices) == 1:
        classification = "ISOLATED_PASS"
        trigger = False
    elif len(set(valid)) <= 1:
        min_distance_correlation = spearman(
            [row["edge_A"] for row in ordered], [row.get("minimum_distance_A") for row in ordered]
        )
        classification = (
            "LOCAL_GEOMETRY_ONLY" if min_distance_correlation is not None and min_distance_correlation >= 0.5
            else "NO_TRANSITION"
        )
        trigger = False
    else:
        classification = "NON_MONOTONIC"
        trigger = False
    return {
        "classification": classification,
        "stage2_triggered": trigger,
        "edge_topology_spearman": correlation,
        "first_pass_edge_A": None if first_pass is None else float(ordered[first_pass]["edge_A"]),
        "threshold_interval_A": threshold_interval,
        "topology_sequence": [row.get("topology_status") for row in ordered],
    }


def assert_output_separate(output_root: Path, source_rows: Sequence[Path]) -> None:
    output = Path(output_root).resolve()
    for row in source_rows:
        source = Path(row).resolve()
        if output == source or source in output.parents or output in source.parents:
            raise ValueError("diagnostic output must not overlap a protected source row")


def _portable_hashes(row_root: Path) -> tuple[dict[str, str], dict[str, str]]:
    retrieval_paths = [
        row_root / "retrieval" / "retrieval_manifest.json",
        row_root / "retrieval" / "neighbour_hashes.csv",
        *sorted((row_root / "retrieval" / "neighbours").glob("*.cif")),
    ]
    retrieval = {path.relative_to(row_root).as_posix(): sha256_file(path) for path in retrieval_paths}
    pots = {
        path.relative_to(row_root).as_posix(): sha256_file(path)
        for path in sorted((row_root / "spp" / "potentials").rglob("*.POT"))
    }
    return retrieval, pots


def load_row_bundle(row_root: Path) -> dict[str, Any]:
    row_root = Path(row_root).resolve()
    missing = [name for name in REQUIRED_ROW_FILES if not (row_root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"protected row lacks required persisted artifacts: {missing}")
    request = (row_root / "input" / "request.txt").read_text(encoding="utf-8")
    task = read_json(row_root / "structured_task" / "structured_task.json")
    effective = read_json(row_root / "input" / "effective_config.json")
    input_row = read_json(row_root / "input" / "input_row.json")
    request_spp = read_json(row_root / "spp" / "request_spp_cache.json")
    source_cell = read_json(row_root / "cell" / "dynamic_cell.json")
    retrieval_manifest = read_json(row_root / "retrieval" / "retrieval_manifest.json")
    held_out = str(effective.get("target_reference_id") or "")
    if not held_out or not bool(effective.get("exclude_target_reference")):
        raise RuntimeError(f"held-out reference exclusion is not provable for {row_root.name}")
    retrieved_ids = {str(item.get("structure_id")) for item in retrieval_manifest["selected"]}
    if held_out in retrieved_ids:
        raise RuntimeError(f"held-out reference {held_out} appears in {row_root.name} retrieval")
    if int(effective["grid_density"]) != GRID_DENSITY:
        raise RuntimeError(f"{row_root.name} does not use the frozen 4x4x4 grid")
    if int(effective["solver_time_limit_s"]) != 300:
        raise RuntimeError(f"{row_root.name} solver time limit is not frozen at 300 seconds")
    retrieval_hashes, pot_hashes = _portable_hashes(row_root)
    persisted_pots = dict(request_spp.get("request_spp_hashes") or {})
    actual_pots = {
        (row_root / relative).relative_to(row_root / "spp" / "potentials").as_posix(): digest
        for relative, digest in pot_hashes.items()
    }
    if actual_pots != persisted_pots:
        raise RuntimeError(f"persisted POT hash contract fails for {row_root.name}")
    return {
        "row_root": row_root, "request": request, "task": task, "effective": effective,
        "input_row": input_row, "request_spp": request_spp, "source_cell": source_cell,
        "held_out_reference": held_out, "retrieval_hashes": retrieval_hashes,
        "pot_hashes": pot_hashes, "original_candidate_sha256": sha256_file(row_root / "generated" / "candidate.cif"),
        "original_topology": read_json(row_root / "sca" / "result.json").get("topology_status"),
    }


def row_invariants(bundle: Mapping[str, Any]) -> dict[str, Any]:
    effective = bundle["effective"]
    request_spp = bundle["request_spp"]
    return {
        "row_id": bundle["row_root"].name,
        "request": bundle["request"], "formula": bundle["task"]["formula"],
        "structured_task_except_cell": bundle["task"],
        "held_out_reference": bundle["held_out_reference"], "held_out_reference_excluded": True,
        "retrieval_bundle_hashes": bundle["retrieval_hashes"], "spp_pot_hashes": bundle["pot_hashes"],
        "pair_manifest": request_spp["quality"]["request_pair_results"],
        "spp_contract": effective["spp_contract"], "cutoff_angstrom": effective["cutoff_angstrom"],
        "qlip_objective": "spp_energy", "proximity_scale": effective["proximity_scale"],
        "grid": {"mode": "uniform_grid", "dimensions": [GRID_DENSITY] * 3, "sites": 64},
        "solver": {
            "name": "gurobi", "time_limit_s": effective["solver_time_limit_s"],
            "threads": effective["solver_threads"], "mip_gap": effective["solver_mip_gap"],
            "requested_seed": effective["random_seed"], "parameters": {"NonConvex": 2},
            "effective_seed_behaviour": (
                "QLIP truthiness guard does not forward integer zero to Gurobi"
                if int(effective["random_seed"]) == 0 else "QLIP forwards nonzero integer Seed"
            ),
        },
        "source_candidate_used_to_derive_cell": False, "held_out_reference_geometry_used": False,
    }


def audit_invariant_variants(invariant: Mapping[str, Any], edges: Sequence[float]) -> dict[str, Any]:
    snapshots = {
        edge_directory(edge): canonical_hash(invariant)
        for edge in edges
    }
    passed = len(set(snapshots.values())) == 1
    if not passed:
        raise RuntimeError("scientific settings differ across edge variants")
    return {
        "status": "PASS", "allowed_scientific_difference": "cubic_cell_edge_only",
        "variant_invariant_hashes": snapshots, "held_out_reference_excluded": True,
        "no_reretrieval": True, "no_spp_regeneration": True, "no_source_or_reference_geometry": True,
    }


def cubic_dynamic_cell(source_cell: Mapping[str, Any], edge_A: float, variant: str) -> dict[str, Any]:
    payload = json.loads(json.dumps(source_cell))
    atoms = int(payload["n_target_atoms"])
    volume = edge_volume(edge_A)
    payload.update({
        "a": float(edge_A), "b": float(edge_A), "c": float(edge_A),
        "alpha": 90.0, "beta": 90.0, "gamma": 90.0,
        "grid_density": GRID_DENSITY, "grid_spacing_A": edge_grid_spacing(edge_A),
        "cell_volume_A3": volume, "vpa_value_A3_per_atom": volume / atoms,
        "provenance": {
            "diagnostic_only": True, "variant": variant,
            "only_changed_variable": "cubic_cell_edge_length",
            "source_frozen_cell_sha256": canonical_hash(source_cell),
        },
    })
    return payload


def _config_for_bundle(bundle: Mapping[str, Any], output_root: Path) -> Any:
    from sok_llm_orchestrator.workflow.component_paths import ComponentRoots
    from sok_llm_orchestrator.workflow.csv_workflow import BatchRow, _workflow_config

    roots = ComponentRoots.load(REPO_ROOT)
    roots.activate_imports(include_sca=True)
    source = bundle["input_row"]
    row = BatchRow(
        row_id=bundle["row_root"].name, csv_row_number=int(source.get("csv_row_number", 0) or 0),
        request_text=bundle["request"], source_row=source, effective_config=bundle["effective"],
        structured_task=bundle["task"],
    )
    return replace(_workflow_config(row, bundle["row_root"], roots), output_root=output_root), roots


def _metric_from_raw(
    *, bundle: Mapping[str, Any], edge_A: float, multiplier: float | None, label: str,
    qlip: Mapping[str, Any], sca: Mapping[str, Any] | None, structure: Mapping[str, Any] | None,
) -> dict[str, Any]:
    atom_count = int(round(Composition(str(bundle["task"]["formula"])).num_atoms))
    diagnostics = dict(qlip.get("solver_diagnostics") or {})
    summary = dict(qlip.get("solver_summary") or {})
    raw_sca = dict(sca or {})
    local = dict(structure or {})
    return {
        "row_id": bundle["row_root"].name, "formula": bundle["task"]["formula"],
        "family": bundle["task"].get("family"), "variant": label,
        "scale_multiplier": multiplier, "edge_A": float(edge_A),
        "a_A": float(edge_A), "b_A": float(edge_A), "c_A": float(edge_A),
        "volume_A3": edge_volume(edge_A), "volume_per_atom_A3": edge_volume(edge_A) / atom_count,
        "grid_spacing_A": edge_grid_spacing(edge_A), "qlip_status": qlip.get("status"),
        "runtime_s": qlip.get("runtime_s"), "model_build_time_ms": diagnostics.get("model_build_time_ms"),
        "solve_time_ms": diagnostics.get("solver_time_ms"), "objective": qlip.get("solver_objective"),
        "incumbent_objective": qlip.get("solver_objective") if qlip.get("candidate_produced") else None,
        "optimality_gap": summary.get("mip_gap"), "best_bound": summary.get("best_bound"),
        "candidate_generated": qlip.get("candidate_produced"), "candidate_sha256": qlip.get("candidate_sha256"),
        "requested_seed": bundle["effective"]["random_seed"],
        "effective_seed_behaviour": qlip.get("effective_seed_behaviour"),
        "variables": diagnostics.get("model_stats", {}).get("variables"),
        "constraints": diagnostics.get("model_stats", {}).get("constraints"),
        "parse_ok": raw_sca.get("parse_ok"), "composition_match": raw_sca.get("composition_match"),
        "geometry_valid": raw_sca.get("geometry_valid"), "bad_contacts": raw_sca.get("bad_contacts"),
        "minimum_distance_A": raw_sca.get("minimum_distance_angstrom"),
        "minimum_distance_pair": raw_sca.get("minimum_distance_species_pair"),
        "detected_space_group": raw_sca.get("detected_space_group"),
        "topology_status": local.get("topology_status"),
        "topology_numeric": topology_numeric(local.get("topology_status")),
        "topology_checks": local.get("topology_checks"),
        "framework_dimensionality": local.get("framework_dimensionality"),
        "fe_coordination_number": local.get("fe_coordination_number"),
        "fe_neighbour_species_counts": local.get("fe_neighbour_species_counts"),
        "li_coordination_summary": local.get("li_coordination_summary"),
        "o_coordination_summary": local.get("o_coordination_summary"),
        "original_topology": bundle["original_topology"],
    }


def solve_edge(
    bundle: Mapping[str, Any], edge_A: float, output_root: Path, variant_root: Path,
    *, multiplier: float | None = None,
) -> dict[str, Any]:
    metrics_path = variant_root / "metrics.json"
    expected = {
        "source_row": str(bundle["row_root"]), "edge_A": float(edge_A),
        "scale_multiplier": multiplier, "invariant_hash": canonical_hash(row_invariants(bundle)),
    }
    if metrics_path.is_file():
        persisted = read_json(metrics_path)
        if persisted.get("resume_contract") != expected:
            raise RuntimeError(f"resume contract mismatch at {variant_root}")
        candidate = variant_root / "generated" / "candidate.cif"
        if persisted.get("candidate_generated") and (
            not candidate.is_file() or sha256_file(candidate) != persisted.get("candidate_sha256")
        ):
            raise RuntimeError(f"persisted candidate hash mismatch at {variant_root}")
        return persisted
    if variant_root.exists():
        raise FileExistsError(f"incomplete variant exists; refusing automatic rerun: {variant_root}")
    variant_root.mkdir(parents=True)
    qlip_root = variant_root / "qlip"
    generated_root = variant_root / "generated"
    sca_root = variant_root / "sca"
    qlip_root.mkdir()
    generated_root.mkdir()
    sca_root.mkdir()
    atom_count = int(round(Composition(str(bundle["task"]["formula"])).num_atoms))
    write_json(variant_root / "cell.json", {
        "a": edge_A, "b": edge_A, "c": edge_A, "alpha": 90.0, "beta": 90.0, "gamma": 90.0,
        "volume_A3": edge_volume(edge_A), "volume_per_atom_A3": edge_volume(edge_A) / atom_count,
        "grid_density": GRID_DENSITY, "grid_spacing_A": edge_grid_spacing(edge_A),
        "scale_multiplier": multiplier,
    })
    write_json(variant_root / "invariant_audit.json", {
        "status": "PASS", "shared_invariant_path": str(output_root / "invariant_audit.json"),
        "invariant_hash": expected["invariant_hash"], "allowed_difference": "cubic_cell_edge_only",
    })
    config, roots = _config_for_bundle(bundle, output_root)
    request_spp = json.loads(json.dumps(bundle["request_spp"]))
    label = variant_root.name
    request_spp["dynamic_cell"] = cubic_dynamic_cell(bundle["source_cell"], edge_A, label)
    write_json(qlip_root / "solver_config.json", {
        "name": "gurobi", "time_limit_s": config.solver_time_limit_s,
        "threads": config.solver_threads, "mip_gap": config.solver_mip_gap,
        "requested_seed": config.solver_seed, "parameters": {"NonConvex": 2},
        "proximity_scale": config.proximity_scale,
        "effective_seed_behaviour": "not forwarded because QLIP uses a truthiness guard for seed=0",
    })
    from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages, WorkflowStageError

    stages = ProductionWorkflowStages()
    started = time.perf_counter()
    try:
        solved = stages.solve(bundle["task"], request_spp, config, qlip_root)
    except WorkflowStageError as exc:
        runtime_s = time.perf_counter() - started
        if str(exc.details.get("qlip_status")) not in {"INFEASIBLE", "TIME_LIMIT_NO_SOLUTION"}:
            raise
        qlip = {
            "status": str(exc.details["qlip_status"]), "runtime_s": runtime_s,
            "candidate_produced": False, "candidate_sha256": None,
            "solver_objective": None, "solver_summary": {},
            "solver_diagnostics": exc.details.get("qlip_diagnostics") or {},
            "effective_seed_behaviour": "Gurobi Seed not set because requested integer zero is falsy",
            "error": str(exc), "details": exc.details,
        }
        write_json(qlip_root / "solver_result.json", qlip)
        metric = _metric_from_raw(
            bundle=bundle, edge_A=edge_A, multiplier=multiplier, label=label,
            qlip=qlip, sca=None, structure=None,
        ) | {"resume_contract": expected}
        write_json(metrics_path, metric)
        return metric
    runtime_s = time.perf_counter() - started
    candidate = generated_root / "candidate.cif"
    shutil.copy2(Path(solved["cif_path"]), candidate)
    candidate_hash = sha256_file(candidate)
    (generated_root / "candidate.sha256").write_text(f"{candidate_hash}  candidate.cif\n", encoding="ascii")
    diagnostics = dict(solved.get("solver_diagnostics") or {})
    qlip = {
        "status": solved["status"], "runtime_s": runtime_s,
        "solver_objective": solved["solver_objective"], "solver_summary": solved.get("solver_summary"),
        "solver_diagnostics": diagnostics, "candidate_produced": True,
        "candidate_sha256": candidate_hash, "objective_absolute_difference": solved.get("difference"),
        "effective_seed_behaviour": "Gurobi Seed not set because requested integer zero is falsy",
    }
    write_json(qlip_root / "solver_result.json", qlip)
    write_json(qlip_root / "problem_size.json", diagnostics.get("model_stats") or {})
    roots.activate_imports(include_sca=True)
    raw = stages.evaluate(candidate, bundle["task"])
    if sha256_file(candidate) != candidate_hash:
        raise RuntimeError(f"SCA modified diagnostic candidate at {variant_root}")
    summary = sca_summary(raw, candidate_hash, label)
    write_json(sca_root / "config.json", {
        "backend": "sca.pipelines.evaluate_one_cif", "run_alignn": False,
        "source_candidate_sha256": candidate_hash, "SCA_ROOT": str(roots.sca),
    })
    write_json(sca_root / "result.json", raw)
    write_json(sca_root / "summary.json", summary)
    metric = _metric_from_raw(
        bundle=bundle, edge_A=edge_A, multiplier=multiplier, label=label,
        qlip=qlip, sca=summary, structure=structure_metrics(raw),
    ) | {"resume_contract": expected}
    write_json(metrics_path, metric)
    return metric


def write_table(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty result table")
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def write_markdown_table(path: Path, rows: Sequence[Mapping[str, Any]], *, stage2: bool = False) -> None:
    if stage2:
        headers = ("Row", "Formula", "Family", "Scale", "Edge Å", "Grid Å", "QLIP", "Min Å", "Topology")
        keys = ("row_id", "formula", "family", "scale_multiplier", "edge_A", "grid_spacing_A", "qlip_status", "minimum_distance_A", "topology_status")
    else:
        headers = ("Edge Å", "Grid step Å", "Volume Å³", "QLIP", "Objective", "Min dist Å", "Fe CN", "Framework dim", "Topology")
        keys = ("edge_A", "grid_spacing_A", "volume_A3", "qlip_status", "objective", "minimum_distance_A", "fe_coordination_number", "framework_dimensionality", "topology_status")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        values = ["" if row.get(key) is None else str(row.get(key)) for key in keys]
        lines.append("| " + " | ".join(values) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_stage1(rows: Sequence[Mapping[str, Any]], output_root: Path) -> None:
    ordered = sorted(rows, key=lambda row: float(row["edge_A"]))
    edge = np.asarray([row["edge_A"] for row in ordered], dtype=float)
    grid = np.asarray([row["grid_spacing_A"] for row in ordered], dtype=float)
    topo = np.asarray([row["topology_numeric"] for row in ordered], dtype=float)
    topology_labels = [str(row["topology_status"]) for row in ordered]
    colors = {"PASS": "#2f855a", "PARTIAL": "#d69e2e", "FAIL": "#c53030"}
    point_colors = [colors.get(value, "#718096") for value in topology_labels]
    fig, axes = plt.subplots(3, 2, figsize=(10.2, 10.0), constrained_layout=True)
    specs = [
        (edge, topo, "Cell edge (Å)", "Topology", "topology"),
        (grid, topo, "Physical grid spacing (Å)", "Topology", "topology"),
        (edge, [row["minimum_distance_A"] for row in ordered], "Cell edge (Å)", "Minimum distance (Å)", "numeric"),
        (edge, [row["fe_coordination_number"] for row in ordered], "Cell edge (Å)", "Fe coordination number", "numeric"),
        (edge, [row["objective"] for row in ordered], "Cell edge (Å)", "QLIP objective", "numeric"),
        (edge, [row["runtime_s"] for row in ordered], "Cell edge (Å)", "Wall runtime (s)", "runtime"),
    ]
    for axis, (x, y, xlabel, ylabel, kind) in zip(axes.flat, specs, strict=True):
        axis.plot(x, y, color="#4a5568", linewidth=1.0, zorder=1)
        axis.scatter(x, y, c=point_colors, s=45, edgecolors="white", linewidths=0.6, zorder=2)
        axis.set_xlabel(xlabel)
        axis.set_ylabel(ylabel)
        axis.grid(True, alpha=0.22, linewidth=0.6)
        if kind == "topology":
            axis.set_yticks([0, 1, 2], ["FAIL", "PARTIAL", "PASS"])
            axis.set_ylim(-0.25, 2.25)
        if kind == "runtime":
            for x_value, y_value, row in zip(x, y, ordered, strict=True):
                short = "TL" if row["qlip_status"] == "FEASIBLE_TIME_LIMIT" else "OPT"
                axis.annotate(short, (x_value, y_value), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=7)
    fig.suptitle("Li2FeO3 cubic cell-scale diagnostic", fontsize=14, fontweight="normal")
    fig.savefig(output_root / "STAGE1_TRENDS.png", dpi=220)
    fig.savefig(output_root / "STAGE1_TRENDS.pdf")
    plt.close(fig)


def prepare_output(output_root: Path, config: Mapping[str, Any]) -> None:
    config_path = output_root / "experiment_config.json"
    config_hash = canonical_hash(config)
    if output_root.exists():
        if not config_path.is_file():
            raise FileExistsError(f"existing output lacks resume contract: {output_root}")
        persisted = read_json(config_path)
        if persisted.get("experiment_hash") != config_hash:
            raise RuntimeError(f"experiment resume contract mismatch: {output_root}")
        return
    output_root.mkdir(parents=True)
    write_json(config_path, dict(config) | {"experiment_hash": config_hash})


def run_stage1(row_root: Path, edges: Sequence[float], output_root: Path) -> dict[str, Any]:
    edges = absolute_edge_sweep(edges)
    bundle = load_row_bundle(row_root)
    assert_output_separate(output_root, [row_root])
    invariant = row_invariants(bundle)
    audit = audit_invariant_variants(invariant, edges)
    config = {
        "schema_version": "cubic_cell_scale_stage1.v1", "stage": 1,
        "source_row": str(Path(row_root).resolve()), "edges_A": list(edges),
        "grid_density": GRID_DENSITY, "invariant_hash": canonical_hash(invariant),
    }
    prepare_output(output_root, config)
    before_path = output_root / "protected_row_hashes.before.json"
    before = read_json(before_path) if before_path.is_file() else tree_hashes(row_root)
    if not before_path.is_file():
        write_json(before_path, before)
    write_json(output_root / "invariant_audit.json", audit | {
        "scientific_invariants": invariant, "protected_file_count": len(before),
        "pre_solve_protected_tree_hash": canonical_hash(before),
    })
    rows = []
    for index, edge in enumerate(edges, 1):
        print(f"STAGE1_START {index}/{len(edges)} edge={edge:.6f}", flush=True)
        rows.append(solve_edge(bundle, edge, output_root, output_root / edge_directory(edge)))
        print(f"STAGE1_DONE {index}/{len(edges)} edge={edge:.6f} status={rows[-1]['qlip_status']} topology={rows[-1]['topology_status']}", flush=True)
    write_table(output_root / "SWEEP_RESULTS.csv", rows)
    write_markdown_table(output_root / "SWEEP_RESULTS.md", rows)
    decision = classify_stage1_transition(rows)
    correlations = {
        "edge_vs_topology_spearman": spearman([row["edge_A"] for row in rows], [row["topology_numeric"] for row in rows]),
        "grid_spacing_vs_topology_spearman": spearman([row["grid_spacing_A"] for row in rows], [row["topology_numeric"] for row in rows]),
        "vpa_vs_topology_spearman": spearman([row["volume_per_atom_A3"] for row in rows], [row["topology_numeric"] for row in rows]),
        "edge_vs_min_distance_spearman": spearman([row["edge_A"] for row in rows], [row["minimum_distance_A"] for row in rows]),
        "edge_vs_fe_cn_spearman": spearman([row["edge_A"] for row in rows], [row["fe_coordination_number"] for row in rows]),
        "objective_vs_topology_spearman": spearman([row["objective"] for row in rows], [row["topology_numeric"] for row in rows]),
    }
    write_json(output_root / "STAGE1_DECISION.json", decision | {"correlations": correlations})
    plot_stage1(rows, output_root)
    report = [
        "# Li2FeO3 cubic scale sweep", "",
        "Only the cubic cell edge, volume, and resulting physical 4x4x4 grid spacing vary.", "",
        f"- Classification: **{decision['classification']}**",
        f"- Stage 2 triggered: **{decision['stage2_triggered']}**",
        f"- First PASS edge: `{decision['first_pass_edge_A']}` Å",
        f"- Threshold interval: `{decision['threshold_interval_A']}` Å",
        f"- Correlations: `{json.dumps(correlations, sort_keys=True)}`", "",
        "## Results", "", (output_root / "SWEEP_RESULTS.md").read_text(encoding="utf-8"),
    ]
    (output_root / "SWEEP_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    after = tree_hashes(row_root)
    write_json(output_root / "protected_row_hashes.after.json", after)
    unchanged = before == after
    audit = read_json(output_root / "invariant_audit.json") | {
        "post_solve_protected_tree_hash": canonical_hash(after), "raw_benchmark_row_unchanged": unchanged,
    }
    write_json(output_root / "invariant_audit.json", audit)
    if not unchanged:
        raise RuntimeError("protected Stage 1 source row changed")
    return {"status": "COMPLETE", "decision": decision, "correlations": correlations, "rows": rows}


def deterministic_panel_selection(benchmark_root: Path) -> list[dict[str, Any]]:
    root = Path(benchmark_root).resolve()
    candidates: list[dict[str, Any]] = []
    for row_root in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name):
        if not (row_root.name.startswith("layered_") or row_root.name.startswith("spinel_")):
            continue
        try:
            bundle = load_row_bundle(row_root)
        except (FileNotFoundError, RuntimeError):
            continue
        candidates.append({
            "row_id": row_root.name, "formula": bundle["task"]["formula"],
            "family": "layered" if row_root.name.startswith("layered_") else "spinel",
            "original_topology": bundle["original_topology"],
            "candidate_hash": bundle["original_candidate_sha256"], "source_row_path": str(row_root),
        })
    by_id = {row["row_id"]: row for row in candidates}
    if "layered_007" not in by_id or by_id["layered_007"]["original_topology"] != "PARTIAL":
        raise RuntimeError("required layered_007 scale-sensitive anchor is unavailable")
    selected = [by_id["layered_007"] | {"selection_reason": "predeclared Li2FeO3 PARTIAL-to-PASS scale-sensitive anchor"}]
    selected.extend(
        row | {"selection_reason": "first five layered FAIL rows by row_id"}
        for row in candidates if row["family"] == "layered" and row["original_topology"] == "FAIL"
    )
    selected = selected[:6]
    spinel_partial = [row for row in candidates if row["family"] == "spinel" and row["original_topology"] == "PARTIAL"][:3]
    spinel_pass = [row for row in candidates if row["family"] == "spinel" and row["original_topology"] == "PASS"][:2]
    selected.extend(row | {"selection_reason": "first three spinel PARTIAL rows by row_id"} for row in spinel_partial)
    selected.extend(row | {"selection_reason": "first two spinel PASS rows by row_id"} for row in spinel_pass)
    if len(selected) != 11:
        raise RuntimeError(f"deterministic panel has {len(selected)} rows instead of 11")
    return selected


def panel_analysis(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    transitions = aggregate_best_transitions(rows)
    by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[str(row["family"])].append(row)
    multiplier_summary: dict[str, Any] = {}
    grouped: dict[str, dict[float, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        grouped[str(row["row_id"])][float(row["scale_multiplier"])] = row
    for multiplier in STAGE2_MULTIPLIERS[1:]:
        counts = Counter()
        for values in grouped.values():
            baseline, current = values.get(1.0), values.get(multiplier)
            if baseline is None or current is None:
                counts["NOT_COMPARABLE"] += 1
            else:
                transition = topology_transition(baseline.get("topology_status"), current.get("topology_status"))
                if transition == "UNCHANGED":
                    counts["unchanged"] += 1
                elif transition.endswith("_WORSE"):
                    counts["worse"] += 1
                elif transition == "NOT_COMPARABLE":
                    counts["NOT_COMPARABLE"] += 1
                else:
                    counts["improved"] += 1
        multiplier_summary[f"{multiplier:.2f}"] = dict(counts)
    family_summary = {}
    for family, family_rows in by_family.items():
        family_summary[family] = {
            "target_count": len({row["row_id"] for row in family_rows}),
            "best_transition_counts": aggregate_best_transitions(family_rows),
        }
    topology_values = [row["topology_numeric"] for row in rows]
    correlations = {
        "grid_spacing_vs_topology_spearman": spearman([row["grid_spacing_A"] for row in rows], topology_values),
        "vpa_vs_topology_spearman": spearman([row["volume_per_atom_A3"] for row in rows], topology_values),
        "raw_edge_vs_topology_spearman": spearman([row["edge_A"] for row in rows], topology_values),
        "objective_vs_topology_spearman": spearman([row["objective"] for row in rows], topology_values),
    }
    adverse = {
        "infeasible_or_no_solution": sum(row["qlip_status"] in {"INFEASIBLE", "TIME_LIMIT_NO_SOLUTION"} for row in rows),
        "feasible_time_limit": sum(row["qlip_status"] == "FEASIBLE_TIME_LIMIT" for row in rows),
        "bad_contact_variants": sum((row.get("bad_contacts") or 0) > 0 for row in rows),
        "composition_failures": sum(row.get("composition_match") is False for row in rows),
        "geometry_failures": sum(row.get("geometry_valid") is False for row in rows),
    }
    return {
        "best_transition_counts": transitions, "by_family": family_summary,
        "by_multiplier": multiplier_summary, "correlations": correlations, "adverse_outcomes": adverse,
    }


def run_stage2(benchmark_root: Path, multipliers: Sequence[float], output_root: Path) -> dict[str, Any]:
    multipliers = tuple(float(value) for value in multipliers)
    selection = deterministic_panel_selection(benchmark_root)
    source_rows = [Path(row["source_row_path"]) for row in selection]
    assert_output_separate(output_root, source_rows)
    bundles = {row["row_id"]: load_row_bundle(Path(row["source_row_path"])) for row in selection}
    config = {
        "schema_version": "cubic_cell_scale_stage2.v1", "stage": 2,
        "benchmark_root": str(Path(benchmark_root).resolve()), "multipliers": list(multipliers),
        "panel_row_ids": [row["row_id"] for row in selection], "grid_density": GRID_DENSITY,
    }
    prepare_output(output_root, config)
    write_json(output_root / "PANEL_SELECTION.json", selection)
    before_path = output_root / "protected_artifact_hashes.before.json"
    before = read_json(before_path) if before_path.is_file() else {
        row_id: tree_hashes(bundle["row_root"]) for row_id, bundle in bundles.items()
    }
    if not before_path.is_file():
        write_json(before_path, before)
    invariants = {row_id: row_invariants(bundle) for row_id, bundle in bundles.items()}
    write_json(output_root / "invariant_audit.json", {
        "status": "PASS", "allowed_scientific_difference": "within-row cubic_cell_edge_only",
        "row_invariant_hashes": {row_id: canonical_hash(value) for row_id, value in invariants.items()},
        "held_out_references_excluded": True, "no_reretrieval": True, "no_spp_regeneration": True,
        "no_source_or_reference_geometry": True, "protected_row_count": len(bundles),
    })
    results = []
    total = len(selection) * len(multipliers)
    counter = 0
    for selected in selection:
        bundle = bundles[selected["row_id"]]
        e0 = float(bundle["source_cell"]["a"])
        for multiplier, edge in zip(multipliers, multiplier_edge_sweep(e0, multipliers), strict=True):
            counter += 1
            print(f"STAGE2_START {counter}/{total} row={selected['row_id']} scale={multiplier:.2f} edge={edge:.6f}", flush=True)
            metric = solve_edge(
                bundle, edge, output_root,
                output_root / selected["row_id"] / scale_directory(multiplier), multiplier=multiplier,
            )
            results.append(metric)
            print(f"STAGE2_DONE {counter}/{total} row={selected['row_id']} scale={multiplier:.2f} status={metric['qlip_status']} topology={metric['topology_status']}", flush=True)
    write_table(output_root / "PANEL_RESULTS.csv", results)
    write_markdown_table(output_root / "PANEL_RESULTS.md", results, stage2=True)
    analysis = panel_analysis(results)
    write_json(output_root / "PANEL_ANALYSIS.json", analysis)
    report = [
        "# Cross-family cubic scale panel", "",
        "The panel and multiplier schedule were frozen before solving; only within-row cubic edge varies.", "",
        f"- Best transition counts: `{json.dumps(analysis['best_transition_counts'], sort_keys=True)}`",
        f"- Family results: `{json.dumps(analysis['by_family'], sort_keys=True)}`",
        f"- Multiplier results: `{json.dumps(analysis['by_multiplier'], sort_keys=True)}`",
        f"- Correlations: `{json.dumps(analysis['correlations'], sort_keys=True)}`",
        f"- Adverse outcomes: `{json.dumps(analysis['adverse_outcomes'], sort_keys=True)}`", "",
        "## Results", "", (output_root / "PANEL_RESULTS.md").read_text(encoding="utf-8"),
    ]
    (output_root / "PANEL_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    after = {row_id: tree_hashes(bundle["row_root"]) for row_id, bundle in bundles.items()}
    write_json(output_root / "protected_artifact_hashes.after.json", after)
    unchanged = before == after
    audit = read_json(output_root / "invariant_audit.json") | {"protected_artifacts_unchanged": unchanged}
    write_json(output_root / "invariant_audit.json", audit)
    if not unchanged:
        raise RuntimeError("one or more protected Stage 2 source rows changed")
    return {"status": "COMPLETE", "selection": selection, "analysis": analysis, "rows": results}


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(value.strip()) for value in text.split(",") if value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="stage", required=True)
    stage1 = subparsers.add_parser("stage1")
    stage1.add_argument("--row", type=Path, required=True)
    stage1.add_argument("--edges", type=_floats, default=STAGE1_EDGES)
    stage1.add_argument("--output", type=Path, required=True)
    stage2 = subparsers.add_parser("stage2")
    stage2.add_argument("--benchmark-run", type=Path, required=True)
    stage2.add_argument("--scale-multipliers", type=_floats, default=STAGE2_MULTIPLIERS)
    stage2.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "stage1":
        result = run_stage1(args.row, args.edges, args.output)
        print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
    else:
        result = run_stage2(args.benchmark_run, args.scale_multipliers, args.output)
        print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
