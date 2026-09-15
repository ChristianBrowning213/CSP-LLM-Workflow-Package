from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from sca.benchmark import benchmark_manifest
from sca.cli import app
from sca.paper_benchmarks.diagnostics import build_paper_target_diagnostics
from sca.paper_benchmarks.manifest_builder import build_paper_run_manifest
from sca.paper_benchmarks.comparators import built_in_comparators
from sca.paper_benchmarks.summary import build_paper_benchmark_summary


FIXTURES = Path("tests/fixtures/paper_benchmarks")
runner = CliRunner()


def _rows_by_metric(summary):
    rows = [row for row in summary.rows if row["summary_scope"] == "global" and not row["comparator_name"]]
    return {row["metric_name"]: row for row in rows}


def test_validity_metrics_and_missing_composition() -> None:
    summary = build_paper_benchmark_summary(FIXTURES / "results_ae.csv", FIXTURES / "manifest.csv")
    rows = _rows_by_metric(summary)

    assert rows["parse_validity_rate"]["our_value"] == 0.8
    assert rows["pre_dft_validity_rate"]["our_value"] == 0.6
    assert rows["bad_contact_rate"]["our_value"] == 0.4
    assert rows["hard_fail_count"]["our_value"] == 2.0

    missing = build_paper_benchmark_summary(FIXTURES / "results_missing.csv", FIXTURES / "manifest.csv")
    missing_rows = _rows_by_metric(missing)
    assert missing_rows["composition_match_rate"]["our_value"] is None
    assert missing_rows["composition_match_rate"]["n_not_computable"] == 2


def test_structure_metrics_n1_nk_and_rms() -> None:
    summary = build_paper_benchmark_summary(FIXTURES / "results_ae.csv", FIXTURES / "manifest.csv")
    rows = _rows_by_metric(summary)

    assert rows["structure_match_rate"]["our_value"] == 0.5
    assert rows["match_rate_n1"]["our_value"] == 0.5
    assert rows["match_rate_nk"]["our_value"] == 1.0
    assert rows["best_rms_dist"]["our_value"] == 0.03
    assert rows["mean_rms_dist"]["our_value"] == 0.07

    missing = build_paper_benchmark_summary(FIXTURES / "results_missing.csv", FIXTURES / "manifest.csv")
    assert _rows_by_metric(missing)["structure_match_rate"]["n_not_computable"] == 2


def test_mlip_and_hull_metrics() -> None:
    summary = build_paper_benchmark_summary(FIXTURES / "results_ae.csv", FIXTURES / "manifest.csv")
    rows = _rows_by_metric(summary)

    assert rows["chgnet_ok_rate"]["our_value"] == 1.0
    assert rows["m3gnet_ok_rate"]["our_value"] == 0.6
    assert rows["mlip_consensus_stable_rate"]["our_value"] == 0.6
    assert rows["mlip_disagreement_rate"]["our_value"] == 0.2
    assert rows["predicted_ehull_rate_0_15"]["our_value"] == 0.6
    assert rows["predicted_metastable_rate_ehull_0_15"]["our_value"] == 0.6

    missing = build_paper_benchmark_summary(FIXTURES / "results_missing.csv", FIXTURES / "manifest.csv")
    assert _rows_by_metric(missing)["predicted_ehull_rate_0_15"]["our_value"] is None


def test_relaxation_metrics_not_faked_from_static_columns() -> None:
    summary = build_paper_benchmark_summary(FIXTURES / "results_ae.csv", FIXTURES / "manifest.csv")
    rows = _rows_by_metric(summary)

    assert rows["relax_success_rate"]["our_value"] == 0.75
    assert rows["median_energy_drop_per_atom"]["our_value"] == 0.10
    assert rows["force_threshold_success_rate_0_20"]["our_value"] == 1.0
    assert rows["rmse_improvement_rate"]["our_value"] == 1.0
    assert rows["median_rmse_delta"]["our_value"] == 0.04

    missing = build_paper_benchmark_summary(FIXTURES / "results_missing.csv", FIXTURES / "manifest.csv")
    assert _rows_by_metric(missing)["relax_success_rate"]["our_value"] is None


