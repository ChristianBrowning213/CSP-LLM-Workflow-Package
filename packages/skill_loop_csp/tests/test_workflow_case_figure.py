from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.build_workflow_case_figure import build_workflow_case_figure


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_workflow_case_figure_writes_outputs_without_fake_pot_or_crystal_render() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        suite_dir = root / "suite"
        out_dir = root / "out"
        run_dir = suite_dir / "coas2_expected_complete"
        solution_cif = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "solution.cif"
        solution_cif.parent.mkdir(parents=True)
        solution_cif.write_text("data_fake\n", encoding="utf-8")

        eval_path = run_dir / "report" / "workflow_evaluation.json"
        exec_path = run_dir / "_raw_run" / "execution" / "execution_run.json"
        _write_json(
            eval_path,
            {
                "goal": "Generate a CoAs2 candidate.",
                "material_system": "CoAs2",
                "evidence_checks": {
                    "retrieval": {"observed": {"corpus_ref": "fake_corpus", "exported_cif_count": 1}},
                    "spp_guidance": {
                        "observed": {
                            "required_pairs": ["As-As", "As-Co", "Co-Co"],
                            "missing_pairs": [],
                            "pot_root": str(root / "missing_pot_root"),
                            "qlip_solve_compatible": True,
                        }
                    },
                },
                "execution_checks": {
                    "solve": {
                        "observed": {
                            "qlip_status": "OPTIMAL",
                            "objective_value": -2.0,
                            "solution_cif_path": str(solution_cif),
                        }
                    }
                },
                "novelty_assessment": {"observed": {"is_novel": False}},
            },
        )
        _write_json(
            exec_path,
            {
                "step_results": [
                    {
                        "tool_name": "crystal.csp_pack",
                        "status": "succeeded",
                        "artifact_refs": [{"ref_name": "candidate_cif_path", "value": "mp-test.cif"}],
                        "output_summary": {
                            "exported_cif_count": 1,
                            "corpus_selection": {"status": "selected", "selected_cif_count": 1},
                        },
                    },
                    {
                        "tool_name": "spp.run_pipeline",
                        "status": "succeeded",
                        "output_summary": {
                            "pot_root_source": "fresh_corpus",
                            "extraction_mode": "qlip_required_pairs",
                            "selected_pot_root": str(root / "missing_pot_root"),
                            "qlip_package_required_pairs": ["As-As", "As-Co", "Co-Co"],
                            "qlip_package_available_pairs": ["As-As", "As-Co", "Co-Co"],
                            "qlip_package_missing_pairs": [],
                            "qlip_solve_compatible": True,
                        },
                    },
                    {"tool_name": "qlip.validate_request", "status": "succeeded", "output_summary": {"package_validation_status": "valid"}},
                    {"tool_name": "qlip.solve", "status": "succeeded", "output_summary": {"status": "OPTIMAL", "objective_value": -2.0, "solution_cif_path": str(solution_cif)}},
                    {"tool_name": "crystal.novelty_check", "status": "succeeded", "output_summary": {}},
                ]
            },
        )
        _write_json(
            suite_dir / "suite_summary.json",
            {
                "runs": [
                    {
                        "run_id": "coas2_expected_complete",
                        "goal": "Generate a CoAs2 candidate.",
                        "material_system": "CoAs2",
                        "final_status": "completed",
                        "qlip_status": "OPTIMAL",
                        "solution_cif_path": str(solution_cif),
                        "novelty_is_novel": False,
                        "artifact_paths": {
                            "workflow_evaluation_json": str(eval_path),
                            "execution_run_json": str(exec_path),
                        },
                    }
                ]
            },
        )

        result = build_workflow_case_figure(suite_dir, "CoAs2", out_dir)

        assert Path(result["png_path"]).exists()
        assert Path(result["svg_path"]).exists()
        table_md = (out_dir / "workflow_case_table.md").read_text(encoding="utf-8")
        for column in [
            "Input",
            "Crystal-DB retrieved corpus",
            "SPP/POT evidence",
            "Visualised optimisation space",
            "Final crystal",
        ]:
            assert column in table_md

        manifest = json.loads((out_dir / "figure_manifest.json").read_text(encoding="utf-8"))
        entry = manifest["figures"][0]
        assert entry["panels"]["spp_pot_guidance"] == "pair_coverage_summary"
        assert entry["panels"]["final_crystal"] == "real solution CIF metadata; structure rendering deferred"
        assert "fake render" in table_md or "solution=" in table_md
