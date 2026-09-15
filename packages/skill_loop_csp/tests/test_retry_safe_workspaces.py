from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from sok_llm_orchestrator.workflow.runner import (
    WorkflowConfig,
    _prepare_execution_attempt,
    _update_execution_attempt,
    _workflow_run_id,
)


REQUEST = "COMPATIBILITY-SMOKE: generate cubic CsPbBr3 halide perovskite."


def config(root: Path) -> WorkflowConfig:
    return WorkflowConfig(output_root=root / "run")


def manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_interrupted_attempt_is_recorded_and_retry_gets_fresh_workspace() -> None:
    with TemporaryDirectory() as directory:
        cfg = config(Path(directory))
        first = _prepare_execution_attempt(cfg, REQUEST, attempt_id="attempt-one")
        _update_execution_attempt(first, "RUNNING")
        retry = _prepare_execution_attempt(cfg, REQUEST, attempt_id="attempt-two")
        assert retry.run_id == first.run_id
        assert retry.attempt_id != first.attempt_id
        assert retry.workspace != first.workspace
        assert retry.prior_incomplete_attempts == ("attempt-one",)
        assert manifest(first.manifest_path)["status"] == "INTERRUPTED_OR_INCOMPLETE"
        assert first.workspace.is_dir()


def test_completed_attempt_is_never_overwritten() -> None:
    with TemporaryDirectory() as directory:
        cfg = config(Path(directory))
        completed = _prepare_execution_attempt(cfg, REQUEST, attempt_id="completed")
        marker = completed.workspace / "scientific-result.txt"
        marker.write_text("preserve", encoding="utf-8")
        _update_execution_attempt(completed, "COMPLETED")
        with pytest.raises(FileExistsError, match="terminal attempt"):
            _prepare_execution_attempt(cfg, REQUEST, attempt_id="completed")
        assert marker.read_text(encoding="utf-8") == "preserve"
        assert manifest(completed.manifest_path)["status"] == "COMPLETED"


def test_unknown_preexisting_path_is_not_deleted_or_modified() -> None:
    with TemporaryDirectory() as directory:
        cfg = config(Path(directory))
        unknown = Path(cfg.output_root) / "attempts" / "unknown"
        unknown.mkdir(parents=True)
        marker = unknown / "owner-data.txt"
        marker.write_text("untouched", encoding="utf-8")
        with pytest.raises(FileExistsError, match="unknown pre-existing"):
            _prepare_execution_attempt(cfg, REQUEST, attempt_id="unknown")
        assert marker.read_text(encoding="utf-8") == "untouched"


def test_run_id_is_stable_but_attempt_ids_and_workspaces_differ() -> None:
    with TemporaryDirectory() as directory:
        cfg = config(Path(directory))
        assert _workflow_run_id(REQUEST, cfg) == _workflow_run_id(REQUEST, cfg)
        first = _prepare_execution_attempt(cfg, REQUEST)
        _update_execution_attempt(first, "FAILED_SOFTWARE")
        second = _prepare_execution_attempt(cfg, REQUEST)
        assert first.run_id == second.run_id
        assert first.attempt_id != second.attempt_id
        assert first.workspace != second.workspace


def test_scale_spp_root_direct_overwrite_remains_rejected() -> None:
    from spp_maker.calibration import scale_spp_root

    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        destination = root / "destination"
        source.mkdir()
        destination.mkdir()
        with pytest.raises(ValueError, match="out_root already exists"):
            scale_spp_root(source, destination, 1.0, convention="reward")
