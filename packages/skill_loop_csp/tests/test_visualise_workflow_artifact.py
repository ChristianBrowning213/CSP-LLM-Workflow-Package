from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from sok_llm_orchestrator.agentic import visualise_workflow_artifact as visualizer
from sok_llm_orchestrator.agentic.visualise_workflow_artifact import VestaRenderError, VestaUnavailableError, visualise_workflow_artifact


@pytest.fixture(autouse=True)
def _clear_real_vesta_env(monkeypatch):
    monkeypatch.delenv("VESTA_EXE", raising=False)
    monkeypatch.delenv("VESTA_PATH", raising=False)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _minimal_cif(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """data_demo

loop_

_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z

Na 0.0 0.0 0.0
Cl 0.5 0.5 0.5
""",
        encoding="utf-8",
    )


def _tiny_png(path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(1, 1))
    ax.imshow([[(0.2, 0.4, 0.8)]])
    ax.set_axis_off()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def test_visualise_workflow_artifact_writes_outputs_and_honest_fallbacks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        _minimal_cif(candidate_cif)
        missing_solution = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "missing_solution.cif"
        pot_root = root / "missing_pot_root"

        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate a compact NaCl crystal from retrieved analogues and solve it with QLIP.",
                "material_system": "NaCl",
                "evidence_checks": {
                    "retrieval": {"observed": {"corpus_ref": str(corpus_dir), "exported_cif_count": 1, "neighbor_count": 3}},
                    "spp_guidance": {
                        "observed": {
                            "pot_root": str(pot_root),
                            "required_pairs": ["Cl-Cl", "Cl-Na", "Na-Na"],
                            "missing_pairs": [],
                            "qlip_solve_compatible": True,
                        }
                    },
                },
                "execution_checks": {
                    "solve": {"observed": {"qlip_status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(missing_solution)}}
                },
                "novelty_assessment": {"observed": {"is_novel": False}},
            },
        )
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {
                        "tool_name": "crystal.csp_pack",
                        "status": "succeeded",
                        "artifact_refs": [
                            {"ref_name": "corpus_ref", "value": str(corpus_dir)},
                            {"ref_name": "candidate_cif_path", "value": str(candidate_cif)},
                        ],
                        "output_summary": {
                            "exported_cif_count": 1,
                            "neighbor_count": 3,
                            "query": "Generate a compact NaCl crystal from retrieved analogues and solve it with QLIP.",
                        },
                    },
                    {
                        "tool_name": "spp.run_pipeline",
                        "status": "succeeded",
                        "output_summary": {
                            "selected_pot_root": str(pot_root),
                            "pot_root_source": "fresh_corpus",
                            "extraction_mode": "qlip_required_pairs",
                            "qlip_package_required_pairs": ["Cl-Cl", "Cl-Na", "Na-Na"],
                            "qlip_package_available_pairs": ["Cl-Cl", "Cl-Na", "Na-Na"],
                            "qlip_package_missing_pairs": [],
                        },
                    },
                    {"tool_name": "qlip.validate_request", "status": "succeeded", "output_summary": {"valid": True, "package_validation_status": "valid"}},
                    {"tool_name": "qlip.solve", "status": "succeeded", "output_summary": {"status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(missing_solution)}},
                ]
            },
        )

        result = visualise_workflow_artifact(run_dir, root / "out", "NaCl")

        assert Path(result["png_path"]).exists()
        assert Path(result["pdf_path"]).exists()
        assert Path(result["svg_path"]).exists()
        manifest_path = Path(result["manifest_path"])
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert Path(manifest["pdf_path"]).exists()
        assert manifest["top_level_panel_count"] == 5
        assert manifest["aspect_ratio"] >= 2.7
        assert manifest["panels"]["crystal_db_retrieved_corpus"]["semantic_neighbours_count"] == 3
        assert len(manifest["panels"]["crystal_db_retrieved_corpus"]["children"]) == 3
        assert manifest["panels"]["crystal_db_retrieved_corpus"]["exported_cif_count"] == 1
        assert Path(manifest["semantic_neighbours_sidecars"]["json"]).exists()
        assert Path(manifest["semantic_neighbours_sidecars"]["csv"]).exists()
        assert Path(manifest["semantic_neighbours_sidecars"]["markdown"]).exists()
        # The SPP panel now preserves row pair-coverage metadata when POT curves
        # cannot be parsed, instead of treating the whole panel as deferred.
        assert manifest["panels"]["spp_pot_guidance"]["render_status"] == "metadata_pair_coverage"
        assert manifest["panels"]["spp_pot_guidance"]["data_status"] == "figure_metadata_pair_coverage"
        assert manifest["panels"]["qlip_optimisation_space"]["true_gurobi_landscape"] is False
        assert manifest["panels"]["qlip_optimisation_space"]["objective_card_used"] is True
        assert manifest["panels"]["final_generated_crystal"]["render_status"] == "deferred_missing_cif"
        assert manifest["panels"]["final_generated_crystal"]["renderer_used"] == "fallback_card"
        assert manifest["panels"]["final_generated_crystal"]["vesta_status"] in {"vesta_unavailable", "available"}
        assert manifest["panels"]["final_generated_crystal"]["final_crystal_source_role"] == "qlip_solution"
        assert manifest["panels"]["final_generated_crystal"]["final_crystal_source_role_validated"] is True
        assert manifest["panels"]["final_generated_crystal"]["final_crystal_file_exists"] is False
        assert manifest["panels"]["final_generated_crystal"]["final_crystal_source_warnings"] == ["noncanonical_solve_cif_name"]
        assert str(missing_solution) not in Path(result["svg_path"]).read_text(encoding="utf-8")
        assert manifest["panels"]["spp_pot_guidance"]["row_specific_spp_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]


def test_visualise_workflow_artifact_plots_one_axis_per_parseable_pair() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        solution_cif = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "solution.cif"
        _minimal_cif(candidate_cif)
        _minimal_cif(solution_cif)
        pot_root = root / "pot_root"
        pot_root.mkdir()
        (pot_root / "Cl-Na.POT").write_text(
            "\n".join([*(f"{i * 0.1:.2f} {i * -0.2:.3f}" for i in range(1, 12)), "2.00 999.000"]),
            encoding="utf-8",
        )
        (pot_root / "Na-Na.POT").write_text("\n".join(f"{i * 0.1:.2f} {i * 0.15:.3f}" for i in range(1, 12)), encoding="utf-8")

        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate NaCl.",
                "material_system": "NaCl",
                "evidence_checks": {
                    "retrieval": {"observed": {"corpus_ref": str(corpus_dir), "exported_cif_count": 1}},
                    "spp_guidance": {"observed": {"pot_root": str(pot_root), "required_pairs": ["Cl-Na", "Na-Na"], "missing_pairs": [], "qlip_solve_compatible": True}},
                },
                "execution_checks": {"solve": {"observed": {"qlip_status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)}}},
                "novelty_assessment": {"observed": {"is_novel": True}},
            },
        )
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {"tool_name": "crystal.csp_pack", "status": "succeeded", "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}], "output_summary": {"exported_cif_count": 1}},
                    {
                        "tool_name": "spp.run_pipeline",
                        "status": "succeeded",
                        "output_summary": {
                            "selected_pot_root": str(pot_root),
                            "pot_root_source": "fresh_corpus",
                            "qlip_package_required_pairs": ["Cl-Na", "Na-Na"],
                            "qlip_package_available_pairs": ["Cl-Na", "Na-Na"],
                        },
                    },
                    {"tool_name": "qlip.solve", "status": "succeeded", "output_summary": {"status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)}},
                ]
            },
        )

        result = visualise_workflow_artifact(run_dir, root / "out", "NaCl")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        spp_panel = manifest["panels"]["spp_pot_guidance"]
        assert spp_panel["render_status"] == "rendered_curves"
        assert spp_panel["data_status"] == "real_pot_curves"
        assert "spp_maker.pot_io" in spp_panel["parser_used"]
        assert spp_panel["spp_plot_layout"] == "1x2"
        assert spp_panel["spp_axis_scaling"] == "display_zoom_raw_curve"
        assert spp_panel["spp_plotting"]["render_mode"] == "workflow_inline"
        assert spp_panel["spp_plotting"]["source_style"] == "standalone_scientific"
        assert spp_panel["spp_plotting"]["axis_label_mode"] == "minimal_composite"
        assert spp_panel["spp_plotting"]["y_axis_scaling"] == "display_zoom_raw_curve"
        assert spp_panel["spp_plotting"]["spp_display_mode"] == "zoomed_raw"
        assert spp_panel["spp_plotting"]["spp_zoom_config"]["spp_zoom_upper_strategy"] == "post_drop_percentile"
        assert "y_axis_by_pair" in spp_panel["spp_plotting"]
        assert spp_panel["spp_render_source"] == "raw_data_inline_plot"
        assert spp_panel["spp_render_mode_workflow"] == "workflow_inline"
        assert spp_panel["spp_workflow_uses_embedded_standalone_png"] is False
        assert spp_panel["spp_workflow_raw_data_reused"] is True
        assert spp_panel["spp_workflow_pair_count"] == 2
        assert spp_panel["spp_workflow_layout"] == "1x2"
        assert spp_panel["spp_layout_columns"] == 2
        assert spp_panel["spp_force_shared_y_scale"] is True
        assert spp_panel["spp_shared_y_scale_used"] is True
        assert spp_panel["spp_standalone_exports_present"] is True
        assert spp_panel["spp_box_aspect"] == "1:1"
        assert len(spp_panel["children"]) == 2
        assert {child["pair"] for child in spp_panel["children"]} == {"Cl-Na", "Na-Na"}
        assert all(child["box_aspect"] == "1:1" for child in spp_panel["children"])
        assert all(child["curve_points"] > 0 for child in spp_panel["children"])
        assert all(child["render_mode"] == "workflow_inline" for child in spp_panel["children"])
        assert all(child["spp_render_source"] == "raw_data_inline_plot" for child in spp_panel["children"])
        assert all(child["workflow_panel_image_path"] == "" for child in spp_panel["children"])
        assert all(child["workflow_panel_uses_standalone_style"] is False for child in spp_panel["children"])
        assert all(child["y_axis_scaling"] == "display_zoom_raw_curve" for child in spp_panel["children"])
        assert all(child["spp_display_mode"] == "zoomed_raw" for child in spp_panel["children"])
        assert spp_panel["spp_display_mode"] == "zoomed_raw"
        assert spp_panel["spp_zoom_note"] == "display-only zoom; raw POT values unchanged"
        assert all(child["post_processing"] == "none" for child in spp_panel["children"])
        assert all("cutoff_marker" not in child for child in spp_panel["children"])
        svg_text = Path(result["svg_path"]).read_text(encoding="utf-8")
        assert "wall clipped" not in svg_text
        assert "short-range excluded" not in svg_text
        assert "cutoff" not in json.dumps(spp_panel).lower()
        assert manifest["panels"]["final_generated_crystal"]["render_status"] == "rendered"
        assert manifest["panels"]["final_generated_crystal"]["renderer_used"] == "matplotlib_cif_scatter"
        assert manifest["panels"]["final_generated_crystal"]["vesta_status"] in {"vesta_unavailable", "available"}
        assert manifest["panels"]["final_generated_crystal"]["final_crystal_source_validated"] is True
        assert manifest["panels"]["final_generated_crystal"]["final_crystal_cif_role"] == "canonical_qlip_solution_cif"


def test_visualise_workflow_artifact_spp_three_pair_layout_and_objective_card() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        solution_cif = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "solution.cif"
        _minimal_cif(candidate_cif)
        _minimal_cif(solution_cif)
        pot_root = root / "pot_root"
        pot_root.mkdir()
        for pair in ("Cl-Na", "Na-Na", "Cl-Cl"):
            (pot_root / f"{pair}.POT").write_text("\n".join(f"{i * 0.1:.2f} {i * 0.05:.3f}" for i in range(1, 12)), encoding="utf-8")
        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate NaCl.",
                "material_system": "NaCl",
                "evidence_checks": {
                    "retrieval": {"observed": {"corpus_ref": str(corpus_dir), "exported_cif_count": 1}},
                    "spp_guidance": {"observed": {"pot_root": str(pot_root), "required_pairs": ["Cl-Na", "Na-Na", "Cl-Cl"], "missing_pairs": [], "qlip_solve_compatible": True}},
                },
                "execution_checks": {"solve": {"observed": {"qlip_status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)}}},
            },
        )
        _write_json(run_dir / "_raw_run" / "execution" / "execution_run.json", {"step_results": [{"tool_name": "crystal.csp_pack", "status": "succeeded", "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}], "output_summary": {"exported_cif_count": 1}}]})

        result = visualise_workflow_artifact(run_dir, root / "out", "NaCl")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        spp_panel = manifest["panels"]["spp_pot_guidance"]
        assert spp_panel["spp_plot_layout"] == "2x2"
        assert spp_panel["spp_box_aspect"] == "1:1"
        assert spp_panel["spp_plotting"]["layout"] == "2x2"
        assert spp_panel["spp_layout_columns"] == 2
        assert spp_panel["spp_shared_y_scale_used"] is True
        assert spp_panel["spp_plotting"]["box_aspect"] == "square"
        assert spp_panel["spp_plotting"]["y_axis_scaling"] == "display_zoom_raw_curve"
        assert spp_panel["spp_plotting"]["render_mode"] == "workflow_inline"
        assert manifest["panels"]["qlip_optimisation_space"]["objective_card_used"] is True
        assert manifest["panels"]["qlip_optimisation_space"]["display_mode"] == "workflow_thumbnail"
        assert manifest["panels"]["qlip_optimisation_space"]["surface_annotation"] == "selected_optimum_only"
        assert manifest["panels"]["qlip_optimisation_space"]["optimisation_surface"]["true_gurobi_landscape"] is False
        assert manifest["panels"]["qlip_optimisation_space"]["optimisation_surface"]["display_mode"] == "standalone_scientific"
        assert manifest["panels"]["qlip_optimisation_space"]["workflow_optimisation_surface"]["display_mode"] == "workflow_thumbnail"
        assert manifest["panels"]["qlip_optimisation_space"]["workflow_optimisation_surface"]["selected_solution_marker"]["marker"] == "star"
        assert manifest["panels"]["qlip_optimisation_space"]["workflow_optimisation_surface"]["optimum_annotation_mode"] == "front_visible_2d_overlay"
        assert manifest["panels"]["qlip_optimisation_space"]["optimum_marker"] == "star"
        assert manifest["panels"]["qlip_optimisation_space"]["optimum_label_front_visible"] is True


def test_visualise_workflow_artifact_spp_workflow_zoom_clips_honestly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        solution_cif = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "solution.cif"
        _minimal_cif(candidate_cif)
        _minimal_cif(solution_cif)
        pot_root = root / "pot_root"
        pot_root.mkdir()
        values = [
            (0.50, 120.0),
            (0.75, 90.0),
            (1.00, 8.0),
            (1.25, 2.0),
            (1.50, -1.0),
            (1.75, -1.8),
            (2.00, -1.2),
            (2.25, -0.5),
            (2.50, 0.2),
            (2.75, 0.6),
            (3.00, 0.8),
        ]
        (pot_root / "Cl-Na.POT").write_text("\n".join(f"{x:.2f} {y:.3f}" for x, y in values), encoding="utf-8")
        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate NaCl.",
                "material_system": "NaCl",
                "evidence_checks": {
                    "retrieval": {"observed": {"corpus_ref": str(corpus_dir), "exported_cif_count": 1}},
                    "spp_guidance": {"observed": {"pot_root": str(pot_root), "required_pairs": ["Cl-Na"], "missing_pairs": [], "qlip_solve_compatible": True}},
                },
                "execution_checks": {"solve": {"observed": {"qlip_status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)}}},
            },
        )
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {"tool_name": "crystal.csp_pack", "status": "succeeded", "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}], "output_summary": {"exported_cif_count": 1}},
                    {
                        "tool_name": "spp.run_pipeline",
                        "status": "succeeded",
                        "output_summary": {
                            "selected_pot_root": str(pot_root),
                            "pot_root_source": "fresh_corpus",
                            "qlip_package_required_pairs": ["Cl-Na"],
                            "qlip_package_available_pairs": ["Cl-Na"],
                        },
                    },
                    {"tool_name": "qlip.solve", "status": "succeeded", "output_summary": {"status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)}},
                ]
            },
        )

        result = visualise_workflow_artifact(run_dir, root / "out", "NaCl")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        spp_panel = manifest["panels"]["spp_pot_guidance"]
        child = spp_panel["children"][0]
        assert child["post_processing"] == "none"
        assert child["raw_point_count"] == len(values)
        assert child["y_axis_clipped"] is True
        assert child["display_y_max"] < child["original_y_max"]
        assert child["spp_clipping_annotation"] == "^"
        assert child["spp_clipping_annotation_meaning"] == "high repulsive values exceed the displayed y-limit"
        assert spp_panel["spp_plotting"]["clipping_annotation_shown"] is True
        assert spp_panel["spp_clipping_indicated"] is True
        assert spp_panel["spp_plotting"]["spp_clipping_marker"] == "^"
        assert spp_panel["spp_zoom_config"]["spp_zoom_ignore_initial_x_below"] == 1.0
        assert spp_panel["spp_zoom_config"]["spp_force_zoom_for_all_pairs"] is True
        assert spp_panel["spp_zoom_config"]["spp_zoom_upper_percentile"] == 0.80
        assert spp_panel["spp_zoom_config"]["spp_zoom_lower_percentile"] == 0.02
        assert spp_panel["spp_zoom_config"]["spp_force_shared_y_scale"] is True
        assert spp_panel["spp_zoom_config"]["spp_shared_y_quantile_low"] == 0.05
        assert spp_panel["spp_zoom_config"]["spp_shared_y_quantile_high"] == 0.90
        assert spp_panel["spp_zoom_config"]["spp_shared_y_pad_fraction"] == 0.30
        assert spp_panel["spp_zoom_config"]["spp_min_display_span"] == 2.0
        assert spp_panel["spp_shared_y_scale_used"] is True
        assert spp_panel["spp_y_limit_policy"] == "shared_robust_percentile"
        assert spp_panel["spp_raw_curve_preserved"] is True
        assert spp_panel["spp_clipped_top_count"] == 1
        assert child["display_y_max"] == spp_panel["spp_shared_y_display_range"][1]
        svg_text = Path(result["svg_path"]).read_text(encoding="utf-8")
        assert "top clipped" not in svg_text
        assert "^" in svg_text


def test_visualise_workflow_artifact_failed_gurobi_license_has_no_fake_optimum() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        _minimal_cif(candidate_cif)
        pot_root = root / "pot_root"
        pot_root.mkdir()
        request_ref = run_dir / "_raw_run" / "execution" / "step_001_spp_run_pipeline" / "qlip_request.json"
        validated_ref = run_dir / "_raw_run" / "execution" / "step_002_qlip_validate_request" / "validated_request.json"
        _write_json(request_ref, {"request": {"context": {"pot_root": str(pot_root)}}})
        _write_json(validated_ref, {"valid": True, "context": {"pot_root": str(pot_root)}})
        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate NaCl.",
                "material_system": "NaCl",
                "artifact_refs": {"request_ref": str(request_ref), "validated_request_ref": str(validated_ref), "solution_cif_path": None},
                "evidence_checks": {
                    "retrieval": {"observed": {"corpus_ref": str(corpus_dir), "exported_cif_count": 1}},
                    "spp_guidance": {
                        "observed": {
                            "pot_root": str(pot_root),
                            "required_pairs": ["Cl-Cl", "Cl-Na", "Na-Na"],
                            "missing_pairs": [],
                            "qlip_solve_compatible": True,
                        }
                    },
                },
                "execution_checks": {
                    "validation": {"observed": {"valid": True, "data_diagnostics": {"gurobi_available": True, "pot_root_resolved": True}}},
                    "solve": {"observed": {"executed": True, "qlip_status": "failed", "objective_value": None, "solution_cif_path": None}},
                },
            },
        )
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {
                        "tool_name": "crystal.csp_pack",
                        "status": "succeeded",
                        "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}],
                        "output_summary": {"exported_cif_count": 1},
                    },
                    {
                        "tool_name": "spp.run_pipeline",
                        "status": "succeeded",
                        "output_summary": {
                            "selected_pot_root": str(pot_root),
                            "pot_root_source": "fallback_precompiled",
                            "qlip_solve_compatible": True,
                            "request_ref": str(request_ref),
                            "qlip_package_required_pairs": ["Cl-Cl", "Cl-Na", "Na-Na"],
                            "qlip_package_available_pairs": ["Cl-Cl", "Cl-Na", "Na-Na"],
                            "qlip_package_missing_pairs": [],
                        },
                    },
                    {
                        "tool_name": "qlip.validate_request",
                        "status": "succeeded",
                        "artifact_refs": [
                            {"ref_name": "validated_request_ref", "value": str(validated_ref)},
                            {"ref_name": "solve_ready_request_ref", "value": str(validated_ref)},
                        ],
                        "output_summary": {
                            "valid": True,
                            "package_valid": True,
                            "package_validation_status": "valid",
                            "solve_ready_request_ref": str(validated_ref),
                            "capabilities": {"gurobi_available": True, "pot_root_resolved": True},
                        },
                    },
                    {
                        "tool_name": "qlip.solve",
                        "status": "failed",
                        "error": {"code": "non_solution_status", "message": "qlip.solve returned status=ERROR"},
                        "output_summary": {
                            "qlip_status": "ERROR",
                            "objective_value": None,
                            "pot_root": str(pot_root),
                            "required_pairs": ["Cl-Cl", "Cl-Na", "Na-Na"],
                            "missing_pairs": [],
                            "qlip_error_codes": ["solve_error"],
                            "qlip_error_messages": ["License 2773015 has expired"],
                        },
                    },
                ]
            },
        )

        result = visualise_workflow_artifact(run_dir, root / "out", "NaCl")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["qlip_failure_category"] == "gurobi_license_expired"
        assert manifest["gurobi_license_status"] == "expired"
        assert manifest["gurobi_available"] is True
        assert manifest["qlip_validate_status"] == "valid"
        assert manifest["qlip_solve_status"] == "ERROR"
        assert manifest["qlip_solve_started"] is True
        assert manifest["qlip_solution_cif_produced"] is False
        optimisation = manifest["panels"]["qlip_optimisation_space"]
        assert optimisation["optimum_marker"] == "none"
        assert optimisation["optimum_label_mode"] == "none"
        assert optimisation["workflow_optimisation_surface"]["selected_solution_marker"]["marker"] == "none"
        assert optimisation["workflow_optimisation_surface"]["optimum_annotation_mode"] == "none"
        final_panel = manifest["panels"]["final_generated_crystal"]
        assert final_panel["render_status"] == "deferred_missing_cif"
        assert final_panel["qlip_failure_category"] == "gurobi_license_expired"
        assert final_panel["qlip_solution_cif_produced"] is False
        assert final_panel["final_crystal_source_validation_reason"] == "no solution CIF path was recorded"
        svg_text = Path(result["svg_path"]).read_text(encoding="utf-8")
        assert "Selected optimum" not in svg_text
        assert "No solution CIF produced" in svg_text
        assert "Gurobi license expired" in svg_text


def test_visualise_workflow_artifact_rejects_semantic_neighbour_as_final_crystal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        _minimal_cif(candidate_cif)
        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate NaCl.",
                "material_system": "NaCl",
                "execution_checks": {
                    "solve": {
                        "observed": {
                            "qlip_status": "OPTIMAL",
                            "objective_value": -1.0,
                            "solution_cif_path": str(candidate_cif),
                        }
                    }
                },
            },
        )
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {
                        "tool_name": "crystal.csp_pack",
                        "status": "succeeded",
                        "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}],
                        "output_summary": {"exported_cif_count": 1},
                    },
                    {
                        "tool_name": "qlip.solve",
                        "status": "succeeded",
                        "output_summary": {"status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(candidate_cif)},
                    },
                ]
            },
        )

        result = visualise_workflow_artifact(run_dir, root / "out", "NaCl")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        final_panel = manifest["panels"]["final_generated_crystal"]
        assert final_panel["render_status"] == "wrong_final_crystal_source"
        assert final_panel["final_crystal_source_validated"] is False
        assert final_panel["final_crystal_source_role"] == "retrieval_corpus"
        assert final_panel["final_crystal_cif_role"] == "retrieval_or_semantic_neighbour_cif"
        assert "retrieval/corpus" in final_panel["final_crystal_source_validation_reason"]


