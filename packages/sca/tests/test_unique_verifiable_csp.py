from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.cli import app
from sca.evaluators.registry import list_evaluator_specs
from sca.evaluators.unique_csp import (
    AuditBundleCompletenessBenchmarkEvaluator,
    ConstraintFaithfulnessBenchmarkEvaluator,
    EvidenceFaithfulnessBenchmarkEvaluator,
    EvidenceTraceabilityBenchmarkEvaluator,
    SolverCertificateBenchmarkEvaluator,
)
from sca.traceability.io import inspect_run_bundle, load_run_bundle
from sca.traceability.schema import TraceableRunBundle
from sca.unique_benchmarks.summary import compute_unique_composite


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
BUNDLE = FIXTURES / "traceable_run_bundle"
runner = CliRunner()


def test_traceable_run_schema_validates() -> None:
    bundle = load_run_bundle(BUNDLE)
    assert isinstance(bundle, TraceableRunBundle)
    assert bundle.run_id == "traceable_run_bundle"
    assert bundle.structured_intent is not None
    assert bundle.structured_intent.prototype_family == "perovskite"


def test_run_bundle_loader_handles_missing_artifacts(tmp_path: Path) -> None:
    (tmp_path / "prompt.txt").write_text("Generate NaCl.", encoding="utf-8")
    inspection = inspect_run_bundle(tmp_path)
    assert inspection.bundle_valid is False
    assert "retrieval_trace" in inspection.missing_artifacts
    assert inspection.to_row()["missing_artifact_count"] > 0


