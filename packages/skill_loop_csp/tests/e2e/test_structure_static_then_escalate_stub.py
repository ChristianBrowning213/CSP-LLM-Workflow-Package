from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def test_structure_static_then_escalate_stub(workdir: Path) -> None:
    state = {"step": 0}

    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        step = int(state["step"])
        state["step"] = step + 1
        action = str(compiled.get("action_id"))
        overrides = dict(compiled.get("guided_overrides", {}))
        structure = workdir / "structure_static_then_escalate" / "same.cif"
        if action == "guided_extreme_structure_probe" and step >= 2:
            structure = workdir / "structure_static_then_escalate" / f"moved_{step}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_{action}_{step}\n_cell_length_a {4.0 + 0.2*step}\n", encoding="utf-8")
        return {
            "feasible": True,
            "primary_objective": 0.4 if action == "guided_extreme_structure_probe" else 0.8,
            "property_estimate": 0.4 if action == "guided_extreme_structure_probe" else 0.8,
            "objective_audit": {
                "objective_total": 0.4 if action == "guided_extreme_structure_probe" else 0.8,
                "objective_terms": [{"term": "baseline", "value": 0.2}, {"term": "spp", "value": 0.2}],
                "objective_terms_signature": f"sig-{step}",
                "spp_term": 0.2,
                "guidance_terms": [{"term": "objective.energy_spp", "value": 0.2}],
                "solver_summary": {},
            },
            "guided_request_trace": {
                "effective_overrides": overrides,
                "request_guidance_ids": ["objective.energy_spp"],
                "guidance_structure_signature": f"guide-{step}",
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
    result = engine.start(query="TiO2 static then escalate", auto_run=True)
    report = json.loads((Path(result.session_path).parent / "report.json").read_text(encoding="utf-8"))
    regime_rows = report.get("regime_level_summary", {}).get("rows", [])
    assert regime_rows
    assert any(
        bool(row.get("structure_change_rate", 0.0) > 0.0)
        and str(row.get("weighting_profile")) == "experimental_extreme"
        for row in regime_rows
    )
