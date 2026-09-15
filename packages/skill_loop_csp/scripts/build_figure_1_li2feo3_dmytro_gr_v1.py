"""Build the live Li2FeO3 paper workflow figure with the historical renderer."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

from pymatgen.core import Structure
from PIL import Image, ImageChops


REPO = Path(__file__).resolve().parents[1]
CRYSTAL = REPO.parent / "Crystal-DB"
RUN = CRYSTAL / "artifacts" / "paper_workflow_li2feo3_dmytro_gr_v1" / "runs" / "layered" / "layered-repaired-041"
OUT = CRYSTAL / "artifacts" / "paper_figures_dmytro_gr_v1" / "figure_1_li2feo3"
VESTA = Path(r"C:\Users\brown\Documents\VESTA-win64\VESTA-win64\VESTA.exe")
OLD_V4_SHA256 = "86f88db42a132549b2fbfa53f076c442a12fc8fa5137b4f3f352f3ef88df4fd6"
PAIR_ORDER = ("Li-Li", "Li-Fe", "Li-O", "Fe-Fe", "Fe-O", "O-O")
STEM = "FIGURE_1_LI2FEO3_DMYTRO_GR_V1"

sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from build_paper_workflow_artifact_package import build_render_bundle  # noqa: E402
from sok_llm_orchestrator.agentic.visualise_workflow_artifact import (  # noqa: E402
    _parse_pot_file,
    visualise_workflow_artifact,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_pair(pair: str) -> str:
    parts = pair.split("-")
    return "-".join(sorted(parts))


def crop_vesta_whitespace(source: Path, destination: Path) -> None:
    image = Image.open(source).convert("RGB")
    difference = ImageChops.difference(image, Image.new("RGB", image.size, "white")).convert("L")
    difference = difference.point(lambda value: 255 if value > 12 else 0)
    box = difference.getbbox()
    if box is None:
        raise ValueError(f"VESTA render contains no visible structure: {source}")
    left, top, right, bottom = box
    pad_x = max(12, int((right - left) * 0.08))
    pad_y = max(12, int((bottom - top) * 0.08))
    cropped = image.crop((max(0, left - pad_x), max(0, top - pad_y), min(image.width, right + pad_x), min(image.height, bottom + pad_y)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(destination)


def main() -> None:
    summary = read_json(RUN / "run_summary.json")
    sca = read_json(RUN / "sca" / "result.json")
    retrieval = read_json(RUN / "retrieval" / "results.json")
    exclusions = read_json(RUN / "retrieval" / "exclusions.json")
    build_path = RUN / "spp" / "fit_round_01" / "spp_build_manifest.json"
    build = read_json(build_path)
    pairs = list((build.get("blend_manifest") or {}).get("pairs") or [])
    raw_cif = RUN / "generated" / "candidate.cif"
    raw_hash = sha256(raw_cif)

    assert summary["candidate_valid"] is True
    assert summary["NO_TARGET_LEAKAGE"] is True
    assert summary["SPP_ARTIFACT_VALID"] is True
    assert summary["spp_corpus_count"] == 30
    assert sca["parse_ok"] is True and sca["geometry_ok"] is True
    assert sca["pre_dft_valid"] is True and sca["topology_status"] == "PASS"
    assert sca["num_bad_contacts"] == 0
    assert build["status"] == "PASS_COMMON_CONTRACT"
    assert build["blend_manifest"]["artifact_contract"] == "dmytro_gr_v1"
    assert build["spp_input_manifest"]["selected_count"] == 30
    assert build["spp_input_manifest"]["selected_hashes_match_declared"] is True
    assert len(pairs) == 6
    assert raw_hash != OLD_V4_SHA256
    excluded_ids = {row["structure_id"] for row in exclusions if row.get("decision") == "excluded"}
    selected_ids = {row["structure_id"] for row in retrieval["selected"]}
    assert not (excluded_ids & selected_ids)

    OUT.mkdir(parents=True, exist_ok=True)
    provenance = OUT / "coherent_live_run"
    provenance.mkdir(parents=True, exist_ok=True)
    shutil.copy2(RUN / "retrieval" / "results.json", provenance / "LIVE_RETRIEVAL_MANIFEST.json")
    shutil.copy2(RUN / "retrieval" / "exclusions.json", provenance / "LIVE_RETRIEVAL_EXCLUSIONS.json")
    shutil.copy2(RUN / "retrieval" / "database_provenance.json", provenance / "LIVE_RETRIEVAL_DATABASE_PROVENANCE.json")
    shutil.copy2(build_path, provenance / "SPP_BUILD_MANIFEST.json")
    shutil.copy2(RUN / "spp" / "evidence_bundle.json", provenance / "SPP_EVIDENCE_BUNDLE.json")
    shutil.copy2(raw_cif, provenance / "RAW_GENERATED_LI2FEO3.cif")
    shutil.copy2(RUN / "sca" / "result.json", provenance / "SCA_SUMMARY.json")

    source_pot_root = Path(pairs[0]["output_pot"]).parents[1]
    preserved_pot_root = provenance / "FINAL_BLENDED_SPP_PACKAGE"
    shutil.copytree(source_pot_root, preserved_pot_root, dirs_exist_ok=True)
    curves_dir = provenance / "spp_curves"
    curves_dir.mkdir(parents=True, exist_ok=True)
    curve_paths: dict[str, str] = {}
    source_by_key = {canonical_pair(row["pair"]): Path(row["output_pot"]) for row in pairs}
    for display_pair in PAIR_ORDER:
        pot = source_by_key[canonical_pair(display_pair)]
        parsed = _parse_pot_file(pot)
        if not parsed:
            raise ValueError(f"unparseable repaired POT: {pot}")
        csv_path = curves_dir / f"{display_pair}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("distance_A", "spp_score"))
            writer.writerows(zip(parsed[0], parsed[1]))
        curve_paths[display_pair] = str(csv_path)

    qlip_summary = {
        "status": summary["qlip_status"],
        "objective_value": summary["qlip_objective"],
        "runtime_seconds": summary["qlip_runtime"],
        "solution": {"formula": summary["formula"], "cif_path": str(raw_cif)},
        "raw_cif_sha256": raw_hash,
    }
    write_json(provenance / "QLIP_SUMMARY.json", qlip_summary)

    adapter = OUT / "_historical_renderer_adapter"
    adapter.mkdir(parents=True, exist_ok=True)
    neighbours = []
    for item in retrieval["selected"]:
        row = json.loads(json.dumps(item))
        cif_path = Path(row["cif_export"]["path"])
        row["formula"] = Structure.from_file(cif_path).composition.reduced_formula.replace(" ", "")
        row["metadata"] = {**(row.get("metadata") or {}), "formula": row["formula"]}
        neighbours.append(row)
    retrieval_payload = {"neighbors": neighbours, "backend": retrieval.get("backend", ""), "config": retrieval.get("config", {})}
    retrieval_trace = adapter / "live_retrieval_for_renderer.json"
    write_json(retrieval_trace, retrieval_payload)
    write_json(adapter / "selected_evidence_payload.json", retrieval_payload)
    write_json(adapter / "paper_display_neighbours_payload.json", {**retrieval_payload, "neighbors": neighbours[:6]})
    spp_trace = adapter / "repaired_spp_for_renderer.json"
    write_json(spp_trace, {
        "artifact_contract": "dmytro_gr_v1",
        "selected_pot_root": str(preserved_pot_root),
        "pot_root": str(preserved_pot_root),
        "required_pairs": list(PAIR_ORDER),
        "available_pairs": list(PAIR_ORDER),
        "missing_pairs": [],
        "row_specific_spp_pairs": list(PAIR_ORDER),
        "selected_evidence_count": 30,
        "blend_manifest": build["blend_manifest"],
    })
    qlip_trace = adapter / "qlip_for_renderer.json"
    write_json(qlip_trace, qlip_summary)

    bundle = OUT / "_historical_render_bundle"
    build_render_bundle({
        "retrieval_trace_path": str(retrieval_trace),
        "spp_trace_path": str(spp_trace),
        "qlip_solution_path": str(qlip_trace),
        "generated_cif_path": str(raw_cif),
        "target_formula": "Li2FeO3",
        "target_family": "layered oxide",
        "input_text": "Generate a plausible layered battery oxide crystal structure for Li2FeO3.",
    }, adapter, bundle, pot_root=str(preserved_pot_root), spp_source_label="repaired dmytro_gr_v1")
    evaluation_path = bundle / "report" / "workflow_evaluation.json"
    evaluation = read_json(evaluation_path)
    evaluation["material_system"] = "Li2FeO3"
    evaluation["figure_title"] = "Traceable retrieval-to-optimisation workflow"
    evaluation["paper_hero_mode"] = True
    evaluation["final_crystal_caption"] = "visualization supercell (1x1x2; display only)"
    evaluation["sca_validation"] = {
        "status": "PASS",
        "pre_dft_valid": sca["pre_dft_valid"],
        "geometry_ok": sca["geometry_ok"],
        "topology_status": sca["topology_status"],
        "num_bad_contacts": sca["num_bad_contacts"],
        "min_distance_A": sca["min_distance"],
    }
    write_json(evaluation_path, evaluation)

    renderer_out = OUT / "historical_renderer_output"
    chosen_render = OUT / "vesta" / "generated_options" / "generated_1x1x2.png"
    chosen_render_cropped = OUT / "vesta" / "generated_options" / "generated_1x1x2_cropped.png"
    crop_vesta_whitespace(chosen_render, chosen_render_cropped)
    rendered = visualise_workflow_artifact(
        bundle, renderer_out, "li2feo3_dmytro_gr_v1",
        vesta_path=VESTA, require_vesta=True, ensure_semantic_neighbour_renders=True,
        include_projected_surface=False, pot_root=preserved_pot_root,
        spp_source_label="repaired dmytro_gr_v1", final_crystal_image_path=chosen_render_cropped,
        require_vesta_images=True, no_fallback_structure_rendering=True,
        semantic_neighbour_target_count=6,
    )
    semantic_root = Path(rendered["manifest"]["panels_dir"]) / "semantic_neighbour_cifs"
    for png in semantic_root.glob("*.png"):
        crop_vesta_whitespace(png, png)
    rendered = visualise_workflow_artifact(
        bundle, renderer_out, "li2feo3_dmytro_gr_v1",
        vesta_path=VESTA, require_vesta=True, ensure_semantic_neighbour_renders=False,
        include_projected_surface=False, pot_root=preserved_pot_root,
        spp_source_label="repaired dmytro_gr_v1", final_crystal_image_path=chosen_render_cropped,
        require_vesta_images=True, no_fallback_structure_rendering=True,
        semantic_neighbour_target_count=6,
    )
    exact_png = OUT / f"{STEM}.png"
    exact_pdf = OUT / f"{STEM}.pdf"
    shutil.copy2(rendered["png_path"], exact_png)
    shutil.copy2(rendered["pdf_path"], exact_pdf)

    display_manifest_path = OUT / "vesta" / "DISPLAY_SUPERCELL_MANIFEST.json"
    display_manifest = read_json(display_manifest_path)
    display_manifest["chosen"] = "1x1x2"
    display_manifest["selection_reason"] = "Smallest tested display supercell that clearly exposes the periodic Li-O and Fe-O motif."
    write_json(display_manifest_path, display_manifest)

    exact_manifest = OUT / f"{STEM}_MANIFEST.json"
    figure_manifest = read_json(Path(rendered["manifest_path"]))
    write_json(exact_manifest, {
        "schema_version": "paper_figure_1_li2feo3_dmytro_gr_v1.v1",
        "historical_renderer": "sok_llm_orchestrator.agentic.visualise_workflow_artifact.visualise_workflow_artifact",
        "historical_bundle_builder": "scripts.build_paper_workflow_artifact_package.build_render_bundle",
        "source_run": str(RUN),
        "live_retrieval_count": len(neighbours),
        "excluded_target_ids": sorted(excluded_ids),
        "selected_target_id_intersection": sorted(excluded_ids & selected_ids),
        "artifact_contract": "dmytro_gr_v1",
        "spp_curve_csvs": curve_paths,
        "final_blended_spp_package": str(preserved_pot_root),
        "qlip": qlip_summary,
        "raw_generated_cif": str(provenance / "RAW_GENERATED_LI2FEO3.cif"),
        "raw_generated_cif_sha256": raw_hash,
        "old_v4_cif_sha256": OLD_V4_SHA256,
        "old_v4_cif_used": False,
        "sca": evaluation["sca_validation"],
        "chosen_visualization_supercell": "1x1x2",
        "display_supercell_manifest": str(display_manifest_path),
        "figure_png": str(exact_png),
        "figure_pdf": str(exact_pdf),
        "coherence_assertion": "One live request -> retrieval -> repaired SPP package -> QLIP solve -> raw CIF -> SCA result.",
        "historical_renderer_manifest": figure_manifest,
    })
    caption = OUT / f"{STEM}_CAPTION_FACTS.md"
    caption.write_text(
        "# Figure 1 caption facts\n\n"
        "A leakage-safe live Crystal-DB retrieval supplied 30 non-target periodic structures to the repaired "
        "`dmytro_gr_v1` SPP build. Six Dmytro-compatible pair potentials (200 bins, 0-10 A, 0.05 A spacing) "
        "guided a scaffold-free, composition-scaled QLIP solve. The fixed 300 s solve returned "
        f"`{summary['qlip_status']}` with objective `{summary['qlip_objective']}` and produced the new raw CIF "
        f"with SHA-256 `{raw_hash}`. SCA passed geometry and layered-topology checks with zero bad contacts "
        f"and a minimum distance of {sca['min_distance']:.4f} A. The displayed crystal is a 1x1x2 "
        "visualization supercell derived only from that raw candidate; QLIP optimized the 1x1x1 six-atom cell.\n",
        encoding="utf-8",
    )
    print(json.dumps({"png": str(exact_png), "pdf": str(exact_pdf), "manifest": str(exact_manifest), "caption": str(caption)}, indent=2))


if __name__ == "__main__":
    main()
