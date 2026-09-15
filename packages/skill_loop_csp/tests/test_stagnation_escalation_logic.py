from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def test_stagnation_escalation_prefers_stronger_regimes(workdir: Path) -> None:
    state = {"step": 0}

    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        step = int(state["step"])
        state["step"] = step + 1
        action = str(compiled.get("action_id"))
        overrides = dict(compiled.get("guided_overrides", {}))
        weighting = str(overrides.get("weighting_profile", "balanced"))
        perturb = str(overrides.get("structure_perturbation_profile", "minimal"))
        structure = workdir / "stagnation_escalation" / "same.cif"
        if action == "guided_extreme_structure_probe" and step >= 2:
            structure = workdir / "stagnation_escalation" / f"changed_{step}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        if structure.name == "same.cif":
            structure.write_text("data_same\n_cell_length_a 4.0\n", encoding="utf-8")
        else:
            structure.write_text(f"data_changed\n_cell_length_a {5.0 + step}\n", encoding="utf-8")
        score = 0.9 if action == "guided_payload_probe" else 0.4
        return {
            "feasible": True,
            "primary_objective": score,
            "property_estimate": score,
            "objective_audit": {
                "objective_total": score,
                "objective_terms": [{"term": "baseline", "value": 0.2}, {"term": "spp", "value": score - 0.2}],
                "objective_terms_signature": f"obj-{weighting}-{perturb}-{step}",
                "spp_term": score - 0.2,
                "guidance_terms": [{"term": "objective.energy_spp", "value": score - 0.2}],
                "solver_summary": {},
            },
            "guided_request_trace": {
                "effective_overrides": overrides,
                "request_guidance_ids": ["objective.energy_spp"],
                "guidance_structure_signature": f"g-{weighting}-{perturb}-{step}",
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
    settings.optimization_stagnation_window = 2
    settings.optimization_exploration_rate = 0.0
    settings.optimization_action_allowlist = ["guided_payload_probe", "guided_extreme_structure_probe"]
    settings.optimization_action_family_limits = {
        "guided_exploit": 0,
        "guided_explore": 4,
        "baseline_control": 0,
        "retrieval_explore": 0,
        "cell_policy": 0,
    }

    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    result = engine.start(query="TiO2 stagnation escalation check", auto_run=True)
    report = json.loads((Path(result.session_path).parent / "report.json").read_text(encoding="utf-8"))
    trace = report.get("iteration_trace", [])
    escalated_rows = [
        row
        for row in trace
        if isinstance(row, dict)
        and isinstance(row.get("action_effectiveness"), dict)
        and bool(row["action_effectiveness"].get("stagnation_escalation_active", False))
    ]
    assert escalated_rows
    assert any(str(row.get("action_id")) == "guided_extreme_structure_probe" for row in escalated_rows)
