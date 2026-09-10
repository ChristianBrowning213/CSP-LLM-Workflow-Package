from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import pyomo.environ as pyo

from qlip.constraints.proximity import AtomicRadii


SUPPORTED_OBJECTIVE_TYPES = {
    "none",
    "spp_energy",
    "density_packing",
    "linear_property",
    "threshold_tradeoff",
}

SUPPORTED_DENSITY_PACKING_PROXIES = {"pair_distance_packing"}
SUPPORTED_BASE_OBJECTIVES = {"none", "spp_energy"}
SUPPORTED_DIRECTIONS = {"minimize", "maximize"}
SUPPORTED_THRESHOLD_SENSES = {">=", "<=", "min", "max"}


@dataclass(frozen=True)
class ObjectiveValidationIssue:
    code: str
    message: str
    path: str


def _objective_type(objective: Dict[str, Any]) -> str:
    return str(objective.get("type", "spp_energy"))


def validate_objective_contract(
    objective: Dict[str, Any],
    *,
    species: Iterable[str],
    site_count: Optional[int],
    guidance: Optional[List[Dict[str, Any]]] = None,
) -> List[ObjectiveValidationIssue]:
    issues: List[ObjectiveValidationIssue] = []
    if not isinstance(objective, dict):
        return [
            ObjectiveValidationIssue(
                code="invalid_objective",
                message="problem.objective must be an object.",
                path="/problem/objective",
            )
        ]
    obj_type = _objective_type(objective)
    species_set = {str(item) for item in species}

    if obj_type not in SUPPORTED_OBJECTIVE_TYPES:
        return [
            ObjectiveValidationIssue(
                code="unsupported_objective",
                message=f"Objective type '{obj_type}' is not supported.",
                path="/problem/objective/type",
            )
        ]

    if obj_type in {"density_packing", "linear_property"}:
        direction = objective.get("direction")
        if direction not in SUPPORTED_DIRECTIONS:
            issues.append(
                ObjectiveValidationIssue(
                    code="invalid_objective",
                    message=f"Objective type '{obj_type}' requires direction to be one of {sorted(SUPPORTED_DIRECTIONS)}.",
                    path="/problem/objective/direction",
                )
            )

    if obj_type == "density_packing":
        proxy = objective.get("proxy", "pair_distance_packing")
        if proxy not in SUPPORTED_DENSITY_PACKING_PROXIES:
            issues.append(
                ObjectiveValidationIssue(
                    code="unsupported_objective_proxy",
                    message=f"density_packing proxy '{proxy}' is not supported.",
                    path="/problem/objective/proxy",
                )
            )

    if obj_type == "linear_property":
        issues.extend(
            _validate_linear_property(
                objective.get("property", {}),
                species_set=species_set,
                site_count=site_count,
                base_path="/problem/objective/property",
            )
        )

    if obj_type == "threshold_tradeoff":
        base_objective = objective.get("base_objective", "spp_energy")
        if base_objective not in SUPPORTED_BASE_OBJECTIVES:
            issues.append(
                ObjectiveValidationIssue(
                    code="unsupported_objective_base",
                    message=f"threshold_tradeoff base_objective '{base_objective}' is not supported.",
                    path="/problem/objective/base_objective",
                )
            )

        threshold = objective.get("threshold", {})
        if not isinstance(threshold, dict):
            issues.append(
                ObjectiveValidationIssue(
                    code="invalid_objective_threshold",
                    message="threshold_tradeoff threshold must be an object.",
                    path="/problem/objective/threshold",
                )
            )
            threshold = {}
        sense = threshold.get("sense")
        if sense not in SUPPORTED_THRESHOLD_SENSES:
            issues.append(
                ObjectiveValidationIssue(
                    code="invalid_objective_threshold",
                    message="threshold_tradeoff requires threshold.sense to be one of ['>=', '<=', 'min', 'max'].",
                    path="/problem/objective/threshold/sense",
                )
            )

        if "value" not in threshold:
            issues.append(
                ObjectiveValidationIssue(
                    code="invalid_objective_threshold",
                    message="threshold_tradeoff requires threshold.value.",
                    path="/problem/objective/threshold/value",
                )
            )

        try:
            weight = float(objective.get("tradeoff_weight", 0.0))
        except Exception:
            weight = -1.0
        if weight < 0:
            issues.append(
                ObjectiveValidationIssue(
                    code="invalid_objective",
                    message="threshold_tradeoff tradeoff_weight must be non-negative.",
                    path="/problem/objective/tradeoff_weight",
                )
            )
        if weight > 0 and objective.get("tradeoff_direction") not in SUPPORTED_DIRECTIONS:
            issues.append(
                ObjectiveValidationIssue(
                    code="invalid_objective",
                    message="threshold_tradeoff requires tradeoff_direction when tradeoff_weight is non-zero.",
                    path="/problem/objective/tradeoff_direction",
                )
            )

        issues.extend(
            _validate_linear_property(
                objective.get("property", {}),
                species_set=species_set,
                site_count=site_count,
                base_path="/problem/objective/property",
            )
        )

    guidance = guidance or []
    if obj_type != "spp_energy" and any(
        inv.get("enabled", True) and inv.get("id") == "objective.energy_spp"
        for inv in guidance
    ):
        issues.append(
            ObjectiveValidationIssue(
                code="invalid_objective_guidance_mix",
                message=(
                    "guidance id 'objective.energy_spp' can only be combined with "
                    "problem.objective.type='spp_energy'."
                ),
                path="/guidance",
            )
        )

    return issues


