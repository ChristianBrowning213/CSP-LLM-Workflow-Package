from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pyomo.environ as pyo
from ase import Atoms

from qlip.allocation import Allocation
from qlip.core.paths import allowed_path_roots, resolve_and_check_path
from qlip.data.registry import default_registry
from qlip.interactions.spp import SPP, SPPCollection


DATA_CATEGORIES = {
    "solver",
    "paths",
    "chemistry",
    "lattice",
    "sites",
    "spp",
    "constraints",
    "guidance",
    "motifs",
    "properties",
}

DATA_ERROR_CODES = {
    "gurobi_unavailable",
    "gurobi_license_missing_or_invalid",
    "pot_root_missing",
    "pot_root_outside_allowed_roots",
    "pot_root_no_pot_files",
    "pot_pair_missing",
    "spp_regularisation_dir_missing",
    "spp_regularisation_dir_outside_allowed_roots",
    "spp_regularisation_dir_no_pot_files",
    "spp_regularisation_dir_no_loadable_pot_files",
    "spp_regulator_pair_missing",
    "radii_data_missing",
    "oxidation_state_missing",
    "neighbor_graph_missing",
    "lattice_template_missing",
    "motif_root_missing",
    "motif_artifacts_missing",
    "property_table_missing",
    "beta_table_missing",
    "unsupported_element_data",
    "solve_data_preflight_failed",
}


@dataclass
class DataDiagnostic:
    code: str
    category: str
    message: str
    path: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "path": self.path,
            "details": dict(self.details),
        }


