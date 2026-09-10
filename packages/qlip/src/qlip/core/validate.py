from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pyomo.environ as pyo
from ase import Atoms

from qlip.allocation import Allocation
from qlip.plugins.registry import ConstraintRegistry, GuidanceRegistry
from qlip.core.models import ValidationIssue, ValidationReport
from qlip.core.objectives import validate_objective_contract
from qlip.core.paths import allowed_path_roots, resolve_and_check_path
from qlip.core import preflight as data_preflight
from qlip.core.chemistry import preflight_charge
from qlip.resources import schema_path
from qlip.scaffolds.occupation import VACANCY_STATE, preflight_ordered_occupation


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _schema_bundle() -> Dict[str, Any]:
    return json.loads(schema_path("MCP_SCHEMA.json").read_text(encoding="utf-8"))


_SCHEMAS = _schema_bundle()


def _solve_request_schema() -> Dict[str, Any]:
    return _SCHEMAS["solve_request"]


def _normalize_request(raw: Dict[str, Any]) -> Dict[str, Any]:
    req = copy.deepcopy(raw)
    req.setdefault("constraints", [])
    req.setdefault("guidance", [])
    req.setdefault("guidance_mode", "weighted_sum")
    req.setdefault("artifacts", {})
    req.setdefault("runtime", {})
    req.setdefault("context", {})

    problem = req.get("problem", {})
    objective = problem.get("objective")
    if not objective:
        problem["objective"] = {"type": "spp_energy"}
        req["problem"] = problem

    for inv in req.get("constraints", []):
        inv.setdefault("enabled", True)
        inv.setdefault("priority", 100)
        inv.setdefault("params", {})

    for inv in req.get("guidance", []):
        inv.setdefault("enabled", True)
        inv.setdefault("weight", 1.0)
        inv.setdefault("level", 0)
        inv.setdefault("epsilon", 0.0)
        inv.setdefault("params", {})

    return req


def _json_path(base: str, parts: Iterable[Any]) -> str:
    suffix = "/".join(str(p) for p in parts)
    return f"{base}/{suffix}" if suffix else base


def _append_issue(
    errors: List[ValidationIssue],
    warnings: List[ValidationIssue],
    strict: bool,
    issue: ValidationIssue,
) -> None:
    if strict:
        errors.append(issue)
    else:
        warnings.append(issue)


def _is_required_property_error(err: Any) -> Optional[str]:
    if getattr(err, "validator", None) != "required":
        return None
    message = getattr(err, "message", "")
    if not isinstance(message, str):
        return None
    marker = "' is a required property"
    if marker not in message:
        return None
    return message.split("'", 2)[1]


def _path_issue(
    code: str,
    message: str,
    path: str,
    *,
    value: Any = None,
    roots: Iterable[Path] = (),
    extra: Optional[Dict[str, Any]] = None,
) -> ValidationIssue:
    details: Dict[str, Any] = {
        "allowed_roots": [str(Path(root).expanduser().resolve()) for root in roots],
    }
    if value is not None:
        details["value"] = str(value)
    if extra:
        details.update(extra)
    return ValidationIssue(code=code, message=message, path=path, details=details)


def _classify_path_exception(exc: Exception, *, missing_code: str = "path_missing") -> str:
    text = str(exc)
    if "does not exist" in text:
        return missing_code
    if "not in allowed roots" in text:
        return "path_outside_allowed_roots"
    return "path_invalid"


def _data_issue_to_validation_issue(item: Dict[str, Any]) -> ValidationIssue:
    return ValidationIssue(
        code=str(item.get("code", "solve_data_preflight_failed")),
        message=str(item.get("message", "Required runtime data is missing.")),
        path=str(item.get("path", "")),
        details=dict(item.get("details", {}) or {}),
    )


