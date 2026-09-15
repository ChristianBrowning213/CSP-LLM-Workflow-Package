from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.cli import app
from sca.io import load_manifest_frame


FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


DUMMY_SPECIES_CIF = """data_dummy
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   5
_cell_length_b   5
_cell_length_c   5
_cell_angle_alpha   90
_cell_angle_beta    90
_cell_angle_gamma   90
_symmetry_Int_Tables_number 1
loop_
 _symmetry_equiv_pos_as_xyz
 'x, y, z'
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 A1 A0+ 0 0 0 1
 O1 O 0.5 0.5 0.5 1
"""


def test_cli_help_commands_work() -> None:
    for args in (
        ["--help"],
        ["crystallm-eval", "--help"],
        ["crystallm-eval", "manifest", "--help"],
        ["benchmark", "--help"],
        ["benchmark", "manifest", "--help"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0


def test_list_evaluators_includes_pre_dft_validity() -> None:
    result = runner.invoke(app, ["list-evaluators"])

    assert result.exit_code == 0
    assert "pre_dft_validity" in result.output
    assert "structure_match" in result.output


def test_registry_lists_chgnet_static() -> None:
    result = runner.invoke(app, ["list-evaluators"])

    assert result.exit_code == 0
    assert "chgnet_static" in result.output


def test_folder_mode_writes_csv_and_jsonl(tmp_path: Path) -> None:
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    (cif_dir / "tiny_valid.cif").write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    csv_out = tmp_path / "eval.csv"
    jsonl_out = tmp_path / "eval.jsonl"

    result = runner.invoke(
        app,
        [
            "crystallm-eval",
            "folder",
            str(cif_dir),
            "--target-formula",
            "NaCl",
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    assert csv_out.exists()
    assert jsonl_out.exists()
    assert pd.read_csv(csv_out)["parse_ok"].tolist() == [True]


def test_manifest_mode_writes_csv_and_jsonl(tmp_path: Path) -> None:
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    (cif_dir / "tiny_valid.cif").write_text((FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,target_formula,target_space_group,method,query_id\ncifs/tiny_valid.cif,NaCl,1,m,q\n",
        encoding="utf-8",
    )
    csv_out = tmp_path / "eval.csv"
    jsonl_out = tmp_path / "eval.jsonl"

    result = runner.invoke(
        app,
        [
            "crystallm-eval",
            "manifest",
            str(manifest),
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["method"].tolist() == ["m"]
    assert jsonl_out.read_text(encoding="utf-8").count("\n") == 1


def test_manifest_loader_preserves_existing_repo_relative_paths(tmp_path: Path, monkeypatch) -> None:
    run_root = tmp_path / "local_runs" / "example_run"
    cif_dir = run_root / "generated_cifs"
    manifest_dir = run_root / "manifests"
    cif_dir.mkdir(parents=True)
    manifest_dir.mkdir(parents=True)
    (cif_dir / "candidate.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    manifest = manifest_dir / "generated_cifs_manifest_for_sca.csv"
    manifest.write_text(
        "cif_path,target_formula\nlocal_runs/example_run/generated_cifs/candidate.cif,NaCl\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    frame = load_manifest_frame(manifest, "cif_path")

    assert Path(frame["cif_path"].iloc[0]) == (cif_dir / "candidate.cif").resolve()
    assert "manifests" not in Path(frame["cif_path"].iloc[0]).parts[-4:]


def test_benchmark_folder_writes_csv_and_jsonl(tmp_path: Path) -> None:
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    (cif_dir / "tiny_valid.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    csv_out = tmp_path / "benchmark.csv"
    jsonl_out = tmp_path / "benchmark.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "folder",
            str(cif_dir),
            "--target-formula",
            "NaCl",
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["parse_ok"].tolist() == [True]
    assert frame["pre_dft_valid"].tolist() == [True]
    assert frame["evaluator_pre_dft_validity_ok"].tolist() == [True]
    assert "pre_dft_validity" in jsonl_out.read_text(encoding="utf-8")


def test_rediscovery_label_reference_not_checked(tmp_path: Path) -> None:
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    (cif_dir / "tiny_valid.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    csv_out = tmp_path / "benchmark.csv"
    jsonl_out = tmp_path / "benchmark.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "folder",
            str(cif_dir),
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["rediscovery_label"].tolist() == ["valid_reference_not_checked"]
    assert "rediscovery_label" in jsonl_out.read_text(encoding="utf-8")


def test_rediscovery_label_known_match_with_reference_folder(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidates"
    reference_dir = tmp_path / "references"
    candidate_dir.mkdir()
    reference_dir.mkdir()
    (candidate_dir / "tiny_valid.cif").write_text(
        (FIXTURES / "tiny_valid_copy.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (reference_dir / "reference.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    csv_out = tmp_path / "benchmark.csv"
    jsonl_out = tmp_path / "benchmark.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "folder",
            str(candidate_dir),
            "--novelty",
            "true",
            "--reference-folder",
            str(reference_dir),
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["known_match"].tolist() == [True]
    assert frame["rediscovery_label"].tolist() == ["valid_known_match"]


def test_benchmark_manifest_preserves_metadata(tmp_path: Path) -> None:
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    (cif_dir / "tiny_valid.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,target_formula,target_space_group,method,query_id\ncifs/tiny_valid.cif,NaCl,1,m,q\n",
        encoding="utf-8",
    )
    csv_out = tmp_path / "benchmark.csv"
    jsonl_out = tmp_path / "benchmark.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "manifest",
            str(manifest),
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["method"].tolist() == ["m"]
    assert frame["query_id"].tolist() == ["q"]
    assert frame["target_formula_match"].tolist() == [True]


def test_direct_cif_set_records_dummy_species_and_continues(tmp_path: Path) -> None:
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    (cif_dir / "tiny_valid.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (cif_dir / "dummy_species.cif").write_text(DUMMY_SPECIES_CIF, encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,target_formula,benchmark_id,attempt_id,method\n"
        "cifs/tiny_valid.cif,NaCl,valid,1,test\n"
        "cifs/dummy_species.cif,AO,dummy,2,test\n",
        encoding="utf-8",
    )
    results_csv = tmp_path / "benchmark_results.csv"
    summary_csv = tmp_path / "benchmark_summary.csv"
    summary_json = tmp_path / "benchmark_summary.json"
    markdown = tmp_path / "benchmark_report.md"

    result = runner.invoke(
        app,
        [
            "benchmark-cif-set",
            "--manifest",
            str(manifest),
            "--out",
            str(results_csv),
            "--summary",
            str(summary_csv),
            "--json",
            str(summary_json),
            "--markdown",
            str(markdown),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(results_csv)
    assert len(frame) == 2
    dummy = frame.loc[frame["benchmark_id"] == "dummy"].iloc[0]
    assert dummy["parse_ok"] == False  # noqa: E712
    assert dummy["chemical_species_valid"] == False  # noqa: E712
    assert "A0+" in dummy["invalid_species"]
    assert dummy["error_type"] == "InvalidSpeciesError"

    summary = pd.read_csv(summary_csv)
    metrics = dict(zip(summary["metric_name"], summary["our_value"]))
    assert metrics["total_cif_count"] == 2.0
    assert metrics["parse_clean_count"] == 1.0
    assert metrics["parse_failure_count"] == 1.0
    assert metrics["invalid_species_count"] == 1.0


def test_benchmark_manifest_structure_match_target_cif(tmp_path: Path) -> None:
    cif_dir = tmp_path / "cifs"
    cif_dir.mkdir()
    (cif_dir / "candidate.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (cif_dir / "target.cif").write_text(
        (FIXTURES / "tiny_valid_copy.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,target_cif_path,reference_id,method,query_id\n"
        "cifs/candidate.cif,cifs/target.cif,ref-1,m,q\n",
        encoding="utf-8",
    )
    csv_out = tmp_path / "benchmark.csv"
    jsonl_out = tmp_path / "benchmark.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "manifest",
            str(manifest),
            "--evaluators",
            "pre_dft_validity,structure_match",
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["structure_match"].tolist() == [True]
    assert frame["anonymous_match"].tolist() == [True]
    assert frame["supercell_match"].tolist() == [False]
    assert frame["matched_reference_id"].tolist() == ["ref-1"]
    assert frame["rms_dist"].tolist() == [0.0]


def test_benchmark_structure_match_anonymous_mode(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.cif"
    target = tmp_path / "target.cif"
    candidate.write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    target.write_text(
        (FIXTURES / "tiny_valid.cif")
        .read_text(encoding="utf-8")
        .replace("data_NaCl", "data_KBr")
        .replace("Na1 Na", "K1 K")
        .replace("Cl1 Cl", "Br1 Br"),
        encoding="utf-8",
    )
    exact_out = tmp_path / "exact.json"
    anonymous_out = tmp_path / "anonymous.json"

    exact_result = runner.invoke(
        app,
        [
            "benchmark",
            "one",
            str(candidate),
            "--evaluators",
            "structure_match",
            "--target-cif-path",
            str(target),
            "--structure-match-mode",
            "exact",
            "--out",
            str(exact_out),
        ],
    )
    anonymous_result = runner.invoke(
        app,
        [
            "benchmark",
            "one",
            str(candidate),
            "--evaluators",
            "structure_match",
            "--target-cif-path",
            str(target),
            "--structure-match-mode",
            "anonymous",
            "--out",
            str(anonymous_out),
        ],
    )

    assert exact_result.exit_code == 0
    assert anonymous_result.exit_code == 0
    exact = pd.read_json(exact_out, typ="series")
    anonymous = pd.read_json(anonymous_out, typ="series")
    assert exact["evaluator_outputs"]["structure_match"]["metrics"]["structure_match"] is False
    assert anonymous["evaluator_outputs"]["structure_match"]["metrics"]["structure_match"] is True


def test_chgnet_static_missing_dependency_is_structured(tmp_path: Path, monkeypatch) -> None:
    import sca.evaluators.chgnet as chgnet

    def missing_model():
        raise RuntimeError("missing chgnet for test")

    monkeypatch.setattr(chgnet, "_load_chgnet_model", missing_model)
    csv_out = tmp_path / "chgnet.csv"
    jsonl_out = tmp_path / "chgnet.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "one",
            str(FIXTURES / "tiny_valid.cif"),
            "--evaluators",
            "chgnet_static",
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["chgnet_ok"].tolist() == [False]
    assert frame["chgnet_error"].tolist() == ["missing chgnet for test"]
    assert frame["evaluator_chgnet_static_skipped"].tolist() == [True]
    assert "missing chgnet for test" in jsonl_out.read_text(encoding="utf-8")


def test_chgnet_relax_missing_dependency_is_structured(tmp_path: Path, monkeypatch) -> None:
    import sca.evaluators.chgnet_relax as chgnet_relax

    def missing_model():
        raise RuntimeError("missing chgnet relax for test")

    monkeypatch.setattr(chgnet_relax, "_load_chgnet_model", missing_model)
    csv_out = tmp_path / "relax.csv"
    jsonl_out = tmp_path / "relax.jsonl"

    result = runner.invoke(
        app,
        [
            "benchmark",
            "one",
            str(FIXTURES / "tiny_valid.cif"),
            "--evaluators",
            "chgnet_relax",
            "--target-cif-path",
            str(FIXTURES / "tiny_valid_copy.cif"),
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["relax_ok"].tolist() == [False]
    assert frame["relax_error"].tolist() == ["missing chgnet relax for test"]
    assert frame["evaluator_chgnet_relax_skipped"].tolist() == [True]
    assert "missing chgnet relax for test" in jsonl_out.read_text(encoding="utf-8")


def test_benchmark_summary_outputs_expected_columns(tmp_path: Path) -> None:
    benchmark_csv = tmp_path / "benchmark.csv"
    pd.DataFrame(
        [
            {
                "method": "m",
                "parse_ok": True,
                "target_formula_match": True,
                "space_group_consistent": True,
                "structure_match": True,
                "known_match": False,
                "novel_by_structure_matcher": True,
                "is_duplicate": False,
                "formation_energy_per_atom": -1.0,
                "chgnet_energy_per_atom": -2.0,
            },
            {
                "method": "m",
                "parse_ok": False,
                "target_formula_match": False,
                "space_group_consistent": False,
                "structure_match": False,
                "known_match": True,
                "novel_by_structure_matcher": False,
                "is_duplicate": True,
                "formation_energy_per_atom": -3.0,
                "chgnet_energy_per_atom": -4.0,
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
    assert list(frame.columns[:11]) == [
        "group_value",
        "num_generated",
        "parse_valid_rate",
        "target_formula_match_rate",
        "space_group_consistency_rate",
        "target_structure_match_rate",
        "known_match_rate",
        "novel_rate",
        "duplicate_rate",
        "median_alignn_formation_energy",
        "median_chgnet_energy_per_atom",
    ]
    assert frame["parse_valid_rate"].tolist() == [0.5]
    assert frame["median_chgnet_energy_per_atom"].tolist() == [-3.0]


def test_benchmark_summary_tolerates_missing_optional_columns(tmp_path: Path) -> None:
    benchmark_csv = tmp_path / "benchmark.csv"
    pd.DataFrame([{"parse_ok": True}, {"parse_ok": False}]).to_csv(benchmark_csv, index=False)
    summary_out = tmp_path / "summary.csv"

    result = runner.invoke(
        app,
        ["benchmark-summary", str(benchmark_csv), "--group-col", "method", "--out", str(summary_out)],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(summary_out)
    assert frame["group_value"].tolist() == ["all"]
    assert frame["num_generated"].tolist() == [2]
    assert frame["parse_valid_rate"].tolist() == [0.5]
    assert "median_chgnet_energy_per_atom" in frame.columns


def test_cli_reference_folder_novelty_finds_known_match(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidates"
    reference_dir = tmp_path / "references"
    candidate_dir.mkdir()
    reference_dir.mkdir()
    (candidate_dir / "tiny_valid.cif").write_text(
        (FIXTURES / "tiny_valid_copy.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (reference_dir / "reference.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    csv_out = tmp_path / "eval.csv"
    jsonl_out = tmp_path / "eval.jsonl"

    result = runner.invoke(
        app,
        [
            "crystallm-eval",
            "folder",
            str(candidate_dir),
            "--novelty",
            "true",
            "--reference-folder",
            str(reference_dir),
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.read_csv(csv_out)
    assert frame["novelty_checked"].tolist() == [True]
    assert frame["known_match"].tolist() == [True]
    assert frame["novel_by_structure_matcher"].tolist() == [False]
    assert "novelty_error" in frame.columns


def test_cli_reference_manifest_novelty_finds_known_match(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidates"
    reference_dir = tmp_path / "references"
    candidate_dir.mkdir()
    reference_dir.mkdir()
    (candidate_dir / "tiny_valid.cif").write_text(
        (FIXTURES / "tiny_valid_copy.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (reference_dir / "reference.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("cif_path,ref_id\nreferences/reference.cif,ref-1\n", encoding="utf-8")
    csv_out = tmp_path / "one.csv"

    result = runner.invoke(
        app,
        [
            "crystallm-eval",
            "one",
            str(candidate_dir / "tiny_valid.cif"),
            "--novelty",
            "true",
            "--reference-manifest",
            str(manifest),
            "--reference-id-col",
            "ref_id",
            "--out",
            str(csv_out),
        ],
    )

    assert result.exit_code == 0
    frame = pd.DataFrame([pd.read_json(csv_out, typ="series")])
    assert frame["nearest_reference_id"].tolist() == ["ref-1"]
    assert frame["known_match"].tolist() == [True]


def test_cli_novelty_without_reference_fails_clearly(tmp_path: Path) -> None:
    output = tmp_path / "one.json"

    result = runner.invoke(
        app,
        [
            "crystallm-eval",
            "one",
            str(FIXTURES / "tiny_valid.cif"),
            "--novelty",
            "true",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code != 0
    assert "--novelty true requires --reference-folder or --reference-manifest" in result.output


def test_bad_reference_cif_does_not_crash_batch(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidates"
    reference_dir = tmp_path / "references"
    candidate_dir.mkdir()
    reference_dir.mkdir()
    (candidate_dir / "tiny_valid.cif").write_text(
        (FIXTURES / "tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (reference_dir / "bad.cif").write_text(
        (FIXTURES / "malformed.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    csv_out = tmp_path / "eval.csv"
    jsonl_out = tmp_path / "eval.jsonl"

    result = runner.invoke(
        app,
        [
            "crystallm-eval",
            "folder",
            str(candidate_dir),
            "--novelty",
            "true",
            "--reference-folder",
            str(reference_dir),
            "--out",
            str(csv_out),
            "--jsonl",
            str(jsonl_out),
        ],
    )

    assert result.exit_code == 0
    assert "0 loaded, 1 failed" in result.output
    frame = pd.read_csv(csv_out)
    assert frame["novelty_checked"].tolist() == [False]


def test_select_top_k_and_summarize(tmp_path: Path) -> None:
    eval_csv = tmp_path / "eval.csv"
    pd.DataFrame(
        [
            {"method": "m", "query_id": "q", "pre_dft_rank_score": 2, "pre_dft_valid": True, "parse_ok": True},
            {"method": "m", "query_id": "q", "pre_dft_rank_score": 1, "pre_dft_valid": True, "parse_ok": True},
            {"method": "m", "query_id": "q", "pre_dft_rank_score": 3, "pre_dft_valid": False, "parse_ok": False},
        ]
    ).to_csv(eval_csv, index=False)
    top_out = tmp_path / "top.csv"
    summary_out = tmp_path / "summary.csv"

    top_result = runner.invoke(
        app,
        ["select-top-k", str(eval_csv), "--group-cols", "method,query_id", "--k", "1", "--out", str(top_out)],
    )
    summary_result = runner.invoke(
        app,
        ["summarize", str(eval_csv), "--group-col", "method", "--out", str(summary_out)],
    )

    assert top_result.exit_code == 0
    assert pd.read_csv(top_out)["pre_dft_rank_score"].tolist() == [1]
    assert summary_result.exit_code == 0
    assert pd.read_csv(summary_out)["num_generated"].tolist() == [3]
