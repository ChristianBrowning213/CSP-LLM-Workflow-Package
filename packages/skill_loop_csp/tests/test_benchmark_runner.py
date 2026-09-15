from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.bench.runner import run_benchmark_cases
from sok_llm_orchestrator.config import Settings


def test_benchmark_runner_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "internal_rediscovery_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir, root]
    settings.allowed_write_roots = [workdir]
    result = run_benchmark_cases(case_file=case_file, mode="stub", workspace=workdir, settings=settings)
    assert Path(result["report_path"]).exists()
