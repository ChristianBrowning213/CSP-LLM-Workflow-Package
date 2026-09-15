from __future__ import annotations

import copy
from typing import Any

from sok_llm_orchestrator.contracts.qlip_schema import validate_solve_request
from sok_llm_orchestrator.orchestrator.cell_selection import CellCandidate
from sok_llm_orchestrator.orchestrator.task_spec import TaskSpec
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle
from sok_llm_orchestrator.spp.artifact_schema import SPPArtifactManifest
from sok_llm_orchestrator.structures.prototype_scaffold import (
    prototype_orbit_candidates_payload_from_request,
    prototype_orbit_solution_from_request,
)


SUPPORTED_PROTOTYPE_SCAFFOLDS: dict[str, dict[str, Any]] = {
    "perovskite": {"scaffold_id": "perovskite_abx3", "site_pattern": "ABX3_cubic_like"},
    "halide perovskite": {"scaffold_id": "halide_perovskite_abx3", "site_pattern": "ABX3_cubic_like"},
    "spinel": {"scaffold_id": "spinel_ab2x4", "site_pattern": "AB2X4_spinel_like"},
    "rocksalt": {"scaffold_id": "rocksalt_ax", "site_pattern": "AX_rocksalt_like"},
    "fluorite": {"scaffold_id": "fluorite_ax2", "site_pattern": "AX2_fluorite_like"},
    "pyrite": {"scaffold_id": "pyrite_ax2", "site_pattern": "AX2_pyrite_like"},
    "layered oxide": {"scaffold_id": "layered_oxide_abx2", "site_pattern": "layered_oct_sheet_like"},
    "olivine phosphate": {"scaffold_id": "olivine_abxo4", "site_pattern": "olivine_phosphate_like"},
    "argyrodite": {"scaffold_id": "argyrodite_a6bxc", "site_pattern": "argyrodite_like"},
    "nitride": {"scaffold_id": "rocksalt_nitride_ax", "site_pattern": "AX_rocksalt_like"},
    "rocksalt-like nitride": {"scaffold_id": "rocksalt_nitride_ax", "site_pattern": "AX_rocksalt_like"},
}


