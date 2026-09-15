from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from pathlib import Path

import pytest
from PIL import Image
from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.workflow import row_visualization as visual
from sok_llm_orchestrator.workflow import timestamped_figure_package as package


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pot(path: Path, values: tuple[float, float, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "spline cubic reverse\nNa core O core 0.0 11.0\n"
        + "\n".join(f"{distance:.3f} {value}" for distance, value in zip((1.5, 2.0, 2.5), values))
        + "\n",
        encoding="utf-8",
    )


def _fixture(root: Path) -> tuple[dict[str, object], Path, list[str]]:
    table_root = root / "table"
    row_dir = table_root / "rows" / "ROW-1"
    attempt = root / "attempt"
    retrieved = attempt / "retrieved_cifs"
    retrieved.mkdir(parents=True)
    ids = ["actual-top-1", "actual-top-2"]
    structures = (
        Structure(Lattice.cubic(4), ["Na"], [(0, 0, 0)]),
        Structure(Lattice.cubic(5), ["O"], [(0, 0, 0)]),
    )
    for structure_id, structure in zip(ids, structures):
        structure.to(filename=retrieved / f"{structure_id}.cif")
    generated = row_dir / "generated.cif"
    generated.parent.mkdir(parents=True)
    Structure(Lattice.cubic(4.2), ["Na", "O"], [(0, 0, 0), (0.5, 0.5, 0.5)]).to(filename=generated)
    request_a, regulator_a = root / "request" / "NA-O.POT", root / "regulator" / "NA-O.POT"
    regulator_b = root / "regulator" / "O-O.POT"
    _pot(request_a, (3, 1, 0)); _pot(regulator_a, (2, 0, -1)); _pot(regulator_b, (4, 2, 0))
    (attempt / "attempt_manifest.json").write_text(json.dumps({"scientific_config": {
        "outer_objective_scale": 10.0, "regulator_coefficient": 2.0,
    }}), encoding="utf-8")
    trace = {
        "attempt_workspace": str(attempt), "retrieved_ids": ids, "retrieval_scores": [0.9, 0.8],
        "qlip_adapter": {"required_pairs": ["Na-O", "O-O"], "guidance_weight": 10.0,
                         "representation": "COMBINED_REQUEST_AND_REGULATOR"},
        "request_pair_results": [
            {"species_pair": "Na-O", "guidance_mode": "REQUEST_PLUS_REGULATOR",
             "request_pot_path": str(request_a), "regulator_pot_path": str(regulator_a)},
            {"species_pair": "O-O", "guidance_mode": "REGULATOR_ONLY_REQUEST_MISSING",
             "request_pot_path": "", "regulator_pot_path": str(regulator_b)},
        ],
    }
    (row_dir / "workflow_trace.json").write_text(json.dumps(trace), encoding="utf-8")
    summary: dict[str, object] = {
        "row_id": "ROW-1", "formula": "NaO", "request": "Generate a sodium oxide candidate from retrieved evidence.",
        "cif_generated": "YES", "cif_path": str(generated), "workflow_status": "PASS",
        "solver_status": "OPTIMAL", "objective_parity": "PASS", "sca_target_formula_match": True,
        "sca_status": "PASS", "sca_topology_status": "PASS", "chgnet_converged": True,
        "generated_space_group": "Pm-3m", "relaxed_space_group": "Pm-3m", "initial_relaxed_match": True,
    }
    return summary, row_dir, ids


def test_canonical_row_figure_uses_actual_retrieval_solver_pots_and_generated_cif(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        summary, row_dir, retrieval_ids = _fixture(root)
        rendered_sources: list[Path] = []

        def fake_render(cif_path: Path, cache_root: Path, vesta_path: str):
            rendered_sources.append(Path(cif_path))
            image_path = cache_root / f"{_hash(Path(cif_path))}.png"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (320, 240), "white").save(image_path)
            return image_path, {"source_cif": str(cif_path), "source_cif_sha256": _hash(Path(cif_path))}

        monkeypatch.setattr(visual, "_resolve_vesta_executable", lambda value=None: "VESTA.exe")
        monkeypatch.setattr(visual, "render_vesta", fake_render)
        manifest = visual.build_row_workflow_figure(summary, row_dir, root / "figures")

        assert Path(manifest["workflow_figure_png"]).is_file()
        assert Path(manifest["workflow_figure_pdf"]).is_file()
        assert manifest["retrieval_ids"] == retrieval_ids
        assert manifest["spp_pairs"] == ["Na-O", "O-O"]
        assert manifest["spp_pair_modes"]["Na-O"] == "REQUEST_PLUS_REGULATOR"
        assert manifest["spp_pair_modes"]["O-O"].startswith("REGULATOR_ONLY")
        assert manifest["generated_cif_sha256"] == _hash(row_dir / "generated.cif")
        assert rendered_sources[0] == row_dir / "generated.cif"
        assert manifest["validation_summary"]["Objective parity"] == "PASS"
        curve_rows = list(csv.DictReader((row_dir / "figures" / "spp_solver_guidance.csv").open(encoding="utf-8")))
        assert {row["species_pair"] for row in curve_rows} == {"Na-O", "O-O"}
        assert all(Path(row["regulator_pot_path"]).is_file() for row in curve_rows)
        assert all(row["regulator_pot_sha256"] == _hash(Path(row["regulator_pot_path"])) for row in curve_rows)
        assert set(manifest["spp_axis_qa"]) == {"Na-O", "O-O"}
        assert all(item["all_finite_points_strictly_inside"] for item in manifest["spp_axis_qa"].values())
        assert all(item["curve_min"] > item["axis_lower"] for item in manifest["spp_axis_qa"].values())
        assert all(item["curve_max"] < item["axis_upper"] for item in manifest["spp_axis_qa"].values())
        labels = manifest["validation_summary"]
        assert "CrystalNN family-topology checks" in labels
        assert "pymatgen SpacegroupAnalyzer" in labels
        assert all("topology validation not available" not in str(value).lower() for value in labels.values())


def test_solver_effective_curve_limits_include_complete_wall_without_clipping() -> None:
    lower, upper = visual.finite_curve_ylim([-1.0e9, -2.0, 0.0, 7.5e8])
    assert lower < -1.0e9
    assert upper > 7.5e8


def test_controlled_failure_cannot_fabricate_a_success_figure() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        row_dir = Path(temporary) / "table" / "rows" / "FAILED"
        row_dir.mkdir(parents=True)
        with pytest.raises(ValueError, match="CIF-emitting canonical row"):
            visual.build_row_workflow_figure(
                {"row_id": "FAILED", "cif_generated": "NO", "workflow_status": "CONTROLLED_WORKFLOW_FAILURE"},
                row_dir, Path(temporary) / "figures",
            )
        assert not (row_dir / "figures" / "workflow_full.png").exists()


def test_shortened_request_removes_only_retrieval_boilerplate() -> None:
    assert visual.shorten_request("Generate a rocksalt nickel oxide structure using retrieved oxide evidence.") == "Generate a rocksalt nickel oxide structure."
    assert visual.shorten_request("Generate Na3Zr2Si2PO12 with requested C2 symmetry.") == "Generate Na3Zr2Si2PO12 with requested C2 symmetry."


def test_timestamped_package_name_is_new_and_auditable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        first = package.timestamped_output_root(Path(temporary))
        assert first.parent == Path(temporary)
        assert first.name.startswith("Paper_results_per_row_traceability_upgrade_")
        assert not first.exists()


def test_real_scaffold_projection_uses_all_twelve_unit_cell_edges() -> None:
    matrix = Lattice.cubic(4.0).matrix
    edges = package._cell_edges(matrix)
    assert len(edges) == 12
    assert all(len(start) == len(end) == 3 for start, end in edges)


def test_final_paper_figure_sources_remain_machine_derived() -> None:
    figures = visual.ROOT / "artifacts" / "final_paper_results" / "figures"
    master_path = visual.ROOT / "artifacts" / "final_paper_results" / "MASTER_RESULTS.csv"
    if not figures.is_dir() or not master_path.is_file():
        pytest.skip("final paper package is not present")
    master = {row["row_id"]: row for row in visual.read_csv(master_path)}
    figure1 = json.loads((figures / "Figure_1_trace_source.json").read_text(encoding="utf-8"))
    assert Path(figure1["source_workflow_figure"]).is_file()
    figure2 = visual.read_csv(figures / "Figure_2_text_intent_showcase_source.csv")
    assert all(row["actual_request"] == master[row["row_id"]]["request"] for row in figure2)
    figure3 = visual.read_csv(figures / "Figure_3_validation_quality_source.csv")
    assert figure3 == [row for row in master.values() if row["experiment_block"] == "BREADTH"]
    scaffold = json.loads((figures / "Figure_4_scaffold_source.json").read_text(encoding="utf-8"))
    assert scaffold["scaffold_id"] == "nasicon_na3zr2si2po12_c2_ordered"
