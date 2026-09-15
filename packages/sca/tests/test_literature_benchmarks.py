from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.benchmark_protocols.metrics import build_comparator_matrix, compute_metric_results
from sca.benchmark_protocols.registry import list_protocols, select_protocols
from sca.cli import app


runner = CliRunner()
FIXTURES = Path("tests/fixtures")


def test_protocol_registry_loads_literature_values() -> None:
    protocols = list_protocols()
    ids = {protocol.protocol_id for protocol in protocols}

    assert "validity_gruver_90" in ids
    assert "crystext_mp20_n1_match_rate" in ids
    assert "lang2str_mpts52_rmse" in ids
    assert "atomgpt_formation_energy_mae" in ids
    assert len(protocols) >= 20
    assert all(protocol.protocol_match_requirements for protocol in protocols)


def test_list_benchmark_protocols_cli_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "protocols.json"

    result = runner.invoke(app, ["list-benchmark-protocols", "--json", str(out)])

    assert result.exit_code == 0
    assert out.exists()
    assert "validity_gruver_90" in result.output


def test_comparator_matrix_higher_lower_threshold_and_not_computable(tmp_path: Path) -> None:
    results = tmp_path / "results.csv"
    pd.DataFrame(
        [
            {
                "parse_ok": True,
                "pre_dft_valid": True,
                "min_distance": 0.8,
                "structure_match": True,
                "benchmark_id": "a",
                "attempt_id": 1,
                "rms_dist": 0.01,
            },
            {
                "parse_ok": True,
                "pre_dft_valid": False,
                "min_distance": 0.4,
                "structure_match": False,
                "benchmark_id": "b",
                "attempt_id": 1,
                "rms_dist": 0.2,
            },
        ]
    ).to_csv(results, index=False)

    metrics = compute_metric_results(results)
    matrix = build_comparator_matrix(select_protocols("validity_gruver_90,min_distance_0_5_crystallm,lang2str_mp20_rmse,atomgpt_formation_energy_mae"), metrics, "subset_protocol")
    by_id = {row["comparator_name"]: row for row in matrix}

    assert by_id["validity_gruver_90"]["beats_paper"] is False
    assert by_id["min_distance_0_5_crystallm"]["beats_paper"] is True
    assert by_id["lang2str_mp20_rmse"]["beats_paper"] is False
    assert by_id["atomgpt_formation_energy_mae"]["beats_paper"] is None
    assert by_id["atomgpt_formation_energy_mae"]["protocol_match_level"] == "not_comparable"


def test_attempt_metrics_n1_nk_and_best_of_k(tmp_path: Path) -> None:
    results = tmp_path / "attempts.csv"
    pd.DataFrame(
        [
            {"benchmark_id": "a", "attempt_id": 1, "structure_match": False, "rms_dist": 0.5, "mlip_energy_mean": -1.0},
            {"benchmark_id": "a", "attempt_id": 2, "structure_match": True, "rms_dist": 0.1, "mlip_energy_mean": -2.0},
            {"benchmark_id": "b", "attempt_id": 1, "structure_match": False, "rms_dist": 0.4, "mlip_energy_mean": -0.5},
        ]
    ).to_csv(results, index=False)

    metrics = compute_metric_results(results)

    assert metrics["match_rate_n1"].our_value == 0.0
    assert metrics["match_rate_nk"].our_value == 0.5
    assert metrics["best_of_k_rms"].our_value == 0.25
    assert metrics["best_of_k_mlip_score"].our_value == -1.25


def test_benchmark_cif_set_folder_mode(tmp_path: Path) -> None:
    cifs = tmp_path / "cifs"
    cifs.mkdir()
    (cifs / "tiny.cif").write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "results.csv"
    summary = tmp_path / "summary.csv"
    json_out = tmp_path / "summary.json"
    markdown = tmp_path / "report.md"

    result = runner.invoke(
        app,
        [
            "benchmark-cif-set",
            "--cif-folder",
            str(cifs),
            "--protocols",
            "validity_gruver_90,atomgpt_formation_energy_mae",
            "--out",
            str(out),
            "--summary",
            str(summary),
            "--json",
            str(json_out),
            "--markdown",
            str(markdown),
        ],
    )

    assert result.exit_code == 0
    assert pd.read_csv(out)["parse_ok"].tolist() == [True]
    summary_frame = pd.read_csv(summary)
    assert "not_comparable" in summary_frame["protocol_match_level"].fillna("").tolist()
    assert "Literature-Replication Direct CIF Benchmark Report" in markdown.read_text(encoding="utf-8")