def test_novelty_sun_metrics_use_hull_then_mlip_fallback() -> None:
    summary = build_paper_benchmark_summary(FIXTURES / "results_ae.csv", FIXTURES / "manifest.csv")
    rows = _rows_by_metric(summary)

    assert rows["unique_rate"]["our_value"] == 0.8
    assert rows["local_novelty_rate"]["our_value"] == 0.8
    assert rows["sun_count"]["our_value"] == 3.0
    assert rows["sun_rate"]["our_value"] == 0.6
    assert "local novelty" in rows["local_novelty_rate"]["notes"]

    no_hull = pd.read_csv(FIXTURES / "results_ae.csv").drop(columns=["predicted_energy_above_hull"])
    temp = FIXTURES / "_tmp_no_hull.csv"
    no_hull.to_csv(temp, index=False)
    try:
        fallback = build_paper_benchmark_summary(temp, FIXTURES / "manifest.csv")
        assert _rows_by_metric(fallback)["sun_rate"]["our_value"] == 0.6
    finally:
        temp.unlink(missing_ok=True)


def test_comparator_logic_and_built_ins() -> None:
    summary = build_paper_benchmark_summary(
        FIXTURES / "results_ae.csv",
        FIXTURES / "manifest.csv",
        include_built_in_comparators=True,
    )
    comparator_rows = [row for row in summary.rows if row["comparator_name"]]
    names = {row["comparator_name"] for row in comparator_rows}

    assert "fixture_validity" in names
    assert "Lang2Str_MP20" in names
    assert any(row["beats_comparator"] is True for row in comparator_rows if row["comparator_name"] == "fixture_validity")
    assert built_in_comparators()


def test_paper_benchmark_summary_cli_writes_csv_json_and_markdown(tmp_path: Path) -> None:
    out_csv = tmp_path / "summary.csv"
    out_json = tmp_path / "summary.json"
    out_md = tmp_path / "summary.md"

    result = runner.invoke(
        app,
        [
            "paper-benchmark-summary",
            str(FIXTURES / "results_ae.csv"),
            "--manifest",
            str(FIXTURES / "manifest.csv"),
            "--include-built-in-comparators",
            "--out",
            str(out_csv),
            "--json",
            str(out_json),
            "--markdown",
            str(out_md),
        ],
    )

    assert result.exit_code == 0
    assert out_csv.exists()
    assert out_json.exists()
    assert out_md.exists()
    assert "SCA Paper-Comparable Benchmark Report" in out_md.read_text(encoding="utf-8")


