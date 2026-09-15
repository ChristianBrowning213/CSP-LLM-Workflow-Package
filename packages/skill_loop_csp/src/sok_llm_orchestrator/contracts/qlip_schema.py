from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator


QLIP_TOOLS = [
    "qlip.shapes",
    "qlip.list_constraints",
    "qlip.list_guidance",
    "qlip.validate_request",
    "qlip.solve",
]

SPP_GUIDANCE_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["spp_package_path"],
    "properties": {
        "spp_package_path": {"type": "string"},
        "pairs_policy": {"type": "string", "enum": ["task_pairs", "all_available"]},
        "oob_policy": {"type": "string", "enum": ["zero", "clamp", "max"]},
        "missing_pair_policy": {
            "type": "string",
            "enum": ["zero", "max_global", "error", "soft_repulsive"],
        },
        "lambda_override": {"type": ["number", "null"]},
        "convention_override": {"type": ["string", "null"], "enum": ["reward", "penalty", None]},
        "r_cut": {"type": ["number", "null"]},
        "top_k_breakdown": {"type": "integer", "minimum": 0},
        "weighting_profile": {
            "type": "string",
            "enum": [
                "base_dominant",
                "balanced",
                "guidance_dominant",
                "property_push_strong",
                "experimental_extreme",
            ],
        },
        "structure_perturbation_profile": {
            "type": "string",
            "enum": ["minimal", "moderate", "aggressive", "template_shuffle"],
        },
        "base_weight_scale": {"type": ["number", "null"]},
        "guidance_weight_scale": {"type": ["number", "null"]},
        "template_seed_profile": {
            "type": "string",
            "enum": ["canonical", "polymorph_mix", "framework_bias", "ordering_bias"],
        },
        "lattice_candidate_profile": {
            "type": "string",
            "enum": ["narrow", "expanded", "multibasin"],
        },
        "symmetry_relaxation_profile": {
            "type": "string",
            "enum": ["strict", "soft", "relaxed"],
        },
        "ordering_perturbation_profile": {
            "type": "string",
            "enum": ["none", "site_shuffle", "cation_swap_bias"],
        },
        "regularisation_spp_dir": {"type": "string"},
        "regularisation_weight": {"type": "number", "minimum": 0},
        "regularization_spp_dir": {"type": "string"},
        "regularization_weight": {"type": "number", "minimum": 0},
    },
}

SPP_PARTIAL_GUIDANCE_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pot_root", "mode", "supported_pairs", "missing_pairs", "missing_pair_policy", "strict_pair_coverage"],
    "properties": {
        "pot_root": {"type": "string"},
        "mode": {"type": "string", "const": "partial"},
        "supported_pairs": {"type": "array", "items": {"type": "string"}},
        "missing_pairs": {"type": "array", "items": {"type": "string"}},
        "missing_pair_policy": {"type": "string", "enum": ["neutral", "zero", "soft_repulsive", "fallback", "block"]},
        "missing_pair_penalty": {"type": "number"},
        "strict_pair_coverage": {"type": "boolean", "const": False},
        "regularisation_spp_dir": {"type": "string"},
        "regularisation_weight": {"type": "number", "minimum": 0},
        "regularization_spp_dir": {"type": "string"},
        "regularization_weight": {"type": "number", "minimum": 0},
        "cutoff": {"type": "number", "exclusiveMinimum": 0},
        "spp_cutoff": {"type": "number", "exclusiveMinimum": 0},
    },
}

SPP_GUIDANCE_CONTEXT_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {"type": "string", "enum": ["complete"]},
        "regularisation_spp_dir": {"type": "string"},
        "regularisation_weight": {"type": "number", "minimum": 0},
        "regularization_spp_dir": {"type": "string"},
        "regularization_weight": {"type": "number", "minimum": 0},
        "cutoff": {"type": "number", "exclusiveMinimum": 0},
        "spp_cutoff": {"type": "number", "exclusiveMinimum": 0},
    },
}

SPP_GUIDANCE_COMPAT_PARAMS_SCHEMA: dict[str, Any] = {
    "oneOf": [
        SPP_GUIDANCE_CONTEXT_PARAMS_SCHEMA,
        SPP_GUIDANCE_PARAMS_SCHEMA,
        SPP_PARTIAL_GUIDANCE_PARAMS_SCHEMA,
    ]
}

LINEAR_PROPERTY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["terms"],
    "properties": {
        "kind": {"type": "string", "const": "occupancy_linear"},
        "intercept": {"type": "number"},
        "terms": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["coefficient"],
                "anyOf": [{"required": ["species"]}, {"required": ["site_label"]}],
                "properties": {
                    "species": {"type": "string", "minLength": 1},
                    "site_label": {"type": "string", "minLength": 1},
                    "coefficient": {"type": "number"},
                },
            },
        },
    },
}

