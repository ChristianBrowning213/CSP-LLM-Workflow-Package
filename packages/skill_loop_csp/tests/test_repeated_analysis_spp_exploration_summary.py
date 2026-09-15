from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_repeated_first_crystal_analysis
from sok_llm_orchestrator.orchestrator.logging import canonical_json, sha256_text


def _executor_factory(_: Path):  # type: ignore[no-untyped-def]
    def _build(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])

        def _run(__: str, compiled: dict[str, Any]) -> dict[str, Any]:
            guided = dict(compiled.get("guided_overrides", {}))
            action = str(compiled.get("action_id"))
            corpus_strategy = str(guided.get("corpus_strategy", "top_k"))
            variant = str(guided.get("spp_package_variant", "default"))
            payload = {
                "lambda_override": float(guided.get("spp_guidance_weight", 0.6) or 0.6),
                "top_k_breakdown": int(guided.get("spp_top_k_breakdown", 10)),
            }
            sig = sha256_text(canonical_json(payload))
            score = 0.65 if action == "guided_property_push" else 0.5
            return {
                "feasible": True,
                "primary_objective": score,
                "property_estimate": score,
                "objective_audit": {
                    "objective_total": score,
                    "objective_terms": [{"term": "baseline", "value": 0.2}, {"term": "spp", "value": score - 0.2}],
                    "objective_terms_signature": sig,
                    "baseline_term": 0.2,
                    "spp_term": score - 0.2,
                    "guidance_terms": [],
                    "solver_summary": {},
                },
                "guided_request_trace": {
                    "effective_overrides": guided,
                    "request_guidance_ids": ["objective.energy_spp"],
                    "builder_input_trace": {
                        "builder_inputs": {
                            "selected_corpus_candidate_id": f"{corpus_strategy}:4:0",
                            "selected_spp_package_variant": variant,
                            "guidance_payload": payload,
                            "corpus_candidate_ids": [f"{corpus_strategy}:3:0", f"{corpus_strategy}:4:0"],
                            "spp_package_candidate_ids": [f"{variant}:0", "default:1"],
                        }
                    },
                },
                "valid_for_learning": True,
                "solver_calls": 1,
                "retrieval_calls": 1,
                "run_reference": {"structure_artifact_path": f"stub/{case_id}/{action}.cif"},
            }

        return _run

    return _build


def test_repeated_analysis_includes_spp_exploration_summary(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cases = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_action_allowlist = [
        "guided_property_push",
        "guided_hybrid_balanced",
        "guided_corpus_branch",
    ]
    out = run_repeated_first_crystal_analysis(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        repeats=2,
        max_iterations=4,
        action_profile="spp_deep_explore",
        analysis_metric_view="property_x",
        executor_factory=_executor_factory(workdir),
    )
    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    assert "spp_richer_exploration_case_run_rate" in summary["aggregate"]
    assert float(summary["aggregate"]["spp_richer_exploration_case_run_rate"]) > 0.0
    assert any(bool(row.get("spp_richer_exploration_detected", False)) for row in summary["run_case_rows"])

