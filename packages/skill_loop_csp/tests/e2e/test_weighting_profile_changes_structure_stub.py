from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def test_weighting_profile_changes_structure_stub(workdir: Path) -> None:
    state = {"step": 0}

    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        step = int(state["step"])
        state["step"] = step + 1
        overrides = dict(compiled.get("guided_overrides", {}))
        weighting = str(overrides.get("weighting_profile", "balanced"))
        perturb = str(overrides.get("structure_perturbation_profile", "minimal"))
        if weighting in {"guidance_dominant", "property_push_strong", "experimental_extreme"} or perturb in {
            "aggressive",
            "template_shuffle",
        }:
            structure = workdir / "weighting_changes_structure" / f"{weighting}_{perturb}_{step}.cif"
        else:
            structure = workdir / "weighting_changes_structure" / "baseline_like.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_{weighting}_{perturb}_{step}\n", encoding="utf-8")
        prop = 0.8 if structure.name != "baseline_like.cif" else 0.6
        return {
            "feasible": True,
            "primary_objective": prop,
            "property_estimate": prop,
            "objective_audit": {
                "objective_total": prop,
                "objective_terms": [{"term": "baseline", "value": 0.2}, {"term": "spp", "value": prop - 0.2}],
                "objective_terms_signature": f"sig-{weighting}-{perturb}-{step}",
                "spp_term": prop - 0.2,
                "guidance_terms": [{"term": "objective.energy_spp", "value": prop - 0.2}],
                "solver_summary": {},
            },
            "guided_request_trace": {
                "effective_overrides": overrides,
                "request_guidance_ids": ["objective.energy_spp"],
                "guidance_structure_signature": f"guide-{weighting}-{perturb}",
            },
            "baseline_request_trace": {"effective_overrides": {}, "request_guidance_ids": []},
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"structure_artifact_path": str(structure)},
        }

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    settings.optimization_max_iterations = 4
    settings.optimization_exploration_rate = 0.0
    settings.optimization_action_allowlist = [
        "guided_payload_probe",
        "guided_hybrid_balanced",
        "guided_property_push",
        "guided_extreme_structure_probe",
    ]
    settings.optimization_action_family_limits = {
        "guided_exploit": 4,
        "guided_explore": 4,
        "baseline_control": 0,
        "retrieval_explore": 0,
        "cell_policy": 0,
    }
    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    result = engine.start(query="TiO2 weighting structure movement", auto_run=True)
    report = json.loads((Path(result.session_path).parent / "report.json").read_text(encoding="utf-8"))
    structure_diag = report["diagnostics"]["structure_diversity_summary"]
    assert int(structure_diag["unique_structure_signature_count"]) > 1
