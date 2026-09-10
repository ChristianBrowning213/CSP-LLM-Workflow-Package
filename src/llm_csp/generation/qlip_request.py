"""Compile workflow state onto packaged QLIP's strict request contract."""

from __future__ import annotations

from copy import deepcopy
from io import StringIO
from typing import Any

from ase.io import read

from llm_csp.schemas.workflow import CSPWorkflowRequest, GenerationConfig, SPPConfig


def compile_qlip_request(
    *,
    request: CSPWorkflowRequest,
    spp: dict[str, Any],
    spp_config: SPPConfig,
    generation: GenerationConfig,
    run_id: str,
) -> dict[str, Any]:
    """Build the QLIP v1 request without implementing any solver behavior."""

    if not spp.get("ready"):
        raise ValueError("SPP guidance is not ready")
    required = list(spp["required_pairs"])
    supported = list(spp["request_supported_pairs"])
    fallback = list(spp["regulator_fallback_pairs"])
    if set(supported) | set(fallback) != set(required):
        raise ValueError("SPP pair decisions do not cover the required pair domain")
    if supported:
        primary = str(spp["request_root"])
        weight = spp_config.outer_objective_scale * spp_config.request_coefficient
        params = {
            "pot_root": primary,
            "mode": "partial",
            "supported_pairs": supported,
            "missing_pairs": fallback,
            "strict_pair_coverage": False,
            "missing_pair_policy": "fallback",
            "regularisation_spp_dir": str(spp["regulator_root"]),
            "regularisation_weight": spp_config.regulator_coefficient,
            "cutoff": spp_config.cutoff,
        }
    else:
        primary = str(spp["regulator_root"])
        weight = spp_config.outer_objective_scale * spp_config.regulator_coefficient
        params = {"pot_root": primary, "mode": "complete", "cutoff": spp_config.cutoff}
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": request.formula},
            "design_space": deepcopy(request.design_space),
            "objective": {"type": "spp_energy"},
        },
        "constraints": [deepcopy(item) for item in request.constraints],
        "guidance": [
            {
                "id": "objective.energy_spp",
                "weight": weight,
                "params": params,
            }
        ],
        "guidance_mode": "weighted_sum",
        "solver": {
            "name": generation.solver_name,
            "time_limit_s": generation.time_limit_s,
            "mip_gap": generation.mip_gap,
            "threads": generation.threads,
            "seed": generation.seed,
            "parameters": {"NonConvex": 2},
        },
        "artifacts": {"return_cif": True},
        "context": {"run_id": run_id, "pot_root": primary}
        | ({"tags": [f"scaffold:{request.scaffold_id}"]} if request.scaffold_id else {}),
    }


def score_compiled_spp_objective(
    *, cif: str, spp: dict[str, Any], spp_config: SPPConfig,
) -> float:
    """Recompute the exact QLIP periodic objective represented by the adapter."""

    from qlip.interactions.spp import SPPCollection

    pairs = [tuple(pair.split("-", 1)) for pair in spp["required_pairs"]]
    supported = list(spp["request_supported_pairs"])
    if supported:
        collection = SPPCollection(
            spp["request_root"],
            cutoff=spp_config.cutoff,
            missing_pair_policy="fallback",
            regularisation_spp_dir=spp["regulator_root"],
            regularisation_weight=spp_config.regulator_coefficient,
        )
        scale = spp_config.outer_objective_scale * spp_config.request_coefficient
    else:
        collection = SPPCollection(
            spp["regulator_root"], cutoff=spp_config.cutoff, missing_pair_policy="block"
        )
        scale = spp_config.outer_objective_scale * spp_config.regulator_coefficient
    collection.load(pairs)
    atoms = read(StringIO(cif), format="cif")
    return float(
        scale
        * collection.score(
            atoms.get_chemical_symbols(), atoms.positions, atoms.cell, pbc=True
        )
    )