def test_visualise_workflow_artifact_nonstandard_solve_cif_name_validates_with_warning() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        solution_cif = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "custom_final.cif"
        _minimal_cif(solution_cif)
        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate NaCl.",
                "material_system": "NaCl",
                "execution_checks": {
                    "solve": {
                        "observed": {
                            "qlip_status": "OPTIMAL",
                            "objective_value": -1.0,
                            "solution_cif_path": str(solution_cif),
                        }
                    }
                },
            },
        )
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {
                        "tool_name": "qlip.solve",
                        "status": "succeeded",
                        "output_summary": {"status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)},
                    },
                ]
            },
        )

        result = visualise_workflow_artifact(run_dir, root / "out", "NaCl")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        final_panel = manifest["panels"]["final_generated_crystal"]
        assert final_panel["render_status"] == "rendered"
        assert final_panel["final_crystal_source_role"] == "qlip_solution"
        assert final_panel["final_crystal_source_validated"] is True
        assert final_panel["final_crystal_file_exists"] is True
        assert final_panel["final_crystal_source_warnings"] == ["noncanonical_solve_cif_name"]


def test_visualise_workflow_artifact_spp_six_pair_layout() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        _minimal_cif(candidate_cif)
        pot_root = root / "pot_root"
        pot_root.mkdir()
        pairs = ["Ba-Ba", "Ba-O", "Ba-Ti", "O-O", "O-Ti", "Ti-Ti"]
        for pair in pairs:
            (pot_root / f"{pair}.POT").write_text("\n".join(f"{i * 0.1:.2f} {i * 0.05:.3f}" for i in range(1, 12)), encoding="utf-8")
        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate BaTiO3.",
                "material_system": "BaTiO3",
                "evidence_checks": {
                    "retrieval": {"observed": {"corpus_ref": str(corpus_dir), "exported_cif_count": 1}},
                    "spp_guidance": {"observed": {"pot_root": str(pot_root), "required_pairs": pairs, "missing_pairs": [], "qlip_solve_compatible": True}},
                },
            },
        )
        _write_json(run_dir / "_raw_run" / "execution" / "execution_run.json", {"step_results": [{"tool_name": "crystal.csp_pack", "status": "succeeded", "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}], "output_summary": {"exported_cif_count": 1}}]})

        result = visualise_workflow_artifact(run_dir, root / "out", "BaTiO3")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        spp_panel = manifest["panels"]["spp_pot_guidance"]
        assert spp_panel["spp_plot_layout"] == "3x2"
        assert spp_panel["spp_box_aspect"] == "1:1"
        assert spp_panel["spp_plotting"]["layout"] == "3x2"
        assert spp_panel["spp_layout_columns"] == 2
        assert spp_panel["spp_shared_y_scale_used"] is True
        assert len(spp_panel["children"]) == 6


def test_visualise_workflow_artifact_uses_proxy_hero_and_records_gurobi_appendix_when_available() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        solution_cif = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "solution.cif"
        gurobi_dir = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "gurobi_visuals"
        spy_png = gurobi_dir / "gurobi_constraint_matrix_spy.png"
        trace_png = gurobi_dir / "gurobi_mip_trace.png"
        meta_json = gurobi_dir / "gurobi_constraint_matrix_meta.json"
        trace_json = gurobi_dir / "gurobi_mip_trace.json"
        trace_csv = gurobi_dir / "gurobi_mip_trace.csv"
        _minimal_cif(candidate_cif)
        _minimal_cif(solution_cif)
        _tiny_png(spy_png)
        _tiny_png(trace_png)
        _write_json(meta_json, {"n_constraints": 7, "n_variables": 11, "nnz": 19, "density": 0.24})
        _write_json(trace_json, {"trace_sparse": True, "samples": []})
        trace_csv.write_text("runtime,incumbent_objective,best_bound,mip_gap\n0,-1,-1,0\n", encoding="utf-8")
        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate NaCl.",
                "material_system": "NaCl",
                "evidence_checks": {"retrieval": {"observed": {"exported_cif_count": 1}}},
                "execution_checks": {"solve": {"observed": {"qlip_status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)}}},
            },
        )
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {"tool_name": "crystal.csp_pack", "status": "succeeded", "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}], "output_summary": {"exported_cif_count": 1}},
                    {
                        "tool_name": "qlip.solve",
                        "status": "succeeded",
                        "artifact_refs": [
                            {"ref_name": "constraint_matrix_spy_path", "value": str(spy_png)},
                            {"ref_name": "constraint_matrix_meta_path", "value": str(meta_json)},
                            {"ref_name": "mip_trace_plot_path", "value": str(trace_png)},
                            {"ref_name": "mip_trace_json_path", "value": str(trace_json)},
                            {"ref_name": "mip_trace_csv_path", "value": str(trace_csv)},
                        ],
                        "output_summary": {"status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)},
                    },
                ]
            },
        )

        result = visualise_workflow_artifact(run_dir, root / "out", "NaCl")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        panel = manifest["panels"]["qlip_optimisation_space"]
        assert panel["panel_type"] == "projected_proxy_surface"
        assert panel["true_gurobi_landscape"] is False
        assert panel["gurobi_diagnostics_available"] is True
        assert panel["gurobi_diagnostics_exported"] is True
        assert panel["gurobi_diagnostics"]["constraint_matrix_spy_path"] == str(spy_png)
        assert panel["gurobi_diagnostics"]["mip_trace_csv_path"] == str(trace_csv)
        assert panel["optimisation_surface"]["true_gurobi_landscape"] is False
        assert panel["display_mode"] == "workflow_thumbnail"
        assert panel["optimisation_surface"]["display_mode"] == "standalone_scientific"
        assert panel["workflow_optimisation_surface"]["display_mode"] == "workflow_thumbnail"
        assert panel["optimisation_surface"]["selected_solution_marker"]["marker"] == "star"
        assert panel["optimisation_surface"]["selected_optimum_label_style"] == "front_visible_2d_overlay_white_bold_black_box"
        assert panel["optimisation_surface"]["optimum_annotation_mode"] == "front_visible_2d_overlay"


def test_visualise_workflow_artifact_uses_existing_rendered_semantic_neighbour_manifest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        out_dir = root / "out"
        panels_dir = out_dir / "workflow_artifact_nacl_panels"
        semantic_dir = panels_dir / "semantic_neighbour_cifs"
        raw_response = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "raw_tool_response.json"
        items = []
        manifest_rows = []
        for rank in range(1, 11):
            png_path = semantic_dir / f"rank_{rank:02d}_s{rank}.png"
            cif_path = semantic_dir / f"rank_{rank:02d}_s{rank}.cif"
            _tiny_png(png_path)
            _minimal_cif(cif_path)
            items.append({"rank": rank, "score": 0.9 - rank * 0.01, "structure_id": f"s{rank}", "source_id": f"mp-{rank}.cif", "export_status": "skipped"})
            manifest_rows.append({"rank": rank, "structure_id": f"s{rank}", "source_id": f"mp-{rank}.cif", "copied_cif_path": str(cif_path), "copy_status": "copied", "png_path": str(png_path), "png_render_status": "rendered"})
        _write_json(raw_response, {"result": {"export": {"items": items}, "neighbors": items}})
        _write_json(semantic_dir / "semantic_neighbour_cifs_manifest.json", manifest_rows)
        _write_json(run_dir / "report" / "workflow_evaluation.json", {"goal": "Generate NaCl.", "material_system": "NaCl"})
        _write_json(run_dir / "_raw_run" / "execution" / "execution_run.json", {"step_results": [{"tool_name": "crystal.csp_pack", "raw_result_ref": str(raw_response), "status": "succeeded", "output_summary": {"exported_cif_count": 1, "neighbor_count": 10}}]})

        result = visualise_workflow_artifact(run_dir, out_dir, "NaCl")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        corpus = manifest["panels"]["crystal_db_retrieved_corpus"]
        assert manifest["semantic_neighbour_render_manifest_used"] is True
        assert manifest["semantic_neighbour_rendered_png_count"] == 10
        assert manifest["semantic_neighbour_cif_count"] == 10
        assert corpus["semantic_neighbour_render_manifest_used"] is True
        assert corpus["semantic_neighbour_rendered_png_count"] == 10
        assert len(corpus["children"]) == 10
        assert all(child["render_status"] == "rendered" for child in corpus["children"])
        assert all(child["renderer_used"] == "pre_rendered_vesta_png" for child in corpus["children"])


def test_visualise_workflow_artifact_ensure_semantic_renders_calls_export_when_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        out_dir = root / "out"
        raw_response = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "raw_tool_response.json"
        items = [{"rank": 1, "score": 0.9, "structure_id": "s1", "source_id": "mp-1.cif", "export_status": "skipped"}]
        _write_json(raw_response, {"result": {"export": {"items": items}, "neighbors": items}})
        _write_json(run_dir / "report" / "workflow_evaluation.json", {"goal": "Generate NaCl.", "material_system": "NaCl"})
        _write_json(run_dir / "_raw_run" / "execution" / "execution_run.json", {"step_results": [{"tool_name": "crystal.csp_pack", "raw_result_ref": str(raw_response), "status": "succeeded", "output_summary": {"exported_cif_count": 0, "neighbor_count": 1}}]})

        def fake_export(*args, **kwargs):
            semantic_dir = out_dir / "workflow_artifact_nacl_panels" / "semantic_neighbour_cifs"
            png_path = semantic_dir / "rank_01_s1.png"
            cif_path = semantic_dir / "rank_01_s1.cif"
            _tiny_png(png_path)
            _minimal_cif(cif_path)
            _write_json(semantic_dir / "semantic_neighbour_cifs_manifest.json", [{"rank": 1, "structure_id": "s1", "copied_cif_path": str(cif_path), "copy_status": "copied", "png_path": str(png_path), "png_render_status": "rendered"}])
            return {"semantic_neighbours_found": 1, "cifs_copied": 1, "pngs_rendered": 1}

        with patch.object(visualizer, "export_and_render_semantic_neighbour_cifs", side_effect=fake_export) as mocked:
            result = visualise_workflow_artifact(run_dir, out_dir, "NaCl", ensure_semantic_neighbour_renders=True)
        mocked.assert_called_once()
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["semantic_neighbour_render_manifest_used"] is True
        assert manifest["semantic_neighbour_rendered_png_count"] == 1


def test_export_final_doc_images_copies_workflow_semantic_and_final_assets() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        figures_dir = root / "figures"
        asset_dir = root / "assets"
        full_png = figures_dir / "workflow_artifact_coas2.png"
        full_pdf = figures_dir / "workflow_artifact_coas2.pdf"
        full_svg = figures_dir / "workflow_artifact_coas2.svg"
        semantic_png = figures_dir / "workflow_artifact_coas2_panels" / "semantic_neighbour_cifs" / "rank_01_s1.png"
        final_png = figures_dir / "workflow_artifact_coas2_panels" / "final_generated_crystal_vesta.png"
        surface_png = figures_dir / "workflow_artifact_coas2_panels" / "optimisation_surface.png"
        spy_png = figures_dir / "workflow_artifact_coas2_panels" / "gurobi_constraint_matrix_spy.png"
        trace_png = figures_dir / "workflow_artifact_coas2_panels" / "gurobi_mip_trace.png"
        trace_csv = figures_dir / "workflow_artifact_coas2_panels" / "gurobi_mip_trace.csv"
        pot_file = root / "pot_root" / "As-As" / "As-As.POT"
        _tiny_png(full_png)
        full_pdf.parent.mkdir(parents=True, exist_ok=True)
        full_pdf.write_bytes(b"%PDF-1.4\n% workflow artifact test pdf\n")
        full_svg.parent.mkdir(parents=True, exist_ok=True)
        full_svg.write_text("<svg></svg>", encoding="utf-8")
        _tiny_png(semantic_png)
        _tiny_png(final_png)
        _tiny_png(surface_png)
        _tiny_png(spy_png)
        _tiny_png(trace_png)
        trace_csv.write_text("runtime,incumbent_objective,best_bound,mip_gap\n", encoding="utf-8")
        pot_file.parent.mkdir(parents=True, exist_ok=True)
        pot_file.write_text("\n".join(f"{i * 0.1:.2f} {i * -0.2:.3f}" for i in range(1, 12)), encoding="utf-8")
        _write_json(
            figures_dir / "workflow_artifact_coas2_manifest.json",
            {
                "case_name": "CoAs2",
                "png_path": str(full_png),
                "pdf_path": str(full_pdf),
                "svg_path": str(full_svg),
                "panels": {
                    "crystal_db_retrieved_corpus": {
                        "children": [
                            {
                                "rank": 1,
                                "render_status": "rendered",
                                "renderer_used": "pre_rendered_vesta_png",
                                "vesta_render_path": str(semantic_png),
                            }
                        ]
                    },
                    "final_generated_crystal": {
                        "render_status": "rendered",
                        "renderer_used": "qlip_vesta_renderer",
                        "vesta_render_path": str(final_png),
                    },
                    "spp_pot_guidance": {
                        "spp_axis_scaling": "raw_full_data_no_postprocess",
                        "children": [
                            {
                                "pair": "As-As",
                                "render_status": "rendered",
                                "source_artifact_path": str(pot_file),
                            }
                        ],
                    },
                    "qlip_optimisation_space": {
                        "panel_type": "projected_proxy_surface",
                        "gurobi_diagnostics": {
                            "constraint_matrix_spy_path": str(spy_png),
                            "mip_trace_plot_path": str(trace_png),
                            "mip_trace_csv_path": str(trace_csv),
                        },
                        "gurobi_diagnostics_available": True,
                        "gurobi_diagnostics_exported": True,
                        "optimisation_surface": {
                            "image_path": str(surface_png),
                            "surface_type": "projected_proxy",
                            "data_source": ["case_name"],
                        }
                    },
                },
            },
        )

        result = visualizer.export_final_doc_images(figures_dir, asset_dir, case_names=["CoAs2"])
        rows = json.loads(Path(result["manifest_json"]).read_text(encoding="utf-8"))
        assert asset_dir.exists()
        assert Path(result["manifest_csv"]).exists()
        assert Path(result["readme"]).exists()
        assert Path(result["alias_manifest_json"]).exists()
        assert Path(result["alias_manifest_csv"]).exists()
        assert Path(result["alias_readme"]).exists()
        assert result["missing_count"] == 0
        roles = {row["image_role"] for row in rows}
        assert "workflow_artifact_png" in roles
        assert "workflow_artifact_pdf" in roles
        assert "workflow_artifact_svg" in roles
        assert "semantic_neighbour_thumbnail" in roles
        assert "final_generated_crystal" in roles
        assert "spp_pair_curve" in roles
        assert "gurobi_constraint_matrix_spy" in roles
        assert "gurobi_mip_trace" in roles
        assert "optimisation_surface" in roles
        assert all(Path(row["exported_path"]).exists() for row in rows)
        assert all(row["exists"] is True for row in rows)
        assert any(row["used_in_workflow_composite"] is True for row in rows)
        assert all(
            Path(row["exported_path"]).parent.name in {"coas2", "gurobi_diagnostics"}
            for row in rows
        )
        spp_rows = [row for row in rows if row["image_role"] == "spp_pair_curve"]
        assert spp_rows[0]["pair"] == "As-As"
        assert spp_rows[0]["pot_file"] == str(pot_file)
        assert spp_rows[0]["y_axis_scaling"] == "raw_full_data_no_postprocess"
        assert spp_rows[0]["render_mode"] == "standalone_scientific"
        assert spp_rows[0]["used_in_workflow_artifact"] is True
        assert spp_rows[0]["used_in_workflow_composite"] is True
        surface_rows = [row for row in rows if row["image_role"] == "optimisation_surface"]
        assert surface_rows[0]["surface_type"] == "projected_proxy"
        gurobi_rows = [row for row in rows if row["image_role"].startswith("gurobi_")]
        assert {"gurobi_constraint_matrix_spy", "gurobi_mip_trace", "gurobi_mip_trace_csv"}.issubset({row["image_role"] for row in gurobi_rows})
        assert all(row["used_in_workflow_artifact"] is False for row in gurobi_rows)
        assert all(Path(row["exported_path"]).parent.name == "gurobi_diagnostics" for row in gurobi_rows)
        assert Path(result["gurobi_diagnostics_readme"]).exists()
        assert Path(result["optimisation_surface_note"]).exists()


def test_projected_optimisation_surface_is_case_specific_and_honest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        coas = visualizer.generate_projected_optimisation_surface(
            {"case_name": "CoAs2", "material_system": "CoAs2", "objective_value": -2.26, "required_pairs": ["As-As", "As-Co", "Co-Co"], "novelty": False},
            root / "coas2_surface.png",
        )
        catio = visualizer.generate_projected_optimisation_surface(
            {"case_name": "CaTiO3", "material_system": "CaTiO3", "objective_value": -8.0, "required_pairs": ["Ca-Ca", "Ca-O", "Ca-Ti", "O-O", "O-Ti", "Ti-Ti"], "novelty": False},
            root / "catio3_surface.png",
        )
        fallback = visualizer.generate_projected_optimisation_surface({"case_name": "Unknown"}, root / "fallback_surface.png")
        assert Path(coas["image_path"]).exists()
        assert Path(catio["image_path"]).exists()
        assert coas["true_gurobi_landscape"] is False
        assert coas["surface_type"] == "projected_proxy"
        assert coas["axis_labels"]["x"] == "structural similarity projection"
        assert coas["axis_labels"]["y"] == "constraint feasibility projection"
        assert coas["selected_solution_marker"]["marker"] == "star"
        assert coas["selected_optimum_label_style"] == "front_visible_2d_overlay_white_bold_black_box"
        assert coas["optimum_annotation_mode"] == "front_visible_2d_overlay"
        assert coas["seed_used"] != catio["seed_used"]
        assert fallback["surface_type"] == "schematic_fallback"


def test_visualise_workflow_artifact_surfaces_corpus_chemistry_mismatch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "aus.cif"
        candidate_cif.parent.mkdir(parents=True, exist_ok=True)
        candidate_cif.write_text(
            """data_bad_analogue
loop_
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Au 0 0 0
S 0.5 0.5 0.5
""",
            encoding="utf-8",
        )
        solution_cif = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "solution.cif"
        _minimal_cif(solution_cif)
        pot_root = root / "pot_root"

        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate BaTiO3.",
                "material_system": "BaTiO3",
                "evidence_checks": {
                    "retrieval": {"observed": {"corpus_ref": str(corpus_dir), "exported_cif_count": 1, "neighbor_count": 10}},
                    "spp_guidance": {"observed": {"pot_root": str(pot_root), "required_pairs": ["Ba-O"], "missing_pairs": [], "qlip_solve_compatible": True}},
                },
                "execution_checks": {"solve": {"observed": {"qlip_status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)}}},
                "novelty_assessment": {"observed": {"is_novel": False}},
            },
        )
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {
                        "tool_name": "crystal.csp_pack",
                        "status": "succeeded",
                        "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}, {"ref_name": "corpus_ref", "value": str(corpus_dir)}],
                        "output_summary": {"exported_cif_count": 1, "neighbor_count": 10},
                    },
                    {"tool_name": "spp.run_pipeline", "status": "succeeded", "output_summary": {"selected_pot_root": str(pot_root), "qlip_package_required_pairs": ["Ba-O"], "qlip_package_available_pairs": ["Ba-O"]}},
                    {"tool_name": "qlip.solve", "status": "succeeded", "output_summary": {"status": "OPTIMAL", "objective_value": -1.0, "solution_cif_path": str(solution_cif)}},
                ]
            },
        )

        result = visualise_workflow_artifact(run_dir, root / "out", "BaTiO3")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        child = manifest["panels"]["crystal_db_retrieved_corpus"]["children"][0]
        assert child["extracted_formula"] == "AuS"
        assert child["contains_target_elements"] is False
        assert "analogue, not target chemistry" in Path(result["svg_path"]).read_text(encoding="utf-8")


def test_visualise_workflow_artifact_require_vesta_fails_when_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        _write_json(run_dir / "report" / "workflow_evaluation.json", {"goal": "Generate NaCl.", "material_system": "NaCl"})
        _write_json(run_dir / "_raw_run" / "execution" / "execution_run.json", {"step_results": []})
        with patch.object(visualizer, "_resolve_vesta_executable", return_value=""):
            with pytest.raises(VestaUnavailableError):
                visualise_workflow_artifact(run_dir, root / "out", "NaCl", require_vesta=True)


def test_visualise_workflow_artifact_uses_qlip_vesta_renderer_when_path_supplied() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        solution_cif = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "solution.cif"
        _minimal_cif(candidate_cif)
        _minimal_cif(solution_cif)
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")
        _write_json(
            run_dir / "report" / "workflow_evaluation.json",
            {
                "goal": "Generate NaCl.",
                "material_system": "NaCl",
                "evidence_checks": {"retrieval": {"observed": {"exported_cif_count": 1}}},
                "execution_checks": {"solve": {"observed": {"qlip_status": "OPTIMAL", "solution_cif_path": str(solution_cif)}}},
            },
        )
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {
                        "tool_name": "crystal.csp_pack",
                        "status": "succeeded",
                        "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}],
                        "output_summary": {"exported_cif_count": 1},
                    },
                    {"tool_name": "qlip.solve", "status": "succeeded", "output_summary": {"status": "OPTIMAL", "solution_cif_path": str(solution_cif)}},
                ]
            },
        )

        def fake_vesta_render(cif_path: Path, out_png: Path, vesta_path: str, **kwargs) -> dict:
            _tiny_png(out_png)
            return {"render_status": "rendered", "renderer_used": "qlip_vesta_renderer", "vesta_render_path": str(out_png), "vesta_call_attempted": True, "vesta_output_exists": True, "vesta_output_size_bytes": out_png.stat().st_size, "vesta_validation_attempts": 1, "timeout_s": kwargs.get("timeout_s"), "call_delay_s": kwargs.get("call_delay_s"), "max_retries": kwargs.get("retries")}

        with patch.object(visualizer, "_render_cif_with_vesta", side_effect=fake_vesta_render):
            result = visualise_workflow_artifact(run_dir, root / "out", "NaCl", vesta_path=fake_vesta)
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["vesta"]["status"] == "available"
        assert manifest["vesta"]["vesta_executable"] == str(fake_vesta.resolve())
        assert manifest["panels"]["final_generated_crystal"]["renderer_used"] == "qlip_vesta_renderer"
        assert manifest["panels"]["final_generated_crystal"]["vesta_status"] == "available"
        assert manifest["panels"]["final_generated_crystal"]["vesta_call_attempted"] is True
        assert manifest["panels"]["final_generated_crystal"]["loader_used"] in {"pil_strict", "pil_load_truncated_safe"}
        assert manifest["vesta_serial_rendering"] is True
        assert manifest["panels"]["final_generated_crystal"]["no_crop_image_mode"] is True