def _validate_linear_property(
    spec: Any,
    *,
    species_set: set[str],
    site_count: Optional[int],
    base_path: str,
) -> List[ObjectiveValidationIssue]:
    issues: List[ObjectiveValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ObjectiveValidationIssue(
                code="invalid_linear_property",
                message="linear property spec must be an object.",
                path=base_path,
            )
        ]

    terms = spec.get("terms")
    if not isinstance(terms, list) or not terms:
        return [
            ObjectiveValidationIssue(
                code="invalid_linear_property",
                message="linear property spec requires a non-empty terms array.",
                path=f"{base_path}/terms",
            )
        ]

    for idx, term in enumerate(terms):
        path = f"{base_path}/terms/{idx}"
        if not isinstance(term, dict):
            issues.append(
                ObjectiveValidationIssue(
                    code="invalid_linear_property_term",
                    message="linear property term must be an object.",
                    path=path,
                )
            )
            continue

        if "coefficient" not in term:
            issues.append(
                ObjectiveValidationIssue(
                    code="invalid_linear_property_term",
                    message="linear property term requires coefficient.",
                    path=f"{path}/coefficient",
                )
            )

        if "species" not in term and "site" not in term:
            issues.append(
                ObjectiveValidationIssue(
                    code="invalid_linear_property_term",
                    message="linear property term must specify species, site, or both.",
                    path=path,
                )
            )

        species = term.get("species")
        if species is not None and str(species) not in species_set:
            issues.append(
                ObjectiveValidationIssue(
                    code="unknown_objective_species",
                    message=f"linear property term references unknown species '{species}'.",
                    path=f"{path}/species",
                )
            )

        site = term.get("site")
        if site is not None and site_count is not None:
            try:
                site_int = int(site)
            except Exception:
                site_int = -1
            if site_int < 0 or site_int >= site_count:
                issues.append(
                    ObjectiveValidationIssue(
                        code="objective_site_out_of_range",
                        message=f"linear property term site {site} is outside 0..{site_count - 1}.",
                        path=f"{path}/site",
                    )
                )

    return issues


