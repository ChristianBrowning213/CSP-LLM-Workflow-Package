from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.bench.reporting import regenerate_optimization_benchmark_report
from sok_llm_orchestrator.bench.runner import run_optimization_benchmark_cases
from sok_llm_orchestrator.config import Settings


def _executor_factory(case: dict[str, Any]):  # type: ignore[no-untyped-def]
    case_id = str(case["case_id"])
    case_class = str(case.get("case_class") or "misleading-local-optimum")
    seen: dict[str, int] = {}

    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        idx = seen.get(action, 0)
        seen[action] = idx + 1
        value = 0.2
        feasible = True
        if case_class == "misleading-local-optimum":
            value = 0.4 + (0.05 * idx) if action.startswith("guided_") else 0.25
        elif case_class == "flat-stagnant":
            value = 0.3
        elif case_class == "repeated-infeasible":
            feasible = False
            value = 0.1
        return {
            "feasible": feasible,
            "primary_objective": value,
            "property_estimate": value if feasible else None,
            "valid_for_learning": feasible,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"case_id": case_id, "action": action},
        }

    return _run


def test_optimization_benchmark_runner_hard_pack(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "hard_structural_guidance_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 0.0
    result = run_optimization_benchmark_cases(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        executor_factory=_executor_factory,
        max_iterations=6,
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["schema_version"] == "benchmark.optimization.report.v1"
    rows = report["per_case_table"]
    assert len(rows) == 5
    assert all(isinstance(row.get("challenge_class"), str) for row in rows)
    assert all(isinstance(row.get("guidance_rationale"), str) and row["guidance_rationale"] for row in rows)
    assert all(
        isinstance(row.get("recommended_guidance_focus"), str) and row["recommended_guidance_focus"] for row in rows
    )

    rebuilt = regenerate_optimization_benchmark_report(Path(result["results_path"]))
    rebuilt_rows = rebuilt["per_case_table"]
    assert len(rebuilt_rows) == len(rows)
    assert all(isinstance(row.get("challenge_class"), str) for row in rebuilt_rows)
    assert all(isinstance(row.get("guidance_rationale"), str) and row["guidance_rationale"] for row in rebuilt_rows)
    assert all(
        isinstance(row.get("recommended_guidance_focus"), str) and row["recommended_guidance_focus"]
        for row in rebuilt_rows
    )