def test_visualise_workflow_artifact_writes_all_semantic_neighbours_sidecars_and_corpus_cards() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        _minimal_cif(candidate_cif)
        raw_response = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "raw_tool_response.json"
        items = [{"rank": 1, "score": 0.95, "structure_id": "s1", "source_id": "db", "cif_path": str(candidate_cif), "export_status": "exported"}]
        items.extend({"rank": rank, "score": 0.95 - rank * 0.01, "structure_id": f"s{rank}", "source_id": "db", "export_status": "skipped"} for rank in range(2, 11))
        _write_json(
            raw_response,
            {
                "result": {
                    "export": {"items": items},
                    "neighbors": [{"rank": item["rank"], "score": item["score"]} for item in items],
                }
            },
        )
        _write_json(run_dir / "report" / "workflow_evaluation.json", {"goal": "Generate NaCl.", "material_system": "NaCl", "evidence_checks": {"retrieval": {"observed": {"exported_cif_count": 1, "neighbor_count": 10}}}})
        _write_json(
            run_dir / "_raw_run" / "execution" / "execution_run.json",
            {
                "step_results": [
                    {
                        "tool_name": "crystal.csp_pack",
                        "status": "succeeded",
                        "raw_result_ref": str(raw_response),
                        "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}],
                        "output_summary": {"exported_cif_count": 1, "neighbor_count": 10},
                    }
                ]
            },
        )
        result = visualise_workflow_artifact(run_dir, root / "out", "NaCl")
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        corpus = manifest["panels"]["crystal_db_retrieved_corpus"]
        assert corpus["semantic_neighbour_count"] == 10
        assert corpus["semantic_neighbours_rendered_count"] == 1
        assert corpus["semantic_neighbours_without_cif_count"] == 9
        assert corpus["spp_exported_cif_count"] == 1
        assert corpus["spp_exported_neighbour_ids"] == ["s1"]
        assert len(corpus["children"]) == 10
        assert sum(1 for child in corpus["children"] if child["render_status"] == "metadata_card_no_cif_export") == 9
        sidecar = Path(manifest["semantic_neighbours_sidecars"]["json"])
        rows = json.loads(sidecar.read_text(encoding="utf-8"))
        assert len(rows) == 10
        assert rows[0]["exported_for_spp"] is True
        assert rows[1]["cif_export_status"] == "not_exported_or_policy_blocked"
        assert rows[0]["render_status"] == "rendered"
        assert Path(rows[0]["vesta_ready_cif_path"]).exists()