def test_paper_target_diagnostics_classifies_wrong_prototype_and_relaxation(tmp_path: Path) -> None:
    generated = tmp_path / "generated.cif"
    reference = tmp_path / "reference.cif"
    relaxed = tmp_path / "relaxed.cif"
    generated.write_text(Path("tests/fixtures/tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    reference.write_text(Path("tests/fixtures/tiny_valid_copy.cif").read_text(encoding="utf-8"), encoding="utf-8")
    relaxed.write_text(Path("tests/fixtures/tiny_valid_copy.cif").read_text(encoding="utf-8"), encoding="utf-8")
    results = tmp_path / "results.csv"
    manifest = tmp_path / "manifest.csv"
    references = tmp_path / "references.csv"
    pd.DataFrame(
        [
            {
                "benchmark_id": "target-1",
                "file_name": "generated.cif",
                "cif_path": str(generated),
                "reference_cif_path": str(reference),
                "reference_id": "ref-1",
                "relaxed_cif_path": str(relaxed),
                "target_formula": "NaCl",
                "generated_reduced_formula": "NaCl",
                "target_structure_family": "rocksalt",
                "structure_match": False,
                "structure_match_after": True,
                "relax_ok": True,
                "energy_drop_per_atom": 0.2,
                "max_force_before": 1.0,
                "max_force_after": 0.1,
                "geometry_ok": True,
                "bond_lengths_reasonable": True,
                "num_bad_contacts": 0,
                "mlip_consensus_stable_flag": True,
            }
        ]
    ).to_csv(results, index=False)
    pd.DataFrame(
        [
            {
                "benchmark_id": "target-1",
                "target_structure_family": "rocksalt",
                "reference_cif_path": str(reference),
                "notes": "Ideal prototype reference.",
            }
        ]
    ).to_csv(manifest, index=False)
    pd.DataFrame(
        [
            {
                "benchmark_id": "target-1",
                "reference_id": "ref-1",
                "reference_cif_path": str(reference),
                "reference_formula": "NaCl",
                "reference_family": "rocksalt",
                "reference_prototype": "B1 rocksalt",
                "notes": "Ideal prototype.",
            }
        ]
    ).to_csv(references, index=False)

    rows = build_paper_target_diagnostics(results, manifest, references)

    assert len(rows) == 1
    row = rows[0]
    assert row["primary_category"] == "near_match"
    assert "relaxation_improved" in row["category_flags"]
    assert row["reference_risk"] == "prototype_or_polymorph_note"
    assert row["generated_space_group"]


def test_paper_target_diagnostics_cli_writes_outputs(tmp_path: Path) -> None:
    generated = tmp_path / "generated.cif"
    reference = tmp_path / "reference.cif"
    generated.write_text(Path("tests/fixtures/tiny_valid.cif").read_text(encoding="utf-8"), encoding="utf-8")
    reference.write_text(Path("tests/fixtures/tiny_valid_copy.cif").read_text(encoding="utf-8"), encoding="utf-8")
    results = tmp_path / "results.csv"
    manifest = tmp_path / "manifest.csv"
    references = tmp_path / "references.csv"
    out_csv = tmp_path / "diagnostics.csv"
    out_json = tmp_path / "diagnostics.json"
    out_md = tmp_path / "diagnostics.md"
    pd.DataFrame(
        [
            {
                "benchmark_id": "target-1",
                "file_name": "generated.cif",
                "cif_path": str(generated),
                "reference_cif_path": str(reference),
                "structure_match": True,
                "relax_ok": False,
                "geometry_ok": True,
                "bond_lengths_reasonable": True,
                "num_bad_contacts": 0,
            }
        ]
    ).to_csv(results, index=False)
    pd.DataFrame([{"benchmark_id": "target-1", "reference_cif_path": str(reference)}]).to_csv(manifest, index=False)
    pd.DataFrame(
        [
            {
                "benchmark_id": "target-1",
                "reference_cif_path": str(reference),
                "reference_formula": "NaCl",
            }
        ]
    ).to_csv(references, index=False)

    result = runner.invoke(
        app,
        [
            "paper-target-diagnostics",
            "--results",
            str(results),
            "--manifest",
            str(manifest),
            "--references",
            str(references),
            "--out",
            str(out_csv),
            "--json",
            str(out_json),
            "--markdown",
            str(out_md),
        ],
    )

    assert result.exit_code == 0
    assert pd.read_csv(out_csv)["primary_category"].tolist() == ["exact_reference_match"]
    assert out_json.exists()
    assert "Paper Target Diagnostics" in out_md.read_text(encoding="utf-8")


def test_build_paper_run_manifest_maps_generated_cifs(tmp_path: Path) -> None:
    targets = tmp_path / "targets.csv"
    targets.write_text(
        "benchmark_id,benchmark_group,target_formula,target_structure_family,target_space_group,prompt\n"
        "sanity_nacl,A_validity,NaCl,rocksalt,Fm-3m,Generate NaCl.\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "challenge_001_nacl_rocksalt_solution.cif").write_text(
        Path("tests/fixtures/tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    out = tmp_path / "generated_manifest.csv"

    frame = build_paper_run_manifest(targets, generated, out)

    assert out.exists()
    assert frame.loc[0, "benchmark_id"] == "sanity_nacl"
    assert frame.loc[0, "attempt_id"] == 1
    assert frame.loc[0, "target_formula"] == "NaCl"
    assert frame.loc[0, "mapping_status"] == "matched"
    assert "mapping_confidence" in frame.columns
    assert "method" in frame.columns


def test_build_paper_run_manifest_maps_by_reduced_formula(tmp_path: Path) -> None:
    targets = tmp_path / "targets.csv"
    targets.write_text(
        "benchmark_id,benchmark_group,target_formula,target_structure_family\n"
        "sanity_nacl,A_validity,Na1Cl1,rocksalt\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "challenge_001_salt_solution.cif").write_text(
        Path("tests/fixtures/tiny_valid.cif").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    frame = build_paper_run_manifest(targets, generated, tmp_path / "manifest.csv")

    assert frame.loc[0, "benchmark_id"] == "sanity_nacl"
    assert frame.loc[0, "mapping_confidence"] == "reduced_formula"


def test_build_paper_run_manifest_disambiguates_by_family_token(tmp_path: Path) -> None:
    targets = tmp_path / "targets.csv"
    targets.write_text(
        "benchmark_id,benchmark_group,target_formula,target_structure_family\n"
        "tio2_rutile,B_structure_reproduction,TiO2,rutile\n"
        "tio2_anatase,B_structure_reproduction,TiO2,anatase\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "challenge_001_tio2_rutile_solution.cif").write_text("not a cif", encoding="utf-8")

    frame = build_paper_run_manifest(targets, generated, tmp_path / "manifest.csv")

    assert frame.loc[0, "benchmark_id"] == "tio2_rutile"
    assert frame.loc[0, "mapping_confidence"] == "exact_formula_and_family"


def test_build_paper_run_manifest_emits_unmatched_and_ambiguous_rows(tmp_path: Path) -> None:
    targets = tmp_path / "targets.csv"
    targets.write_text(
        "benchmark_id,benchmark_group,target_formula,target_structure_family\n"
        "tio2_rutile,B_structure_reproduction,TiO2,rutile\n"
        "tio2_anatase,B_structure_reproduction,TiO2,anatase\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "challenge_001_tio2_solution.cif").write_text("not a cif", encoding="utf-8")
    (generated / "challenge_002_xyz_solution.cif").write_text("not a cif", encoding="utf-8")
    unmatched = tmp_path / "unmatched.csv"

    frame = build_paper_run_manifest(targets, generated, tmp_path / "manifest.csv", unmatched_out=unmatched)
    unmatched_frame = pd.read_csv(unmatched)

    assert set(frame["mapping_status"]) == {"ambiguous", "unmatched"}
    assert set(unmatched_frame["mapping_status"]) == {"ambiguous", "unmatched"}


def test_build_paper_run_manifest_strict_fails_on_unmatched(tmp_path: Path) -> None:
    targets = tmp_path / "targets.csv"
    targets.write_text(
        "benchmark_id,benchmark_group,target_formula\nsanity_nacl,A_validity,NaCl\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "challenge_001_xyz_solution.cif").write_text("not a cif", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Unmatched or ambiguous"):
        build_paper_run_manifest(targets, generated, tmp_path / "manifest.csv", strict=True)


def test_benchmark_manifest_preserves_paper_metadata(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,benchmark_id,benchmark_group,attempt_id,target_formula,target_structure_family,paper_source\n"
        f"{Path('tests/fixtures/tiny_valid.cif').resolve()},sanity_nacl,A_validity,1,NaCl,rocksalt,fixture\n",
        encoding="utf-8",
    )

    records = benchmark_manifest(
        manifest,
        evaluator_names=["pre_dft_validity"],
        formula_col="target_formula",
        method_col="paper_source",
        query_id_col="benchmark_id",
    )

    row = records[0].to_row()
    assert row["benchmark_id"] == "sanity_nacl"
    assert row["benchmark_group"] == "A_validity"
    assert str(row["attempt_id"]) == "1"
    assert row["target_structure_family"] == "rocksalt"
    assert row["target_formula_match"] is True


def test_structure_match_uses_reference_cif_path_alias(tmp_path: Path) -> None:
    reference = Path("tests/fixtures/tiny_valid.cif").resolve()
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "cif_path,benchmark_id,benchmark_group,target_formula,reference_cif_path,reference_id\n"
        f"{reference},sanity_nacl,B_structure_reproduction,NaCl,{reference},ref-nacl\n",
        encoding="utf-8",
    )

    records = benchmark_manifest(
        manifest,
        evaluator_names=["pre_dft_validity", "structure_match"],
        formula_col="target_formula",
        reference_id_col="reference_id",
    )

    row = records[0].to_row()
    assert row["reference_cif_path"] == str(reference)
    assert row["structure_match"] is True
    assert row["matched_reference_id"] == "ref-nacl"
