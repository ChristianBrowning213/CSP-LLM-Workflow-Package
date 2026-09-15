from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.bench.runner import run_benchmark_cases
from sok_llm_orchestrator.config import Settings


def test_phase2_external_predictor_stub_happy_path(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workdir.resolve()]
    case_file = workdir / "phase2_happy.json"
    case_file.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "phase2-happy",
                        "composition": "TiO2",
                        "retrieval_mode": "metadata",
                        "allowed_corpora": ["default"],
                        "cell_candidate_policy": "fixed_benchmark",
                        "evaluation_preset": "baseline",
                        "property_bias": "qlip.native.density_packing_proxy",
                        "external_predictors": [
                            {
                                "predictor_id": "phase2.external.pymatgen_composition_descriptor",
                                "target": "mean_atomic_number",
                            }
                        ],
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_benchmark_cases(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        strict_phase1_benchmark_mode=True,
    )
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    row = report["per_case_table"][0]
    assert row["qlip_objective_family"] == "density_packing"
    prediction = row["external_phase2"]["guided"]["predictions"][0]
    assert prediction["predictor_id"] == "phase2.external.pymatgen_composition_descriptor"
    assert prediction["native_phase1_objective"] is False
    assert report["external_phase2_summary"]["predictor_ids"] == [
        "phase2.external.pymatgen_composition_descriptor"
    ]