def test_export_and_render_semantic_neighbour_cifs_utility() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        first_cif = corpus_dir / "first.cif"
        second_cif = corpus_dir / "second.cif"
        _minimal_cif(first_cif)
        _minimal_cif(second_cif)
        raw_response = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "raw_tool_response.json"
        items = [
            {"rank": 1, "score": 0.9, "structure_id": "s1", "source_id": "db", "cif_path": str(first_cif), "export_status": "exported"},
            {"rank": 2, "score": 0.8, "structure_id": "s2", "source_id": "db", "cif_path": str(second_cif), "export_status": "exported"},
            {"rank": 3, "score": 0.7, "structure_id": "s3", "source_id": "db", "export_status": "skipped"},
        ]
        _write_json(raw_response, {"result": {"export": {"items": items}, "neighbors": items}})
        _write_json(run_dir / "report" / "workflow_evaluation.json", {"goal": "Generate NaCl.", "material_system": "NaCl"})
        _write_json(run_dir / "_raw_run" / "execution" / "execution_run.json", {"step_results": [{"tool_name": "crystal.csp_pack", "raw_result_ref": str(raw_response), "status": "succeeded", "output_summary": {"exported_cif_count": 2, "neighbor_count": 3}}]})
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")

        def fake_render(cif_path: Path, out_png: Path, vesta_path: str, **kwargs) -> dict:
            _tiny_png(out_png)
            return {"render_status": "rendered", "renderer_used": "qlip_vesta_renderer", "vesta_render_path": str(out_png), "vesta_output_exists": True, "vesta_output_size_bytes": out_png.stat().st_size}

        with patch.object(visualizer, "_render_cif_with_vesta", side_effect=fake_render):
            result = visualizer.export_and_render_semantic_neighbour_cifs(
                run_dir,
                root / "out",
                "NaCl",
                root / "semantic_cifs",
                export_cifs=True,
                render_pngs=True,
                vesta_path=fake_vesta,
            )

        assert result["semantic_neighbours_found"] == 3
        assert result["cifs_copied"] == 2
        assert result["pngs_rendered"] == 2
        assert not result["failed_renders"]
        assert (root / "semantic_cifs" / "rank_01_s1.cif").exists()
        assert (root / "semantic_cifs" / "rank_01_s1.png").exists()
        rows = json.loads(Path(result["manifest_json"]).read_text(encoding="utf-8"))
        assert rows[2]["copy_status"] == "no_cif_available"


