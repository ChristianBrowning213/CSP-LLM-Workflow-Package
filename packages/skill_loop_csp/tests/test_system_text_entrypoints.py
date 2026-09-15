from __future__ import annotations

import json
import importlib.util
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

from sok_llm_orchestrator import system_entrypoint
from sok_llm_orchestrator.contracts.spp_regularisation import (
    CONFIG_C_REGULARISATION_SPP_DIR,
    CONFIG_C_REGULARISATION_WEIGHT,
)


LOW_LEVEL_TERMS = {
    "objective.energy_spp",
    "problem.objective",
    "context.pot_root",
    "supported_pairs",
    "missing_pairs",
}


def load_script_module(script_name: str):
    root = Path(__file__).resolve().parents[1]
    module_path = root / "scripts" / script_name
    module_name = f"_test_{module_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def repo_tmp_dir(name: str) -> Path:
    root = Path.cwd() / ".test_artifacts" / "system_text_entrypoints" / f"{name}_{uuid.uuid4().hex[:8]}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_run_text_request_calls_pipeline_and_records_summary(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_csp_pipeline(**kwargs):  # noqa: ANN001
        calls.append(dict(kwargs))
        workspace = Path(kwargs["workspace"])
        run_dir = workspace / "runs" / "fake-run"
        run_dir.mkdir(parents=True)
        (run_dir / "candidate.cif").write_text("data_fake\n", encoding="utf-8")
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({"status": "SUCCEEDED", "failure_reason": None}) + "\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            run_id="fake-run",
            run_dir=run_dir,
            manifest_path=manifest_path,
            status="SUCCEEDED",
        )

    monkeypatch.setattr(system_entrypoint, "_run_csp_pipeline", fake_run_csp_pipeline)
    out_root = repo_tmp_dir("run_text")
    summary = system_entrypoint.run_system_text(
        "Find a stable TiO2 crystal candidate",
        out_root=out_root,
        mode="stub",
    )

    assert calls
    assert calls[0]["query"] == "Find a stable TiO2 crystal candidate"
    assert calls[0]["mode"] == "stub"
    overrides = calls[0]["execution_overrides"]
    assert overrides["allow_qlip_without_spp"] is True
    assert overrides["spp_regularisation_dir"] == str(Path(CONFIG_C_REGULARISATION_SPP_DIR).resolve())
    assert overrides["spp_regularisation_weight"] == CONFIG_C_REGULARISATION_WEIGHT
    assert summary["status"] == "SUCCEEDED"
    assert summary["generated_cifs"]
    summary_path = Path(str(summary["summary_path"]))
    assert summary_path.exists()
    on_disk = json.loads(summary_path.read_text(encoding="utf-8"))
    assert on_disk["input"]["text"] == "Find a stable TiO2 crystal candidate"


def test_run_text_request_records_pipeline_failure(monkeypatch) -> None:
    def fake_run_csp_pipeline(**kwargs):  # noqa: ANN001, ARG001
        raise RuntimeError("pipeline unavailable")

    monkeypatch.setattr(system_entrypoint, "_run_csp_pipeline", fake_run_csp_pipeline)
    summary = system_entrypoint.run_system_text(
        "Find a stable MgO crystal candidate",
        out_root=repo_tmp_dir("failure"),
        mode="stub",
    )

    assert summary["status"] == "FAILED"
    assert summary["failure_reason"] == "pipeline unavailable"
    assert Path(str(summary["summary_path"])).exists()


def test_run_text_request_no_guidance_does_not_apply_regularisation_default(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_csp_pipeline(**kwargs):  # noqa: ANN001
        calls.append(dict(kwargs))
        workspace = Path(kwargs["workspace"])
        run_dir = workspace / "runs" / "fake-run"
        run_dir.mkdir(parents=True)
        (run_dir / "candidate.cif").write_text("data_fake\n", encoding="utf-8")
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({"status": "SUCCEEDED", "failure_reason": None}) + "\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            run_id="fake-run",
            run_dir=run_dir,
            manifest_path=manifest_path,
            status="SUCCEEDED",
        )

    monkeypatch.setattr(system_entrypoint, "_run_csp_pipeline", fake_run_csp_pipeline)
    summary = system_entrypoint.run_system_text(
        "Generate BaTiO3 without guidance",
        out_root=repo_tmp_dir("no_guidance"),
        mode="stub",
        with_spp=False,
    )

    assert summary["status"] == "SUCCEEDED"
    assert calls[0]["with_spp"] is False
    assert calls[0]["execution_overrides"] is None


