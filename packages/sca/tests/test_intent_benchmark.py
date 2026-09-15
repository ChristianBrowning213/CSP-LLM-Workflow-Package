from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.cli import app
from sca.evaluators.intent_satisfaction import IntentSatisfactionBenchmarkEvaluator


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
runner = CliRunner()


def test_build_intent_benchmark_manifest_creates_100_rows(tmp_path: Path) -> None:
    csv_out = tmp_path / "intent_prompts_100.csv"
    json_out = tmp_path / "intent_prompts_100.json"

    result = runner.invoke(
        app,
        [
            "build-intent-benchmark-manifest",
            "--out",
            str(csv_out),
            "--json",
            str(json_out),
            "--seed",
            "20260626",
            "--num-prompts",
            "100",
        ],
    )

    assert result.exit_code == 0, result.output
    frame = pd.read_csv(csv_out)
    assert len(frame) == 100
    assert set(frame["seed"]) == {20260626}
    assert frame["benchmark_mode"].value_counts().to_dict() == {
        "loose_design_intent": 30,
        "motif_specific": 25,
        "retrieval_evidence_grounded": 15,
        "solver_constraint_heavy": 15,
        "adversarial_or_infeasible": 10,
        "repair_or_diagnostic": 5,
    }
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert len(data["rows"]) == 100