def test_benchmark_cif_set_manifest_mode_preserves_metadata(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,benchmark_id,target_formula,attempt_id,method\n"
        f"{(FIXTURES / 'tiny_valid.cif').resolve()},nacl,NaCl,1,tester\n",
        encoding="utf-8",
    )
    out = tmp_path / "results.csv"
    summary = tmp_path / "summary.csv"

    result = runner.invoke(
        app,
        [
            "benchmark-cif-set",
            "--manifest",
            str(manifest),
            "--protocols",
            "validity_gruver_90",
            "--out",
            str(out),
            "--summary",
            str(summary),
            "--json",
            str(tmp_path / "summary.json"),
            "--markdown",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(out)
    assert frame["benchmark_id"].tolist() == ["nacl"]
    assert frame["method"].tolist() == ["tester"]


def test_e2e_runner_with_fake_generator(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts.csv"
    prompts.write_text(
        "prompt_id,paper_source,benchmark_family,input_text,target_formula,target_structure_family,target_space_group,reference_cif_path,reference_id,num_attempts,expected_metrics,required_tools,notes\n"
        "p1,test,A_validity,Generate NaCl.,NaCl,rocksalt,,,,2,validity,none,test\n",
        encoding="utf-8",
    )
    summary = tmp_path / "summary.csv"
    markdown = tmp_path / "report.md"
    command = f'"{sys.executable}" tests\\fixtures\\fake_generator.py --prompt {{prompt}} --out-dir {{out_dir}} --attempts {{num_attempts}}'

    result = runner.invoke(
        app,
        [
            "run-e2e-text-benchmark",
            "--prompts",
            str(prompts),
            "--generator-command",
            command,
            "--out-dir",
            str(tmp_path / "runs"),
            "--num-attempts",
            "2",
            "--protocols",
            "validity_gruver_90",
            "--summary",
            str(summary),
            "--markdown",
            str(markdown),
        ],
    )

    assert result.exit_code == 0
    manifest = tmp_path / "runs" / "generated_cifs_manifest.csv"
    assert len(pd.read_csv(manifest)) == 2
    assert (tmp_path / "runs" / "generation_log.csv").exists()
    assert "E2E Text-to-Crystal Benchmark Report" in markdown.read_text(encoding="utf-8")


def test_e2e_failed_generator_is_structured(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts.csv"
    prompts.write_text(
        "prompt_id,paper_source,benchmark_family,input_text,target_formula,target_structure_family,target_space_group,reference_cif_path,reference_id,num_attempts,expected_metrics,required_tools,notes\n"
        "p1,test,A_validity,Generate NaCl.,NaCl,rocksalt,,,,1,validity,none,test\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" tests\\fixtures\\fake_generator.py --prompt {{prompt}} --out-dir {{out_dir}} --attempts {{num_attempts}} --fail'

    result = runner.invoke(
        app,
        [
            "run-e2e-text-benchmark",
            "--prompts",
            str(prompts),
            "--generator-command",
            command,
            "--out-dir",
            str(tmp_path / "runs"),
            "--num-attempts",
            "1",
            "--protocols",
            "validity_gruver_90",
            "--summary",
            str(tmp_path / "summary.csv"),
            "--markdown",
            str(tmp_path / "report.md"),
        ],
    )

    assert result.exit_code == 0
    log = pd.read_csv(tmp_path / "runs" / "generation_log.csv")
    assert log["status"].tolist() == ["generator_failed"]
    assert pd.read_csv(tmp_path / "runs" / "generated_cifs_manifest.csv").empty


def test_dataset_scaffolds_and_asset_registries_parse() -> None:
    paths = [
        "benchmarks/dataset_replicas/mp20_subset/targets.csv",
        "benchmarks/dataset_replicas/mpts52_subset/targets.csv",
        "benchmarks/dataset_replicas/chemeleon_chemical_spaces/chemical_spaces.csv",
        "benchmarks/dataset_replicas/atomgpt_property/property_targets.csv",
        "benchmarks/assets/reference_cif_bundles.csv",
        "benchmarks/assets/hull_reference_bundles.csv",
        "benchmarks/assets/property_target_bundles.csv",
        "benchmarks/e2e_text_prompts/e2e_prompts_v1.csv",
    ]
    for path in paths:
        frame = pd.read_csv(path)
        assert not frame.empty
