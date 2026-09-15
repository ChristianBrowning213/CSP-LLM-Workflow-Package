from __future__ import annotations

import os
import re
from typing import Any, Mapping


_FORMULA_TOKEN_RE = re.compile(r"^(?:[A-Z][a-z]?\d*)+$")
_FORMULA_FRAGMENT_RE = re.compile(r"[A-Z][a-z]?(?:[A-Z][a-z]?|\d)+")
_STOP_TOKENS = {
    "Build",
    "Make",
    "Generate",
    "Find",
    "Create",
    "Design",
    "Optimize",
    "Produce",
    "Candidate",
    "Structure",
}


class MaterialSystemError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def infer_formula(query: str) -> str:
    tokens = [tok.strip(",.;:") for tok in query.split() if tok.strip(",.;:")]
    for token in tokens:
        if _FORMULA_TOKEN_RE.fullmatch(token):
            return token
    for token in tokens:
        for match in _FORMULA_FRAGMENT_RE.finditer(token):
            fragment = match.group(0)
            if _FORMULA_TOKEN_RE.fullmatch(fragment):
                return fragment
    for token in tokens:
        if token not in _STOP_TOKENS and any(ch.isupper() for ch in token):
            return token
    return "UNKNOWN"


def _string_value(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else ""


def resolve_formula(
    query: str,
    *,
    material_system: str | None = None,
    qlip_package: Mapping[str, Any] | None = None,
    formula: str | None = None,
) -> str:
    package = qlip_package if isinstance(qlip_package, Mapping) else {}
    candidates = [
        material_system.strip() if isinstance(material_system, str) and material_system.strip() else "",
        _string_value(package, "material_system"),
        _string_value(package, "formula"),
        formula.strip() if isinstance(formula, str) and formula.strip() else "",
    ]
    for candidate in candidates:
        resolved = infer_formula(candidate)
        if resolved != "UNKNOWN":
            if resolved == "ABO3":
                raise MaterialSystemError(
                    "non_concrete_formula",
                    "ABO3 is a prototype pattern, not a concrete formula. Provide a concrete composition such as CaTiO3.",
                )
            return resolved
    inferred = infer_formula(query) if isinstance(query, str) and query.strip() else "UNKNOWN"
    if inferred == "ABO3":
        raise MaterialSystemError(
            "non_concrete_formula",
            "ABO3 is a prototype pattern, not a concrete formula. Provide a concrete composition such as CaTiO3.",
        )
    if inferred == "UNKNOWN":
        raise MaterialSystemError(
            "material_system_missing",
            "Cannot build QLIP request without a concrete material system/formula.",
        )
    return inferred


def build_solve_request(
    query: str,
    spp_package_path: str | None = None,
    pot_root: str | None = None,
    *,
    material_system: str | None = None,
    qlip_package: Mapping[str, Any] | None = None,
    formula: str | None = None,
    partial_spp_guidance: Mapping[str, Any] | None = None,
    spp_guidance_weight: float | None = None,
    spp_regularisation_dir: str | None = None,
    spp_regularisation_weight: float | None = None,
) -> dict:
    resolved_formula = resolve_formula(
        query,
        material_system=material_system,
        qlip_package=qlip_package,
        formula=formula,
    )
    guidance: list[dict[str, object]] = []
    guidance_weight = 1.0 if spp_guidance_weight is None else float(spp_guidance_weight)
    regularisation_weight = 0.0 if spp_regularisation_weight is None else float(spp_regularisation_weight)
    partial = partial_spp_guidance if isinstance(partial_spp_guidance, Mapping) else {}
    regularisation_dir = spp_regularisation_dir
    if partial and not regularisation_dir:
        regularisation_dir = partial.get("regularisation_spp_dir") or partial.get("regularization_spp_dir")
    if partial and spp_regularisation_weight is None:
        raw_regularisation_weight = partial.get("regularisation_weight", partial.get("regularization_weight", 0.0))
        regularisation_weight = float(raw_regularisation_weight or 0.0)

    def _with_regularisation(params: dict[str, object]) -> dict[str, object]:
        if regularisation_dir:
            params["regularisation_spp_dir"] = str(regularisation_dir)
        if regularisation_weight:
            params["regularisation_weight"] = regularisation_weight
        return params

    if partial:
        guidance.append(
            {
                "id": "objective.energy_spp",
                "weight": guidance_weight,
                "params": _with_regularisation({
                    "pot_root": str(partial.get("pot_root") or ""),
                    "mode": "partial",
                    "supported_pairs": list(partial.get("supported_pairs", [])),
                    "missing_pairs": list(partial.get("missing_pairs", [])),
                    "missing_pair_policy": str(partial.get("missing_pair_policy") or "neutral"),
                    "missing_pair_penalty": float(partial.get("missing_pair_penalty", 0.0)),
                    "strict_pair_coverage": False,
                }),
            }
        )
    elif pot_root:
        guidance.append({"id": "objective.energy_spp", "weight": guidance_weight, "params": _with_regularisation({})})
    elif spp_package_path:
        guidance.append(
            {
                "id": "objective.energy_spp",
                "weight": guidance_weight,
                "params": {
                    "spp_package_path": spp_package_path,
                    "pairs_policy": "task_pairs",
                    "oob_policy": "max",
                    "missing_pair_policy": "max_global",
                    "top_k_breakdown": 10,
                },
            }
        )
    lattice = {
        "a": 4.6,
        "b": 4.6,
        "c": 3.0,
        "alpha": 90.0,
        "beta": 90.0,
        "gamma": 90.0,
        "units": "angstrom",
    }
    if os.environ.get("SKILL_LOOP_FORCE_CUBIC_LATTICE_TEMPLATE", "").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            cubic_a = float(os.environ.get("SKILL_LOOP_CUBIC_LATTICE_A", "4.6"))
        except ValueError:
            cubic_a = 4.6
        lattice = {
            "a": cubic_a,
            "b": cubic_a,
            "c": cubic_a,
            "alpha": 90.0,
            "beta": 90.0,
            "gamma": 90.0,
            "units": "angstrom",
        }
    request = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": resolved_formula},
            "design_space": {
                "template": {"lattice": lattice},
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}},
            },
        },
        "constraints": [],
        "guidance": guidance,
        "solver": {"name": "gurobi"},
    }
    if guidance:
        request["problem"]["objective"] = {"type": "spp_energy"}
    if partial and partial.get("pot_root"):
        request["context"] = {"pot_root": str(partial.get("pot_root"))}
    elif pot_root:
        request["context"] = {"pot_root": pot_root}
    return request
