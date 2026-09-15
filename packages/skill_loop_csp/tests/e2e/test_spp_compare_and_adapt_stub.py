from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.orchestrator.logging import canonical_json, sha256_text


def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
    guided = dict(compiled.get("guided_overrides", {}))
    action = str(compiled.get("action_id", "unknown"))
    variant = str(guided.get("spp_package_variant", "default"))
    corpus_strategy = str(guided.get("corpus_strategy", "top_k"))
    weight = float(guided.get("spp_guidance_weight", 0.5) or 0.5)
    base_score = 0.3
    if action == "guided_property_push":
        base_score = 0.8
    elif action == "guided_payload_probe":
        base_score = 0.45
    score = base_score + (0.03 if corpus_strategy == "property_biased" else 0.0) + min(0.05, weight * 0.02)
    request_payload = {
        "guidance_payload": {
            "lambda_override": weight,
            "top_k_breakdown": int(guided.get("spp_top_k_breakdown", 10)),
        },
        "variant": variant,
        "corpus_strategy": corpus_strategy,
    }
    payload_sig = sha256_text(canonical_json(request_payload))
    return {
        "feasible": True,
        "primary_objective": score,
        "property_estimate": score,
        "objective_audit": {
            "objective_total": score,
            "objective_terms": [{"term": "baseline", "value": 0.2}, {"term": "spp", "value": score - 0.2}],
            "objective_terms_signature": payload_sig,
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
                    "guidance_payload": request_payload["guidance_payload"],
                    "corpus_candidate_ids": [f"{corpus_strategy}:3:0", f"{corpus_strategy}:4:0"],
                    "spp_package_candidate_ids": [f"{variant}:0", "default:1"],
                }
            },
        },
        "valid_for_learning": True,
        "solver_calls": 1,
        "retrieval_calls": 1,
        "run_reference": {"structure_artifact_path": f"stub/{action}.cif"},
    }


def test_spp_compare_and_adapt_stub(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    settings.optimization_max_iterations = 5
    settings.optimization_exploration_rate = 0.0
    settings.optimization_action_allowlist = ["guided_payload_probe", "guided_property_push"]
    settings.optimization_action_family_limits = {
        "guided_exploit": 5,
        "guided_explore": 5,
        "retrieval_explore": 0,
        "cell_policy": 0,
        "baseline_control": 0,
    }

    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    result = engine.start(query="SrTiO3 compare and adapt", auto_run=True)
    report = json.loads((Path(result.session_path).parent / "report.json").read_text(encoding="utf-8"))
    actions = [row.get("action_id") for row in report.get("iteration_trace", []) if isinstance(row, dict)]
    assert "guided_payload_probe" in actions
    assert "guided_property_push" in actions
    assert all(action == "guided_property_push" for action in actions[-3:])
    spp = report["spp_exploration_summary"]
    assert int(spp["branch_count"]) >= 1