def apply_objective_contract(allocation, objective: Dict[str, Any]) -> str:
    obj_type = _objective_type(objective)
    base_expr = _active_objective_expr(allocation.m)

    if obj_type == "spp_energy":
        return obj_type

    if obj_type == "none":
        _replace_objective(allocation.m, 0.0)
        return obj_type

    if obj_type == "density_packing":
        expr = _density_packing_expr(allocation)
        if objective.get("direction") == "maximize":
            expr = -expr
        _replace_objective(allocation.m, expr)
        return obj_type

    if obj_type == "linear_property":
        prop_expr = _linear_property_expr(allocation, objective["property"])
        expr = prop_expr
        if objective.get("direction") == "maximize":
            expr = -expr
        _replace_objective(allocation.m, expr)
        setattr(
            allocation.m,
            "qprop_" + _safe_name(objective["property"].get("name", "linear_property")),
            pyo.Expression(expr=prop_expr),
        )
        return obj_type

    if obj_type == "threshold_tradeoff":
        prop_expr = _linear_property_expr(allocation, objective["property"])
        prop_name = _safe_name(objective["property"].get("name", "threshold_property"))
        setattr(allocation.m, "qprop_" + prop_name, pyo.Expression(expr=prop_expr))
        _attach_threshold_constraint(allocation.m, prop_expr, objective["threshold"])

        base_objective = objective.get("base_objective", "spp_energy")
        expr = base_expr if base_objective == "spp_energy" else 0.0
        weight = float(objective.get("tradeoff_weight", 0.0))
        if weight:
            if objective.get("tradeoff_direction") == "maximize":
                expr = expr - weight * prop_expr
            else:
                expr = expr + weight * prop_expr
        _replace_objective(allocation.m, expr)
        return obj_type

    raise ValueError(f"Objective type '{obj_type}' is not supported.")


def _active_objective_expr(model):
    objs = list(model.component_objects(pyo.Objective, active=True))
    if not objs:
        return 0.0
    return objs[0].expr


def _replace_objective(model, expr) -> None:
    for obj in list(model.component_objects(pyo.Objective, active=True)):
        model.del_component(obj)
    model.obj = pyo.Objective(expr=expr, sense=pyo.minimize)


def _density_packing_expr(allocation):
    radii = AtomicRadii().rad
    terms = []
    site_count = len(allocation.positions)
    for i in range(site_count):
        for j in range(i + 1, site_count):
            dist = float(allocation._dist[i, j])
            if dist <= 1e-12:
                continue
            for t1, t2 in allocation.pairs:
                radius_sum = float(radii[t1]) + float(radii[t2])
                coeff = radius_sum / dist
                terms.append(coeff * allocation.m.x[t1, i] * allocation.m.x[t2, j])
                if t1 != t2:
                    terms.append(coeff * allocation.m.x[t2, i] * allocation.m.x[t1, j])
    return pyo.quicksum(terms) if terms else 0.0


def _linear_property_expr(allocation, spec: Dict[str, Any]):
    expr = float(spec.get("offset", 0.0))
    for term in spec.get("terms", []):
        coeff = float(term["coefficient"])
        species = term.get("species")
        site = term.get("site")
        if species is not None and site is not None:
            expr = expr + coeff * allocation.m.x[str(species), int(site)]
        elif species is not None:
            expr = expr + coeff * pyo.quicksum(allocation.m.x[str(species), i] for i in allocation.m.Pos)
        elif site is not None:
            expr = expr + coeff * pyo.quicksum(allocation.m.x[t, int(site)] for t in allocation.m.Types)
    return expr


def _attach_threshold_constraint(model, expr, threshold: Dict[str, Any]) -> None:
    if hasattr(model, "qlip_threshold_tradeoff_bound"):
        model.del_component(model.qlip_threshold_tradeoff_bound)
    sense = threshold["sense"]
    value = float(threshold["value"])
    if sense in {">=", "min"}:
        model.qlip_threshold_tradeoff_bound = pyo.Constraint(expr=expr >= value)
    elif sense in {"<=", "max"}:
        model.qlip_threshold_tradeoff_bound = pyo.Constraint(expr=expr <= value)
    else:
        raise ValueError(f"Unsupported threshold sense '{sense}'.")


def _safe_name(name: Any) -> str:
    raw = str(name or "property")
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw)
    return cleaned or "property"
