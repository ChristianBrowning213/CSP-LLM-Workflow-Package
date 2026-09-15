from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.cli import app


FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


class FakeChgnet:
    def predict_structure(self, structure):
        return {"energy_per_atom": -0.8, "forces": [[0.0, 0.0, 0.0] for _ in structure]}


def test_property_targets_and_predicted_hull_from_manifest(tmp_path: Path, monkeypatch) -> None:
    import sca.evaluators.chgnet as chgnet

    monkeypatch.setattr(chgnet, "_load_chgnet_model", lambda: FakeChgnet())
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    (cif_dir / "tiny_valid.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,target_formation_energy_per_atom,target_energy_above_hull,"
        "target_band_gap,target_property_name,target_property_value,method\n"
        "cifs/tiny_valid.cif,-1.0,0.0,1.5,formation_energy_per_atom,-1.0,m\n",
        encoding="utf-8",
    )
    hull_refs = tmp_path / "hull_refs.csv"
    hull_refs.write_text(
        "material_id,formula,formation_energy_per_atom,source\n"
        "Na,Na,0.0,fixture\n"
        "Cl,Cl,0.0,fixture\n"
        "NaCl,NaCl,-1.0,fixture\n",
        encoding="utf-8",
    )
    csv_out = tmp_path / "bench.csv"
    jsonl_out = tmp_path / "bench.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "manifest",
            str(manifest),
            "--evaluators",
            "chgnet_static,property_targets,predicted_hull",
            "--hull-reference",
            str(hull_refs),
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["target_formation_energy_per_atom"].tolist() == [-1.0]
    assert frame["target_energy_above_hull"].tolist() == [0.0]
    assert frame["target_band_gap"].tolist() == [1.5]
    assert frame["property_target_ok"].tolist() == [True]
    assert frame["formation_energy_error"].round(6).tolist() == [0.2]
    assert frame["property_error"].round(6).tolist() == [0.2]
    assert frame["hull_ok"].tolist() == [True]
    assert frame["predicted_energy_above_hull"].round(6).tolist() == [0.2]
    assert frame["predicted_hull_energy_source"].tolist() == ["predicted_surrogate"]
    assert "predicted_energy_above_hull" in jsonl_out.read_text(encoding="utf-8")


def test_predicted_hull_missing_reference_is_structured(tmp_path: Path, monkeypatch) -> None:
    import sca.evaluators.chgnet as chgnet

    monkeypatch.setattr(chgnet, "_load_chgnet_model", lambda: FakeChgnet())
    csv_out = tmp_path / "bench.csv"
    jsonl_out = tmp_path / "bench.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "one",
            str(FIXTURES / "tiny_valid.cif"),
            "--evaluators",
            "chgnet_static,predicted_hull",
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["hull_ok"].tolist() == [False]
    assert frame["evaluator_predicted_hull_skipped"].tolist() == [True]
    assert frame["hull_error"].tolist() == ["hull_reference_path was not provided"]


def test_benchmark_summary_includes_property_and_hull_columns(tmp_path: Path) -> None:
    benchmark_csv = tmp_path / "bench.csv"
    pd.DataFrame(
        [
            {
                "method": "m",
                "parse_ok": True,
                "hull_ok": True,
                "predicted_energy_above_hull": 0.2,
                "property_target_ok": True,
                "property_error": 0.3,
            },
            {
                "method": "m",
                "parse_ok": True,
                "hull_ok": False,
                "predicted_energy_above_hull": 0.4,
                "property_target_ok": False,
                "property_error": -0.1,
            },
        ]
    ).to_csv(benchmark_csv, index=False)
    summary_out = tmp_path / "summary.csv"

    result = runner.invoke(
        app,
        ["benchmark-summary", str(benchmark_csv), "--group-col", "method", "--out", str(summary_out)],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(summary_out)
    assert frame["predicted_hull_ok_rate"].tolist() == [0.5]
    assert frame["median_predicted_energy_above_hull"].tolist() == [0.3]
    assert frame["property_target_ok_rate"].tolist() == [0.5]
    assert frame["median_abs_property_error"].tolist() == [0.2]