@dataclass
class PreflightReport:
    ready: bool
    missing_data: List[DataDiagnostic] = field(default_factory=list)
    available_data: List[Dict[str, Any]] = field(default_factory=list)
    required_data: List[Dict[str, Any]] = field(default_factory=list)
    suggested_next_actions: List[str] = field(default_factory=list)
    capabilities: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ready": self.ready,
            "missing_data": [item.to_dict() for item in self.missing_data],
            "available_data": list(self.available_data),
            "required_data": list(self.required_data),
            "suggested_next_actions": list(self.suggested_next_actions),
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _formula_to_species_pairs(formula: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    atoms = Atoms(symbols=formula)
    alloc = Allocation(atoms)
    return alloc.types, alloc.pairs


def _pair_name(pair: Tuple[str, str]) -> str:
    return "-".join(pair)


def _pair_key(pair: str) -> Tuple[str, str]:
    left, right = str(pair).split("-", 1)
    ordered = sorted([left, right], key=str.lower)
    return ordered[0], ordered[1]


def _path_details(value: Any = None, roots: Iterable[Path] = (), extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    details: Dict[str, Any] = {
        "allowed_roots": [str(Path(root).expanduser().resolve()) for root in roots],
    }
    if value is not None:
        details["value"] = str(value)
    if extra:
        details.update(extra)
    return details


def _classify_path_exception(exc: Exception, *, missing_code: str, outside_code: str = "path_outside_allowed_roots") -> str:
    text = str(exc)
    if "does not exist" in text:
        return missing_code
    if "not in allowed roots" in text:
        return outside_code
    return "path_invalid"


def _needs_spp(request: Dict[str, Any]) -> bool:
    problem = request.get("problem", {}) if isinstance(request.get("problem"), dict) else {}
    objective = problem.get("objective", {}) if isinstance(problem.get("objective"), dict) else {}
    if objective.get("type", "spp_energy") == "spp_energy":
        return True
    if objective.get("type") == "threshold_tradeoff" and objective.get("base_objective", "spp_energy") == "spp_energy":
        return True
    return any(
        inv.get("enabled", True) and inv.get("id") == "objective.energy_spp"
        for inv in request.get("guidance", [])
        if isinstance(inv, dict)
    )


def _spp_guidance_params(request: Dict[str, Any]) -> Dict[str, Any]:
    for inv in request.get("guidance", []):
        if not isinstance(inv, dict):
            continue
        if inv.get("enabled", True) and inv.get("id") == "objective.energy_spp":
            params = inv.get("params")
            return params if isinstance(params, dict) else {}
    return {}


def _regularisation_setting(params: Dict[str, Any], key: str, american_key: str, env_names: Tuple[str, ...] = ()) -> Any:
    if key in params:
        return params.get(key)
    if american_key in params:
        return params.get(american_key)
    for env_name in env_names:
        value = os.environ.get(env_name)
        if value not in (None, ""):
            return value
    return None


def _regularisation_params(params: Dict[str, Any]) -> Tuple[Optional[str], float]:
    raw_dir = _regularisation_setting(
        params,
        "regularisation_spp_dir",
        "regularization_spp_dir",
        ("QLIP_SPP_REGULARISATION_DIR", "QLIP_SPP_REGULARIZATION_DIR"),
    )
    raw_weight = _regularisation_setting(
        params,
        "regularisation_weight",
        "regularization_weight",
        (),
    )
    try:
        weight = float(raw_weight or 0.0)
    except Exception:
        weight = 0.0
    return str(raw_dir) if raw_dir not in (None, "") else None, weight


def _loadable_pot_count(root: Path) -> Tuple[int, List[Dict[str, str]]]:
    loadable = 0
    errors: List[Dict[str, str]] = []
    for pot_file in sorted(root.rglob("*.POT")):
        try:
            r_grid, u_grid = SPPCollection._read_pot(pot_file)
            SPP(r_grid, u_grid)
            loadable += 1
        except Exception as exc:
            errors.append({"path": str(pot_file), "error": str(exc)})
    return loadable, errors


def _pot_candidates(root: Path, a: str, b: str) -> List[Path]:
    pair0 = f"{a}-{b}"
    pair0_rev = f"{b}-{a}"
    pair1 = f"{a.upper()}-{b.upper()}"
    pair2 = f"{b.upper()}-{a.upper()}"
    return [
        root / pair0 / f"{pair0}.POT",
        root / pair0_rev / f"{pair0_rev}.POT",
        root / f"{pair0}.POT",
        root / f"{pair0_rev}.POT",
        root / pair1 / f"{pair1}.POT",
        root / pair2 / f"{pair2}.POT",
        root / f"{pair1}.POT",
        root / f"{pair2}.POT",
    ]


def _find_pot(root: Path, a: str, b: str) -> Optional[Path]:
    for path in _pot_candidates(root, a, b):
        if path.exists():
            return path
    return None


def _pot_load_error(path: Path) -> Optional[str]:
    try:
        r_grid, u_grid = SPPCollection._read_pot(path)
        SPP(r_grid, u_grid)
    except Exception as exc:
        return str(exc)
    return None


def _read_radii() -> Tuple[Optional[Dict[str, float]], Optional[Path], Optional[Exception]]:
    registry = default_registry()
    path = registry.data_dir / "radii.json"
    try:
        payload = registry.radii()
        field = registry.radius_policy().get("default_radius_field", "qlip_default_radius_angstrom")
        records = payload.get("records", {})
        return {
            symbol: float(record[field])
            for symbol, record in records.items()
            if record.get(field) is not None
        }, path, None
    except Exception as exc:
        return None, path, exc


def _enabled_constraints(request: Dict[str, Any]) -> List[Tuple[int, Dict[str, Any]]]:
    return [
        (idx, inv)
        for idx, inv in enumerate(request.get("constraints", []))
        if isinstance(inv, dict) and inv.get("enabled", True)
    ]


def _objective(request: Dict[str, Any]) -> Dict[str, Any]:
    problem = request.get("problem", {}) if isinstance(request.get("problem"), dict) else {}
    objective = problem.get("objective", {}) if isinstance(problem.get("objective"), dict) else {}
    return objective


def _formula(request: Dict[str, Any]) -> str:
    problem = request.get("problem", {}) if isinstance(request.get("problem"), dict) else {}
    chemistry = problem.get("chemistry", {}) if isinstance(problem.get("chemistry"), dict) else {}
    return str(chemistry.get("formula", ""))


def _add_action(actions: List[str], action: str) -> None:
    if action not in actions:
        actions.append(action)


def _check_solver(report: PreflightReport) -> None:
    report.required_data.append(
        {"code": "gurobi_available", "category": "solver", "path": "/solver/name", "solver": "gurobi"}
    )
    try:
        solver = pyo.SolverFactory("gurobi")
        if solver and solver.available(exception_flag=False):
            report.available_data.append(
                {"code": "gurobi_available", "category": "solver", "path": "/solver/name", "solver": "gurobi"}
            )
            report.capabilities["gurobi_available"] = True
            return
        code = "gurobi_unavailable"
        message = "Gurobi solver is not available."
    except Exception as exc:
        text = str(exc).lower()
        if "license" in text:
            code = "gurobi_license_missing_or_invalid"
            message = "Gurobi license is missing or invalid."
        else:
            code = "gurobi_unavailable"
            message = f"Gurobi solver is not available: {exc}"
    report.capabilities["gurobi_available"] = False
    report.missing_data.append(
        DataDiagnostic(code=code, category="solver", message=message, path="/solver/name")
    )
    _add_action(report.suggested_next_actions, "Install Gurobi and configure a valid license before solving.")


def _check_spp(request: Dict[str, Any], report: PreflightReport, roots: List[Path], species: List[str], pairs: List[Tuple[str, str]]) -> Optional[Path]:
    if not _needs_spp(request):
        report.capabilities["pot_root_resolved"] = False
        return None

    required_pairs = [_pair_name(pair) for pair in pairs]
    report.required_data.append(
        {
            "code": "spp_potentials",
            "category": "spp",
            "path": "/context/pot_root",
            "formula": _formula(request),
            "required_pairs": required_pairs,
        }
    )
    context = request.get("context", {}) if isinstance(request.get("context"), dict) else {}
    guidance_params = _spp_guidance_params(request)
    regularisation_dir_raw, regularisation_weight = _regularisation_params(guidance_params)
    regularisation_dir: Optional[Path] = None
    report.capabilities["spp_regularisation"] = {
        "enabled": regularisation_weight > 0.0,
        "regularisation_spp_dir": regularisation_dir_raw,
        "regularisation_weight": regularisation_weight,
        "regularisation_pairs_loaded": 0,
        "load_errors": [],
    }
    if regularisation_weight > 0.0:
        if not regularisation_dir_raw:
            report.missing_data.append(
                DataDiagnostic(
                    code="spp_regularisation_dir_missing",
                    category="spp",
                    message="regularisation_spp_dir is required when regularisation_weight is greater than zero.",
                    path="/guidance/0/params/regularisation_spp_dir",
                    details=_path_details(roots=roots, extra={"regularisation_weight": regularisation_weight}),
                )
            )
        else:
            try:
                regularisation_dir = resolve_and_check_path(regularisation_dir_raw, roots, must_exist=True)
                pot_files = list(Path(regularisation_dir).rglob("*.POT"))
                if not pot_files:
                    report.missing_data.append(
                        DataDiagnostic(
                            code="spp_regularisation_dir_no_pot_files",
                            category="spp",
                            message="regularisation_spp_dir exists but contains no .POT files.",
                            path="/guidance/0/params/regularisation_spp_dir",
                            details=_path_details(value=regularisation_dir, roots=roots),
                        )
                    )
                else:
                    loadable_count, load_errors = _loadable_pot_count(Path(regularisation_dir))
                    report.capabilities["spp_regularisation"].update(
                        {
                            "regularisation_spp_dir": str(regularisation_dir),
                            "regularisation_pairs_loaded": loadable_count,
                            "load_errors": load_errors,
                        }
                    )
                    if loadable_count == 0:
                        report.missing_data.append(
                            DataDiagnostic(
                                code="spp_regularisation_dir_no_loadable_pot_files",
                                category="spp",
                                message="regularisation_spp_dir contains no loadable .POT files.",
                                path="/guidance/0/params/regularisation_spp_dir",
                                details=_path_details(value=regularisation_dir, roots=roots, extra={"load_errors": load_errors[:5]}),
                            )
                        )
                    else:
                        report.available_data.append(
                            {
                                "code": "spp_regularisation_available",
                                "category": "spp",
                                "path": str(regularisation_dir),
                                "regularisation_weight": regularisation_weight,
                                "regularisation_pairs_loaded": loadable_count,
                                "load_error_count": len(load_errors),
                            }
                        )
            except Exception as exc:
                code = _classify_path_exception(
                    exc,
                    missing_code="spp_regularisation_dir_missing",
                    outside_code="spp_regularisation_dir_outside_allowed_roots",
                )
                report.missing_data.append(
                    DataDiagnostic(
                        code=code,
                        category="spp" if code == "spp_regularisation_dir_missing" else "paths",
                        message=str(exc),
                        path="/guidance/0/params/regularisation_spp_dir",
                        details=_path_details(value=regularisation_dir_raw, roots=roots),
                    )
                )
    mode = str(guidance_params.get("mode", "complete"))
    missing_pair_policy = str(guidance_params.get("missing_pair_policy", "block" if mode == "partial" else "block"))
    strict_pair_coverage = bool(guidance_params.get("strict_pair_coverage", mode != "partial"))
    supported_pairs_param = [
        str(pair)
        for pair in guidance_params.get("supported_pairs", [])
        if isinstance(pair, str) and "-" in pair
    ] if isinstance(guidance_params.get("supported_pairs"), list) else []
    missing_pairs_param = [
        str(pair)
        for pair in guidance_params.get("missing_pairs", [])
        if isinstance(pair, str) and "-" in pair
    ] if isinstance(guidance_params.get("missing_pairs"), list) else []
    # ``fallback`` is admissible only when an enabled, resolved regulator
    # directory supplies a real, loadable POT for every missing pair.  Exact
    # pair validation happens below; directory-level availability is not enough.
    regulator_fallback_configured = (
        missing_pair_policy == "fallback"
        and regularisation_weight > 0.0
        and regularisation_dir is not None
    )
    partial_missing_pair_policy = (
        missing_pair_policy in {"neutral", "zero", "soft_repulsive"}
        or regulator_fallback_configured
    )
    partial_missing_pair_allowed = mode == "partial" and partial_missing_pair_policy and not strict_pair_coverage
    partial_neutral = partial_missing_pair_allowed and missing_pair_policy in {"neutral", "zero"}
    pot_root_raw = guidance_params.get("pot_root") or context.get("pot_root")
    if not pot_root_raw:
        report.capabilities["pot_root_resolved"] = False
        report.missing_data.append(
            DataDiagnostic(
                code="pot_root_missing",
                category="spp",
                message="context.pot_root is required for SPP potentials.",
                path="/context/pot_root",
                details=_path_details(roots=roots, extra={"formula": _formula(request), "required_pairs": required_pairs}),
            )
        )
        _add_action(report.suggested_next_actions, "Provide context.pot_root pointing to a directory containing SPP .POT files.")
        return None

    try:
        pot_root = resolve_and_check_path(pot_root_raw, roots, must_exist=True)
    except Exception as exc:
        code = _classify_path_exception(
            exc,
            missing_code="pot_root_missing",
            outside_code="pot_root_outside_allowed_roots",
        )
        report.capabilities["pot_root_resolved"] = False
        report.missing_data.append(
            DataDiagnostic(
                code=code,
                category="paths",
                message=str(exc),
                path="/context/pot_root",
                details=_path_details(value=pot_root_raw, roots=roots, extra={"required_pairs": required_pairs}),
            )
        )
        _add_action(report.suggested_next_actions, "Move the POT root under an allowed path root or update QLIP_ALLOWED_PATH_ROOTS.")
        return None

    pot_files = list(Path(pot_root).rglob("*.POT"))
    if not pot_files:
        report.capabilities["pot_root_resolved"] = False
        report.missing_data.append(
            DataDiagnostic(
                code="pot_root_no_pot_files",
                category="spp",
                message="context.pot_root exists but contains no .POT files.",
                path="/context/pot_root",
                details=_path_details(value=pot_root, roots=roots, extra={"required_pairs": required_pairs}),
            )
        )
        _add_action(report.suggested_next_actions, "Populate context.pot_root with the required SPP .POT files.")
        return pot_root

    found_by_pair: Dict[str, Path] = {}
    required_pair_keys = {_pair_key(pair) for pair in required_pairs}
    supported_pair_keys = {_pair_key(pair) for pair in supported_pairs_param}
    missing_pair_keys = {_pair_key(pair) for pair in missing_pairs_param}
    effective_missing_pairs = list(missing_pairs_param)
    effective_missing_pair_keys = set(missing_pair_keys)
    if partial_missing_pair_allowed:
        effective_missing_pairs = [
            pair for pair in required_pairs
            if _pair_key(pair) not in supported_pair_keys
        ]
        effective_missing_pair_keys = {_pair_key(pair) for pair in effective_missing_pairs}
    if partial_missing_pair_allowed:
        bad_supported = sorted(pair for pair in supported_pairs_param if _pair_key(pair) not in required_pair_keys)
        bad_missing = sorted(pair for pair in missing_pairs_param if _pair_key(pair) not in required_pair_keys)
        if bad_supported or bad_missing:
            report.missing_data.append(
                DataDiagnostic(
                    code="spp_partial_pair_set_invalid",
                    category="spp",
                    message="Partial SPP supported_pairs and missing_pairs must be subsets of required pairs.",
                    path="/guidance/0/params",
                    details={
                        "required_pairs": required_pairs,
                        "invalid_supported_pairs": bad_supported,
                        "invalid_missing_pairs": bad_missing,
                    },
                )
            )
        report.available_data.append(
            {
                "code": "spp_partial_guidance",
                "category": "spp",
                "path": "/guidance/0/params",
                "spp_guidance_mode": "partial_spp",
                "spp_missing_pair_policy": missing_pair_policy,
                "spp_supported_pairs_requested": supported_pairs_param,
                "spp_missing_pairs_unguided": effective_missing_pairs if partial_neutral else [],
                "spp_missing_pairs_soft_repulsive": effective_missing_pairs if missing_pair_policy == "soft_repulsive" else [],
                "spp_missing_pairs_regulator_fallback": effective_missing_pairs if missing_pair_policy == "fallback" else [],
                "strict_pair_coverage": False,
            }
        )

    for a, b in pairs:
        pair = _pair_name((a, b))
        found = _find_pot(pot_root, a, b)
        if found and (not partial_missing_pair_allowed or not supported_pair_keys or _pair_key(pair) in supported_pair_keys):
            found_by_pair[pair] = found
            report.available_data.append(
                {"code": "pot_pair_available", "category": "spp", "path": str(found), "pair": pair}
            )

    available_pairs = sorted(found_by_pair)
    missing_any = False
    for a, b in pairs:
        pair = _pair_name((a, b))
        if pair in found_by_pair:
            continue
        if partial_missing_pair_allowed and _pair_key(pair) in effective_missing_pair_keys:
            regulator_path: Optional[Path] = None
            if missing_pair_policy == "fallback":
                regulator_path = _find_pot(regularisation_dir, a, b) if regularisation_dir is not None else None
                regulator_load_error = _pot_load_error(regulator_path) if regulator_path is not None else None
                if regulator_path is None or regulator_load_error is not None:
                    missing_any = True
                    attempted = (
                        [str(path) for path in _pot_candidates(regularisation_dir, a, b)]
                        if regularisation_dir is not None else []
                    )
                    report.missing_data.append(
                        DataDiagnostic(
                            code="spp_regulator_pair_missing",
                            category="spp",
                            message=f"Missing loadable regulator POT file for fallback pair {pair}.",
                            path="/guidance/0/params/regularisation_spp_dir",
                            details={
                                "formula": _formula(request),
                                "pair": pair,
                                "regularisation_spp_dir": str(regularisation_dir) if regularisation_dir else None,
                                "attempted_paths": attempted,
                                "load_error": regulator_load_error,
                            },
                        )
                    )
                    continue
            report.available_data.append(
                {
                    "code": (
                        "pot_pair_neutral_missing" if partial_neutral
                        else "pot_pair_regulator_fallback" if missing_pair_policy == "fallback"
                        else "pot_pair_soft_missing"
                    ),
                    "category": "spp",
                    "path": "/guidance/0/params/missing_pairs",
                    "pair": pair,
                    "policy": missing_pair_policy,
                    "regulator_path": str(regulator_path) if regulator_path is not None else None,
                }
            )
            continue
        missing_any = True
        attempted = [str(path) for path in _pot_candidates(pot_root, a, b)]
        report.missing_data.append(
            DataDiagnostic(
                code="pot_pair_missing",
                category="spp",
                message=f"Missing SPP POT file for required pair {pair}.",
                path="/context/pot_root",
                details={
                    "formula": _formula(request),
                    "pair": pair,
                    "required_pairs": required_pairs,
                    "available_pairs": available_pairs,
                    "attempted_paths": attempted,
                },
            )
        )

    report.capabilities["pot_root_resolved"] = not missing_any
    report.capabilities["spp_partial_guidance"] = {
        "enabled": partial_missing_pair_allowed,
        "guidance_id": "objective.energy_spp" if partial_missing_pair_allowed else None,
        "mode": "partial" if partial_missing_pair_allowed else None,
        "missing_pair_policy": missing_pair_policy if partial_missing_pair_allowed else None,
        "strict_pair_coverage": False if partial_missing_pair_allowed else True,
        "supported_pairs": available_pairs if partial_missing_pair_allowed else [],
        "missing_pairs": effective_missing_pairs if partial_missing_pair_allowed else [],
        "supported_pair_count": len(available_pairs) if partial_missing_pair_allowed else 0,
        "missing_pair_count": len(effective_missing_pairs) if partial_missing_pair_allowed else 0,
        "pot_root": str(pot_root) if partial_missing_pair_allowed else None,
        "missing_pairs_require_pots": False if partial_missing_pair_allowed else True,
        "missing_pairs_are_neutral": partial_neutral,
        "missing_pairs_use_soft_repulsive": partial_missing_pair_allowed and missing_pair_policy == "soft_repulsive",
        "missing_pairs_use_regulator_fallback": partial_missing_pair_allowed and missing_pair_policy == "fallback",
    }
    report.capabilities["spp_supported_pairs_used"] = available_pairs
    report.capabilities["spp_missing_pairs_unguided"] = effective_missing_pairs if partial_neutral else []
    report.capabilities["spp_missing_pairs_soft_repulsive"] = effective_missing_pairs if partial_missing_pair_allowed and missing_pair_policy == "soft_repulsive" else []
    report.capabilities["spp_missing_pairs_regulator_fallback"] = effective_missing_pairs if partial_missing_pair_allowed and missing_pair_policy == "fallback" else []
    if missing_any:
        _add_action(report.suggested_next_actions, "Fetch or generate SPP POT files for each missing required pair.")
    return pot_root


def _check_radii(request: Dict[str, Any], report: PreflightReport, species: List[str]) -> None:
    constraints = [
        (idx, inv)
        for idx, inv in _enabled_constraints(request)
        if inv.get("id") == "proximity.atomic_radii"
    ]
    if not constraints and _objective(request).get("type") != "density_packing":
        return

    report.required_data.append(
        {
            "code": "atomic_radii",
            "category": "constraints",
            "path": "/constraints",
            "elements": species,
        }
    )
    radii, radii_path, exc = _read_radii()
    if radii is None:
        report.missing_data.append(
            DataDiagnostic(
                code="radii_data_missing",
                category="chemistry",
                message="Atomic radii data file could not be read.",
                path="/constraints",
                details={"radii_path": str(radii_path), "error": str(exc) if exc else None},
            )
        )
        _add_action(report.suggested_next_actions, "Restore or provide atomic radii data for requested proximity constraints.")
        return

    for element in species:
        if element in radii:
            report.available_data.append(
                {
                    "code": "radii_data_available",
                    "category": "chemistry",
                    "path": str(radii_path),
                    "element": element,
                }
            )
            continue
        for idx, inv in constraints or [(-1, {"id": "density_packing"})]:
            path = f"/constraints/{idx}" if idx >= 0 else "/problem/objective"
            report.missing_data.append(
                DataDiagnostic(
                    code="radii_data_missing",
                    category="chemistry",
                    message=f"Missing atomic radius data for element {element}.",
                    path=path,
                    details={
                        "element": element,
                        "formula": _formula(request),
                        "constraint_id": inv.get("id"),
                        "radii_path": str(radii_path),
                    },
                )
            )
        _add_action(report.suggested_next_actions, "Add validated atomic radius entries for every element in the formula.")


def _check_oxidation_states(request: Dict[str, Any], report: PreflightReport, species: List[str]) -> None:
    problem = request.get("problem", {}) if isinstance(request.get("problem"), dict) else {}
    chemistry = problem.get("chemistry", {}) if isinstance(problem.get("chemistry"), dict) else {}
    charge_model = chemistry.get("charge_model", "none")
    if charge_model == "none":
        return

    report.required_data.append(
        {
            "code": "oxidation_states",
            "category": "chemistry",
            "path": "/problem/chemistry/oxidation_states",
            "elements": species,
            "charge_model": charge_model,
        }
    )
    supplied = chemistry.get("oxidation_states") if isinstance(chemistry.get("oxidation_states"), dict) else {}
    missing = [element for element in species if element not in supplied]
    if not missing:
        report.available_data.append(
            {
                "code": "oxidation_states_available",
                "category": "chemistry",
                "path": "/problem/chemistry/oxidation_states",
                "elements": species,
            }
        )
        return

    for element in missing:
        report.missing_data.append(
            DataDiagnostic(
                code="oxidation_state_missing",
                category="chemistry",
                message=f"Missing oxidation state data for element {element}.",
                path="/problem/chemistry/oxidation_states",
                details={"element": element, "charge_model": charge_model, "formula": _formula(request)},
            )
        )
    _add_action(report.suggested_next_actions, "Provide oxidation_states for every formula element when charge constraints require them.")


def _check_motifs(request: Dict[str, Any], report: PreflightReport, roots: List[Path]) -> Optional[Path]:
    motif_constraints = [
        (idx, inv)
        for idx, inv in _enabled_constraints(request)
        if inv.get("id") == "motif.linking"
    ]
    if not motif_constraints:
        report.capabilities["motif_root_resolved"] = False
        return None

    report.required_data.append(
        {
            "code": "motif_artifacts",
            "category": "motifs",
            "path": "/context/motif_root",
            "artifacts": ["motifs.json", "instances.json"],
        }
    )
    context = request.get("context", {}) if isinstance(request.get("context"), dict) else {}
    motif_root_raw = context.get("motif_root")
    if motif_root_raw is None:
        motif_root_raw = _repo_root() / "gen_artifacts"

    try:
        motif_root = resolve_and_check_path(motif_root_raw, roots, must_exist=True)
    except Exception as exc:
        code = _classify_path_exception(exc, missing_code="motif_root_missing")
        report.capabilities["motif_root_resolved"] = False
        report.missing_data.append(
            DataDiagnostic(
                code=code,
                category="motifs" if code == "motif_root_missing" else "paths",
                message=str(exc),
                path="/context/motif_root",
                details=_path_details(value=motif_root_raw, roots=roots),
            )
        )
        _add_action(report.suggested_next_actions, "Provide context.motif_root containing motifs.json and instances.json.")
        return None

    missing_files = [name for name in ("motifs.json", "instances.json") if not (motif_root / name).exists()]
    if missing_files:
        report.capabilities["motif_root_resolved"] = False
        report.missing_data.append(
            DataDiagnostic(
                code="motif_artifacts_missing",
                category="motifs",
                message="Motif artifacts not found (motifs.json/instances.json).",
                path="/context/motif_root",
                details={"motif_root": str(motif_root), "missing_files": missing_files},
            )
        )
        _add_action(report.suggested_next_actions, "Generate or provide motif artifacts before enabling motif.linking.")
        return motif_root

    report.capabilities["motif_root_resolved"] = True
    report.available_data.append(
        {
            "code": "motif_artifacts_available",
            "category": "motifs",
            "path": str(motif_root),
            "artifacts": ["motifs.json", "instances.json"],
        }
    )
    return motif_root


def _check_property_tables(request: Dict[str, Any], report: PreflightReport, roots: List[Path]) -> None:
    objective = _objective(request)
    if objective.get("type") not in {"linear_property", "threshold_tradeoff"}:
        return
    prop = objective.get("property", {}) if isinstance(objective.get("property"), dict) else {}
    for key, code in (
        ("property_table_path", "property_table_missing"),
        ("table_path", "property_table_missing"),
        ("beta_table_path", "beta_table_missing"),
    ):
        if key not in prop:
            continue
        raw = prop.get(key)
        report.required_data.append(
            {"code": code, "category": "properties", "path": f"/problem/objective/property/{key}"}
        )
        try:
            resolved = resolve_and_check_path(raw, roots, must_exist=True)
            report.available_data.append(
                {"code": code.replace("_missing", "_available"), "category": "properties", "path": str(resolved)}
            )
        except Exception as exc:
            report.missing_data.append(
                DataDiagnostic(
                    code=code,
                    category="properties",
                    message=f"Declared property table path is unavailable: {exc}",
                    path=f"/problem/objective/property/{key}",
                    details=_path_details(value=raw, roots=roots),
                )
            )
            _add_action(report.suggested_next_actions, "Provide declared property or beta table files under an allowed path root.")


def run_data_preflight(request: Dict[str, Any]) -> PreflightReport:
    report = PreflightReport(ready=False)
    roots = allowed_path_roots()
    try:
        species, pairs = _formula_to_species_pairs(_formula(request))
    except Exception:
        species, pairs = [], []

    _check_solver(report)
    _check_spp(request, report, roots, species, pairs)
    _check_radii(request, report, species)
    _check_oxidation_states(request, report, species)
    _check_motifs(request, report, roots)
    _check_property_tables(request, report, roots)

    report.ready = not report.missing_data
    if report.missing_data:
        _add_action(report.suggested_next_actions, "Re-run qlip.validate_request after the missing data is available.")
    return report
