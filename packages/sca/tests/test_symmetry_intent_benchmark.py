from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.benchmark_protocols.symmetry_intent import evaluate_symmetry_intent_row
from sca.cli import app


FIXTURES = Path("tests/fixtures")
runner = CliRunner()


def test_symmetry_intent_exact_target_sg_match() -> None:
    row = _row("Pm-3m", "cubic", "perovskite")

    result = evaluate_symmetry_intent_row(row)

    assert result["declared_space_group"] == "P 1"
    assert result["declared_space_group_number"] == 1
    assert result["analyzed_space_group"] == "Pm-3m"
    assert result["analyzed_space_group_number"] == 221
    assert result["space_group_exact_match"] is True
    assert result["space_group_number_match"] is True
    assert result["symmetry_match_level"] == "exact_space_group"
    assert result["symmetry_score"] == 1.0


def test_symmetry_intent_declared_p1_can_analyze_higher_symmetry() -> None:
    result = evaluate_symmetry_intent_row(_row("221", "cubic", "rocksalt"))

    assert result["declared_space_group"] == "P 1"
    assert result["analyzed_space_group"] == "Pm-3m"
    assert result["declared_space_group_number"] != result["analyzed_space_group_number"]


def test_symmetry_intent_same_crystal_system_different_sg() -> None:
    result = evaluate_symmetry_intent_row(_row("Fm-3m", "cubic", "rocksalt"))

    assert result["space_group_exact_match"] is False
    assert result["crystal_system_match"] is True
    assert result["symmetry_match_level"] == "same_crystal_system"
    assert result["symmetry_score"] == 0.75


def test_symmetry_intent_family_compatible_without_sg_target() -> None:
    result = evaluate_symmetry_intent_row(_row("", "", "rocksalt"))

    assert result["family_symmetry_compatible"] is True
    assert result["symmetry_match_level"] == "family_compatible"
    assert result["symmetry_score"] == 0.5


def test_symmetry_intent_missing_cif_is_not_computable(tmp_path: Path) -> None:
    row = _row("Pm-3m", "cubic", "perovskite")
    row["cif_path"] = str(tmp_path / "missing.cif")

    result = evaluate_symmetry_intent_row(row)

    assert result["symmetry_match_level"] == "not_computable"
    assert result["symmetry_status"] == "not_computable"
    assert "No such file" in result["symmetry_error"] or "cannot find" in result["symmetry_error"].lower()


def test_symmetry_intent_cli_writes_outputs(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        [
            _row("Pm-3m", "cubic", "perovskite"),
            _row("Fm-3m", "cubic", "rocksalt"),
        ]
    ).to_csv(manifest, index=False)

    result = runner.invoke(
        app,
        [
            "run-symmetry-intent-benchmark",
            "--manifest",
            str(manifest),
            "--out-dir",
            str(tmp_path / "symmetry"),
            "--symprec",
            "0.01",
            "--angle-tolerance",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    out = tmp_path / "symmetry"
    assert (out / "symmetry_results.csv").exists()
    assert (out / "symmetry_summary.json").exists()
    assert (out / "symmetry_report.md").exists()
    summary = json.loads((out / "symmetry_summary.json").read_text(encoding="utf-8"))
    assert summary["total_rows"] == 2
    assert summary["parseable_rows"] == 2
    assert "Family Compatibility Heuristic" in (out / "symmetry_report.md").read_text(encoding="utf-8")


def _row(space_group: str, crystal_system: str, family: str) -> dict[str, str]:
    return {
        "prompt_id": "p1",
        "benchmark_id": "b1",
        "target_formula": "NaCl",
        "target_structure_family": family,
        "target_space_group": space_group,
        "target_space_group_number": "",
        "target_crystal_system": crystal_system,
        "chemistry_family": family,
        "intent_constraints_json": "",
        "cif_path": str((FIXTURES / "tiny_valid.cif").resolve()),
    }