def test_export_and_render_semantic_neighbour_cifs_resolves_source_id_from_search_root() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        search_root = root / "crystal_db" / "data" / "cifs"
        source_cif = search_root / "mp-28884.cif"
        _minimal_cif(source_cif)
        raw_response = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "raw_tool_response.json"
        items = [
            {"rank": 1, "score": 0.9, "structure_id": "s1", "source_id": "mp-exported.cif", "cif_path": str(source_cif), "export_status": "exported"},
            {"rank": 2, "score": 0.8, "structure_id": "s2", "source_id": "mp-28884.cif", "export_status": "skipped"},
        ]
        _write_json(raw_response, {"result": {"export": {"items": items}, "neighbors": items}})
        _write_json(run_dir / "report" / "workflow_evaluation.json", {"goal": "Generate NaCl.", "material_system": "NaCl"})
        _write_json(run_dir / "_raw_run" / "execution" / "execution_run.json", {"step_results": [{"tool_name": "crystal.csp_pack", "raw_result_ref": str(raw_response), "status": "succeeded", "output_summary": {"exported_cif_count": 1, "neighbor_count": 2}}]})

        result = visualizer.export_and_render_semantic_neighbour_cifs(
            run_dir,
            root / "out",
            "NaCl",
            root / "semantic_cifs",
            export_cifs=True,
            render_pngs=False,
            semantic_neighbour_cif_search_roots=[search_root],
        )

        rows = json.loads(Path(result["manifest_json"]).read_text(encoding="utf-8"))
        assert result["semantic_neighbours_found"] == 2
        assert result["cifs_copied"] == 2
        assert rows[0]["cif_resolution_method"] == "existing_source_path"
        assert rows[1]["cif_resolution_method"] == "source_id_search"
        assert Path(rows[1]["resolved_source_cif_path"]).is_file()
        assert str(source_cif) in rows[1]["cif_search_matches"]
        assert rows[1]["copy_status"] == "copied"
        assert (root / "semantic_cifs" / "rank_02_s2.cif").exists()


