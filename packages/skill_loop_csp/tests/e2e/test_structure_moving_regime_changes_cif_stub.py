from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def test_structure_moving_regime_changes_cif_stub(workdir: Path) -> None:
    state = {"last_action": None}

    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        overrides = dict(compiled.get("guided_overrides", {}))
        action_id = str(compiled.get("action_id", "unknown"))
        seed = str(overrides.get("template_seed_profile", "canonical"))
        lattice = str(overrides.get("lattice_candidate_profile", "narrow"))
        symmetry = str(overrides.get("symmetry_relaxation_profile", "strict"))
        ordering = str(overrides.get("ordering_perturbation_profile", "none"))
        strong = any(
            [
                seed != "canonical",
                lattice != "narrow",
                symmetry != "strict",
                ordering != "none",
            ]
        )
        if strong:
            structure = workdir / "structure_moving_regime" / f"{seed}_{lattice}_{symmetry}_{ordering}.cif"
            prop = 0.81
        else:
            structure = workdir / "structure_moving_regime" / "baseline.cif"
            prop = 0.61
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(
            f"data_solution\n_seed {seed}\n_lattice {lattice}\n_sym {symmetry}\n_ord {ordering}\n",
            encoding="utf-8",
        )
        # Encourage the policy to branch across actions instead of replaying one.
        if state["last_action"] == action_id:
            prop = prop - 0.25
        state["last_action"] = action_id
        return {
            "feasible": True,
            "primary_objective": prop,
            "property_estimate": prop,
            "objective_audit": {
                "objective_total": -1.53,
                "objective_terms": [{"term": "baseline", "value": -1.53}, {"term": "spp", "value": -0.2}],
                "objective_terms_signature": f"sig-{seed}-{lattice}-{symmetry}-{ordering}",
                "spp_term": -0.2,
                "guidance_terms": [{"term": "objective.energy_spp", "value": -0.2}],
                "solver_summary": {"property_x": prop},
            },
            "guided_request_trace": {
                "effective_overrides": overrides,
                "request_guidance_ids": ["objective.energy_spp"],
                "guidance_structure_signature": f"guide-{seed}-{lattice}-{symmetry}-{ordering}",
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
    settings.optimization_exploration_rate = 1.0
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_action_allowlist = [
        "guided_payload_probe",
        "guided_extreme_structure_probe",
        "guided_property_push",
    ]
    settings.optimization_action_family_limits = {
        "guided_exploit": 4,
        "guided_explore": 4,
        "baseline_control": 0,
        "retrieval_explore": 0,
        "cell_policy": 0,
    }
    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    result = engine.start(query="SrTiO3 structure-moving regime check", auto_run=True)
    report = json.loads((Path(result.session_path).parent / "report.json").read_text(encoding="utf-8"))
    structure_diag = report["diagnostics"]["structure_diversity_summary"]
    assert int(structure_diag["unique_structure_signature_count"]) > 1
    regime = report["regime_level_summary"]
    assert any(
        float(value) > 0.0
        for value in regime.get("structure_change_rate_by_regime", {}).values()
        if isinstance(value, (int, float))
    )
