from __future__ import annotations

import json
from pathlib import Path

import pytest

from sok_llm_orchestrator.bench.runner import run_benchmark_cases
from sok_llm_orchestrator.config import Settings


def test_phase2_benchmark_mode_rejects_nonimplemented_external_predictor(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    case_file = workdir / "nonimplemented_external.json"
    case_file.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "phase2-nonimplemented",
                        "composition": "TiO2",
                        "retrieval_mode": "metadata",
                        "allowed_corpora": ["default"],
                        "cell_candidate_policy": "fixed_benchmark",
                        "evaluation_preset": "baseline",
                        "external_predictors": ["phase2.external.matminer_formation_energy_rf"],
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="PHASE2_BENCHMARK_REJECTED_PHASE2_EXTERNAL_PREDICTOR_NOT_IMPLEMENTED"):
        run_benchmark_cases(
            case_file=case_file,
            mode="stub",
            workspace=workdir,
            settings=settings,
            strict_phase1_benchmark_mode=True,
        )