def test_vesta_output_initially_truncated_then_valid_after_retry() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cif = root / "demo.cif"
        out_png = root / "out.png"
        _minimal_cif(cif)
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")

        staged_output = {"path": None}

        def fake_export(cif_path: Path, output_path: Path, vesta_path: str) -> Path:
            staged_output["path"] = output_path
            output_path.write_bytes(b"\x89PNG\r\n\x1a\nbroken")
            return output_path

        sleeps = {"count": 0}

        def fake_sleep(seconds: float) -> None:
            sleeps["count"] += 1
            if staged_output["path"] is not None:
                _tiny_png(staged_output["path"])

        with patch.object(visualizer, "_call_qlip_vesta_export", side_effect=fake_export), patch.object(visualizer.time, "sleep", side_effect=fake_sleep):
            result = visualizer._render_cif_with_vesta(
                cif,
                out_png,
                str(fake_vesta),
                timeout_s=0.2,
                call_delay_s=0,
                retries=0,
                stabilization_poll_interval_s=0.01,
                stabilization_required_identical_checks=1,
            )

        assert result["render_status"] == "rendered"
        assert result["vesta_output_exists"] is True
        assert result["vesta_validation_attempts"] >= 1


def test_vesta_renderer_waits_for_delayed_source_and_uses_short_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staging_root = root / "staging"
        monkeypatch.setattr(visualizer, "_VESTA_STAGING_ROOT", staging_root)
        monkeypatch.setattr(visualizer, "_VESTA_BUILD_UUID", "build-delayed")
        source = root / "delayed" / "source.cif"
        out_png = root / "package" / "very" / "long" / "final.png"
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")
        sleeps = {"count": 0}
        launched: dict[str, Path] = {}

        def fake_sleep(_seconds: float) -> None:
            sleeps["count"] += 1
            if sleeps["count"] == 2 and not source.exists():
                _minimal_cif(source)

        def fake_export(cif_path: Path, output_path: Path, _vesta_path: str) -> Path:
            launched["cif"] = cif_path
            launched["png"] = output_path
            assert cif_path.name == "input.cif"
            assert output_path.name == "output.png"
            assert staging_root in cif_path.parents
            _tiny_png(output_path)
            return output_path

        with patch.object(visualizer, "_call_qlip_vesta_export", side_effect=fake_export):
            result = visualizer._render_cif_with_vesta(
                source,
                out_png,
                str(fake_vesta),
                timeout_s=1.0,
                call_delay_s=0,
                retries=0,
                stabilization_poll_interval_s=0.01,
                stabilization_required_identical_checks=1,
                sleep_func=fake_sleep,
            )

        assert result["render_status"] == "rendered"
        assert Path(result["vesta_render_path"]) == out_png
        assert out_png.exists()
        assert result["staged_cif_path"].endswith("input.cif")
        assert result["staged_ready_wait_ms"] >= 0
        assert not Path(result["staging_dir"]).exists()
        assert launched["cif"] != source