QLIP_OBJECTIVE_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["type"],
            "properties": {"type": {"type": "string", "const": "spp_energy"}},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["type"],
            "properties": {"type": {"type": "string", "const": "none"}},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "proxy"],
            "properties": {
                "type": {"type": "string", "const": "density_packing"},
                "proxy": {"type": "string", "const": "pair_distance_packing"},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "linear_property"],
            "properties": {
                "type": {"type": "string", "const": "linear_property"},
                "linear_property": LINEAR_PROPERTY_SCHEMA,
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "linear_property", "threshold"],
            "properties": {
                "type": {"type": "string", "const": "threshold_tradeoff"},
                "linear_property": LINEAR_PROPERTY_SCHEMA,
                "threshold": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["operator", "value"],
                    "properties": {
                        "operator": {"type": "string", "enum": [">=", "<=", "=="]},
                        "value": {"type": "number"},
                    },
                },
                "base": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type"],
                    "properties": {"type": {"type": "string", "enum": ["spp_energy", "none"]}},
                },
                "property_weight": {"type": "number"},
            },
        },
    ]
}

SOLVE_REQUEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["version", "problem", "constraints", "guidance", "solver"],
    "properties": {
        "version": {"type": "string", "const": "1.0"},
        "problem": {
            "type": "object",
            "additionalProperties": False,
            "required": ["chemistry", "design_space"],
            "properties": {
                "chemistry": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["formula"],
                    "properties": {"formula": {"type": "string"}},
                },
                "design_space": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["template", "sites"],
                    "properties": {
                        "template": {"type": "object"},
                        "template_candidates": {"type": "array"},
                        "seeding": {"type": "object"},
                        "sites": {"type": "object"},
                    },
                },
                "symmetry": {"type": "object"},
                "prototype": {"type": "object"},
                "objective": QLIP_OBJECTIVE_SCHEMA,
            },
        },
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "params"],
                "properties": {
                    "id": {"type": "string"},
                    "params": {"type": "object"},
                    "name": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "priority": {"type": "integer"},
                },
            },
        },
        "guidance": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "params"],
                "properties": {
                    "id": {"type": "string"},
                    "params": {"type": "object"},
                    "name": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "weight": {"type": "number"},
                    "level": {"type": "integer"},
                    "epsilon": {"type": "number"},
                },
            },
        },
        "guidance_mode": {"type": "string"},
        "solver": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "const": "gurobi"},
                "time_limit_s": {"type": "integer"},
                "mip_gap": {"type": "number"},
                "threads": {"type": ["integer", "null"]},
                "seed": {"type": ["integer", "null"]},
                "parameters": {"type": "object"},
            },
        },
        "artifacts": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "return_cif": {"type": "boolean"},
                "return_decoder_debug": {"type": "boolean"},
                "render_vesta": {"type": "boolean"},
                "vesta_path": {"type": ["string", "null"]},
                "supercell": {
                    "type": ["array", "null"],
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
        },
        "runtime": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "max_sites": {"type": ["integer", "null"]},
                "max_binary_vars": {"type": ["integer", "null"]},
                "max_constraints": {"type": ["integer", "null"]},
                "export_gurobi_visuals": {"type": "boolean"},
                "gurobi_visuals_dir": {"type": ["string", "null"]},
            },
        },
        "context": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "run_id": {"type": ["string", "null"]},
                "pot_root": {"type": ["string", "null"]},
                "motif_root": {"type": ["string", "null"]},
                "gurobi_visuals_dir": {"type": ["string", "null"]},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


@dataclass(slots=True)
class QLIPValidationError(ValueError):
    pointer: str
    message: str

    def __str__(self) -> str:
        return f"{self.pointer}: {self.message}"


def _pointer(path: tuple[Any, ...]) -> str:
    if not path:
        return "/"
    return "/" + "/".join(str(item) for item in path)


def validate_solve_request(
    request: dict[str, Any],
    *,
    enforce_objective_guidance_contract: bool = True,
) -> None:
    validator = Draft202012Validator(SOLVE_REQUEST_SCHEMA)
    errors = sorted(validator.iter_errors(request), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        raise QLIPValidationError(pointer=_pointer(tuple(err.absolute_path)), message=err.message)

    spp_validator = Draft202012Validator(SPP_GUIDANCE_COMPAT_PARAMS_SCHEMA)
    guidance_items = request.get("guidance", [])
    for index, item in enumerate(guidance_items):
        if item.get("id") != "objective.energy_spp":
            continue
        problem = request.get("problem") if isinstance(request.get("problem"), dict) else {}
        objective = problem.get("objective") if isinstance(problem.get("objective"), dict) else {}
        if enforce_objective_guidance_contract and objective.get("type") != "spp_energy":
            raise QLIPValidationError(
                pointer=f"/guidance/{index}",
                message="objective.energy_spp guidance requires problem.objective.type='spp_energy'",
            )
        params = item.get("params")
        if not isinstance(params, dict):
            raise QLIPValidationError(
                pointer=f"/guidance/{index}/params",
                message="must be an object",
            )
        params_errors = sorted(spp_validator.iter_errors(params), key=lambda e: list(e.absolute_path))
        if params_errors:
            err = params_errors[0]
            suffix = _pointer(tuple(err.absolute_path))
            pointer = f"/guidance/{index}/params" + ("" if suffix == "/" else suffix)
            raise QLIPValidationError(pointer=pointer, message=err.message)


def validate_qlip_objective(objective: dict[str, Any]) -> None:
    validator = Draft202012Validator(QLIP_OBJECTIVE_SCHEMA)
    errors = sorted(validator.iter_errors(objective), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        raise QLIPValidationError(pointer=_pointer(tuple(err.absolute_path)), message=err.message)
