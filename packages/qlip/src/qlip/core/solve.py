from __future__ import annotations

import io
import csv
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyomo.environ as pyo
from pyomo.repn import generate_standard_repn
from ase import Atoms
from ase.geometry import cellpar_to_cell
from ase.io import write

from qlip.allocation import Allocation
from qlip.core.models import ArtifactItem, SolveError, SolveOutputs, SolveResult, SolveSummary
from qlip.core.chemistry import preflight_charge
from qlip.core.objectives import apply_objective_contract
from qlip.core.paths import allowed_path_roots, resolve_and_check_path
from qlip.core.validate import validate_request
from qlip.grids import uniform
from qlip.interactions.spp import SPPCollection
from qlip.plugins.registry import ConstraintRegistry, GuidanceRegistry
from qlip.visualization.plot import _extract_placements

_SUCCESS_STATUSES = {"OPTIMAL", "FEASIBLE"}
# A time-limited MIP solve is never OPTIMAL/FEASIBLE-by-proof, so these two
# statuses are kept OUT of _SUCCESS_STATUSES (preserving exact backward
# compatibility for any caller checking `status in _SUCCESS_STATUSES`).
# FEASIBLE_TIME_LIMIT still carries a real, decodable CIF and objective
# value; TIME_LIMIT_NO_SOLUTION never does. See core/solve.py::solve() and
# the scaled-cell incumbent audit for the full rationale.
_TIME_LIMIT_NO_SOLUTION = "TIME_LIMIT_NO_SOLUTION"
_FEASIBLE_TIME_LIMIT = "FEASIBLE_TIME_LIMIT"
_KNOWN_CIF_PLACEHOLDERS = {"data_solution"}
_REQUIRED_CIF_TOKENS = (
    "_cell_length_a",
    "_cell_length_b",
    "_cell_length_c",
    "_atom_site_fract_x",
    "_atom_site_fract_y",
    "_atom_site_fract_z",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_pot_root(context: Dict[str, Any]) -> Path:
    pot_root = _to_text(context.get("pot_root"))
    if pot_root:
        return resolve_and_check_path(pot_root, allowed_path_roots(), must_exist=True)
    raise ValueError(
        "SPP objective requires context.pot_root (or guidance POT parameters) "
        "pointing to a compatible user-supplied POT library"
    )


def _pair_name(pair: Tuple[str, str]) -> str:
    return "-".join(pair)


def _pair_key(pair: str) -> Tuple[str, str]:
    left, right = str(pair).split("-", 1)
    ordered = sorted([left, right], key=str.lower)
    return ordered[0], ordered[1]


def _spp_guidance_params(request: Dict[str, Any]) -> Dict[str, Any]:
    for inv in request.get("guidance", []):
        if not isinstance(inv, dict):
            continue
        if inv.get("enabled", True) and inv.get("id") == "objective.energy_spp":
            params = inv.get("params")
            return params if isinstance(params, dict) else {}
    return {}


def _regularisation_params(params: Dict[str, Any]) -> Tuple[Optional[str], float]:
    raw_dir = params.get("regularisation_spp_dir")
    if not raw_dir:
        raw_dir = params.get("regularization_spp_dir")
    if not raw_dir:
        raw_dir = os.getenv("QLIP_SPP_REGULARISATION_DIR") or os.getenv("QLIP_SPP_REGULARIZATION_DIR")
    raw_weight = params.get("regularisation_weight")
    if raw_weight is None:
        raw_weight = params.get("regularization_weight")
    try:
        weight = float(raw_weight or 0.0)
    except Exception:
        weight = 0.0
    return _to_text(raw_dir), weight


def _resolve_spp_pot_root(request: Dict[str, Any]) -> Path:
    params = _spp_guidance_params(request)
    if params.get("pot_root"):
        return resolve_and_check_path(_to_text(params.get("pot_root")), allowed_path_roots(), must_exist=True)
    return _resolve_pot_root(request.get("context", {}) if isinstance(request.get("context"), dict) else {})


def _spp_pairs_to_load(request: Dict[str, Any], allocation: Allocation) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
    params = _spp_guidance_params(request)
    regularisation_dir, regularisation_weight = _regularisation_params(params)
    mode = str(params.get("mode", "complete"))
    policy = str(params.get("missing_pair_policy", "block"))
    strict = bool(params.get("strict_pair_coverage", mode != "partial"))
    supported_pairs = [
        str(pair)
        for pair in params.get("supported_pairs", [])
        if isinstance(pair, str) and "-" in pair
    ] if isinstance(params.get("supported_pairs"), list) else []
    missing_pairs = [
        str(pair)
        for pair in params.get("missing_pairs", [])
        if isinstance(pair, str) and "-" in pair
    ] if isinstance(params.get("missing_pairs"), list) else []
    partial_policy_allowed = policy in {"neutral", "zero", "soft_repulsive", "fallback"}
    if mode == "partial" and partial_policy_allowed and not strict and supported_pairs:
        supported_keys = {_pair_key(pair) for pair in supported_pairs}
        pairs = [
            pair for pair in allocation.pairs
            if policy in {"soft_repulsive", "fallback"} or _pair_key(_pair_name(pair)) in supported_keys
        ]
        missing_pairs = [
            _pair_name(pair)
            for pair in allocation.pairs
            if _pair_key(_pair_name(pair)) not in supported_keys
        ]
        return pairs, {
            "mode": "partial",
            "spp_guidance_mode": "partial_spp",
            "partial_guidance": True,
            "spp_missing_pair_policy": policy,
            "missing_pair_policy": policy,
            "strict_pair_coverage": False,
            "supported_pairs": [
                _pair_name(pair) for pair in allocation.pairs
                if _pair_key(_pair_name(pair)) in supported_keys
            ],
            "missing_pairs": missing_pairs,
            "spp_supported_pairs_used": [
                _pair_name(pair) for pair in allocation.pairs
                if _pair_key(_pair_name(pair)) in supported_keys
            ],
            "spp_missing_pairs_unguided": missing_pairs if policy in {"neutral", "zero"} else [],
            "spp_missing_pairs_soft_repulsive": missing_pairs if policy == "soft_repulsive" else [],
            "spp_missing_pairs_regulator_fallback": missing_pairs if policy == "fallback" else [],
            "spp_terms_added_count": len(pairs),
            "terms_added_count": len(pairs),
            "spp_terms_skipped_missing_pair_count": len(missing_pairs) if policy in {"neutral", "zero"} else 0,
            "terms_skipped_missing_pair_count": len(missing_pairs) if policy in {"neutral", "zero"} else 0,
            "spp_missing_pair_fallback_term_count": len(missing_pairs) if policy == "soft_repulsive" else 0,
            "spp_partial_guidance": True,
            "missing_pairs_are_neutral": policy in {"neutral", "zero"},
            "missing_pairs_use_soft_repulsive": policy == "soft_repulsive",
            "missing_pairs_use_regulator_fallback": policy == "fallback",
            "pot_root": str(params.get("pot_root") or ""),
            "regularisation_spp_dir": regularisation_dir,
            "regularisation_weight": regularisation_weight,
            "spp_regularisation_enabled": regularisation_weight > 0.0,
        }
    return allocation.pairs, {
        "mode": "complete",
        "spp_guidance_mode": "complete_spp",
        "partial_guidance": False,
        "spp_missing_pair_policy": "block",
        "missing_pair_policy": "block",
        "strict_pair_coverage": True,
        "supported_pairs": [_pair_name(pair) for pair in allocation.pairs],
        "missing_pairs": [],
        "spp_supported_pairs_used": [_pair_name(pair) for pair in allocation.pairs],
        "spp_missing_pairs_unguided": [],
        "spp_terms_added_count": len(allocation.pairs),
        "terms_added_count": len(allocation.pairs),
        "spp_terms_skipped_missing_pair_count": 0,
        "terms_skipped_missing_pair_count": 0,
        "spp_partial_guidance": False,
        "missing_pairs_are_neutral": False,
        "pot_root": str(params.get("pot_root") or request.get("context", {}).get("pot_root") or ""),
        "regularisation_spp_dir": regularisation_dir,
        "regularisation_weight": regularisation_weight,
        "spp_regularisation_enabled": regularisation_weight > 0.0,
    }


def _build_positions(design_space: Dict[str, Any]) -> Atoms:
    template = design_space["template"]
    lattice = template["lattice"]
    units = lattice.get("units", "angstrom")
    scale = 1.0
    if units == "bohr":
        scale = 0.529177
    cell = cellpar_to_cell(
        [
            float(lattice["a"]) * scale,
            float(lattice["b"]) * scale,
            float(lattice["c"]) * scale,
            float(lattice["alpha"]),
            float(lattice["beta"]),
            float(lattice["gamma"]),
        ]
    )

    sites = design_space["sites"]
    mode = sites["mode"]
    if mode == "uniform_grid":
        spec = sites["uniform_grid"]
        density = int(spec["density"])
        grid = uniform(density)
        jitter = float(spec.get("jitter", 0.0))
        if jitter > 0:
            rng = np.random.default_rng(spec.get("seed"))
            noise = rng.uniform(-jitter, jitter, size=grid.shape)
            grid = np.clip(grid + noise, 0.0, 0.999999)
    elif mode == "explicit_fractional_sites":
        pts = sites.get("explicit_fractional_sites") or []
        grid = np.asarray(pts, dtype=float)
    else:
        raise ValueError(f"Unsupported sites.mode '{mode}'")

    positions = Atoms("H" * len(grid), cell=cell, pbc=True)
    if len(grid) > 0:
        positions.set_scaled_positions(grid)
    return positions


def _objective_value(model) -> Optional[float]:
    objs = list(model.component_objects(pyo.Objective, active=True))
    if not objs:
        return None
    try:
        return float(pyo.value(objs[0]))
    except Exception:
        return None


def _to_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return f"<unprintable {type(value).__name__}>"


def _candidate_site_count(design_space: Dict[str, Any]) -> Optional[int]:
    sites = design_space.get("sites") if isinstance(design_space.get("sites"), dict) else {}
    mode = sites.get("mode")
    if mode == "uniform_grid":
        spec = sites.get("uniform_grid") if isinstance(sites.get("uniform_grid"), dict) else {}
        density = spec.get("density")
        if isinstance(density, int) and density > 0:
            return density * density * density
    if mode == "explicit_fractional_sites":
        pts = sites.get("explicit_fractional_sites")
        if isinstance(pts, list):
            return len(pts)
    return None


def _design_space_diagnostics(request: Dict[str, Any]) -> Dict[str, Any]:
    problem = request.get("problem", {}) if isinstance(request.get("problem"), dict) else {}
    chemistry = problem.get("chemistry", {}) if isinstance(problem.get("chemistry"), dict) else {}
    design_space = problem.get("design_space", {}) if isinstance(problem.get("design_space"), dict) else {}
    template = design_space.get("template") if isinstance(design_space.get("template"), dict) else {}
    lattice = template.get("lattice") if isinstance(template.get("lattice"), dict) else {}
    sites = design_space.get("sites") if isinstance(design_space.get("sites"), dict) else {}
    formula = _to_text(chemistry.get("formula")) or ""
    species_count = None
    formula_units = None
    try:
        stoic = Atoms(symbols=formula)
        species_count = len(set(stoic.get_chemical_symbols()))
        formula_units = len(stoic)
    except Exception:
        pass
    candidate_sites = _candidate_site_count(design_space)
    hints: List[str] = []
    category = None
    if not design_space:
        category = "unit_cell_missing"
        hints.append("Add problem.design_space with template lattice and candidate sites.")
    elif not lattice:
        category = "lattice_template_missing"
        hints.append("Add problem.design_space.template.lattice before solving.")
    elif any(float(lattice.get(key, 0) or 0) <= 0 for key in ("a", "b", "c")):
        category = "lattice_bounds_invalid"
        hints.append("Use positive lattice lengths a, b, c.")
    elif not sites:
        category = "candidate_sites_missing"
        hints.append("Add problem.design_space.sites before solving.")
    elif candidate_sites == 0:
        category = "candidate_sites_empty"
        hints.append("Provide at least one candidate site.")
    elif formula_units is not None and candidate_sites is not None and formula_units > candidate_sites:
        category = "composition_site_capacity_mismatch"
        hints.append("Increase candidate site count or reduce formula units.")
    return {
        "qlip_status": None,
        "infeasibility_category": category,
        "model_stats": {
            "variables": None,
            "constraints": None,
            "candidate_sites": candidate_sites,
            "species_count": species_count,
            "formula_units": formula_units,
        },
        "diagnostic_hints": hints,
    }


def _model_stats(allocation: Allocation, diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    stats = dict(diagnostics.get("model_stats", {}) or {})
    try:
        stats["variables"] = sum(1 for _ in allocation.m.component_data_objects(pyo.Var, active=True))
    except Exception:
        stats["variables"] = None
    try:
        stats["constraints"] = sum(1 for _ in allocation.m.component_data_objects(pyo.Constraint, active=True))
    except Exception:
        stats["constraints"] = None
    try:
        stats["candidate_sites"] = len(allocation.positions)
    except Exception:
        pass
    try:
        stats["species_count"] = len(allocation.types)
    except Exception:
        pass
    return stats


def _export_gurobi_visuals_enabled(req: Dict[str, Any]) -> bool:
    runtime = req.get("runtime", {}) if isinstance(req.get("runtime"), dict) else {}
    if runtime.get("export_gurobi_visuals") is True:
        return True
    value = os.getenv("QLIP_EXPORT_GUROBI_VISUALS", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _gurobi_visuals_dir(req: Dict[str, Any]) -> Path:
    context = req.get("context", {}) if isinstance(req.get("context"), dict) else {}
    runtime = req.get("runtime", {}) if isinstance(req.get("runtime"), dict) else {}
    raw = context.get("gurobi_visuals_dir") or runtime.get("gurobi_visuals_dir") or os.getenv("QLIP_GUROBI_VISUALS_DIR")
    if raw:
        return Path(str(raw)).expanduser().resolve()
    run_id = context.get("run_id") or f"qlip_{int(time.time())}"
    return (_repo_root() / "out" / "gurobi_visuals" / str(run_id)).resolve()


def _variable_type_counts(model: Any) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for var in model.component_data_objects(pyo.Var, active=True):
        domain = "continuous"
        if var.is_binary():
            domain = "binary"
        elif var.is_integer():
            domain = "integer"
        counts[domain] = counts.get(domain, 0) + 1
    return counts


def _constraint_sense_counts(constraints: List[Any]) -> Dict[str, int]:
    counts = {"<=": 0, ">=": 0, "==": 0, "range": 0}
    for con in constraints:
        has_lb = con.lower is not None
        has_ub = con.upper is not None
        if con.equality:
            counts["=="] += 1
        elif has_lb and has_ub:
            counts["range"] += 1
        elif has_ub:
            counts["<="] += 1
        elif has_lb:
            counts[">="] += 1
    return counts


def _build_pyomo_constraint_matrix(model: Any) -> tuple[np.ndarray, Dict[int, int], List[Any], List[Any], int]:
    variables = list(model.component_data_objects(pyo.Var, active=True))
    constraints = [con for con in model.component_data_objects(pyo.Constraint, active=True) if con.active]
    var_index = {id(var): idx for idx, var in enumerate(variables)}
    matrix = np.zeros((len(constraints), len(variables)), dtype=float)
    nnz = 0
    for row, con in enumerate(constraints):
        body = con.body
        repn = generate_standard_repn(body, compute_values=False)
        for var, coef in zip(repn.linear_vars or [], repn.linear_coefs or []):
            col = var_index.get(id(var))
            if col is None:
                continue
            try:
                value = float(pyo.value(coef))
            except Exception:
                value = float(coef)
            if value != 0:
                matrix[row, col] += value
        nnz += int(np.count_nonzero(matrix[row, :]))
    return matrix, var_index, variables, constraints, nnz


def _export_gurobi_visual_artifacts(allocation: Allocation, result: Any, req: Dict[str, Any], status: str, objective_value: Optional[float], best_bound: Any, mip_gap: Any) -> Dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = _gurobi_visuals_dir(req)
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix, _, variables, constraints, nnz = _build_pyomo_constraint_matrix(allocation.m)
    rows, cols = matrix.shape
    density = float(nnz / (rows * cols)) if rows and cols else 0.0
    matrix_path = out_dir / "gurobi_constraint_matrix.npy"
    np.save(matrix_path, matrix)
    spy_path = out_dir / "gurobi_constraint_matrix_spy.png"
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    ax.spy(matrix, markersize=1.2 if max(rows, cols) > 100 else 4)
    ax.set_title("QLIP MILP constraint matrix")
    ax.set_xlabel("variables")
    ax.set_ylabel("constraints")
    fig.tight_layout()
    fig.savefig(spy_path, dpi=180)
    plt.close(fig)
    meta = {
        "schema_version": "qlip.gurobi_visuals.v1",
        "matrix_format": "numpy_dense",
        "matrix_path": str(matrix_path),
        "spy_plot_path": str(spy_path),
        "n_constraints": rows,
        "n_variables": cols,
        "nnz": nnz,
        "density": density,
        "row_count": rows,
        "col_count": cols,
        "model_sense": "minimize",
        "objective_sense": "minimize",
        "variable_type_counts": _variable_type_counts(allocation.m),
        "constraint_sense_counts": _constraint_sense_counts(constraints),
    }
    meta_path = out_dir / "gurobi_constraint_matrix_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")

    trace_rows = [
        {
            "sample": 0,
            "runtime": 0.0,
            "node_count": "",
            "incumbent_objective": objective_value if objective_value is not None else "",
            "best_bound": best_bound if best_bound is not None else "",
            "mip_gap": mip_gap if mip_gap is not None else "",
            "solution_count": "",
            "status": status,
        }
    ]
    trace_csv = out_dir / "gurobi_mip_trace.csv"
    with trace_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(trace_rows[0].keys()))
        writer.writeheader()
        writer.writerows(trace_rows)
    trace_json = out_dir / "gurobi_mip_trace.json"
    trace_payload = {
        "schema_version": "qlip.gurobi_mip_trace.v1",
        "trace_sparse": True,
        "reason": "Pyomo shell solve path exposes final solver result but not callback progress samples.",
        "samples": trace_rows,
        "status": status,
    }
    trace_json.write_text(json.dumps(trace_payload, indent=2, sort_keys=True), encoding="utf-8")
    trace_png = out_dir / "gurobi_mip_trace.png"
    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    ax.scatter([0], [objective_value if objective_value is not None else 0.0], color="tab:blue", label="final incumbent")
    if best_bound is not None:
        ax.scatter([0], [float(best_bound)], color="tab:orange", label="final best bound")
    ax.set_title("Gurobi MIP trace (sparse)")
    ax.set_xlabel("callback sample")
    ax.set_ylabel("objective / bound")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(trace_png, dpi=180)
    plt.close(fig)

    return {
        "enabled": True,
        "artifact_dir": str(out_dir),
        "constraint_matrix_path": str(matrix_path),
        "constraint_matrix_meta_path": str(meta_path),
        "constraint_matrix_spy_path": str(spy_path),
        "mip_trace_csv_path": str(trace_csv),
        "mip_trace_json_path": str(trace_json),
        "mip_trace_plot_path": str(trace_png),
        "trace_sparse": True,
        "matrix": meta,
    }


def _classify_cif_output(value: Any) -> tuple[str, Optional[str], Dict[str, Any]]:
    text = _to_text(value)
    if text is None:
        return "empty", None, {"reason": "missing"}

    stripped = text.strip()
    if not stripped:
        return "empty", None, {"reason": "blank"}

    content_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not content_lines:
        return "empty", None, {"reason": "comment_only"}

    first_line = content_lines[0]
    if stripped in _KNOWN_CIF_PLACEHOLDERS:
        return "placeholder", text, {"reason": "known_placeholder"}
    if len(content_lines) == 1 and first_line.startswith("data_"):
        return "placeholder", text, {"reason": "header_only"}
    if not first_line.startswith("data_"):
        return "malformed", text, {"reason": "missing_data_block"}

    missing_tokens = [token for token in _REQUIRED_CIF_TOKENS if token not in text]
    if missing_tokens:
        return "malformed", text, {"reason": "missing_required_tokens", "missing": missing_tokens}

    return "valid_cif_like", text, {}


def _build_cif_text(task) -> Optional[str]:
    try:
        placements = _extract_placements(task)
    except Exception:
        return None

    symbols: List[str] = []
    scaled: List[Tuple[float, float, float]] = []
    for el, pts in placements.items():
        for fx, fy, fz in pts:
            symbols.append(el)
            scaled.append((float(fx), float(fy), float(fz)))

    atoms = Atoms(symbols=symbols, cell=task.positions.cell, pbc=True)
    if scaled:
        atoms.set_scaled_positions(np.asarray(scaled, dtype=float))

    buf = io.BytesIO()
    write(buf, atoms, format="cif")
    return buf.getvalue().decode("latin-1")


def _apply_constraints(allocation, constraints: List[Dict[str, Any]], context: Dict[str, Any]) -> None:
    ordered = []
    for idx, inv in enumerate(constraints):
        if not inv.get("enabled", True):
            continue
        ordered.append((int(inv.get("priority", 100)), idx, inv))
    for _, _, inv in sorted(ordered):
        plugin = ConstraintRegistry.get(inv["id"])
        if not plugin:
            continue
        params = dict(inv.get("params", {}))
        if inv["id"] == "motif.linking":
            if not params.get("motif_dir"):
                params["motif_dir"] = context.get("motif_root")
        plugin.apply(allocation, params)


def _apply_guidance(allocation, guidance: List[Dict[str, Any]], guidance_mode: str) -> None:
    for inv in guidance:
        if not inv.get("enabled", True):
            continue
        plugin = GuidanceRegistry.get(inv["id"])
        if not plugin:
            continue
        plugin.apply(allocation, inv, guidance_mode)


def _solve_model(allocation, solver_cfg: Dict[str, Any]) -> Any:
    solver = pyo.SolverFactory("gurobi")
    if solver is None or not solver.available(exception_flag=False):
        raise RuntimeError("Gurobi solver is not available.")

    options = {}
    if solver_cfg.get("time_limit_s"):
        options["TimeLimit"] = int(solver_cfg["time_limit_s"])
    if solver_cfg.get("mip_gap") is not None:
        options["MIPGap"] = float(solver_cfg["mip_gap"])
    if solver_cfg.get("threads"):
        options["Threads"] = int(solver_cfg["threads"])
    if solver_cfg.get("seed"):
        options["Seed"] = int(solver_cfg["seed"])
    options.update(solver_cfg.get("parameters", {}) or {})
    normalized = {}
    for key, value in options.items():
        if isinstance(key, (bytes, bytearray)):
            key = _to_text(key)
        if isinstance(value, (bytes, bytearray)):
            value = _to_text(value)
        normalized[key] = value
    solver.options.update(normalized)

    return solver.solve(allocation.m, tee=False)


def solve(request: Dict[str, Any]) -> SolveResult:
    start = time.time()
    report = validate_request(request, strict=True)
    if not report.valid:
        summary = SolveSummary(
            solver="gurobi",
            timing_ms=int((time.time() - start) * 1000),
            objective_value=None,
            best_bound=None,
            mip_gap=None,
            termination="validation_failed",
        )
        errors = [
            SolveError(code=issue.code, message=issue.message, details=issue.details)
            for issue in report.errors
        ]
        return SolveResult(status="ERROR", summary=summary, outputs=SolveOutputs(), errors=errors)

    req = report.normalized_request or request
    diagnostics = _design_space_diagnostics(req)
    problem = req["problem"]
    chemistry = problem["chemistry"]
    design_space = problem["design_space"]
    objective = problem.get("objective", {})
    context = req.get("context", {})
    artifacts = req.get("artifacts", {})

    try:
        diagnostics["explicit_chemistry"] = preflight_charge(chemistry).to_dict()
        model_build_started = time.perf_counter()
        stoic = Atoms(symbols=chemistry["formula"])
        allocation = Allocation(stoic)
        allocation.positions = _build_positions(design_space)
        allocation.ordered_orbits = list(
            design_space.get("sites", {}).get("ordered_orbits", [])
        )
        allocation.explicit_vacancy_count = design_space.get("sites", {}).get("vacancy_count")

        spp_params = _spp_guidance_params(req)
        objective_type = str(objective.get("type", "spp_energy"))
        if objective_type == "none" and not spp_params:
            # Explicit NO_SPP mode. The discrete allocation model, chemistry,
            # orbit, and solver paths remain real; no potential root is
            # resolved and no statistical pair term is silently fabricated.
            allocation.cost = None
            allocation.pairs = []
            diagnostics["spp_guidance"] = {
                "mode": "none",
                "spp_guidance_mode": "NO_SPP",
                "partial_guidance": False,
                "spp_terms_added_count": 0,
                "terms_added_count": 0,
                "reason": "problem.objective.type is none and no SPP guidance invocation was supplied",
            }
        else:
            pot_root = _resolve_spp_pot_root(req)
            spp_cutoff = spp_params.get("cutoff", spp_params.get("spp_cutoff", 11.0))
            spp_pairs, spp_diagnostics = _spp_pairs_to_load(req, allocation)
            spp = SPPCollection(
                pot_root,
                cutoff=spp_cutoff,
                missing_pair_policy=spp_diagnostics.get("missing_pair_policy", "neutral"),
                regularisation_spp_dir=spp_diagnostics.get("regularisation_spp_dir"),
                regularisation_weight=spp_diagnostics.get("regularisation_weight", 0.0),
            )
            spp_diagnostics["regularisation_pairs_loaded"] = len(getattr(spp, "regularisation_spps", {}) or {})
            spp_diagnostics["regularisation_load_errors"] = list(getattr(spp, "regularisation_load_errors", []) or [])
            diagnostics["spp_guidance"] = spp_diagnostics
            spp.load(spp_pairs)
            allocation.cost = spp
            # In partial SPP mode, neutral missing pairs are unguided while
            # soft_repulsive missing pairs remain in the objective with a finite
            # deterministic fallback coefficient.
            allocation.pairs = list(spp_pairs)

        _apply_constraints(allocation, req.get("constraints", []), context)
        allocation.encode()
        diagnostics["vacancy_states"] = dict(getattr(allocation, "vacancy_state_diagnostics", {}))
        apply_objective_contract(allocation, objective)
        _apply_guidance(allocation, req.get("guidance", []), req.get("guidance_mode", "weighted_sum"))
        diagnostics["model_stats"] = _model_stats(allocation, diagnostics)
        diagnostics["model_build_time_ms"] = int((time.perf_counter() - model_build_started) * 1000)

        solver_cfg = req.get("solver", {})
        solver_started = time.perf_counter()
        result = _solve_model(allocation, solver_cfg)
        diagnostics["solver_time_ms"] = int((time.perf_counter() - solver_started) * 1000)
        term = getattr(result.solver, "termination_condition", None)
        term_str = str(term) if term is not None else "unknown"

        status = "ERROR"
        if term == pyo.TerminationCondition.optimal:
            status = "OPTIMAL"
        elif term == pyo.TerminationCondition.feasible:
            status = "FEASIBLE"
        elif term == pyo.TerminationCondition.infeasible:
            status = "INFEASIBLE"
        elif term == pyo.TerminationCondition.maxTimeLimit:
            # A Gurobi TIME_LIMIT does not by itself mean no incumbent was
            # found: Pyomo's Gurobi interface loads a feasible incumbent's
            # variable values into `allocation.m` whenever SolCount>=1, even
            # under TIME_LIMIT (see the scaled-cell incumbent audit). This is
            # a provisional label; it is upgraded to FEASIBLE_TIME_LIMIT
            # below if a usable candidate can actually be decoded, and left
            # as-is (still not OPTIMAL/FEASIBLE) if SolCount==0.
            status = _TIME_LIMIT_NO_SOLUTION

        objective_value = _objective_value(allocation.m) if status in {"OPTIMAL", "FEASIBLE"} else None
        best_bound = getattr(result.solver, "best_bound", None)
        mip_gap = getattr(result.solver, "mip_gap", None)
        gurobi_visuals: Dict[str, Any] = {"enabled": False}
        if _export_gurobi_visuals_enabled(req):
            gurobi_visuals = _export_gurobi_visual_artifacts(
                allocation,
                result,
                req,
                status,
                objective_value,
                best_bound,
                mip_gap,
            )

        errors: List[SolveError] = []
        cif_text = None
        decoder_debug = None
        if artifacts.get("return_decoder_debug", False):
            decoder_debug = getattr(allocation, "decoder_debug", None)

        if status in _SUCCESS_STATUSES and artifacts.get("return_cif", True):
            cif_kind, cif_text, cif_details = _classify_cif_output(_build_cif_text(allocation))
            if cif_kind != "valid_cif_like":
                status = "ERROR"
                errors.append(
                    SolveError(
                        code="invalid_cif_output",
                        message="Solve completed without producing a valid CIF artifact.",
                        details={
                            "artifact_status": cif_kind,
                            "termination": term_str,
                            **cif_details,
                        },
                    )
                )
        elif status == _TIME_LIMIT_NO_SOLUTION and artifacts.get("return_cif", True):
            try:
                cif_kind, candidate_cif_text, cif_details = _classify_cif_output(_build_cif_text(allocation))
            except Exception:
                cif_kind, candidate_cif_text, cif_details = "no_incumbent_loaded", None, {}
            if cif_kind == "valid_cif_like" and candidate_cif_text:
                status = _FEASIBLE_TIME_LIMIT
                cif_text = candidate_cif_text
                objective_value = _objective_value(allocation.m)
                diagnostics["feasible_time_limit_cif_details"] = cif_details
            else:
                diagnostics["infeasibility_category"] = diagnostics.get("infeasibility_category") or "time_limit_no_feasible_incumbent"
                diagnostics.setdefault("diagnostic_hints", []).append(
                    "Solver reached its time limit without a usable incumbent (SolCount==0 or the incumbent could not be decoded)."
                )
                errors.append(
                    SolveError(
                        code="solve_terminated_without_solution",
                        message=f"Solver terminated with '{term_str}' before producing a solved structure.",
                        details={"termination": term_str},
                    )
                )
        elif status == "INFEASIBLE":
            diagnostics["infeasibility_category"] = diagnostics.get("infeasibility_category") or "solver_infeasible_no_solution"
            diagnostics.setdefault("diagnostic_hints", []).append(
                "Solver proved infeasibility; relax constraints or enlarge candidate site/design space."
            )
            errors.append(
                SolveError(
                    code="infeasible",
                    message="Solver reported the problem as infeasible; no solved structure was produced.",
                    details={"termination": term_str},
                )
            )
        elif status not in _SUCCESS_STATUSES:
            diagnostics["infeasibility_category"] = diagnostics.get("infeasibility_category") or "qlip_solver_runtime_error"
            diagnostics.setdefault("diagnostic_hints", []).append(
                "Solver terminated without a usable solution; inspect termination and runtime data."
            )
            errors.append(
                SolveError(
                    code="solve_terminated_without_solution",
                    message=f"Solver terminated with '{term_str}' before producing a solved structure.",
                    details={"termination": term_str},
                )
            )

        if status == "ERROR":
            cif_text = None

        artifact_items: List[ArtifactItem] = []
        for key, mime in (
            ("constraint_matrix_meta_path", "application/json"),
            ("constraint_matrix_spy_path", "image/png"),
            ("mip_trace_csv_path", "text/csv"),
            ("mip_trace_json_path", "application/json"),
            ("mip_trace_plot_path", "image/png"),
        ):
            path_value = gurobi_visuals.get(key)
            if path_value:
                artifact_items.append(ArtifactItem(kind=key, data=str(path_value), mime=mime))
        outputs = SolveOutputs(cif=cif_text, decoder_debug=_to_text(decoder_debug), artifacts=artifact_items)

        summary = SolveSummary(
            solver="gurobi",
            timing_ms=int((time.time() - start) * 1000),
            objective_value=objective_value,
            best_bound=best_bound if best_bound is not None else None,
            mip_gap=mip_gap if mip_gap is not None else None,
            termination=term_str,
        )
        diagnostics["qlip_status"] = status
        if gurobi_visuals.get("enabled"):
            diagnostics["gurobi_visuals"] = gurobi_visuals
        return SolveResult(
            status=status,
            summary=summary,
            outputs=outputs,
            errors=errors,
            certificates={"diagnostics": diagnostics},
        )
    except Exception as exc:
        if os.getenv("QLIP_TRACEBACK") == "1":
            print("\n[TRACEBACK] uncaught exception in solve:", file=sys.stderr)
            traceback.print_exc()
            print(f"[TRACEBACK] type={type(exc)} repr={repr(exc)}", file=sys.stderr)
            if "context" in locals():
                print(f"[TRACEBACK] context={context!r}", file=sys.stderr)
            if "artifacts" in locals():
                print(f"[TRACEBACK] artifacts={artifacts!r}", file=sys.stderr)
            if "solver_cfg" in locals():
                print(f"[TRACEBACK] solver_cfg={solver_cfg!r}", file=sys.stderr)
            if "pot_root" in locals():
                print(f"[TRACEBACK] pot_root_type={type(pot_root)} value={pot_root!r}", file=sys.stderr)
            if "cif_text" in locals():
                cif_len = len(cif_text) if hasattr(cif_text, "__len__") else "n/a"
                print(
                    f"[TRACEBACK] cif_text_type={type(cif_text)} len={cif_len}",
                    file=sys.stderr,
                )
            if "decoder_debug" in locals():
                dbg_len = len(decoder_debug) if hasattr(decoder_debug, "__len__") else "n/a"
                print(
                    f"[TRACEBACK] decoder_debug_type={type(decoder_debug)} len={dbg_len}",
                    file=sys.stderr,
                )
            if "request" in locals():
                print(f"[TRACEBACK] request_type={type(request)}", file=sys.stderr)
        summary = SolveSummary(
            solver="gurobi",
            timing_ms=int((time.time() - start) * 1000),
            objective_value=None,
            best_bound=None,
            mip_gap=None,
            termination="error",
        )
        err_message = _to_text(getattr(exc, "message", None) or exc)
        if err_message is None:
            err_message = f"{type(exc).__name__}"
        err = SolveError(code="solve_error", message=err_message)
        diagnostics = diagnostics if "diagnostics" in locals() else _design_space_diagnostics(request)
        diagnostics["qlip_status"] = "ERROR"
        diagnostics["infeasibility_category"] = diagnostics.get("infeasibility_category") or "qlip_solver_runtime_error"
        diagnostics.setdefault("diagnostic_hints", []).append(
            "QLIP raised an exception while building or solving the model; inspect request formula, unit cell, site space, and runtime data."
        )
        return SolveResult(
            status="ERROR",
            summary=summary,
            outputs=SolveOutputs(),
            errors=[err],
            certificates={"diagnostics": diagnostics},
        )