def test_vesta_renderer_does_not_launch_when_source_never_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setattr(visualizer, "_VESTA_STAGING_ROOT", root / "staging")
        source = root / "missing.cif"
        out_png = root / "out.png"
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")

        with patch.object(visualizer, "_call_qlip_vesta_export") as mocked_export, pytest.raises(VestaRenderError) as exc_info:
            visualizer._render_cif_with_vesta(
                source,
                out_png,
                str(fake_vesta),
                timeout_s=0.01,
                call_delay_s=0,
                retries=0,
                stabilization_poll_interval_s=0.001,
                sleep_func=lambda _seconds: None,
            )

        assert exc_info.value.code == "vesta_source_cif_not_ready"
        mocked_export.assert_not_called()


def test_vesta_failed_render_retains_staging_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setattr(visualizer, "_VESTA_STAGING_ROOT", root / "staging")
        source = root / "source.cif"
        _minimal_cif(source)
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")

        def fake_export(cif_path: Path, _output_path: Path, _vesta_path: str) -> Path:
            raise FileNotFoundError(f"The input file was not found: {cif_path}")

        with patch.object(visualizer, "_call_qlip_vesta_export", side_effect=fake_export), pytest.raises(VestaRenderError) as exc_info:
            visualizer._render_cif_with_vesta(
                source,
                root / "out.png",
                str(fake_vesta),
                timeout_s=0.01,
                call_delay_s=0,
                retries=1,
                stabilization_poll_interval_s=0.001,
                sleep_func=lambda _seconds: None,
            )

        assert exc_info.value.code == "vesta_input_file_not_found"
        staged = Path(exc_info.value.diagnostics["staged_cif_path"])
        assert staged.exists()
        assert staged.name == "input.cif"
        assert exc_info.value.diagnostics["cleanup_status"] == "retained_for_debugging"
        assert exc_info.value.diagnostics["retry_count"] == 1


def test_vesta_successful_output_is_verified_before_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setattr(visualizer, "_VESTA_STAGING_ROOT", root / "staging")
        source = root / "source.cif"
        out_png = root / "final.png"
        _minimal_cif(source)
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")

        def fake_export(_cif_path: Path, output_path: Path, _vesta_path: str) -> Path:
            _tiny_png(output_path)
            return output_path

        with patch.object(visualizer, "_call_qlip_vesta_export", side_effect=fake_export):
            result = visualizer._render_cif_with_vesta(
                source,
                out_png,
                str(fake_vesta),
                timeout_s=0.2,
                call_delay_s=0,
                retries=0,
                stabilization_poll_interval_s=0.01,
                stabilization_required_identical_checks=1,
            )

        image, _diag = visualizer._load_vesta_png(out_png)
        assert image.shape[0] > 0
        assert result["published_output_size_bytes"] == out_png.stat().st_size