def test_inspect_run_bundle_cli_writes_reports(tmp_path: Path) -> None:
    csv_path = tmp_path / "inspection.csv"
    json_path = tmp_path / "inspection.json"
    md_path = tmp_path / "inspection.md"
    result = runner.invoke(
        app,
        [
            "inspect-run-bundle",
            "--run-dir",
            str(BUNDLE),
            "--out",
            str(csv_path),
            "--json",
            str(json_path),
            "--markdown",
            str(md_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert pd.read_csv(csv_path)["bundle_valid"].tolist() == [True]
    assert json.loads(json_path.read_text(encoding="utf-8"))["rows"][0]["bundle_valid"] is True
    assert "# Traceable Run Bundle Inspection" in md_path.read_text(encoding="utf-8")


def test_unique_evaluators_registered() -> None:
    names = {spec.name for spec in list_evaluator_specs()}
    assert {
        "evidence_traceability",
        "constraint_faithfulness",
        "solver_certificate",
        "evidence_faithfulness",
        "audit_bundle_completeness",
    }.issubset(names)


def test_evidence_traceability_evaluator_scores_complete_vs_incomplete(tmp_path: Path) -> None:
    complete = EvidenceTraceabilityBenchmarkEvaluator().evaluate_row(_row())
    assert complete.ok is True
    assert complete.metrics["evidence_trace_score"] > 0.9

    (tmp_path / "prompt.txt").write_text("Generate NaCl.", encoding="utf-8")
    incomplete = EvidenceTraceabilityBenchmarkEvaluator().evaluate_row({"run_bundle_dir": str(tmp_path)})
    assert incomplete.ok is False
    assert incomplete.error_type == "missing_bundle"


def test_constraint_faithfulness_handles_formula_sg_and_prototype() -> None:
    result = ConstraintFaithfulnessBenchmarkEvaluator().evaluate_row(_row())
    assert result.ok is True
    assert result.metrics["formula_constraint_satisfied"] is True
    assert result.metrics["space_group_constraint_satisfied"] is True
    assert result.metrics["prototype_constraint_satisfied"] is True
    assert result.metrics["constraint_satisfaction_rate"] == 1.0


def test_solver_certificate_handles_optimal_infeasible_and_missing(tmp_path: Path) -> None:
    optimal = SolverCertificateBenchmarkEvaluator().evaluate_row(_row())
    assert optimal.metrics["solver_optimal"] is True
    assert optimal.metrics["solver_certificate_score"] > 0.8

    infeasible_dir = tmp_path / "infeasible"
    _copy_bundle_minimal(BUNDLE, infeasible_dir)
    (infeasible_dir / "solver_trace.json").write_text(
        json.dumps(
            {
                "backend": "fake",
                "solver_status": "infeasible",
                "num_variables": 2,
                "num_constraints": 5,
                "infeasibility_explanation": "composition/site mismatch",
            }
        ),
        encoding="utf-8",
    )
    infeasible = SolverCertificateBenchmarkEvaluator().evaluate_row({"run_bundle_dir": str(infeasible_dir)})
    assert infeasible.metrics["solver_infeasible"] is True
    assert infeasible.metrics["infeasibility_explanation_present"] is True

    missing = SolverCertificateBenchmarkEvaluator().evaluate_row({"run_bundle_dir": str(tmp_path / "missing")})
    assert missing.ok is False


def test_evidence_faithfulness_detects_unsupported_claims(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "trap"
    _copy_bundle_minimal(BUNDLE, bundle_dir)
    (bundle_dir / "final_decision.json").write_text(
        json.dumps(
            {
                "decision": "accept",
                "explanation": "Used imaginary-perovskite and evidence from rutile TiO2.",
                "citations": [],
            }
        ),
        encoding="utf-8",
    )
    result = EvidenceFaithfulnessBenchmarkEvaluator().evaluate_row({"run_bundle_dir": str(bundle_dir)})
    assert result.metrics["num_unsupported_evidence_claims"] >= 1
    assert result.metrics["wrong_family_evidence_rate"] > 0


def test_audit_bundle_completeness_scores_complete_and_incomplete(tmp_path: Path) -> None:
    complete = AuditBundleCompletenessBenchmarkEvaluator().evaluate_row(_row())
    assert complete.metrics["artifact_bundle_complete"] is True
    assert complete.metrics["audit_bundle_score"] == 1.0

    (tmp_path / "prompt.txt").write_text("Generate NaCl.", encoding="utf-8")
    incomplete = AuditBundleCompletenessBenchmarkEvaluator().evaluate_row({"run_bundle_dir": str(tmp_path)})
    assert incomplete.metrics["artifact_bundle_complete"] is False
    assert incomplete.metrics["missing_artifact_count"] > 0


def test_retrieval_ablation_runner_works_with_fake_generator(tmp_path: Path) -> None:
    summary = tmp_path / "ablation.csv"
    result = runner.invoke(
        app,
        [
            "run-retrieval-ablation-benchmark",
            "--prompts",
            str(ROOT / "benchmarks" / "unique_verifiable_csp" / "retrieval_ablation_prompts.csv"),
            "--generator-command",
            "python tests\\fixtures\\fake_generator.py --prompt {prompt} --out-dir {out_dir} --attempts {num_attempts}",
            "--retrieval-modes",
            "none,metadata,evidence_spp",
            "--out-dir",
            str(tmp_path / "ablation_runs"),
            "--summary",
            str(summary),
            "--json",
            str(tmp_path / "ablation.json"),
            "--markdown",
            str(tmp_path / "ablation.md"),
        ],
    )
    assert result.exit_code == 0, result.output
    frame = pd.read_csv(summary)
    assert "evidence_spp_vs_none_delta" in frame.columns
    assert (frame["retrieval_mode"] == "uplift").any()


def test_repairability_runner_works_with_fake_repair(tmp_path: Path) -> None:
    summary = tmp_path / "repair.csv"
    result = runner.invoke(
        app,
        [
            "run-repairability-benchmark",
            "--cases",
            str(ROOT / "benchmarks" / "unique_verifiable_csp" / "repair_cases.csv"),
            "--repair-command",
            "python tests\\fixtures\\fake_repair.py --input-cif {input_cif} --prompt {prompt} --out-dir {out_dir}",
            "--out-dir",
            str(tmp_path / "repair_runs"),
            "--summary",
            str(summary),
            "--json",
            str(tmp_path / "repair.json"),
            "--markdown",
            str(tmp_path / "repair.md"),
        ],
    )
    assert result.exit_code == 0, result.output
    frame = pd.read_csv(summary)
    assert frame.loc[frame["case_id"] == "ALL", "repair_attempt_success_rate"].iloc[0] == 1.0


def test_unique_composite_score_computes_expected_value() -> None:
    row = {
        "output_validity": 1.0,
        "constraint_faithfulness_score": 0.5,
        "structure_or_prototype_match_score": 0.5,
        "mlip_or_relaxation_robustness_score": 0.0,
        "evidence_trace_score": 1.0,
        "audit_bundle_score": 1.0,
        "solver_certificate_score": 1.0,
    }
    assert compute_unique_composite(row) == 0.675


def test_unique_csp_benchmark_summary_writes_markdown_sections(tmp_path: Path) -> None:
    results = tmp_path / "results.csv"
    pd.DataFrame([{"pre_dft_valid": True, "structure_match": True}]).to_csv(results, index=False)
    markdown = tmp_path / "unique.md"
    result = runner.invoke(
        app,
        [
            "unique-csp-benchmark-summary",
            "--results",
            str(results),
            "--bundles",
            str(BUNDLE),
            "--out",
            str(tmp_path / "unique.csv"),
            "--json",
            str(tmp_path / "unique.json"),
            "--markdown",
            str(markdown),
        ],
    )
    assert result.exit_code == 0, result.output
    text = markdown.read_text(encoding="utf-8")
    for section in (
        "## Summary",
        "## Evidence traceability",
        "## Repairability",
        "## Why this benchmark is different",
    ):
        assert section in text


def test_prompt_suite_csvs_parse() -> None:
    root = ROOT / "benchmarks" / "unique_verifiable_csp"
    for name in (
        "traceable_csp_prompts_v1.csv",
        "infeasible_prompts.csv",
        "retrieval_ablation_prompts.csv",
        "repair_cases.csv",
        "evidence_trap_prompts.csv",
    ):
        frame = pd.read_csv(root / name)
        assert not frame.empty


def test_all_new_clis_show_help() -> None:
    for command in (
        "inspect-run-bundle",
        "run-retrieval-ablation-benchmark",
        "run-repairability-benchmark",
        "unique-csp-benchmark-summary",
    ):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, result.output


def _row() -> dict:
    return {
        "run_bundle_dir": str(BUNDLE),
        "target_formula": "BaTiO3",
        "target_structure_family": "perovskite",
        "target_space_group": 221,
        "formula": "BaTiO3",
        "reduced_formula": "BaTiO3",
        "target_formula_match": True,
        "detected_space_group": 221,
        "space_group_consistent": True,
        "min_distance": 2.0,
        "num_bad_contacts": 0,
    }


def _copy_bundle_minimal(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.is_file():
            (dest / path.name).write_bytes(path.read_bytes())
