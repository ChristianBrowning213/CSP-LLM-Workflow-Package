from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.cli import app


FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_sun_benchmark_uniqueness_novelty_and_missing_stability(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    references = tmp_path / "references"
    generated.mkdir()
    references.mkdir()
    (generated / "nacl_a.cif").write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    (generated / "nacl_b.cif").write_text((FIXTURES / "tiny_valid_copy.cif").read_text(encoding="utf-8"), encoding="utf-8")
    (generated / "kbr.cif").write_text(_kbr_cif(), encoding="utf-8")
    (references / "nacl_ref.cif").write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")

    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,sample_id\n"
        "generated/nacl_a.cif,a\n"
        "generated/nacl_b.cif,b\n"
        "generated/kbr.cif,c\n",
        encoding="utf-8",
    )
    reference_manifest = tmp_path / "reference_manifest.csv"
    reference_manifest.write_text("cif_path,ref_id\nreferences/nacl_ref.cif,nacl-ref\n", encoding="utf-8")
    out_dir = tmp_path / "sun"

    result = runner.invoke(
        app,
        [
            "run-sun-benchmark",
            "--manifest",
            str(manifest),
            "--reference-manifest",
            str(reference_manifest),
            "--reference-id-col",
            "ref_id",
            "--out-dir",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    rows = pd.read_csv(out_dir / "sun_results.csv")
    clusters = pd.read_csv(out_dir / "sun_duplicate_clusters.csv")
    summary = json.loads((out_dir / "sun_summary.json").read_text(encoding="utf-8"))
    report = (out_dir / "sun_report.md").read_text(encoding="utf-8")

    assert len(rows) == 3
    assert summary["num_generated"] == 3
    assert summary["num_unique_structures"] == 2
    assert summary["uniqueness_rate"] < 1.0
    assert rows.loc[rows["sample_id"] == "a", "known_match"].iloc[0] == True  # noqa: E712
    assert rows.loc[rows["sample_id"] == "c", "novel"].iloc[0] == True  # noqa: E712
    assert summary["novelty_rate"] == 1 / 3
    assert summary["stability_status"] == "not_computable"
    assert "predicted_energy_above_hull" in summary["stability_required_inputs"]
    assert "not an MP-20 training/test leaderboard claim" in report
    assert "### Duplicate Clusters" in report
    assert clusters["cluster_size"].sum() == len(rows)
    assert {"cluster_id", "cluster_size", "representative_cif_path", "formulas", "prompt_ids"}.issubset(clusters.columns)


def test_sun_benchmark_stability_columns(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "nacl.cif").write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    (generated / "kbr.cif").write_text(_kbr_cif(), encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,predicted_energy_above_hull,formation_energy_per_atom\n"
        "generated/nacl.cif,0.03,-1.2\n"
        "generated/kbr.cif,0.20,-0.8\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "run-sun-benchmark",
            "--manifest",
            str(manifest),
            "--out-dir",
            str(tmp_path / "sun"),
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads((tmp_path / "sun" / "sun_summary.json").read_text(encoding="utf-8"))
    assert summary["stability_status"] == "computable"
    assert summary["stable_under_0.05ev_per_atom_rate"] == 0.5
    assert summary["formation_energy_per_atom_mean"] == -1.0


def test_build_reference_manifest_and_use_for_novelty(tmp_path: Path) -> None:
    reference_dir = tmp_path / "reference_sets" / "tiny" / "cifs"
    generated_dir = tmp_path / "generated"
    reference_dir.mkdir(parents=True)
    generated_dir.mkdir()
    (reference_dir / "nacl_ref.cif").write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    (generated_dir / "nacl.cif").write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    (generated_dir / "kbr.cif").write_text(_kbr_cif(), encoding="utf-8")
    reference_manifest = tmp_path / "reference_sets" / "tiny" / "metadata.csv"

    build = runner.invoke(
        app,
        [
            "build-reference-manifest",
            "--cif-dir",
            str(reference_dir),
            "--out",
            str(reference_manifest),
            "--reference-set-name",
            "tiny",
        ],
    )

    assert build.exit_code == 0, build.output
    refs = pd.read_csv(reference_manifest)
    assert len(refs) == 1
    assert Path(refs["cif_path"].iloc[0]).is_absolute()
    assert refs["reference_set_name"].tolist() == ["tiny"]

    generated_manifest = tmp_path / "manifest.csv"
    generated_manifest.write_text(
        "cif_path,sample_id\n"
        "generated/nacl.cif,nacl\n"
        "generated/kbr.cif,kbr\n",
        encoding="utf-8",
    )
    sun = runner.invoke(
        app,
        [
            "run-sun-benchmark",
            "--manifest",
            str(generated_manifest),
            "--reference-manifest",
            str(reference_manifest),
            "--reference-id-col",
            "reference_id",
            "--out-dir",
            str(tmp_path / "sun_from_ref_manifest"),
        ],
    )

    assert sun.exit_code == 0, sun.output
    rows = pd.read_csv(tmp_path / "sun_from_ref_manifest" / "sun_results.csv")
    assert rows.loc[rows["sample_id"] == "nacl", "known_match"].iloc[0] == True  # noqa: E712
    assert rows.loc[rows["sample_id"] == "kbr", "novel"].iloc[0] == True  # noqa: E712


def _kbr_cif() -> str:
    return (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8").replace("data_NaCl", "data_KBr").replace("Na1 Na", "K1 K").replace("Cl1 Cl", "Br1 Br")
