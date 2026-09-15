from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.bench.reporting import regenerate_optimization_benchmark_report
from sok_llm_orchestrator.bench.runner import run_optimization_benchmark_cases
from sok_llm_orchestrator.config import Settings


def _executor_factory(case: dict[str, Any]):  # type: ignore[no-untyped-def]
    case_id = str(case["case_id"])
    seen: dict[str, int] = {}

    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        idx = seen.get(action, 0)
        seen[action] = idx + 1
        value = 0.2
        if action.startswith("guided_"):
            value = 0.35 + 0.04 * idx
        return {
            "feasible": True,
            "primary_objective": value,
            "property_estimate": value,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"case_id": case_id, "action": action},
        }

    return _run


def test_benchmark_runner_adversarial_pack(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "adversarial_hard_crystal_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_exploration_rate = 0.0
    result = run_optimization_benchmark_cases(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        executor_factory=_executor_factory,
        max_iterations=4,
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    rows = report["per_case_table"]
    assert len(rows) == 5
    assert all(isinstance(row.get("challenge_class"), str) for row in rows)
    assert all(isinstance(row.get("hypotheses"), list) and len(row["hypotheses"]) >= 2 for row in rows)
    assert all(isinstance(row.get("suggested_corpus_bias"), str) for row in rows)
    assert all(isinstance(row.get("suggested_perturbation_bias"), str) for row in rows)

    rebuilt = regenerate_optimization_benchmark_report(Path(result["results_path"]))
    rebuilt_rows = rebuilt["per_case_table"]
    assert len(rebuilt_rows) == len(rows)
    assert all(isinstance(row.get("challenge_class"), str) for row in rebuilt_rows)
    assert all(isinstance(row.get("hypotheses"), list) and len(row["hypotheses"]) >= 2 for row in rebuilt_rows)
