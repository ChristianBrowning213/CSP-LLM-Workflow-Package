from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.bench.external import EXTERNAL_REGIMES, run_external_benchmark_matrix
from sok_llm_orchestrator.config import Settings


def _write_normalized_case(root: Path, dataset: str, split: str) -> None:
    normalized = root / "benchmarks" / "external" / dataset / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    row = {
        "benchmark_dataset": dataset,
        "split": split,
        "case_id": f"{dataset}_{split}_000000",
        "composition": "TiO2",
        "cif": "data_tio2\n_chemical_formula_sum 'TiO2'\n",
        "source_metadata": {"reference_cif_signature": "abc123"},
    }
    (normalized / f"{split}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_external_benchmark_matrix_runner(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    for split in ("train", "val", "test"):
        _write_normalized_case(workdir, "mp_20", split)

    def _fake_pipeline_row(**kwargs):  # type: ignore[no-untyped-def]
        case = kwargs["case"]
        regime = kwargs["regime"]
        return {
            "dataset": case["benchmark_dataset"],
            "split": case["split"],
            "case_id": case["case_id"],
            "composition": case["composition"],
            "regime": regime,
            "budget": kwargs["budget"],
            "status": "SUCCEEDED",
            "solved_valid": True,
            "best_objective_within_budget": 0.25,
            "structure_diversity_within_budget": 1,
            "structure_signature": f"sig-{regime}",
            "structure_artifact_path": "stub.cif",
            "property_x": 0.7,
            "rediscovery_match": False,
            "reference_cif_signature": "abc123",
            "objective_term_signature": "term-sig",
            "objective_terms_count": 2,
            "spp_term": 0.2,
            "request_guidance_ids": ["objective.energy_spp"],
            "run_reference": {"run_id": "r1"},
        }

    def _fake_orchestrator_row(**kwargs):  # type: ignore[no-untyped-def]
        case = kwargs["case"]
        return {
            "dataset": case["benchmark_dataset"],
            "split": case["split"],
            "case_id": case["case_id"],
            "composition": case["composition"],
            "regime": "qlip_full_orchestrator",
            "budget": kwargs["budget"],
            "status": "STOPPED",
            "solved_valid": True,
            "best_objective_within_budget": 0.4,
            "structure_diversity_within_budget": 2,
            "structure_signature": "sig-orch",
            "structure_artifact_path": "best.cif",
            "property_x": 0.8,
            "rediscovery_match": False,
            "reference_cif_signature": "abc123",
            "objective_term_signature": "term-sig-orch",
            "objective_terms_count": 3,
            "spp_term": 0.3,
            "request_guidance_ids": ["objective.energy_spp"],
            "run_reference": {"session_id": "s1"},
            "orchestrator_diagnostics": {
                "branch_switch_count": 1,
                "spp_unique_corpus_strategy_count": 2,
                "spp_unique_package_variant_count": 2,
                "spp_unique_payload_signature_count": 2,
                "richer_exploration_detected": True,
            },
        }

    monkeypatch.setattr("sok_llm_orchestrator.bench.external._pipeline_matrix_row", _fake_pipeline_row)
    monkeypatch.setattr("sok_llm_orchestrator.bench.external._orchestrator_matrix_row", _fake_orchestrator_row)

    settings = Settings.from_sources(None)
    settings.workspace_root = workdir / ".workspace"
    result = run_external_benchmark_matrix(
        datasets=["mp_20"],
        mode="stub",
        workspace=settings.workspace_root,
        settings=settings,
        splits=["test"],
        regimes=list(EXTERNAL_REGIMES),
        max_cases_per_split=1,
        max_iterations=3,
        repo_root=workdir,
    )
    raw = json.loads(Path(result["results_path"]).read_text(encoding="utf-8"))
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))

    assert raw["schema_version"] == "benchmark.external.matrix.v1"
    assert len(raw["rows"]) == 4
    assert {row["regime"] for row in raw["rows"]} == set(EXTERNAL_REGIMES)
    assert report["schema_version"] == "benchmark.external.matrix.report.v1"
    assert len(report["grouped_summary"]) == 4
