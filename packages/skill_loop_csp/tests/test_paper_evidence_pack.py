from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.build_paper_evidence_pack import build_evidence_pack


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_build_paper_evidence_pack_from_tiny_fake_suite() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        suite_dir = tmp_path / "suite"
        _run_tiny_fake_suite_assertions(tmp_path, suite_dir)


def _run_tiny_fake_suite_assertions(tmp_path: Path, suite_dir: Path) -> None:
    complete_dir = suite_dir / "complete_case"
    partial_dir = suite_dir / "partial_case"
    solution_cif = complete_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "solution.cif"
    solution_cif.parent.mkdir(parents=True)
    solution_cif.write_text("data_fake\n", encoding="utf-8")

    _write_json(
        complete_dir / "report" / "workflow_evaluation.json",
        {
            "final_status": "completed",
            "evaluator_summary": "Solved fake case.",
            "evidence_checks": {
                "retrieval": {"observed": {"exported_cif_count": 1}},
                "spp_guidance": {"observed": {"qlip_solve_compatible": True}},
            },
            "execution_checks": {
                "validation": {"status": "pass"},
                "solve": {
                    "observed": {
                        "objective_value": -1.2,
                        "qlip_status": "OPTIMAL",
                        "solution_cif_path": str(solution_cif),
                    }
                },
            },
            "novelty_assessment": {"observed": {"is_novel": False}},
            "failure_assessment": {},
        },
    )
    _write_json(
        complete_dir / "_raw_run" / "execution" / "execution_run.json",
        {
            "step_results": [
                {"tool_name": "crystal.csp_pack", "status": "succeeded", "output_summary": {"exported_cif_count": 1}},
                {
                    "tool_name": "spp.run_pipeline",
                    "status": "succeeded",
                    "output_summary": {
                        "qlip_package_status": "ready",
                        "pot_root_source": "fresh_corpus",
                        "extraction_mode": "qlip_required_pairs",
                        "qlip_solve_compatible": True,
                    },
                },
                {"tool_name": "qlip.validate_request", "status": "succeeded", "output_summary": {"package_validation_status": "valid"}},
                {"tool_name": "qlip.solve", "status": "succeeded", "output_summary": {"status": "OPTIMAL", "solution_cif_path": str(solution_cif)}},
                {"tool_name": "crystal.novelty_check", "status": "succeeded", "output_summary": {}},
            ]
        },
    )

    _write_json(
        partial_dir / "report" / "workflow_evaluation.json",
        {
            "final_status": "partial",
            "evaluator_summary": "Blocked truthfully.",
            "evidence_checks": {
                "retrieval": {"observed": {"exported_cif_count": 0}},
                "spp_guidance": {"observed": {"qlip_solve_compatible": False}},
            },
            "execution_checks": {"validation": {"status": "blocked"}, "solve": {"status": "blocked"}},
            "novelty_assessment": {"observed": {"is_novel": None}},
            "failure_assessment": {
                "failed_tool": "spp.run_pipeline",
                "error_code": "corpus_unsuitable_for_spp",
                "error_message": "No valid corpus.",
            },
        },
    )
    _write_json(
        partial_dir / "_raw_run" / "execution" / "execution_run.json",
        {
            "step_results": [
                {"tool_name": "crystal.csp_pack", "status": "succeeded", "output_summary": {"exported_cif_count": 0}},
                {"tool_name": "spp.run_pipeline", "status": "blocked", "output_summary": {"qlip_package_status": "partial"}},
            ]
        },
    )

    _write_json(
        suite_dir / "suite_summary.json",
        {
            "runs": [
                {
                    "run_id": "complete_case",
                    "goal": "Generate a fake supported crystal.",
                    "material_system": "XaY",
                    "expected_outcome": "completed",
                    "expected_outcome_pass": True,
                    "final_status": "completed",
                    "overall_score_0_100": 100,
                    "qlip_status": "OPTIMAL",
                    "solution_cif_path": str(solution_cif),
                    "novelty_is_novel": False,
                    "evidence_dimensions": {
                        "retrieval_executed": True,
                        "spp_executed": True,
                        "qlip_validated": True,
                        "qlip_solved": True,
                        "novelty_checked": True,
                    },
                    "artifact_paths": {
                        "workflow_evaluation_json": str(complete_dir / "report" / "workflow_evaluation.json"),
                        "execution_run_json": str(complete_dir / "_raw_run" / "execution" / "execution_run.json"),
                    },
                },
                {
                    "run_id": "partial_case",
                    "goal": "Generate an unsupported fake crystal.",
                    "material_system": "Nope2",
                    "expected_outcome": "partial",
                    "expected_outcome_pass": True,
                    "final_status": "partial",
                    "overall_score_0_100": 48,
                    "failed_tool": "spp.run_pipeline",
                    "failure_code": "corpus_unsuitable_for_spp",
                    "solution_cif_path": "",
                    "evidence_dimensions": {"retrieval_executed": True, "spp_executed": True},
                    "artifact_paths": {
                        "workflow_evaluation_json": str(partial_dir / "report" / "workflow_evaluation.json"),
                        "execution_run_json": str(partial_dir / "_raw_run" / "execution" / "execution_run.json"),
                    },
                },
            ]
        },
    )

    out_dir = tmp_path / "evidence"
    result = build_evidence_pack(suite_dir, out_dir)

    assert result["run_count"] == 2
    assert (out_dir / "paper_results_table.csv").exists()
    assert (out_dir / "paper_results_table.md").exists()
    assert (out_dir / "paper_results_table.json").exists()
    assert (out_dir / "workflow_case_matrix.md").exists()
    assert (out_dir / "comparison_axes_table.md").exists()
    assert (out_dir / "figure_manifest.json").exists()
    assert (out_dir / "spp_visualisation_status.md").exists()
    assert (out_dir / "final_crystal_artifacts.md").exists()

    rows = json.loads((out_dir / "paper_results_table.json").read_text(encoding="utf-8"))["rows"]
    partial = next(row for row in rows if row["run_id"] == "partial_case")
    assert partial["solution_cif_path"] == ""
    assert partial["error_code"] == "corpus_unsuitable_for_spp"

    manifest = json.loads((out_dir / "figure_manifest.json").read_text(encoding="utf-8"))
    assert any(item["path"].endswith("workflow_outcome_counts.png") for item in manifest["figures"])
    assert any(item["path"].endswith("spp_visualisation_status.md") and item["status"] == "deferred" for item in manifest["figures"])
