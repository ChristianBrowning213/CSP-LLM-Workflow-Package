from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.cli import app
from sca.traceability.adapters.llm_csp_archive import (
    detect_llm_csp_archive,
    load_llm_csp_archive,
)
from sca.traceability.io import inspect_run_bundle


ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = ROOT / "tests" / "fixtures" / "run_archives"
runner = CliRunner()


def test_archive_detection() -> None:
    assert detect_llm_csp_archive(ARCHIVES / "complete_run") is True
    assert detect_llm_csp_archive(ARCHIVES / "cif_only") is True
    assert detect_llm_csp_archive(ROOT / "tests" / "fixtures") is True
    assert detect_llm_csp_archive(ROOT / "does_not_exist") is False


def test_load_archive_maps_realish_artifacts() -> None:
    bundle = load_llm_csp_archive(ARCHIVES / "complete_run", run_id="run_001")
    assert bundle.run_id == "run_001"
    assert bundle.retrieval_trace is not None
    assert bundle.retrieval_trace.retrieved[0].evidence_id == "ev_batio3"
    assert bundle.solver_trace is not None
    assert bundle.solver_trace.solver_status == "optimal"
    assert bundle.generated_candidates is not None
    assert bundle.generated_candidates.candidates


def test_single_conversion_writes_bundle_and_inspects(tmp_path: Path) -> None:
    out_dir = tmp_path / "bundle"
    result = runner.invoke(
        app,
        [
            "convert-run-archive-to-bundle",
            "--archive",
            str(ARCHIVES / "complete_run"),
            "--out-dir",
            str(out_dir),
            "--run-id",
            "run_001",
            "--markdown",
            str(tmp_path / "inspection.md"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "bundle.json").exists()
    assert (out_dir / "bundle_manifest.csv").exists()
    inspection = inspect_run_bundle(out_dir)
    assert inspection.bundle_valid is True


def test_missing_artifacts_are_recorded(tmp_path: Path) -> None:
    out_dir = tmp_path / "missing_retrieval"
    result = runner.invoke(
        app,
        [
            "convert-run-archive-to-bundle",
            "--archive",
            str(ARCHIVES / "missing_retrieval"),
            "--out-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = pd.read_csv(out_dir / "bundle_manifest.csv")
    missing = manifest["missing_source_artifacts"].iloc[0]
    assert "retrieval_trace" in missing
    inspection = inspect_run_bundle(out_dir)
    assert inspection.bundle_valid is False
    assert "retrieval_trace" in inspection.missing_artifacts


def test_invalid_json_is_reported_without_crashing(tmp_path: Path) -> None:
    out_dir = tmp_path / "invalid"
    result = runner.invoke(
        app,
        [
            "convert-run-archive-to-bundle",
            "--archive",
            str(ARCHIVES / "invalid_json"),
            "--out-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads((out_dir / "bundle.json").read_text(encoding="utf-8"))
    assert any("retrieval_trace.json" in error for error in data["errors"])


def test_batch_conversion_and_unique_summary(tmp_path: Path) -> None:
    bundles = tmp_path / "bundles"
    summary = tmp_path / "conversion.csv"
    result = runner.invoke(
        app,
        [
            "convert-run-archives-to-bundles",
            "--archives-root",
            str(ARCHIVES),
            "--out-dir",
            str(bundles),
            "--summary",
            str(summary),
        ],
    )
    assert result.exit_code == 0, result.output
    frame = pd.read_csv(summary)
    assert {"complete_run", "missing_retrieval", "missing_solver", "cif_only", "invalid_json"}.issubset(
        set(frame["run_id"])
    )

    unique = runner.invoke(
        app,
        [
            "unique-csp-benchmark-summary",
            "--bundles",
            str(bundles),
            "--out",
            str(tmp_path / "unique.csv"),
            "--json",
            str(tmp_path / "unique.json"),
            "--markdown",
            str(tmp_path / "unique.md"),
        ],
    )
    assert unique.exit_code == 0, unique.output
    assert "# Unique Verifiable CSP Benchmark Report" in (tmp_path / "unique.md").read_text(encoding="utf-8")


def test_conversion_help_commands() -> None:
    for command in ("convert-run-archive-to-bundle", "convert-run-archives-to-bundles"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, result.output