def _normalized_family(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _prototype_scaffold_for(task_spec: TaskSpec) -> dict[str, Any] | None:
    family = _normalized_family(task_spec.prototype or task_spec.target_structure_family)
    if family is None:
        return None
    scaffold = SUPPORTED_PROTOTYPE_SCAFFOLDS.get(family)
    if scaffold is None:
        return None
    if not (task_spec.symmetry_request.space_group or task_spec.target_crystal_system):
        return None
    return {
        **scaffold,
        "family": family,
        "limitations": [
            "prototype scaffold metadata and candidate-site source only",
            "not a Wyckoff-orbit MILP enforcement module",
        ],
    }


def _is_exact_space_group(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return not any(token in lowered for token in (" or ", "dependent", "subgroup", "analogue", "family"))


def _candidate_to_template(candidate: CellCandidate) -> dict[str, Any]:
    return {"lattice": dict(candidate.lattice)}


def _perturb_lattice(lattice: dict[str, Any], profile: str) -> dict[str, Any]:
    out: dict[str, Any] = dict(lattice)
    key = str(profile or "minimal").strip().lower()
    try:
        a = float(out.get("a", 4.0))
        b = float(out.get("b", 4.0))
        c = float(out.get("c", 4.0))
        alpha = float(out.get("alpha", 90.0))
        beta = float(out.get("beta", 90.0))
        gamma = float(out.get("gamma", 90.0))
    except (TypeError, ValueError):
        return out

    if key == "moderate":
        a, b, c = a * 1.02, b * 0.98, c * 1.01
        beta = beta + 0.5
    elif key == "aggressive":
        a, b, c = a * 1.08, b * 0.93, c * 1.05
        alpha, beta, gamma = alpha + 1.0, beta + 1.2, gamma - 0.8
    elif key == "template_shuffle":
        a, b, c = b * 1.03, c * 0.97, a * 1.01
        alpha, beta, gamma = beta, gamma, alpha
    # minimal and unknown keep original.

    out.update(
        {
            "a": max(0.1, float(a)),
            "b": max(0.1, float(b)),
            "c": max(0.1, float(c)),
            "alpha": float(alpha),
            "beta": float(beta),
            "gamma": float(gamma),
        }
    )
    return out


def _site_density_for_profile(profile: str) -> int:
    key = str(profile or "minimal").strip().lower()
    return {
        "minimal": 4,
        "moderate": 5,
        "aggressive": 6,
        "template_shuffle": 7,
    }.get(key, 4)


def _template_seed_transform(lattice: dict[str, Any], seed_profile: str) -> dict[str, Any]:
    out = dict(lattice)
    key = str(seed_profile or "canonical").strip().lower()
    try:
        a = float(out.get("a", 4.0))
        b = float(out.get("b", 4.0))
        c = float(out.get("c", 4.0))
    except (TypeError, ValueError):
        return out
    if key == "polymorph_mix":
        a, b, c = a * 1.01, b * 1.04, c * 0.97
    elif key == "framework_bias":
        a, b, c = a * 0.96, b * 1.03, c * 1.06
    elif key == "ordering_bias":
        a, b, c = a * 1.05, b * 0.95, c * 1.02
    out.update({"a": float(max(0.1, a)), "b": float(max(0.1, b)), "c": float(max(0.1, c))})
    return out


def _lattice_candidates_from_profile(lattice: dict[str, Any], profile: str) -> list[dict[str, Any]]:
    key = str(profile or "narrow").strip().lower()
    variants: list[tuple[float, float, float]] = [(1.0, 1.0, 1.0)]
    if key == "expanded":
        variants.extend([(1.03, 0.98, 1.02), (0.97, 1.02, 0.99)])
    elif key == "multibasin":
        variants.extend([(1.06, 0.94, 1.04), (0.94, 1.06, 0.96), (1.02, 1.02, 0.92)])
    out: list[dict[str, Any]] = []
    for idx, (sa, sb, sc) in enumerate(variants):
        try:
            a = float(lattice.get("a", 4.0)) * sa
            b = float(lattice.get("b", 4.0)) * sb
            c = float(lattice.get("c", 4.0)) * sc
            alpha = float(lattice.get("alpha", 90.0))
            beta = float(lattice.get("beta", 90.0))
            gamma = float(lattice.get("gamma", 90.0))
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "candidate_id": f"lat-{key}-{idx}",
                "lattice": {
                    "a": float(max(0.1, a)),
                    "b": float(max(0.1, b)),
                    "c": float(max(0.1, c)),
                    "alpha": float(alpha),
                    "beta": float(beta),
                    "gamma": float(gamma),
                },
            }
        )
    return out


