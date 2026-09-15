from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def test_structure_changes_without_property_gain_stub(workdir: Path) -> None:
    state = {"step": 0}

    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        step = int(state["step"])
        state["step"] = step + 1
        structure = workdir / "structure_changes_no_gain" / f"sol_{step}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_sol_{step}\n_cell_length_a {4.0 + step}\n", encoding="utf-8")
        return {
            "feasible": True,
            "primary_objective": -1.53,
            "property_estimate": 0.62,
            "objective_audit": {
                "objective_total": -1.53,
                "objective_terms": [{"term": "baseline", "value": -1.53}],
                "objective_terms_signature": "obj-static",
                "spp_term": None,
                "guidance_terms": [],
                "solver_summary": {},
            },
            "guided_request_trace": {
                "effective_overrides": dict(compiled.get("guided_overrides", {})),
                "request_guidance_ids": ["objective.energy_spp"],
                "guidance_structure_signature": "guide-static",
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
    settings.optimization_exploration_rate = 0.0
    settings.optimization_action_allowlist = ["guided_property_push"]
    settings.optimization_action_family_limits = {"guided_exploit": 3, "guided_explore": 0, "baseline_control": 0, "retrieval_explore": 0, "cell_policy": 0}

    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    result = engine.start(query="TiO2 structure changes no property gain", auto_run=True)
    report = json.loads((Path(result.session_path).parent / "report.json").read_text(encoding="utf-8"))
    trace = report["objective_vs_structure_trace"]
    assert any(
        str(item.get("classification")) == "structure_changed_no_property_gain"
        for item in trace
    )
