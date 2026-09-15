from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.bench.runner import run_benchmark_cases
from sok_llm_orchestrator.config import Settings


def test_phase1_density_packing_proxy_strict_benchmark_mode_accepts(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    case_file = workdir / "density_cases.json"
    case_file.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "density-case",
                        "composition": "TiO2",
                        "retrieval_mode": "metadata",
                        "allowed_corpora": ["default"],
                        "cell_candidate_policy": "fixed_benchmark",
                        "evaluation_preset": "baseline",
                        "property_bias": "qlip.native.density_packing_proxy",
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_benchmark_cases(case_file, "stub", workdir, settings, strict_phase1_benchmark_mode=True)
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["per_case_table"][0]["qlip_objective_family"] == "density_packing"