def test_parse_prompt_lines_ignores_blank_and_comment_lines() -> None:
    prompts = system_entrypoint.parse_prompt_lines(
        """
        # comment
        Generate BaTiO3

        Generate LiF
          # another comment
        """
    )

    assert prompts == ["Generate BaTiO3", "Generate LiF"]


def test_batch_mode_writes_expected_outputs(monkeypatch) -> None:
    def fake_run_csp_pipeline(**kwargs):  # noqa: ANN001
        workspace = Path(kwargs["workspace"])
        run_dir = workspace / "runs" / "fake-run"
        run_dir.mkdir(parents=True)
        if "BaTiO3" in str(kwargs["query"]):
            (run_dir / "candidate.cif").write_text("data_fake\n", encoding="utf-8")
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({"status": "SUCCEEDED", "failure_reason": None}) + "\n",
            encoding="utf-8",
        )
        return SimpleNamespace(
            run_id="fake-run",
            run_dir=run_dir,
            manifest_path=manifest_path,
            status="SUCCEEDED",
        )

    monkeypatch.setattr(system_entrypoint, "_run_csp_pipeline", fake_run_csp_pipeline)
    out_root = repo_tmp_dir("batch")
    summary = system_entrypoint.run_text_batch(
        [
            "Generate a plausible BaTiO3 perovskite oxide candidate",
            "Generate a plausible LiF rocksalt-like ionic crystal candidate",
        ],
        out_root=out_root,
        batch_id="batch_test",
        mode="stub",
    )
    batch_root = out_root / "batch_test"

    assert summary["count"] == 2
    assert (batch_root / "batch_summary.json").exists()
    assert (batch_root / "batch_summary.md").exists()
    assert (batch_root / "generation_log.csv").exists()
    assert (batch_root / "generation_log.jsonl").exists()
    assert (batch_root / "generated_cifs_manifest.csv").exists()
    assert (batch_root / "runs" / "run_001").exists()
    assert (batch_root / "runs" / "run_002").exists()
    assert "candidate.cif" in (batch_root / "generated_cifs_manifest.csv").read_text(encoding="utf-8")


def test_text_entrypoint_scripts_stay_user_facing() -> None:
    root = Path(__file__).resolve().parents[1]
    for rel_path in [
        Path("scripts/run_system_from_terminal.py"),
        Path("scripts/run_system_from_file.py"),
    ]:
        source = (root / rel_path).read_text(encoding="utf-8")
        for term in LOW_LEVEL_TERMS:
            assert term not in source


def test_terminal_cli_returns_zero_for_recorded_pipeline_failure(monkeypatch) -> None:
    module = load_script_module("run_system_from_terminal.py")

    def fake_run_text_request(text, **kwargs):  # noqa: ANN001
        out_root = Path(kwargs["out_root"])
        run_root = out_root / str(kwargs["run_id"])
        run_root.mkdir(parents=True)
        summary_path = run_root / "summary.json"
        summary = {
            "status": "FAILED",
            "failure_reason": "pipeline unavailable",
            "summary_path": str(summary_path),
            "generated_cifs": [],
            "input": {"text": text},
        }
        summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        return summary

    monkeypatch.setattr(system_entrypoint, "run_text_request", fake_run_text_request)
    out_root = repo_tmp_dir("terminal_cli")
    code = module.main(
        [
            "Generate BaTiO3",
            "--out-root",
            str(out_root),
            "--run-id",
            "failed_run",
        ]
    )

    assert code == 0
    assert (out_root / "failed_run" / "summary.json").exists()


def test_terminal_cli_defaults_to_config_c_regularisation(monkeypatch) -> None:
    module = load_script_module("run_system_from_terminal.py")
    seen: dict[str, object] = {}

    def fake_run_text_request(text, **kwargs):  # noqa: ANN001
        seen.update(kwargs)
        out_root = Path(kwargs["out_root"])
        run_root = out_root / str(kwargs["run_id"])
        run_root.mkdir(parents=True)
        summary_path = run_root / "summary.json"
        summary = {"status": "SUCCEEDED", "summary_path": str(summary_path), "generated_cifs": []}
        summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        return summary

    monkeypatch.setattr(system_entrypoint, "run_text_request", fake_run_text_request)
    out_root = repo_tmp_dir("terminal_cli_config_c")
    code = module.main(["Generate BaTiO3", "--out-root", str(out_root), "--run-id", "run_001"])

    assert code == 0
    assert seen["regularisation_spp_dir"] == Path(CONFIG_C_REGULARISATION_SPP_DIR)


