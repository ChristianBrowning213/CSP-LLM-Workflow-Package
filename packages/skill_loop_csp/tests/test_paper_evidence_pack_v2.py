from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.run_paper_evidence_pack_v2 import (
    FAILURE_CATEGORIES,
    MANIFEST_COLUMNS,
    _parser,
    run,
    _write_spp_objective_audit_sidecar,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run_paper_evidence_pack_v2.py"
CSV_PATH = REPO_ROOT / "challenge_queries_100.csv"
REQUIRED_COLUMNS = [
    "case_id",
    "short_name",
    "target_formula",
    "query",
    "chemistry_family",
    "challenge_type",
    "expected_motifs_or_priors",
    "difficulty_notes",
    "intent_specificity",
    "benchmark_split",
    "expected_formula_terms",
    "expected_family_terms",
    "expected_coordination_terms",
    "expected_connectivity_terms",
    "evaluation_notes",
]


def _run_runner(out_root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(RUNNER),
        "--csv",
        str(CSV_PATH),
        "--out-root",
        str(out_root),
        *extra,
    ]
    return subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=True)


def _manifest_rows(out_root: Path) -> list[dict]:
    payload = json.loads((out_root / "manifests" / "paper_evidence_pack_v2_manifest.json").read_text(encoding="utf-8"))
    return payload["rows"]


def _isolated_out_root() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix="paper_evidence_pack_v2_tests_")


def test_challenge_queries_csv_schema_and_rows() -> None:
    assert CSV_PATH.exists()
    with CSV_PATH.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        assert set(REQUIRED_COLUMNS).issubset(reader.fieldnames)
        rows = list(reader)

    assert len(rows) == 100
    case_ids = [row["case_id"].strip() for row in rows]
    assert len(case_ids) == len(set(case_ids))
    assert all(row["short_name"].strip() for row in rows)
    assert all(row["query"].strip() for row in rows)
    assert all(row["target_formula"].strip() for row in rows)
    assert {row["intent_specificity"] for row in rows} == {"medium"}
    assert {row["benchmark_split"] for row in rows} == {"mixed_specificity"}


def test_challenge_query_specificity_banks_are_distinct_and_complete() -> None:
    bank_specs = [
        ("challenge_queries_loose_design_intent", "loose", "loose_design_intent"),
        ("challenge_queries_specific_structural_intent", "specific", "specific_structural_intent"),
        ("challenge_queries_mixed_specificity", "medium", "mixed_specificity"),
    ]
    rows_by_bank: dict[str, list[dict[str, str]]] = {}
    forbidden_fragments = ["angstrom", "wyckoff", "tilt angle", "tilt angles"]

    for stem, specificity, split in bank_specs:
        csv_path = REPO_ROOT / f"{stem}.csv"
        json_path = REPO_ROOT / f"{stem}.json"
        assert csv_path.exists()
        assert json_path.exists()
        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames is not None
            assert set(REQUIRED_COLUMNS).issubset(reader.fieldnames)
            rows = list(reader)
        payload = json.loads(json_path.read_text(encoding="utf-8"))

        assert len(rows) == 100
        assert payload["row_count"] == 100
        assert {row["intent_specificity"] for row in rows} == {specificity}
        assert {row["benchmark_split"] for row in rows} == {split}
        assert all(row["expected_formula_terms"] == row["target_formula"] for row in rows)
        assert not any(
            any(fragment in row["query"].lower() for fragment in forbidden_fragments)
            or "Å" in row["query"]
            or "°" in row["query"]
            for row in rows
        )
        rows_by_bank[stem] = rows

    loose_by_id = {row["case_id"]: row for row in rows_by_bank["challenge_queries_loose_design_intent"]}
    specific_by_id = {row["case_id"]: row for row in rows_by_bank["challenge_queries_specific_structural_intent"]}
    assert loose_by_id["challenge_001"]["query"] != specific_by_id["challenge_001"]["query"]
    assert "BaTiO3" in loose_by_id["challenge_001"]["expected_motifs_or_priors"]
    assert "oxide perovskite" in loose_by_id["challenge_001"]["expected_motifs_or_priors"]
    assert "TiO6" not in loose_by_id["challenge_001"]["expected_motifs_or_priors"]
    assert "TiO6" in specific_by_id["challenge_001"]["expected_motifs_or_priors"]
    assert "corner-sharing" in specific_by_id["challenge_001"]["expected_motifs_or_priors"]