def test_long_source_paths_render_through_short_staged_path(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setattr(visualizer, "_VESTA_STAGING_ROOT", root / "stage")
        long_dir = root / ("a" * 40) / ("b" * 40) / ("c" * 40)
        source = long_dir / "source_with_a_long_name.cif"
        _minimal_cif(source)
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")
        seen: dict[str, Path] = {}

        def fake_export(cif_path: Path, output_path: Path, _vesta_path: str) -> Path:
            seen["cif"] = cif_path
            _tiny_png(output_path)
            return output_path

        with patch.object(visualizer, "_call_qlip_vesta_export", side_effect=fake_export):
            visualizer._render_cif_with_vesta(source, root / "out.png", str(fake_vesta), timeout_s=0.2, call_delay_s=0, retries=0)

        assert seen["cif"].name == "input.cif"
        assert len(str(seen["cif"])) < len(str(source))


def test_build_lock_blocks_simultaneous_destructive_builds() -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "build_paper_workflow_artifact_package.py"
    spec = importlib.util.spec_from_file_location("build_paper_workflow_artifact_package_for_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    BuildLock = module.BuildLock

    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "build.lock"
        with BuildLock(lock_path, timeout_s=0.01):
            with pytest.raises(RuntimeError):
                with BuildLock(lock_path, timeout_s=0.01):
                    pass
        assert not lock_path.exists()


def test_paper_display_and_spp_flags_survive_semantic_row_build() -> None:
    row = {
        "rank": 1,
        "paper_display_rank": 1,
        "paper_display_score": 12.5,
        "score": 99.0,
        "structure_id": "display-1",
        "source_id": "mp-1.cif",
        "formula": "BaTiO3",
        "cif_path": "",
        "selected_for_spp": False,
        "selected_for_paper_display": True,
        "visual_similarity_reason": "same prototype family",
    }
    data = {
        "export_items": [row],
        "neighbors": [row],
        "retrieved_cifs": [],
        "material_system": "BaTiO3",
    }

    built = visualizer._build_semantic_neighbor_rows(data)[0]

    assert built["selected_for_spp"] is False
    assert built["exported_for_spp"] is False
    assert built["selected_for_paper_display"] is True
    assert built["paper_display_score"] == 12.5
    assert built["visual_similarity_reason"] == "same prototype family"


def test_vesta_missing_output_retries_then_succeeds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cif = root / "demo.cif"
        out_png = root / "retry.png"
        _minimal_cif(cif)
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")
        attempts = {"count": 0}

        def fake_export(cif_path: Path, output_path: Path, vesta_path: str) -> Path:
            attempts["count"] += 1
            if attempts["count"] == 2:
                _tiny_png(output_path)
            return output_path

        with patch.object(visualizer, "_call_qlip_vesta_export", side_effect=fake_export), patch.object(visualizer.time, "sleep", return_value=None):
            result = visualizer._render_cif_with_vesta(
                cif,
                out_png,
                str(fake_vesta),
                timeout_s=0.05,
                call_delay_s=0,
                retries=2,
                stabilization_poll_interval_s=0.01,
                stabilization_required_identical_checks=1,
            )

        assert attempts["count"] == 2
        assert result["render_status"] == "rendered"
        assert result["vesta_attempts"] == 2
        assert result["output_exists_each_attempt"] == [False, True]


def test_vesta_missing_output_after_retries_reports_specific_code() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cif = root / "demo.cif"
        out_png = root / "missing.png"
        _minimal_cif(cif)
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")

        def fake_export(cif_path: Path, output_path: Path, vesta_path: str) -> Path:
            return output_path

        with patch.object(visualizer, "_call_qlip_vesta_export", side_effect=fake_export), patch.object(visualizer.time, "sleep", return_value=None):
            with pytest.raises(VestaRenderError) as exc_info:
                visualizer._render_cif_with_vesta(
                    cif,
                    out_png,
                    str(fake_vesta),
                    timeout_s=0.05,
                    call_delay_s=0,
                    retries=1,
                    stabilization_poll_interval_s=0.01,
                    stabilization_required_identical_checks=1,
                )

        assert exc_info.value.code == "vesta_output_missing_after_retries"
        assert exc_info.value.diagnostics["vesta_attempts"] == 2
        assert exc_info.value.diagnostics["output_exists_each_attempt"] == [False, False]


def test_visualise_workflow_artifact_passes_vesta_runtime_cli_settings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        corpus_dir = run_dir / "_raw_run" / "execution" / "step_000_crystal_csp_pack" / "csp_pack" / "cifs"
        candidate_cif = corpus_dir / "nacl.cif"
        solution_cif = run_dir / "_raw_run" / "execution" / "step_003_qlip_solve" / "solution.cif"
        _minimal_cif(candidate_cif)
        _minimal_cif(solution_cif)
        fake_vesta = root / "VESTA.exe"
        fake_vesta.write_text("fake", encoding="utf-8")
        _write_json(run_dir / "report" / "workflow_evaluation.json", {"goal": "Generate NaCl.", "material_system": "NaCl", "execution_checks": {"solve": {"observed": {"solution_cif_path": str(solution_cif)}}}})
        _write_json(run_dir / "_raw_run" / "execution" / "execution_run.json", {"step_results": [{"tool_name": "crystal.csp_pack", "status": "succeeded", "artifact_refs": [{"ref_name": "candidate_cif_path", "value": str(candidate_cif)}], "output_summary": {"exported_cif_count": 1, "neighbor_count": 1}}, {"tool_name": "qlip.solve", "status": "succeeded", "output_summary": {"solution_cif_path": str(solution_cif)}}]})

        def fake_vesta_render(cif_path: Path, out_png: Path, vesta_path: str, **kwargs) -> dict:
            _tiny_png(out_png)
            return {"render_status": "rendered", "renderer_used": "qlip_vesta_renderer", "vesta_render_path": str(out_png), "vesta_call_attempted": True, "vesta_output_exists": True, "vesta_output_size_bytes": out_png.stat().st_size, "vesta_validation_attempts": 1, "timeout_s": kwargs.get("timeout_s"), "call_delay_s": kwargs.get("call_delay_s"), "max_retries": kwargs.get("retries")}

        with patch.object(visualizer, "_render_cif_with_vesta", side_effect=fake_vesta_render):
            result = visualise_workflow_artifact(run_dir, root / "out", "NaCl", vesta_path=fake_vesta, vesta_timeout_s=12, vesta_call_delay_s=0.5, vesta_retries=4)
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["vesta_timeout_s"] == 12
        assert manifest["vesta_call_delay_s"] == 0.5
        assert manifest["vesta_retries"] == 4
        assert manifest["panels"]["final_generated_crystal"]["timeout_s"] == 12
        assert manifest["panels"]["final_generated_crystal"]["call_delay_s"] == 0.5
        assert manifest["panels"]["final_generated_crystal"]["max_retries"] == 4


def test_vesta_png_loader_tolerates_viewable_truncated_output() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_png = root / "viewable.png"
        _tiny_png(out_png)
        from PIL import Image, ImageFile

        original_open = Image.open

        def fake_open(path):
            if not ImageFile.LOAD_TRUNCATED_IMAGES:
                raise OSError("image file is truncated")
            return original_open(path)

        with patch("PIL.Image.open", side_effect=fake_open):
            image, diagnostics = visualizer._load_vesta_png(out_png)

        assert image.shape[2] == 4
        assert diagnostics["loader_used"] == "pil_load_truncated_safe"
        assert diagnostics["truncated_tolerance_used"] is True
        assert "vesta_png_required_truncated_tolerance" in diagnostics["warnings"]


def test_vesta_output_remains_truncated_reports_specific_code() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_png = root / "truncated.png"
        out_png.write_bytes(b"\x89PNG\r\n\x1a\nbroken")
        with pytest.raises(VestaRenderError) as exc_info:
            visualizer._wait_for_complete_image(out_png, timeout_s=0.01, interval_s=0.001)
        assert exc_info.value.code == "vesta_output_truncated"
        assert exc_info.value.diagnostics["vesta_output_exists"] is True
        assert exc_info.value.diagnostics["vesta_output_size_bytes"] > 0


def test_vesta_png_loader_unreadable_file_reports_specific_code() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad_png = root / "bad.png"
        bad_png.write_text("not an image", encoding="utf-8")
        with pytest.raises(VestaRenderError) as exc_info:
            visualizer._load_vesta_png(bad_png)
        assert exc_info.value.code == "vesta_output_unreadable"
        assert exc_info.value.diagnostics["vesta_output_exists"] is True
