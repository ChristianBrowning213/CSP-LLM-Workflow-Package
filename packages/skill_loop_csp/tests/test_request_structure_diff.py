from __future__ import annotations

from sok_llm_orchestrator.optimization.backend_sensitivity import (
    build_request_objective_diff_summary,
    normalize_qlip_request_structure,
)
from sok_llm_orchestrator.orchestrator.logging import canonical_json, sha256_text


def _sig(obj: object) -> str:
    return sha256_text(canonical_json(obj))


def test_request_structure_diff_detects_guidance_and_constraint_changes() -> None:
    req_a = {
        "version": "1.0",
        "problem": {"chemistry": {"formula": "TiO2"}, "design_space": {"template": {"lattice": {"a": 4.6}}}},
        "constraints": [{"id": "constraint.space_group", "params": {"space_group": "P42/mnm"}}],
        "guidance": [],
        "solver": {"name": "gurobi"},
    }
    req_b = {
        "version": "1.0",
        "problem": {"chemistry": {"formula": "TiO2"}, "design_space": {"template": {"lattice": {"a": 4.6}}}},
        "constraints": [],
        "guidance": [{"id": "objective.energy_spp", "params": {"spp_package_path": "SPPs/A"}}],
        "solver": {"name": "gurobi"},
    }
    norm_a = normalize_qlip_request_structure(req_a)
    norm_b = normalize_qlip_request_structure(req_b)
    baseline = {
        "compiled_action": {"guided_overrides": {"guidance_mode": "none"}, "baseline_overrides": {}},
        "request_trace": {
            "effective_overrides": {"guidance_mode": "none"},
            "request_structure": norm_a,
            "request_structure_signature": _sig(norm_a),
            "guidance_structure_signature": _sig(norm_a.get("guidance_entries", [])),
            "constraint_structure_signature": _sig(norm_a.get("constraint_entries", [])),
            "objective_structure_signature": _sig(norm_a.get("objective_structure", {})),
            "request_guidance_ids": [],
            "request_constraint_ids": ["constraint.space_group"],
        },
        "objective_audit": {"objective_total": -1.0, "objective_terms_signature": "t1", "solver_summary": {}},
    }
    variant = {
        "compiled_action": {"guided_overrides": {"guidance_mode": "guidance_only"}, "baseline_overrides": {}},
        "request_trace": {
            "effective_overrides": {"guidance_mode": "guidance_only"},
            "request_structure": norm_b,
            "request_structure_signature": _sig(norm_b),
            "guidance_structure_signature": _sig(norm_b.get("guidance_entries", [])),
            "constraint_structure_signature": _sig(norm_b.get("constraint_entries", [])),
            "objective_structure_signature": _sig(norm_b.get("objective_structure", {})),
            "request_guidance_ids": ["objective.energy_spp"],
            "request_constraint_ids": [],
        },
        "objective_audit": {"objective_total": -1.0, "objective_terms_signature": "t1", "solver_summary": {}},
    }
    diff = build_request_objective_diff_summary(baseline, variant)
    req_diff = diff["executable_request_diff"]
    assert req_diff["request_structure_changed"] is True
    assert req_diff["guidance_structure_changed"] is True
    assert req_diff["constraint_structure_changed"] is True
    assert req_diff["objective_structure_changed"] is True