def test_runner_dry_run_creates_directories_and_manifest() -> None:
    with _isolated_out_root() as tmp:
        out_root = Path(tmp) / "paper_evidence_pack_v2"
        _run_runner(out_root, "--dry-run", "--limit", "2", "--seed", "2026")

        for name in ["raw_runs", "figures", "final_doc_images", "manifests", "reports", "logs"]:
            assert (out_root / name).is_dir()

        rows = _manifest_rows(out_root)
        assert len(rows) == 2
        assert all(row["status"] == "dry_run" for row in rows)
        assert all(row["failure_message"] == "Dry run: workflow not executed." for row in rows)
        assert all(row["failure_category"] in FAILURE_CATEGORIES for row in rows)
        assert all(not row["solution_cif_produced"] for row in rows)
        assert not any(row["qlip_solve_status"] for row in rows)


def test_limit_and_offset_select_expected_rows() -> None:
    with _isolated_out_root() as tmp:
        out_root = Path(tmp) / "paper_evidence_pack_v2"
        _run_runner(out_root, "--dry-run", "--limit", "2", "--offset", "1")

        rows = _manifest_rows(out_root)
        assert [row["case_id"] for row in rows] == ["challenge_002", "challenge_003"]


def test_runner_does_not_overwrite_v1() -> None:
    v1 = REPO_ROOT / "test_workdir" / "paper_evidence_pack_v1"
    assert v1.exists()
    before_entries = sorted(path.name for path in v1.iterdir())
    before_manifest_mtime = (v1 / "figure_manifest.json").stat().st_mtime_ns

    with _isolated_out_root() as tmp:
        out_root = Path(tmp) / "paper_evidence_pack_v2"
        _run_runner(out_root, "--dry-run", "--limit", "1")

    assert v1.exists()
    assert sorted(path.name for path in v1.iterdir()) == before_entries
    assert (v1 / "figure_manifest.json").stat().st_mtime_ns == before_manifest_mtime


def test_manifest_schema_and_failure_categories() -> None:
    with _isolated_out_root() as tmp:
        out_root = Path(tmp) / "paper_evidence_pack_v2"
        _run_runner(out_root, "--dry-run", "--limit", "2")

        rows = _manifest_rows(out_root)
        assert rows
        for row in rows:
            assert set(MANIFEST_COLUMNS).issubset(row)
            assert row["failure_category"] in FAILURE_CATEGORIES

        csv_path = out_root / "manifests" / "paper_evidence_pack_v2_manifest.csv"
        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == MANIFEST_COLUMNS
            assert len(list(reader)) == 2


def test_runner_accepts_soft_repulsive_spp_missing_pair_policy() -> None:
    args = _parser().parse_args(["--spp-missing-pair-policy", "soft_repulsive"])

    assert args.spp_missing_pair_policy == "soft_repulsive"


def test_runner_accepts_spp_regularisation_flags() -> None:
    args = _parser().parse_args(
        [
            "--spp-regularization-dir",
            "C:/tmp/global_spp",
            "--spp-regularization-weight",
            "0.75",
        ]
    )

    assert args.spp_regularisation_dir == "C:/tmp/global_spp"
    assert args.spp_regularisation_weight == 0.75