def test_run_skill_loop_intent_benchmark_with_fake_generator(tmp_path: Path) -> None:
    prompts = _write_100_prompt_manifest(tmp_path)
    out_root = tmp_path / "run"
    command = _fake_command()

    result = runner.invoke(
        app,
        [
            "run-skill-loop-intent-benchmark",
            "--prompts",
            str(prompts),
            "--skill-loop-command",
            command,
            "--out-root",
            str(out_root),
            "--seed",
            "20260626",
            "--num-attempts",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    log = pd.read_csv(out_root / "logs" / "generation_log.csv")
    assert len(log) == 100
    assert (log["status"] == "generator_failed").sum() == 0
    manifest = pd.read_csv(out_root / "manifests" / "generated_cifs_manifest_for_sca.csv")
    assert not manifest.empty
    assert {"cif_path", "prompt_id", "intent_constraints_json", "raw_run_dir"}.issubset(manifest.columns)
    assert Path(manifest["cif_path"].iloc[0]).is_absolute()
    assert Path(manifest["raw_run_dir"].iloc[0]).is_absolute()
    assert Path(manifest["run_dir"].iloc[0]).is_absolute()
    adversarial = log[log["benchmark_mode"] == "adversarial_or_infeasible"]
    assert set(adversarial["status"]) == {"infeasible_or_invalid"}


def test_skill_loop_intent_benchmark_writes_structured_task_spec(tmp_path: Path) -> None:
    prompts = _write_100_prompt_manifest(tmp_path)
    out_root = tmp_path / "run"
    script = FIXTURES / "fake_skill_loop_intent_generator.py"
    command = f"{sys.executable} {script} --prompt {{prompt}} --out-dir {{out_dir}} --seed {{seed}} --task-spec {{task_spec_json}}"

    result = runner.invoke(
        app,
        [
            "run-skill-loop-intent-benchmark",
            "--prompts",
            str(prompts),
            "--skill-loop-command",
            command,
            "--out-root",
            str(out_root),
            "--seed",
            "20260626",
            "--num-attempts",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    task_spec_path = out_root / "skill_loop_raw_runs" / "run_001" / "task_spec.json"
    task_spec = json.loads(task_spec_path.read_text(encoding="utf-8"))
    assert task_spec["symmetry_request"]["space_group"] == "Pm-3m or subgroup"
    assert task_spec["symmetry_request"]["hardness"] == "hard"
    assert task_spec["target_crystal_system"] == "cubic/tetragonal"
    assert task_spec["target_structure_family"] == "perovskite"
    log = pd.read_csv(out_root / "logs" / "generation_log.csv")
    command_text = log.loc[log["run_index"] == 1, "command"].iloc[0]
    assert "task_spec.json" in command_text
    assert "run_001" in command_text


def test_intent_satisfaction_positive_and_negative(tmp_path: Path) -> None:
    cif = tmp_path / "candidate.cif"
    cif.write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    evaluator = IntentSatisfactionBenchmarkEvaluator()

    positive = evaluator.evaluate_row(
        {
            "input_path": str(cif),
            "target_formula": "NaCl",
            "target_structure_family": "rocksalt",
            "target_space_group": "P 1",
            "target_crystal_system": "triclinic",
            "input_text": "Generate rocksalt NaCl.",
            "intent_constraints_json": json.dumps({"formula": "NaCl", "structure_family": "rocksalt", "expected_solver_status": "expected_valid"}),
        }
    )
    negative = evaluator.evaluate_row(
        {
            "input_path": str(cif),
            "target_formula": "BaTiO3",
            "target_structure_family": "perovskite",
            "input_text": "Generate perovskite BaTiO3.",
            "intent_constraints_json": json.dumps({"formula": "BaTiO3", "structure_family": "perovskite", "expected_solver_status": "expected_valid"}),
        }
    )

    assert positive.metrics["intent_formula_satisfied"] is True
    assert positive.metrics["intent_satisfaction_score"] > negative.metrics["intent_satisfaction_score"]
    assert negative.metrics["intent_formula_satisfied"] is False


def test_full_intent_evaluation_on_fake_outputs(tmp_path: Path) -> None:
    out_root = _run_small_one_shot(tmp_path, skip_evaluation=True)
    manifest = out_root / "manifests" / "generated_cifs_manifest_for_sca.csv"

    result = runner.invoke(
        app,
        [
            "run-full-intent-benchmark-evaluation",
            "--run-root",
            str(out_root),
            "--manifest",
            str(manifest),
            "--seed",
            "20260626",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (out_root / "sca_intent_benchmark" / "intent_results.csv").exists()
    assert (out_root / "diagnostics" / "grouped_by_benchmark_mode.csv").exists()
    assert (out_root / "reports" / "FULL_100_INTENT_BENCHMARK_REPORT.md").exists()


def test_one_shot_cli_small_fake_generator(tmp_path: Path) -> None:
    out_root = _run_small_one_shot(tmp_path, skip_evaluation=False)

    assert (out_root / "prompts" / "intent_prompts_5.csv").exists()
    assert (out_root / "logs" / "generation_log.csv").exists()
    assert (out_root / "reports" / "FULL_100_INTENT_BENCHMARK_SUMMARY.json").exists()


def test_adversarial_no_cif_is_not_generator_crash(tmp_path: Path) -> None:
    prompts = _write_100_prompt_manifest(tmp_path)
    out_root = tmp_path / "run"
    result = runner.invoke(
        app,
        [
            "run-skill-loop-intent-benchmark",
            "--prompts",
            str(prompts),
            "--skill-loop-command",
            _fake_command(),
            "--out-root",
            str(out_root),
            "--seed",
            "20260626",
        ],
    )

    assert result.exit_code == 0, result.output
    log = pd.read_csv(out_root / "logs" / "generation_log.csv")
    adversarial = log[log["benchmark_mode"] == "adversarial_or_infeasible"]
    assert (adversarial["num_cifs_found"] == 0).all()
    assert (adversarial["status"] == "infeasible_or_invalid").all()


def _write_100_prompt_manifest(tmp_path: Path) -> Path:
    csv_out = tmp_path / "intent_prompts_100.csv"
    result = runner.invoke(
        app,
        [
            "build-intent-benchmark-manifest",
            "--out",
            str(csv_out),
            "--seed",
            "20260626",
            "--num-prompts",
            "100",
        ],
    )
    assert result.exit_code == 0, result.output
    return csv_out


def _fake_command() -> str:
    script = FIXTURES / "fake_skill_loop_intent_generator.py"
    return f"{sys.executable} {script} --prompt {{prompt}} --out-dir {{out_dir}} --seed {{seed}}"


def _run_small_one_shot(tmp_path: Path, *, skip_evaluation: bool) -> Path:
    out_root = tmp_path / ("one_shot_no_eval" if skip_evaluation else "one_shot")
    args = [
        "run-full-skill-loop-intent-benchmark",
        "--skill-loop-command",
        _fake_command(),
        "--out-root",
        str(out_root),
        "--seed",
        "20260626",
        "--num-prompts",
        "5",
    ]
    if skip_evaluation:
        args.append("--skip-evaluation")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return out_root
