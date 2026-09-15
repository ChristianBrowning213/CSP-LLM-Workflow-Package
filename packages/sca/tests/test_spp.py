from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.cli import app
from sca.spp.schema import SppArtifact, load_spp_artifact


FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _write_spp(path: Path, include_pair: bool = True) -> None:
    species_pairs = {}
    if include_pair:
        species_pairs["Cl--Na"] = {
            "bin_edges": [0.0, 2.0, 4.0, 8.0],
            "penalties": [10.0, 0.5, 2.0],
            "tail_penalty": 20.0,
        }
    else:
        species_pairs["Na--Na"] = {
            "bin_edges": [0.0, 8.0],
            "penalties": [1.0],
        }
    path.write_text(
        SppArtifact(
            species_pairs=species_pairs,
            corpus_hash="fixture",
            cutoff_policy={"cutoff": 8.0},
            provenance={"created_by": "test"},
            corpus_summary={"num_structures": 1},
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )


def test_spp_artifact_schema_roundtrip(tmp_path: Path) -> None:
    artifact_path = tmp_path / "spp.v1.json"
    _write_spp(artifact_path)

    artifact = load_spp_artifact(artifact_path)

    assert artifact.schema_version == "1.0"
    assert artifact.corpus_hash == "fixture"
    assert artifact.species_pairs["Cl--Na"].penalties == [10.0, 0.5, 2.0]


def test_benchmark_spp_scores_and_reports_missing_pairs(tmp_path: Path) -> None:
    artifact_path = tmp_path / "spp.v1.json"
    _write_spp(artifact_path, include_pair=False)
    csv_out = tmp_path / "spp.csv"
    jsonl_out = tmp_path / "spp.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "one",
            str(FIXTURES / "tiny_valid.cif"),
            "--evaluators",
            "spp",
            "--spp-artifact",
            str(artifact_path),
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["spp_ok"].tolist() == [True]
    assert frame["spp_missing_pair_count"].tolist() == [1]
    assert "benchmark_rank_score" in frame.columns
    assert "per_pair_breakdown" in jsonl_out.read_text(encoding="utf-8")


def test_registry_lists_spp_and_mlip_evaluators() -> None:
    result = runner.invoke(app, ["list-evaluators"])

    assert result.exit_code == 0
    for name in ("spp", "m3gnet_static", "mace_static", "sevennet_static", "mlip_ensemble"):
        assert name in result.output


def test_mlip_missing_dependencies_are_structured(tmp_path: Path) -> None:
    csv_out = tmp_path / "mlip.csv"
    jsonl_out = tmp_path / "mlip.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "one",
            str(FIXTURES / "tiny_valid.cif"),
            "--evaluators",
            "mace_static,sevennet_static",
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["mace_ok"].tolist() == [False]
    assert frame["sevennet_ok"].tolist() == [False]
    assert frame["evaluator_mace_static_skipped"].tolist() == [True]
    assert frame["evaluator_sevennet_static_skipped"].tolist() == [True]


def test_mlip_ensemble_flags_disagreement(tmp_path: Path, monkeypatch) -> None:
    import sca.evaluators.chgnet as chgnet

    class FakeChgnet:
        def predict_structure(self, structure):
            return {"energy_per_atom": -1.0, "forces": [[0.0, 0.0, 0.0] for _ in structure]}

    monkeypatch.setattr(chgnet, "_load_chgnet_model", lambda: FakeChgnet())
    monkeypatch.setenv("SCA_MLIP_DISAGREEMENT_THRESHOLD", "0.1")
    csv_out = tmp_path / "ensemble.csv"
    jsonl_out = tmp_path / "ensemble.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "one",
            str(FIXTURES / "tiny_valid.cif"),
            "--evaluators",
            "chgnet_static,mlip_ensemble",
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["mlip_energy_mean"].tolist() == [-1.0]
    assert frame["evaluator_mlip_ensemble_skipped"].tolist() == [True]
