from __future__ import annotations

import json
from pathlib import Path

import pytest

from sok_llm_orchestrator.bench.runner import run_benchmark_cases
from sok_llm_orchestrator.config import Settings


def _write_case_file(path: Path, *, property_bias: str) -> Path:
    payload = {
        "cases": [
            {
                "case_id": "strict-case",
                "composition": "TiO2",
                "retrieval_mode": "metadata",
                "allowed_corpora": ["default"],
                "cell_candidate_policy": "fixed_benchmark",
                "evaluation_preset": "baseline",
                "property_bias": property_bias,
            }
        ]
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_benchmark_mode_rejects_unresolved_property_bias(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]

    case_file = _write_case_file(workdir / "strict_unresolved_cases.json", property_bias="unicorn_property")
    with pytest.raises(ValueError, match="PHASE1_BENCHMARK_REJECTED_PHASE1_UNKNOWN_PROPERTY_REQUEST"):
        run_benchmark_cases(
            case_file=case_file,
            mode="stub",
            workspace=workdir,
            settings=settings,
            strict_phase1_benchmark_mode=True,
        )