def test_terminal_cli_empty_regularisation_arg_disables_fallback(monkeypatch) -> None:
    module = load_script_module("run_system_from_terminal.py")
    seen: dict[str, object] = {}

    def fake_run_text_request(text, **kwargs):  # noqa: ANN001
        seen.update(kwargs)
        out_root = Path(kwargs["out_root"])
        run_root = out_root / str(kwargs["run_id"])
        run_root.mkdir(parents=True)
        summary_path = run_root / "summary.json"
        summary = {"status": "SUCCEEDED", "summary_path": str(summary_path), "generated_cifs": []}
        summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        return summary

    monkeypatch.setattr(system_entrypoint, "run_text_request", fake_run_text_request)
    out_root = repo_tmp_dir("terminal_cli_no_fallback")
    code = module.main(
        [
            "Generate BaTiO3",
            "--out-root",
            str(out_root),
            "--run-id",
            "run_001",
            "--regularisation-spp-dir",
            "",
        ]
    )

    assert code == 0
    assert seen["regularisation_spp_dir"] is None


def test_terminal_cli_returns_two_in_strict_pipeline_failure_mode(monkeypatch) -> None:
    module = load_script_module("run_system_from_terminal.py")

    def fake_run_text_request(text, **kwargs):  # noqa: ANN001, ARG001
        out_root = Path(kwargs["out_root"])
        run_root = out_root / str(kwargs["run_id"])
        run_root.mkdir(parents=True)
        summary_path = run_root / "summary.json"
        summary = {"status": "FAILED", "summary_path": str(summary_path), "generated_cifs": []}
        summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        return summary

    monkeypatch.setattr(system_entrypoint, "run_text_request", fake_run_text_request)
    out_root = repo_tmp_dir("terminal_cli_strict")
    code = module.main(
        [
            "Generate BaTiO3",
            "--out-root",
            str(out_root),
            "--run-id",
            "failed_run",
            "--fail-on-pipeline-failure",
        ]
    )

    assert code == 2
    assert (out_root / "failed_run" / "summary.json").exists()


def test_batch_cli_returns_zero_for_recorded_prompt_failures(monkeypatch) -> None:
    module = load_script_module("run_system_from_file.py")

    def fake_run_text_batch(prompts, **kwargs):  # noqa: ANN001
        batch_root = Path(kwargs["out_root"]) / str(kwargs["batch_id"])
        batch_root.mkdir(parents=True)
        summary_path = batch_root / "batch_summary.json"
        summary = {
            "count": len(prompts),
            "failed": 1,
            "succeeded": 0,
            "summary_path": str(summary_path),
            "runs": [],
        }
        summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        return summary

    monkeypatch.setattr(system_entrypoint, "run_text_batch", fake_run_text_batch)
    out_root = repo_tmp_dir("batch_cli")
    prompts_path = out_root / "prompts.txt"
    prompts_path.write_text("Generate BaTiO3\n", encoding="utf-8")
    code = module.main([str(prompts_path), "--out-root", str(out_root), "--batch-id", "batch_failed"])

    assert code == 0
    assert (out_root / "batch_failed" / "batch_summary.json").exists()


def test_batch_cli_returns_two_in_strict_pipeline_failure_mode(monkeypatch) -> None:
    module = load_script_module("run_system_from_file.py")

    def fake_run_text_batch(prompts, **kwargs):  # noqa: ANN001
        batch_root = Path(kwargs["out_root"]) / str(kwargs["batch_id"])
        batch_root.mkdir(parents=True)
        summary_path = batch_root / "batch_summary.json"
        summary = {
            "count": len(prompts),
            "failed": 1,
            "succeeded": 0,
            "summary_path": str(summary_path),
            "runs": [],
        }
        summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        return summary

    monkeypatch.setattr(system_entrypoint, "run_text_batch", fake_run_text_batch)
    out_root = repo_tmp_dir("batch_cli_strict")
    prompts_path = out_root / "prompts.txt"
    prompts_path.write_text("Generate BaTiO3\n", encoding="utf-8")
    code = module.main(
        [
            str(prompts_path),
            "--out-root",
            str(out_root),
            "--batch-id",
            "batch_failed",
            "--fail-on-pipeline-failure",
        ]
    )

    assert code == 2
    assert (out_root / "batch_failed" / "batch_summary.json").exists()


def test_file_script_help_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, "scripts/run_system_from_file.py", "--help"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "plain text file" in proc.stdout