def test_spp_objective_audit_sidecar_records_soft_repulsive_policy() -> None:
    with _isolated_out_root() as tmp:
        case_dir = Path(tmp) / "raw_runs" / "challenge_001_probe"
        request_path = case_dir / "qlip_request.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(
            json.dumps(
                {
                    "guidance": [
                        {
                            "id": "objective.energy_spp",
                            "weight": 10.0,
                            "params": {
                                "pot_root": str(Path(tmp) / "partial_pots"),
                                "mode": "partial",
                                "supported_pairs": ["Al-Al"],
                                "missing_pairs": ["Al-Mg"],
                                "missing_pair_policy": "soft_repulsive",
                                "regularisation_spp_dir": str(Path(tmp) / "global_pots"),
                                "regularisation_weight": 0.75,
                                "strict_pair_coverage": False,
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        fields = _write_spp_objective_audit_sidecar(
            case_dir,
            qlip_request_path=str(request_path),
            solution_cif_path="",
            qlip_objective="",
        )
        payload = json.loads((case_dir / "qlip" / "qlip_spp_objective_audit.json").read_text(encoding="utf-8"))

        assert fields["spp_objective_audit_path"].endswith("qlip_spp_objective_audit.json")
        assert fields["spp_objective_audit_available"] is False


def test_rescore_existing_robocrys_intent_is_no_solve_and_backs_up_reports(monkeypatch) -> None:
    import scripts.run_paper_evidence_pack_v2 as runner
    import sok_llm_orchestrator.agentic.robocrys_intent_validator as validator

    with _isolated_out_root() as tmp:
        out_root = Path(tmp) / "existing_pack"
        case_dir = out_root / "raw_runs" / "challenge_001_batio3_perovskite"
        robocrys_dir = case_dir / "robocrys"
        reports = out_root / "reports"
        manifests = out_root / "manifests"
        robocrys_dir.mkdir(parents=True)
        reports.mkdir(parents=True)
        manifests.mkdir(parents=True)
        description_path = robocrys_dir / "generated_cif_robocrys_description.txt"
        description_path.write_text("BaTiO3 is perovskite structured. Ti is bonded to six O atoms to form TiO6 octahedra.", encoding="utf-8")
        (case_dir / "crystal_db_query.json").write_text(
            json.dumps({"crystal_db_retrieval_query": "BaTiO3 perovskite structured TiO6 octahedra"}),
            encoding="utf-8",
        )
        old_summary = reports / "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.json"
        old_summary.write_text(json.dumps({"llm_judged_count": 0}), encoding="utf-8")
        (reports / "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.md").write_text("old summary\n", encoding="utf-8")

        row = {column: "" for column in MANIFEST_COLUMNS}
        row.update(
            {
                "case_id": "challenge_001",
                "short_name": "batio3_perovskite",
                "target_formula": "BaTiO3",
                "query": "Generate BaTiO3 perovskite.",
                "chemistry_family": "oxide_perovskite",
                "challenge_type": "known_structure",
                "expected_motifs_or_priors": "perovskite; TiO6 octahedra",
                "intent_specificity": "medium",
                "benchmark_split": "mixed_specificity",
                "status": "success",
                "failure_category": "success",
                "solution_cif_produced": True,
                "solution_cif_path": str(case_dir / "solution.cif"),
                "case_dir": "raw_runs/challenge_001_batio3_perovskite",
                "generated_cif_robocrys_available": True,
                "generated_cif_robocrys_description_path": str(description_path),
                "generated_cif_robocrys_error": "",
            }
        )
        (manifests / "paper_evidence_pack_v2_manifest.json").write_text(
            json.dumps({"schema_version": "paper_evidence_pack.v2", "rows": [row]}),
            encoding="utf-8",
        )

        def fail_if_solve_loader_called():
            raise AssertionError("QLIP solve path should not be loaded during Robocrys intent rescore")

        def fake_judge(**kwargs):
            return {
                "validator_version": "v1_llm_robocrys_intent_judge",
                "available": True,
                "score": 0.91,
                "correct": True,
                "judgement": "correct",
                "matched_requirements": ["perovskite", "TiO6 octahedra"],
                "missing_requirements": [],
                "contradictions": [],
                "concerns": [],
                "explanation": "mocked live judge",
                "not_physical_validation_notice": True,
                "prompt": "mock prompt",
                "raw_response": "{\"score\": 0.91}",
            }

        monkeypatch.setattr(runner, "_load_run_paper_smoke_suite", fail_if_solve_loader_called)
        monkeypatch.setattr(runner, "_ollama_model_names", lambda url, timeout_s: (["mock-model"], ""))
        monkeypatch.setattr(validator, "judge_robocrys_intent_alignment_with_llm", fake_judge)

        args = _parser().parse_args(
            [
                "--rescore-existing-robocrys-intent",
                "--out-root",
                str(out_root),
                "--use-llm-robocrys-intent-judge",
                "--llm-judge-backend",
                "ollama",
                "--llm-judge-url",
                "http://localhost:11434",
                "--llm-judge-model",
                "mock-model",
            ]
        )
        result = run(args)

        assert result["mode"] == "NO_SOLVE_RESCORE_MODE"
        assert result["qlip_solve_disabled"] is True
        assert result["llm_judged_count"] == 1
        assert result["backups"]
        assert any(path.name.startswith("ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.before_rescore_") for path in reports.iterdir())
        updated = json.loads((reports / "ROBOCRYS_INTENT_ALIGNMENT_SUMMARY.json").read_text(encoding="utf-8"))
        assert updated["llm_judged_count"] == 1
        assert updated["mean_llm_score"] == 0.91
        updated_manifest = json.loads((manifests / "paper_evidence_pack_v2_manifest.json").read_text(encoding="utf-8"))
        assert updated_manifest["rows"][0]["solution_cif_path"] == str(case_dir / "solution.cif")
        rescore_log = json.loads((out_root / "logs" / "robocrys_intent_rescore.json").read_text(encoding="utf-8"))
        assert rescore_log["mode"] == "NO_SOLVE_RESCORE_MODE"
        assert rescore_log["qlip_solve_disabled"] is True
        assert not (case_dir / "_raw_run" / "execution" / "step_003_qlip_solve").exists()


def test_final_doc_images_manifest_created_in_dry_run() -> None:
    with _isolated_out_root() as tmp:
        out_root = Path(tmp) / "paper_evidence_pack_v2"
        _run_runner(out_root, "--dry-run", "--limit", "2")

        csv_path = out_root / "final_doc_images" / "final_doc_images_manifest.csv"
        json_path = out_root / "final_doc_images" / "final_doc_images_manifest.json"
        assert csv_path.exists()
        assert json_path.exists()

        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == [
                "image_id",
                "case_id",
                "short_name",
                "image_type",
                "source_path",
                "copied_path",
                "exists",
                "file_size_bytes",
                "notes",
            ]
            assert list(reader) == []

        summary = (out_root / "reports" / "PAPER_EVIDENCE_PACK_V2_SUMMARY.md").read_text(encoding="utf-8")
        assert "missing file count from manifest paths: 0" in summary


def test_dry_run_with_robocrys_query_skill_writes_query_sidecar() -> None:
    with _isolated_out_root() as tmp:
        out_root = Path(tmp) / "paper_evidence_pack_v2"
        _run_runner(out_root, "--dry-run", "--limit", "1", "--use-robocrys-query-skill")

        rows = _manifest_rows(out_root)
        assert rows[0]["query_style"] == "robocrys_descriptive"
        assert rows[0]["query_skill_version"] == "v1_rule_based"
        sidecar = out_root / rows[0]["case_dir"] / "crystal_db_query.json"
        assert sidecar.exists()
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        assert payload["original_user_query"]
        assert payload["crystal_db_retrieval_query"]
        assert payload["query_rewrite_reason"] == "align semantic query with robocrys text_docs retrieval surface"


def test_capability_audit_only_writes_support_outputs() -> None:
    with _isolated_out_root() as tmp:
        out_root = Path(tmp) / "paper_evidence_pack_v2"
        _run_runner(out_root, "--capability-audit-only")

        json_path = out_root / "reports" / "CRYSTAL_DB_CAPABILITY_AUDIT.json"
        csv_path = out_root / "reports" / "CRYSTAL_DB_CAPABILITY_AUDIT.csv"
        md_path = out_root / "reports" / "CRYSTAL_DB_CAPABILITY_AUDIT.md"
        assert json_path.exists()
        assert csv_path.exists()
        assert md_path.exists()
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert len(payload["challenge_support"]) == 100
        allowed = {"fully_supported", "pair_supported", "partially_supported", "element_only_supported", "unsupported"}
        assert {row["support_classification"] for row in payload["challenge_support"]}.issubset(allowed)


def test_preflight_support_only_records_recommendations() -> None:
    with _isolated_out_root() as tmp:
        out_root = Path(tmp) / "paper_evidence_pack_v2"
        _run_runner(out_root, "--preflight-support-only")

        payload = json.loads((out_root / "reports" / "CRYSTAL_DB_CAPABILITY_AUDIT.json").read_text(encoding="utf-8"))
        first = payload["challenge_support"][0]
        assert "missing_pairs" in first
        assert "exportable_pair_support_counts" in first
        assert first["recommendation"] in {
            "run_full_workflow",
            "run_without_fresh_spp",
            "run_retrieval_only",
            "needs_corpus_expansion",
        }
