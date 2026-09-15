from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_repeated_first_crystal_analysis


def _executor_factory(workdir: Path):  # type: ignore[no-untyped-def]
    call_index = {"n": 0}

    def _build(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])
        static_structure = workdir / "repeated_structure_summary" / case_id / "same.cif"
        static_structure.parent.mkdir(parents=True, exist_ok=True)
        static_structure.write_text("data_static\n_cell_length_a 4.0\n", encoding="utf-8")

        def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
            step = int(call_index["n"])
            call_index["n"] = step + 1
            return {
                "feasible": True,
                "primary_objective": -1.53,
                "property_estimate": 0.60 + 0.01 * (step % 2),
                "objective_audit": {
                    "objective_total": -1.53,
                    "objective_terms": [{"term": "baseline", "value": -1.53}, {"term": "spp", "value": -0.2}],
                    "objective_terms_signature": f"sig-{step % 3}",
                    "spp_term": -0.2,
                    "guidance_terms": [{"term": "objective.energy_spp", "value": -0.2}],
                    "solver_summary": {},
                },
                "guided_request_trace": {
                    "effective_overrides": dict(compiled.get("guided_overrides", {})),
                    "request_guidance_ids": ["objective.energy_spp"],
                    "guidance_structure_signature": f"guide-{step % 3}",
                    "builder_input_trace": {"builder_inputs": {"guidance_payload": {"lambda_override": 0.4 + 0.1 * (step % 3)}}},
                },
                "baseline_request_trace": {"effective_overrides": {}, "request_guidance_ids": []},
                "valid_for_learning": True,
                "solver_calls": 1,
                "retrieval_calls": 1,
                "run_reference": {"structure_artifact_path": str(static_structure)},
            }

        return _run

    return _build


def test_repeated_analysis_structure_diversity_summary(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cases = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    out = run_repeated_first_crystal_analysis(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        repeats=2,
        max_iterations=3,
        action_profile="spp_deep_explore",
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    aggregate = summary["aggregate"]
    assert "structure_changed_case_run_rate" in aggregate
    assert "dominance_warning_case_run_rate" in aggregate
    assert float(aggregate["dominance_warning_case_run_rate"]) >= 0.0