def _formula_to_pairs(formula: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    atoms = Atoms(symbols=formula)
    alloc = Allocation(atoms)
    return alloc.types, alloc.pairs


def _site_count(design_space: Dict[str, Any]) -> Optional[int]:
    sites = design_space.get("sites", {})
    mode = sites.get("mode")
    if mode == "uniform_grid":
        density = sites.get("uniform_grid", {}).get("density")
        if isinstance(density, int) and density > 0:
            return density * density * density
        return None
    if mode == "explicit_fractional_sites":
        pts = sites.get("explicit_fractional_sites")
        if isinstance(pts, list):
            return len(pts)
    return None


def _design_space_issues(
    design_space: Dict[str, Any],
    species: Optional[Iterable[str]] = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    template = design_space.get("template") if isinstance(design_space.get("template"), dict) else {}
    lattice = template.get("lattice") if isinstance(template.get("lattice"), dict) else {}
    sites = design_space.get("sites") if isinstance(design_space.get("sites"), dict) else {}
    if not template:
        issues.append(
            ValidationIssue(
                code="lattice_template_missing",
                message="problem.design_space.template is required for solving.",
                path="/problem/design_space/template",
            )
        )
    elif not lattice:
        issues.append(
            ValidationIssue(
                code="lattice_template_missing",
                message="problem.design_space.template.lattice is required for solving.",
                path="/problem/design_space/template/lattice",
            )
        )
    else:
        invalid_lengths = [key for key in ("a", "b", "c") if float(lattice.get(key, 0) or 0) <= 0]
        invalid_angles = [key for key in ("alpha", "beta", "gamma") if float(lattice.get(key, 0) or 0) <= 0]
        if invalid_lengths or invalid_angles:
            issues.append(
                ValidationIssue(
                    code="lattice_bounds_invalid",
                    message="Lattice lengths and angles must be positive.",
                    path="/problem/design_space/template/lattice",
                    details={"invalid_lengths": invalid_lengths, "invalid_angles": invalid_angles},
                )
            )
    if not sites:
        issues.append(
            ValidationIssue(
                code="candidate_sites_missing",
                message="problem.design_space.sites is required for solving.",
                path="/problem/design_space/sites",
            )
        )
    elif sites.get("mode") == "uniform_grid":
        spec = sites.get("uniform_grid") if isinstance(sites.get("uniform_grid"), dict) else {}
        density = spec.get("density")
        if not isinstance(density, int) or density <= 0:
            issues.append(
                ValidationIssue(
                    code="candidate_sites_empty",
                    message="uniform_grid.density must be a positive integer.",
                    path="/problem/design_space/sites/uniform_grid/density",
                )
            )
    elif sites.get("mode") == "explicit_fractional_sites":
        pts = sites.get("explicit_fractional_sites")
        if not isinstance(pts, list):
            issues.append(
                ValidationIssue(
                    code="candidate_sites_missing",
                    message="explicit_fractional_sites must be provided for explicit site mode.",
                    path="/problem/design_space/sites/explicit_fractional_sites",
                )
            )
        elif len(pts) == 0:
            issues.append(
                ValidationIssue(
                    code="candidate_sites_empty",
                    message="explicit_fractional_sites cannot be empty.",
                    path="/problem/design_space/sites/explicit_fractional_sites",
                )
            )
        orbits = sites.get("ordered_orbits", [])
        if isinstance(orbits, list) and isinstance(pts, list):
            known_species = set(species or [])
            claimed_sites: Dict[int, str] = {}
            orbit_ids: set[str] = set()
            for orbit_idx, orbit in enumerate(orbits):
                if not isinstance(orbit, dict):
                    continue
                base = f"/problem/design_space/sites/ordered_orbits/{orbit_idx}"
                orbit_id = str(orbit.get("orbit_id", ""))
                if orbit_id in orbit_ids:
                    issues.append(ValidationIssue(
                        code="ordered_orbit_id_duplicate",
                        message=f"ordered orbit id '{orbit_id}' is duplicated.",
                        path=f"{base}/orbit_id",
                    ))
                orbit_ids.add(orbit_id)
                for atom_type in orbit.get("allowed_species", []):
                    if known_species and atom_type != VACANCY_STATE and atom_type not in known_species:
                        issues.append(ValidationIssue(
                            code="ordered_orbit_species_unknown",
                            message=f"Species '{atom_type}' is not present in the requested formula.",
                            path=f"{base}/allowed_species",
                        ))
                fixed_species = orbit.get("fixed_species")
                if fixed_species and fixed_species not in orbit.get("allowed_species", []):
                    issues.append(ValidationIssue(
                        code="ordered_orbit_fixed_species_not_allowed",
                        message=f"Fixed species '{fixed_species}' is absent from the orbit allowlist.",
                        path=f"{base}/fixed_species",
                    ))
                if fixed_species and known_species and fixed_species not in known_species:
                    issues.append(ValidationIssue(
                        code="ordered_orbit_fixed_species_unknown",
                        message=f"Fixed species '{fixed_species}' is not present in the requested formula.",
                        path=f"{base}/fixed_species",
                    ))
                if str(orbit.get("required_state", "AUTO")).upper() == "EMPTY" and not (
                    orbit.get("vacancy_allowed", False) or VACANCY_STATE in orbit.get("allowed_species", [])
                ):
                    issues.append(ValidationIssue(
                        code="ordered_orbit_empty_state_without_vacancy",
                        message="An EMPTY orbit must explicitly allow vacancy.",
                        path=f"{base}/required_state",
                    ))
                for site_idx in orbit.get("site_indices", []):
                    if not isinstance(site_idx, int) or site_idx < 0 or site_idx >= len(pts):
                        issues.append(ValidationIssue(
                            code="ordered_orbit_site_out_of_range",
                            message=f"Site index {site_idx!r} is outside the explicit site domain.",
                            path=f"{base}/site_indices",
                            details={"site_count": len(pts)},
                        ))
                    elif site_idx in claimed_sites:
                        issues.append(ValidationIssue(
                            code="ordered_orbit_site_overlap",
                            message=f"Site index {site_idx} is already assigned to orbit '{claimed_sites[site_idx]}'.",
                            path=f"{base}/site_indices",
                        ))
                    else:
                        claimed_sites[site_idx] = orbit_id
            vacancy_count = sites.get("vacancy_count", 0)
            if isinstance(vacancy_count, int) and vacancy_count > len(pts):
                issues.append(ValidationIssue(
                    code="ordered_orbit_vacancy_count_out_of_range",
                    message="vacancy_count cannot exceed the candidate-site count.",
                    path="/problem/design_space/sites/vacancy_count",
                ))
    return issues


def validate_request(request: Dict[str, Any], strict: bool = True) -> ValidationReport:
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []
    missing_fields: List[str] = []
    invalid_guidance_params: List[Dict[str, Any]] = []
    path_diagnostics: List[Dict[str, Any]] = []

    try:
        from jsonschema import Draft202012Validator
    except Exception as exc:
        errors.append(
            ValidationIssue(
                code="validator_unavailable",
                message=f"jsonschema is required for validation: {exc}",
                path="",
            )
        )
        return ValidationReport(valid=False, errors=errors, warnings=warnings)

    normalized = _normalize_request(request)
    validator = Draft202012Validator(_solve_request_schema())
    for err in sorted(validator.iter_errors(normalized), key=str):
        missing = _is_required_property_error(err)
        path = _json_path("", err.path)
        if missing:
            path = f"{path}/{missing}" if path else f"/{missing}"
            missing_fields.append(path)
        errors.append(
            ValidationIssue(
                code="schema_validation_error",
                message=err.message,
                path=path,
                details={"schema_path": list(err.schema_path)},
            )
        )

    problem = normalized.get("problem", {})
    objective = problem.get("objective", {}) if isinstance(problem, dict) else {}
    design_space = problem.get("design_space", {}) if isinstance(problem, dict) else {}
    chemistry = problem.get("chemistry", {}) if isinstance(problem, dict) else {}
    try:
        charge = preflight_charge(chemistry)
        if not charge.accepted:
            _append_issue(
                errors,
                warnings,
                strict,
                ValidationIssue(
                    code="explicit_chemistry_rejected",
                    message=charge.rejection_reason or "Explicit chemistry preflight failed.",
                    path="/problem/chemistry",
                    details=charge.to_dict(),
                ),
            )
    except Exception as exc:
        _append_issue(
            errors,
            warnings,
            strict,
            ValidationIssue(
                code="explicit_chemistry_error",
                message=str(exc),
                path="/problem/chemistry",
            ),
        )
    site_count = _site_count(design_space)
    try:
        types, _ = _formula_to_pairs(problem.get("chemistry", {}).get("formula", ""))
    except Exception:
        types = []
    for issue in _design_space_issues(design_space, types):
        _append_issue(errors, warnings, strict, issue)
    sites = design_space.get("sites", {}) if isinstance(design_space, dict) else {}
    ordered_orbits = sites.get("ordered_orbits", []) if isinstance(sites, dict) else []
    ordered_errors = {
        issue.code for issue in errors
        if issue.code.startswith("ordered_orbit") or issue.code.startswith("candidate_sites")
    }
    if site_count is not None and ordered_orbits and not ordered_errors:
        try:
            occupation = preflight_ordered_occupation(
                str(problem.get("chemistry", {}).get("formula", "")),
                site_count,
                ordered_orbits,
                vacancy_count=int(sites.get("vacancy_count", 0) or 0),
            )
            if not occupation.stoichiometry_representable:
                _append_issue(
                    errors,
                    warnings,
                    strict,
                    ValidationIssue(
                        code="ordered_orbit_stoichiometry_not_representable",
                        message=occupation.rejection_reason or "Ordered-orbit stoichiometry is not representable.",
                        path="/problem/design_space/sites/ordered_orbits",
                        details=occupation.to_dict(),
                    ),
                )
        except Exception as exc:
            _append_issue(
                errors,
                warnings,
                strict,
                ValidationIssue(
                    code="ordered_orbit_preflight_error",
                    message=str(exc),
                    path="/problem/design_space/sites/ordered_orbits",
                ),
            )

    for issue in validate_objective_contract(
        objective,
        species=types,
        site_count=site_count,
        guidance=normalized.get("guidance", []),
    ):
        errors.append(
            ValidationIssue(
                code=issue.code,
                message=issue.message,
                path=issue.path,
            )
        )

    guidance_mode = normalized.get("guidance_mode", "weighted_sum")
    if guidance_mode not in {"weighted_sum"}:
        errors.append(
            ValidationIssue(
                code="unsupported_guidance_mode",
                message=f"Guidance mode '{guidance_mode}' is not supported.",
                path="/guidance_mode",
            )
        )

    # Plugin validation
    for idx, inv in enumerate(normalized.get("constraints", [])):
        if not inv.get("enabled", True):
            continue
        plugin = ConstraintRegistry.get(inv.get("id", ""))
        if plugin is None:
            _append_issue(
                errors,
                warnings,
                strict,
                ValidationIssue(
                    code="unknown_constraint_id",
                    message=f"Unknown constraint id '{inv.get('id')}'.",
                    path=f"/constraints/{idx}/id",
                ),
            )
            continue
        for err in Draft202012Validator(plugin.params_schema).iter_errors(inv.get("params", {})):
            _append_issue(
                errors,
                warnings,
                strict,
                ValidationIssue(
                    code="invalid_constraint_params",
                    message=err.message,
                    path=_json_path(f"/constraints/{idx}/params", err.path),
                    details={"schema_path": list(err.schema_path)},
                ),
            )

    for idx, inv in enumerate(normalized.get("guidance", [])):
        if not inv.get("enabled", True):
            continue
        plugin = GuidanceRegistry.get(inv.get("id", ""))
        if plugin is None:
            _append_issue(
                errors,
                warnings,
                strict,
                ValidationIssue(
                    code="unknown_guidance_id",
                    message=f"Unknown guidance id '{inv.get('id')}'.",
                    path=f"/guidance/{idx}/id",
                ),
            )
            continue
        for err in Draft202012Validator(plugin.params_schema).iter_errors(inv.get("params", {})):
            missing = _is_required_property_error(err)
            path = _json_path(f"/guidance/{idx}/params", err.path)
            if missing:
                path = f"{path}/{missing}" if path else f"/guidance/{idx}/params/{missing}"
            offending_keys = sorted((inv.get("params") or {}).keys()) if isinstance(inv.get("params"), dict) else []
            invalid_guidance_params.append(
                {
                    "index": idx,
                    "id": inv.get("id"),
                    "path": path,
                    "message": err.message,
                    "offending_keys": offending_keys,
                    "schema_path": list(err.schema_path),
                }
            )
            _append_issue(
                errors,
                warnings,
                strict,
                ValidationIssue(
                    code="invalid_guidance_params",
                    message=err.message,
                    path=path,
                    details={
                        "schema_path": list(err.schema_path),
                        "offending_keys": offending_keys,
                        "guidance_id": inv.get("id"),
                    },
                ),
            )

    context = normalized.get("context", {}) if isinstance(normalized.get("context"), dict) else {}
    roots = allowed_path_roots()
    data_preflight.pyo.SolverFactory = pyo.SolverFactory
    preflight = data_preflight.run_data_preflight(normalized)
    data_diagnostics = preflight.to_dict()
    missing_data = data_diagnostics["missing_data"]
    available_data = data_diagnostics["available_data"]
    required_data = data_diagnostics["required_data"]
    suggested_next_actions = data_diagnostics["suggested_next_actions"]
    for item in missing_data:
        issue = _data_issue_to_validation_issue(item)
        if issue.path.startswith("/context/"):
            path_diagnostics.append(issue.to_dict())
        _append_issue(errors, warnings, strict, issue)

    if missing_data:
        _append_issue(
            errors,
            warnings,
            strict,
            ValidationIssue(
                code="solve_data_preflight_failed",
                message="Required runtime data is missing for the requested objective, guidance, or constraints.",
                path="/",
                details={"missing_codes": sorted({str(item.get("code")) for item in missing_data})},
            ),
        )

    pot_root = context.get("pot_root")
    if pot_root:
        try:
            normalized.setdefault("context", {})["pot_root"] = str(
                resolve_and_check_path(pot_root, roots, must_exist=True)
            )
        except Exception:
            pass

    motif_needed = any(
        inv.get("enabled", True) and inv.get("id") == "motif.linking"
        for inv in normalized.get("constraints", [])
    )
    if motif_needed:
        motif_root = context.get("motif_root")
        if motif_root is None:
            motif_root = _repo_root() / "gen_artifacts"
        try:
            motif_root = resolve_and_check_path(motif_root, roots, must_exist=True)
            normalized.setdefault("context", {})["motif_root"] = str(motif_root)
        except Exception as exc:
            code = _classify_path_exception(exc, missing_code="motif_root_missing")
            issue = _path_issue(code, str(exc), "/context/motif_root", value=motif_root, roots=roots)
            path_diagnostics.append(issue.to_dict())
            motif_root = None

    for idx, inv in enumerate(normalized.get("constraints", [])):
        if inv.get("id") == "motif.linking":
            motif_dir = inv.get("params", {}).get("motif_dir")
            if motif_dir:
                try:
                    resolved = resolve_and_check_path(motif_dir, roots, must_exist=True)
                    inv.setdefault("params", {})["motif_dir"] = str(resolved)
                except Exception as exc:
                    code = _classify_path_exception(exc, missing_code="motif_dir_missing")
                    issue = _path_issue(
                        code,
                        str(exc),
                        f"/constraints/{idx}/params/motif_dir",
                        value=motif_dir,
                        roots=roots,
                    )
                    path_diagnostics.append(issue.to_dict())
                    _append_issue(
                        errors,
                        warnings,
                        strict,
                        issue,
                    )

    artifacts = normalized.get("artifacts", {}) if isinstance(normalized.get("artifacts"), dict) else {}
    vesta_path = artifacts.get("vesta_path")
    if vesta_path:
        try:
            resolved_vesta = resolve_and_check_path(vesta_path, roots, must_exist=True)
            normalized.setdefault("artifacts", {})["vesta_path"] = str(resolved_vesta)
        except Exception as exc:
            code = _classify_path_exception(exc, missing_code="artifact_path_missing")
            issue = _path_issue(code, str(exc), "/artifacts/vesta_path", value=vesta_path, roots=roots)
            path_diagnostics.append(issue.to_dict())
            _append_issue(errors, warnings, strict, issue)

    # Runtime limits
    runtime = normalized.get("runtime", {}) if isinstance(normalized.get("runtime"), dict) else {}
    runtime_site_count = site_count or 0
    if runtime.get("max_sites") and runtime_site_count > int(runtime["max_sites"]):
        _append_issue(
            errors,
            warnings,
            strict,
            ValidationIssue(
                code="runtime_limit_exceeded",
                message=f"site_count {runtime_site_count} exceeds max_sites {runtime['max_sites']}",
                path="/runtime/max_sites",
            ),
        )

    if runtime.get("max_binary_vars"):
        try:
            types, _ = _formula_to_pairs(problem.get("chemistry", {}).get("formula", ""))
            binaries = runtime_site_count * len(types)
            if binaries > int(runtime["max_binary_vars"]):
                _append_issue(
                    errors,
                    warnings,
                    strict,
                    ValidationIssue(
                        code="runtime_limit_exceeded",
                        message=f"binary_vars {binaries} exceeds max_binary_vars {runtime['max_binary_vars']}",
                        path="/runtime/max_binary_vars",
                    ),
                )
        except Exception:
            pass

    is_valid = len(errors) == 0
    report = ValidationReport(
        valid=is_valid,
        errors=errors,
        warnings=warnings,
        normalized_request=normalized if is_valid else None,
        capabilities={
            "gurobi_available": bool(preflight.capabilities.get("gurobi_available", False)),
            "pot_root_resolved": bool(preflight.capabilities.get("pot_root_resolved", False)),
            "motif_root_resolved": bool(preflight.capabilities.get("motif_root_resolved", False)),
            "spp_partial_guidance": preflight.capabilities.get("spp_partial_guidance", {"enabled": False}),
            "spp_supported_pairs_used": preflight.capabilities.get("spp_supported_pairs_used", []),
            "spp_missing_pairs_unguided": preflight.capabilities.get("spp_missing_pairs_unguided", []),
            "spp_missing_pairs_soft_repulsive": preflight.capabilities.get("spp_missing_pairs_soft_repulsive", []),
            "spp_regularisation": preflight.capabilities.get(
                "spp_regularisation",
                {
                    "enabled": False,
                    "regularisation_spp_dir": None,
                    "regularisation_weight": 0.0,
                    "regularisation_pairs_loaded": 0,
                    "load_errors": [],
                },
            ),
        },
        missing_fields=sorted(set(missing_fields)),
        invalid_guidance_params=invalid_guidance_params,
        path_diagnostics=path_diagnostics,
        data_diagnostics=data_diagnostics,
        missing_data=missing_data,
        available_data=available_data,
        required_data=required_data,
        suggested_next_actions=suggested_next_actions,
    )
    return report
