from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.reporting import regenerate_report_from_session_artifacts


def test_regime_level_structure_change_reporting_regenerates_stably(workdir: Path) -> None:
    def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        overrides = dict(compiled.get("guided_overrides", {}))
        regime = "|".join(
            [
                str(overrides.get("weighting_profile", "balanced")),
                str(overrides.get("structure_perturbation_profile", "minimal")),
                str(overrides.get("template_seed_profile", "canonical")),
                str(overrides.get("lattice_candidate_profile", "narrow")),
                str(overrides.get("symmetry_relaxation_profile", "strict")),
                str(overrides.get("ordering_perturbation_profile", "none")),
            ]
        )
        structure = workdir / "regime_reporting_regen" / f"{regime}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_{regime}\n", encoding="utf-8")
        return {
            "feasible": True,
            "primary_objective": -1.53,
            "property_estimate": 0.70 if "minimal" in regime else 0.74,
            "objective_audit": {
                "objective_total": -1.53,
                "objective_terms": [{"term": "baseline", "value": -1.53}, {"term": "spp", "value": -0.2}],
                "objective_terms_signature": f"obj-{regime}",
                "spp_term": -0.2,
                "guidance_terms": [{"term": "objective.energy_spp", "value": -0.2}],
                "solver_summary": {"property_x": 0.70 if "minimal" in regime else 0.74},
            },
            "guided_request_trace": {
                "effective_overrides": overrides,
                "request_guidance_ids": ["objective.energy_spp"],
                "guidance_structure_signature": f"guide-{regime}",
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
    settings.optimization_action_allowlist = [
        "guided_payload_probe",
        "guided_hybrid_balanced",
        "guided_extreme_structure_probe",
    ]
    settings.optimization_action_family_limits = {
        "guided_exploit": 3,
        "guided_explore": 3,
        "baseline_control": 0,
        "retrieval_explore": 0,
        "cell_policy": 0,
    }
    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    result = engine.start(query="regime reporting regeneration", auto_run=True)
    report_path = Path(result.session_path).parent / "report.json"
    on_disk = json.loads(report_path.read_text(encoding="utf-8"))
    regenerated = regenerate_report_from_session_artifacts(Path(result.session_path))
    assert on_disk["regime_level_summary"] == regenerated["regime_level_summary"]
