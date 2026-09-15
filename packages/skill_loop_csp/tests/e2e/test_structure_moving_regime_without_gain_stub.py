from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def test_structure_moving_regime_without_gain_stub(workdir: Path) -> None:
    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        overrides = dict(compiled.get("guided_overrides", {}))
        action_id = str(compiled.get("action_id", "unknown"))
        seed = str(overrides.get("template_seed_profile", "canonical"))
        ordering = str(overrides.get("ordering_perturbation_profile", "none"))
        structure = workdir / "structure_moving_without_gain" / f"{action_id}_{seed}_{ordering}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_solution\n_seed {seed}\n_ordering {ordering}\n", encoding="utf-8")
        # Structure can move, but property/total objective stay flat.
        return {
            "feasible": True,
            "primary_objective": -1.53,
            "property_estimate": 0.72,
            "objective_audit": {
                "objective_total": -1.53,
                "objective_terms": [{"term": "baseline", "value": -1.53}, {"term": "spp", "value": -0.2}],
                "objective_terms_signature": f"sig-{seed}-{ordering}",
                "spp_term": -0.2,
                "guidance_terms": [{"term": "objective.energy_spp", "value": -0.2}],
                "solver_summary": {"property_x": 0.72},
            },
            "guided_request_trace": {
                "effective_overrides": overrides,
                "request_guidance_ids": ["objective.energy_spp"],
                "guidance_structure_signature": f"guide-{seed}-{ordering}",
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
    settings.optimization_max_iterations = 3
    settings.optimization_exploration_rate = 1.0
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_action_allowlist = ["guided_payload_probe", "guided_extreme_structure_probe"]
    settings.optimization_action_family_limits = {
        "guided_exploit": 0,
        "guided_explore": 3,
        "baseline_control": 0,
        "retrieval_explore": 0,
        "cell_policy": 0,
    }
    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    result = engine.start(query="Sr2FeMoO6 no-gain regime", auto_run=True)
    report = json.loads((Path(result.session_path).parent / "report.json").read_text(encoding="utf-8"))
    structure_diag = report["diagnostics"]["structure_diversity_summary"]
    assert int(structure_diag["unique_structure_signature_count"]) > 1
    classifications = [
        str(item.get("classification"))
        for item in report.get("objective_vs_structure_trace", [])
        if isinstance(item, dict)
    ]
    assert "structure_changed_no_property_gain" in classifications