def build_solve_request_v2(
    task_spec: TaskSpec,
    cell_candidates: list[CellCandidate],
    retrieval_bundle: RetrievalBundle,
    spp_artifact: SPPArtifactManifest | None,
    guidance_mode: str = "guidance_only",
    guidance_config: dict[str, Any] | None = None,
    weighting_profile: str | None = None,
    structure_perturbation_profile: str | None = None,
    template_seed_profile: str | None = None,
    lattice_candidate_profile: str | None = None,
    symmetry_relaxation_profile: str | None = None,
    ordering_perturbation_profile: str | None = None,
    active_symmetry_mode: str | None = None,
    qlip_objective: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    chosen = cell_candidates[0] if cell_candidates else CellCandidate(
        candidate_id="fallback",
        lattice={"a": 4.6, "b": 4.6, "c": 3.0, "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
        source="fallback",
    )
    perturb_profile = str(structure_perturbation_profile or "minimal").strip().lower()
    weight_profile = str(weighting_profile or "balanced").strip().lower()
    seed_profile = str(template_seed_profile or "canonical").strip().lower()
    lattice_profile = str(lattice_candidate_profile or "narrow").strip().lower()
    symmetry_profile = str(symmetry_relaxation_profile or "strict").strip().lower()
    ordering_profile = str(ordering_perturbation_profile or "none").strip().lower()
    requested_symmetry_mode = str(active_symmetry_mode or "").strip().lower()
    use_orbit_mode = requested_symmetry_mode == "prototype_orbit_qlip"
    use_variable_spp_orbit_mode = requested_symmetry_mode == "prototype_orbit_variable_spp_qlip"
    use_variable_orbit_mode = requested_symmetry_mode in {
        "prototype_orbit_variable_qlip",
        "prototype_orbit_variable_spp_qlip",
    }
    perturbed_template = _candidate_to_template(chosen)
    lattice = perturbed_template.get("lattice", {})
    if isinstance(lattice, dict):
        seeded = _template_seed_transform(lattice, seed_profile)
        perturbed_template["lattice"] = _perturb_lattice(seeded, perturb_profile)
    lattice_for_candidates = (
        dict(perturbed_template.get("lattice", {}))
        if isinstance(perturbed_template.get("lattice"), dict)
        else {}
    )
    scaffold = _prototype_scaffold_for(task_spec)
    constraints: list[dict[str, Any]] = []
    if task_spec.symmetry_request.space_group and symmetry_profile == "strict" and _is_exact_space_group(task_spec.symmetry_request.space_group):
        constraints.append(
            {"id": "constraint.space_group", "params": {"space_group": task_spec.symmetry_request.space_group}}
        )
    if task_spec.symmetry_request.space_group and symmetry_profile in {"soft", "relaxed"} and _is_exact_space_group(task_spec.symmetry_request.space_group):
        constraints.append(
            {
                "id": "constraint.space_group_soft",
                "params": {
                    "space_group": task_spec.symmetry_request.space_group,
                    "tolerance": 0.15 if symmetry_profile == "soft" else 0.35,
                    "mode": symmetry_profile,
                },
            }
        )
    if scaffold is not None:
        scaffold_mode = (
            "prototype_orbit_variable_spp_qlip"
            if use_variable_spp_orbit_mode
            else "prototype_orbit_variable_qlip"
            if use_variable_orbit_mode
            else "prototype_orbit_qlip"
            if use_orbit_mode
            else "prototype_scaffold"
        )
        scaffold_enforcement = (
            "variable_closed_wyckoff_orbit_selection"
            if use_variable_orbit_mode
            else "closed_wyckoff_orbit_selection"
            if use_orbit_mode
            else "candidate_site_scaffold"
        )
        limitations = (
            [
                "first variable orbit-level SPP-scored symmetry-preserving QLIP smoke",
                "enumerates cubic perovskite A-site prototype-orbit species only",
                "SPP objective is used only when pair-distance POT curves are available",
                "not a general CSP Wyckoff optimizer",
            ]
            if use_variable_spp_orbit_mode
            else [
                "first variable orbit-level symmetry-preserving QLIP smoke",
                "enumerates cubic perovskite A-site prototype-orbit species only",
                "not a general CSP Wyckoff optimizer",
            ]
            if use_variable_orbit_mode
            else
            [
                "first orbit-level symmetry-preserving QLIP smoke",
                "fixed prototype orbit assignment for supported benchmark smoke families only",
                "not a general CSP Wyckoff optimizer",
            ]
            if use_orbit_mode
            else list(scaffold["limitations"])
        )
        constraints.append(
            {
                "id": "constraint.prototype_scaffold",
                "params": {
                    "scaffold_id": scaffold["scaffold_id"],
                    "family": scaffold["family"],
                    "target_space_group": task_spec.symmetry_request.space_group or task_spec.target_space_group,
                    "target_crystal_system": task_spec.target_crystal_system,
                    "mode": scaffold_mode,
                    "enforcement": scaffold_enforcement,
                    "limitations": limitations,
                },
            }
        )
    if perturb_profile != "minimal":
        constraints.append(
            {
                "id": "constraint.structure_perturbation_profile",
                "params": {"profile": perturb_profile},
            }
        )
    if ordering_profile != "none":
        constraints.append(
            {
                "id": "constraint.ordering_perturbation_profile",
                "params": {"profile": ordering_profile, "strength": 0.25 if ordering_profile == "site_shuffle" else 0.45},
            }
        )
    objective_payload = qlip_objective if qlip_objective is not None else task_spec.qlip_objective
    objective_type = objective_payload.get("type") if isinstance(objective_payload, dict) else None
    guidance: list[dict[str, Any]] = []
    if (
        guidance_mode != "none"
        and spp_artifact is not None
        and objective_type in {None, "spp_energy"}
    ):
        cfg = dict(guidance_config or {})
        pairs_policy = str(cfg.get("pairs_policy", "task_pairs"))
        oob_policy = str(cfg.get("oob_policy", "max"))
        missing_pair_policy = str(cfg.get("missing_pair_policy", "max_global"))
        top_k_breakdown = int(cfg.get("top_k_breakdown", 10))
        lambda_override = cfg.get("lambda_override")
        if not isinstance(lambda_override, (int, float)):
            lambda_override = None
        convention_override = cfg.get("convention_override")
        if not isinstance(convention_override, str):
            convention_override = None
        r_cut = cfg.get("r_cut")
        if not isinstance(r_cut, (int, float)):
            r_cut = None
        guidance.append(
            {
                "id": "objective.energy_spp",
                "params": {
                    "spp_package_path": spp_artifact.metadata.get("spp_package_path", "SPPs/UNKNOWN"),
                    "pairs_policy": pairs_policy,
                    "oob_policy": oob_policy,
                    "missing_pair_policy": missing_pair_policy,
                    "lambda_override": float(lambda_override) if isinstance(lambda_override, (int, float)) else None,
                    "convention_override": convention_override,
                    "r_cut": float(r_cut) if isinstance(r_cut, (int, float)) else None,
                    "top_k_breakdown": max(0, top_k_breakdown),
                    "weighting_profile": weight_profile,
                    "structure_perturbation_profile": perturb_profile,
                    "base_weight_scale": (
                        float(cfg.get("base_weight_scale"))
                        if isinstance(cfg.get("base_weight_scale"), (int, float))
                        else None
                    ),
                    "guidance_weight_scale": (
                        float(cfg.get("guidance_weight_scale"))
                        if isinstance(cfg.get("guidance_weight_scale"), (int, float))
                        else None
                    ),
                    "template_seed_profile": seed_profile,
                    "lattice_candidate_profile": lattice_profile,
                    "symmetry_relaxation_profile": symmetry_profile,
                    "ordering_perturbation_profile": ordering_profile,
                },
            }
        )

    sites_payload = {
        "mode": "uniform_grid" if ordering_profile == "none" else "ordered_priors",
        "uniform_grid": {"density": _site_density_for_profile(perturb_profile)},
        "ordering_priors": {
            "profile": ordering_profile,
            "bias_strength": 0.0 if ordering_profile == "none" else (0.3 if ordering_profile == "site_shuffle" else 0.55),
        },
    }
    if scaffold is not None:
        scaffold_mode = (
            "prototype_orbit_variable_spp_qlip"
            if use_variable_spp_orbit_mode
            else "prototype_orbit_variable_qlip"
            if use_variable_orbit_mode
            else "prototype_orbit_qlip"
            if use_orbit_mode
            else "prototype_scaffold"
        )
        site_mode = (
            "prototype_orbit_variable"
            if use_variable_orbit_mode
            else "prototype_orbit"
            if use_orbit_mode
            else "prototype_scaffold"
        )
        candidate_site_source = (
            "prototype_orbit_variable_scaffold"
            if use_variable_orbit_mode
            else "prototype_orbit_scaffold"
            if use_orbit_mode
            else "prototype_scaffold"
        )
        sites_payload = {
            **sites_payload,
            "mode": scaffold_mode,
            "site_mode": site_mode,
            "candidate_site_source": candidate_site_source,
            "prototype_scaffold": {
                "scaffold_id": scaffold["scaffold_id"],
                "family": scaffold["family"],
                "site_pattern": scaffold["site_pattern"],
                "target_space_group": task_spec.symmetry_request.space_group or task_spec.target_space_group,
                "target_crystal_system": task_spec.target_crystal_system,
            },
        }

    request = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": task_spec.composition_target or "UNKNOWN"},
            "symmetry": {
                "requested_space_group": task_spec.symmetry_request.space_group or task_spec.target_space_group,
                "requested_space_group_number": task_spec.target_space_group_number,
                "requested_crystal_system": task_spec.target_crystal_system,
                "hardness": task_spec.symmetry_request.hardness,
                "source": "structured_task_spec" if task_spec.symmetry_request.space_group or task_spec.target_crystal_system else "none",
            },
            "prototype": {
                "requested_family": task_spec.target_structure_family,
                "requested_prototype": task_spec.prototype,
                "scaffold_mode": "prototype_scaffold" if scaffold is not None else "none",
                "scaffold_id": scaffold.get("scaffold_id") if scaffold is not None else None,
            },
            "design_space": {
                "template": {
                    **perturbed_template,
                    "seed_profile": seed_profile,
                    "perturbation_profile": perturb_profile,
                    "symmetry_relaxation_profile": symmetry_profile,
                    "ordering_perturbation_profile": ordering_profile,
                },
                "template_candidates": _lattice_candidates_from_profile(lattice_for_candidates, lattice_profile),
                "seeding": {
                    "template_seed_profile": seed_profile,
                    "lattice_candidate_profile": lattice_profile,
                    "symmetry_relaxation_profile": symmetry_profile,
                },
                "sites": sites_payload,
            },
        },
        "constraints": constraints,
        "guidance": guidance,
        "solver": {"name": "gurobi"},
    }
    if spp_artifact is not None:
        pot_root = spp_artifact.metadata.get("pot_root")
        if isinstance(pot_root, str) and pot_root.strip():
            request["context"] = {"pot_root": pot_root.strip()}
    if objective_payload is not None:
        request["problem"]["objective"] = copy.deepcopy(objective_payload)
    elif guidance:
        request["problem"]["objective"] = {"type": "spp_energy"}
    if scaffold is not None and (use_orbit_mode or use_variable_orbit_mode):
        solution = prototype_orbit_solution_from_request(request)
        if solution is not None:
            candidates_payload = prototype_orbit_candidates_payload_from_request(request) if use_variable_orbit_mode else None
            sites_payload = request["problem"]["design_space"]["sites"]
            site_ids_by_orbit: dict[str, list[str]] = {}
            for site in solution.sites:
                site_ids_by_orbit.setdefault(site.orbit_id, []).append(site.site_id)
            sites_payload["orbit_count"] = len(solution.orbits)
            sites_payload["site_count"] = len(solution.sites)
            sites_payload["target_space_group"] = solution.target_space_group
            sites_payload["target_space_group_number"] = solution.target_space_group_number
            sites_payload["target_crystal_system"] = solution.crystal_system
            sites_payload["target_family"] = solution.family
            sites_payload["selected_orbits"] = [orbit.orbit_id for orbit in solution.orbits]
            sites_payload["selected_sites"] = [site.site_id for site in solution.sites]
            if use_variable_orbit_mode:
                sites_payload["orbit_variable_selection"] = True
                sites_payload["formula_constraints"] = {
                    "target_formula": solution.formula,
                    "target_counts": candidates_payload.get("target_counts") if candidates_payload else {},
                    "site_count": len(solution.sites),
                    "must_select_complete_orbits": True,
                }
                sites_payload["selected_species_by_orbit"] = solution.selected_species_by_orbit or {}
                sites_payload["selected_candidate_id"] = solution.selected_candidate_id
                sites_payload["objective_value"] = solution.objective_value
                sites_payload["spp_scoring_status"] = solution.spp_scoring_status
                sites_payload["spp_objective_enabled"] = solution.spp_scoring_status in {"scored", "test_fixture"}
                sites_payload["spp_source"] = solution.spp_source
                sites_payload["spp_source_type"] = solution.spp_source_type
                sites_payload["spp_pot_dir"] = solution.spp_pot_dir
                sites_payload["spp_fallback_reason"] = solution.spp_fallback_reason
                sites_payload["selected_pair_score_breakdown"] = solution.selected_pair_score_breakdown or []
                if candidates_payload:
                    sites_payload["required_pairs"] = candidates_payload.get("required_pairs", [])
                    sites_payload["loaded_pair_count"] = candidates_payload.get("loaded_pair_count", 0)
                    sites_payload["missing_pairs"] = candidates_payload.get("missing_pairs", [])
                sites_payload["orbit_assignment_solver"] = "enumeration_backed_qlip_style_selector"
                sites_payload["species_orbit_variables"] = [
                    {
                        "variable_id": f"x({species},{orbit.orbit_id})",
                        "orbit_id": orbit.orbit_id,
                        "species": species,
                        "multiplicity": orbit.multiplicity,
                    }
                    for orbit in solution.orbits
                    for species in orbit.allowed_species
                ]
            sites_payload["orbit_selectors"] = [
                {
                    "selector_id": f"select_{orbit.orbit_id}",
                    "orbit_id": orbit.orbit_id,
                    "selection_scope": "orbit",
                    "fixed_selected": not use_variable_orbit_mode,
                    "selected_species": (solution.selected_species_by_orbit or {}).get(orbit.orbit_id),
                    "site_ids": site_ids_by_orbit.get(orbit.orbit_id, []),
                }
                for orbit in solution.orbits
            ]
            sites_payload["orbits"] = [
                {
                    "orbit_id": orbit.orbit_id,
                    "wyckoff_label": orbit.wyckoff_label,
                    "allowed_species": list(orbit.allowed_species),
                    "preferred_species": orbit.preferred_species,
                    "multiplicity": orbit.multiplicity,
                    "fractional_coordinates": [list(coords) for coords in orbit.fractional_coordinates],
                    "target_space_group": orbit.target_space_group,
                    "target_space_group_number": orbit.target_space_group_number,
                    "crystal_system": orbit.crystal_system,
                }
                for orbit in solution.orbits
            ]
    validate_solve_request(request)
    resolved_symmetry_mode = (
        "prototype_orbit_variable_qlip"
        if scaffold is not None and use_variable_orbit_mode and not use_variable_spp_orbit_mode
        else "prototype_orbit_variable_spp_qlip"
        if scaffold is not None and use_variable_spp_orbit_mode
        else
        "prototype_orbit_qlip"
        if scaffold is not None and use_orbit_mode
        else "prototype_scaffold"
        if scaffold is not None
        else ("request_only" if task_spec.symmetry_request.space_group or task_spec.target_crystal_system else "none")
    )
    provenance = {
        "builder_version": "qlip_builders_v2",
        "guidance_mode": guidance_mode,
        "weighting_profile": weight_profile,
        "structure_perturbation_profile": perturb_profile,
        "template_seed_profile": seed_profile,
        "lattice_candidate_profile": lattice_profile,
        "symmetry_relaxation_profile": symmetry_profile,
        "ordering_perturbation_profile": ordering_profile,
        "task_spec_defaults": list(task_spec.defaults_used),
        "cell_candidate_id": chosen.candidate_id,
        "retrieval_id": retrieval_bundle.retrieval_id,
        "retrieval_items": [item["structure_id"] for item in retrieval_bundle.items[:5]],
        "spp_artifact_id": spp_artifact.artifact_id if spp_artifact else None,
        "guidance_payload": dict(guidance_config or {}),
        "qlip_objective": copy.deepcopy(objective_payload) if isinstance(objective_payload, dict) else None,
        "active_symmetry_mode": resolved_symmetry_mode,
        "prototype_scaffold": copy.deepcopy(scaffold),
    }
    return request, provenance
