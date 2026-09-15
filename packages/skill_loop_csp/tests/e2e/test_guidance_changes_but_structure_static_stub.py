from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def test_guidance_changes_but_structure_static_stub(workdir: Path) -> None:
    structure = workdir / "static_structure.cif"
    structure.write_text("data_static\n_cell_length_a 4.0\n", encoding="utf-8")
    state = {"step": 0}

    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        step = int(state["step"])
        state["step"] = step + 1
        guidance_payload = {"lambda_override": 0.4 + 0.1 * step, "top_k_breakdown": 8 + step}
        return {
            "feasible": True,
            "primary_objective": -1.53 + 0.001 * step,
            "property_estimate": 0.62,
            "objective_audit": {
                "objective_total": -1.53 + 0.001 * step,
                "objective_terms": [{"term": "baseline", "value": -1.53}, {"term": "spp", "value": -0.2 - 0.01 * step}],
                "objective_terms_signature": f"obj-{step}",
                "spp_term": -0.2 - 0.01 * step,
                "guidance_terms": [{"term": "objective.energy_spp", "value": -0.2 - 0.01 * step}],
                "solver_summary": {},
            },
            "guided_request_trace": {
                "effective_overrides": dict(compiled.get("guided_overrides", {})),
                "request_guidance_ids": ["objective.energy_spp"],
                "guidance_structure_signature": f"guide-{step}",
                "builder_input_trace": {"builder_inputs": {"guidance_payload": guidance_payload}},
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
    settings.optimization_action_allowlist = ["guided_hybrid_balanced"]
    settings.optimization_action_family_limits = {"guided_exploit": 3, "guided_explore": 0, "baseline_control": 0, "retrieval_explore": 0, "cell_policy": 0}

    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    result = engine.start(query="TiO2 static structure diagnostic", auto_run=True)
    report = json.loads((Path(result.session_path).parent / "report.json").read_text(encoding="utf-8"))
    diag = report["diagnostics"]["structure_diversity_summary"]
    assert int(diag["unique_structure_signature_count"]) == 1
    assert int(diag["objective_changed_structure_unchanged_count"]) >= 1
    assert bool(diag["dominance_warning"]) is True
