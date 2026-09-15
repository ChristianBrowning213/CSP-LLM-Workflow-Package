from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.bench.runner import run_benchmark_cases
from sok_llm_orchestrator.config import Settings


def test_existing_benchmark_backwards_compatibility(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "internal_rediscovery_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    result = run_benchmark_cases(case_file=case_file, mode="stub", workspace=workdir, settings=settings)
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["schema_version"] == "benchmark.report.v1"
    assert report["aggregate_summary"]["total_cases"] > 0
