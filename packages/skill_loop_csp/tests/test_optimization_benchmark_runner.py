from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.bench.reporting import regenerate_optimization_benchmark_report
from sok_llm_orchestrator.bench.runner import run_optimization_benchmark_cases
from sok_llm_orchestrator.config import Settings


def _executor_factory(case: dict[str, Any]):  # type: ignore[no-untyped-def]
    case_id = str(case["case_id"])
    case_class = str(case.get("case_class") or "easy-improvement")
    seen: dict[str, int] = {}

    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        idx = seen.get(action, 0)
        seen[action] = idx + 1
        feasible = True
        value = 0.1

        if case_class == "easy-improvement":
            if action == "guided_hybrid_balanced":
                value = 0.4 + 0.2 * idx
            elif action == "guided_property_push":
                value = 0.2 + 0.1 * idx
            else:
                value = 0.1
        elif case_class == "flat-stagnant":
            value = 0.2
        elif case_class == "misleading-local-optimum":
            if action == "baseline_control":
                value = 0.55
            elif action == "guided_hybrid_balanced":
                value = 0.3 + 0.3 * idx
            else:
                value = 0.25
        elif case_class == "repeated-infeasible":
            feasible = False
            value = 0.05

        return {
            "feasible": feasible,
            "primary_objective": value,
            "property_estimate": value if feasible else None,
            "valid_for_learning": feasible,
            "solver_calls": 2,
            "retrieval_calls": 2,
            "run_reference": {"case_id": case_id, "action": action, "case_class": case_class},
        }

    return _run


def test_optimization_benchmark_runner_and_regeneration(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cases = root / "docs" / "branch" / "benchmarks" / "internal_optimization_behavior_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 0.0
    settings.optimization_allow_midloop_clarification = True
    settings.optimization_max_failed_iterations = 2
    settings.optimization_stagnation_window = 3
    result = run_optimization_benchmark_cases(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        executor_factory=_executor_factory,
        max_iterations=8,
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["schema_version"] == "benchmark.optimization.report.v1"
    assert report["per_case_table"]
    row = report["per_case_table"][0]
    assert {"case_id", "case_class", "iteration_count", "initial_best_score", "final_best_score", "improvement_delta", "stop_reason"}.issubset(row.keys())
    classes = {item["case_class"] for item in report["per_case_table"]}
    assert {"easy-improvement", "flat-stagnant", "misleading-local-optimum", "repeated-infeasible"}.issubset(classes)
    assert "case_classes" in report["aggregate_summary"]

    rebuilt = regenerate_optimization_benchmark_report(Path(result["results_path"]))
    assert rebuilt["schema_version"] == "benchmark.optimization.report.v1"
    assert len(rebuilt["per_case_table"]) == len(report["per_case_table"])
    assert rebuilt["aggregate_summary"]["total_cases"] == report["aggregate_summary"]["total_cases"]
    assert rebuilt["aggregate_summary"]["case_classes"] == report["aggregate_summary"]["case_classes"]
