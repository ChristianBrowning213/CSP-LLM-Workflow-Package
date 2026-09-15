"""Fail closed when a timestamped LLM-CSP figure package is incomplete or untruthful."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from pymatgen.core import Structure

from sok_llm_orchestrator.workflow.row_visualization import read_csv, sha256


NAME = re.compile(r"^Paper_results_[A-Za-z0-9_]+_\d{4}-\d{2}-\d{2}_\d{6}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--master", type=Path, default=Path("artifacts/final_paper_results/MASTER_RESULTS.csv"))
    parser.add_argument("--source-table", type=Path, default=Path("artifacts/final_paper_results/table_run"))
    args = parser.parse_args()
    root, master_path, source_table = args.package.resolve(), args.master.resolve(), args.source_table.resolve()
    require(root.is_dir() and NAME.fullmatch(root.name) is not None, "package root does not follow the timestamped naming rule")
    for name in ("README.md", "MANIFEST.csv", "GENERATION_AUDIT.md", "FIGURE_SELECTION_NOTES.md", "VISUAL_QA_REPORT.md", "ROW_WORKFLOW_FIGURES.csv", "FIGURE_SOURCE_MANIFEST.csv"):
        require((root / name).is_file() and (root / name).stat().st_size > 0, f"missing package deliverable: {name}")
    master = read_csv(master_path); by_id = {row["row_id"]: row for row in master}
    eligible = [row for row in master if row["cif_emitted"] == "YES"]
    row_index = read_csv(root / "ROW_WORKFLOW_FIGURES.csv")
    require([row["row_id"] for row in row_index] == [row["row_id"] for row in eligible], "row figure index is not the ordered successful-CIF projection")
    require(all(row["visual_QA_status"] == "PASS" for row in row_index), "row visual QA incomplete")
    for record in row_index:
        row_id = record["row_id"]; manifest_path = root / "per_row" / row_id / "workflow_figure_manifest.json"
        require(manifest_path.is_file(), f"missing row manifest: {row_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(manifest["visual_qa_status"] == "PASS", f"row manifest QA incomplete: {row_id}")
        require("using retrieved evidence" not in manifest["request_short"].lower(), f"request boilerplate remains: {row_id}")
        require(not any("sca" == key.lower() or key.lower().startswith("sca ") for key in manifest["validation_summary"]), f"internal SCA label exposed: {row_id}")
        generated = Path(manifest["generated_cif_path"])
        require(generated.is_file() and sha256(generated) == manifest["generated_cif_sha256"], f"generated CIF mismatch: {row_id}")
        require(manifest["generated_vesta_provenance"]["renderer"] == "VESTA", f"generated render is not VESTA: {row_id}")
        trace_path = source_table / "rows" / row_id / "workflow_trace.json"
        if trace_path.is_file():
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            require(manifest["retrieval_ids"] == trace["retrieved_ids"][:4], f"top retrieval mismatch: {row_id}")
            require(manifest["spp_pairs"] == trace["qlip_adapter"]["required_pairs"], f"SPP required-pair mismatch: {row_id}")
        curve_path = Path(manifest["spp_curve_source_csv"])
        curve_rows = read_csv(curve_path) if curve_path.stat().st_size else []
        require({row["species_pair"] for row in curve_rows} == set(manifest["spp_pairs"]), f"plotted SPP pair mismatch: {row_id}")
        for curve in curve_rows:
            regulator = Path(curve["regulator_pot_path"])
            require(regulator.is_file() and sha256(regulator) == curve["regulator_pot_sha256"], f"regulator POT mismatch: {row_id}")
            if curve["request_pot_path"]:
                request = Path(curve["request_pot_path"])
                require(request.is_file() and sha256(request) == curve["request_pot_sha256"], f"request POT mismatch: {row_id}")
    expected = {
        "Figure_1_trace_candidate_A", "Figure_1_trace_candidate_B", "Figure_2_intent_showcase",
        "Figure_3_validation_summary", "Figure_4_scaffold_variant_A", "Figure_4_scaffold_variant_B",
    }
    for stem in expected:
        for suffix in ("png", "pdf"):
            require((root / "paper_figures" / f"{stem}.{suffix}").is_file(), f"missing paper figure: {stem}.{suffix}")
    paper = read_csv(root / "FIGURE_SOURCE_MANIFEST.csv")
    require(len(paper) == 6 and all(row["visual_QA_status"] == "PASS" for row in paper), "paper source manifest/QA incomplete")
    figure2 = read_csv(root / "paper_figures" / "Figure_2_intent_showcase_source.csv")
    require(all(row["actual_request"] == by_id[row["row_id"]]["request"] for row in figure2), "Figure 2 request differs from master")
    require(all("using retrieved evidence" not in row["request_short"].lower() for row in figure2), "Figure 2 boilerplate remains")
    figure3 = read_csv(root / "paper_figures" / "Figure_3_validation_summary_source.csv")
    require(figure3 == [row for row in master if row["experiment_block"] == "BREADTH"], "Figure 3 differs from MASTER_RESULTS")
    scaffold = json.loads((root / "paper_figures" / "Figure_4_scaffold_source.json").read_text(encoding="utf-8"))
    source_structure = Structure.from_file(Path(scaffold["source_cif_path"]))
    orbit_indices = [index for orbit in scaffold["orbits"] for index in orbit["site_indices"]]
    require(scaffold["scaffold_id"] == "nasicon_na3zr2si2po12_c2_ordered" and max(orbit_indices) < len(source_structure), "Figure 4 is not grounded in the registered scaffold geometry")
    require(any(orbit["mode"].startswith("VARIABLE") for orbit in scaffold["orbits"]), "Figure 4 has no real variable orbits")
    for item in read_csv(root / "MANIFEST.csv"):
        path = root / item["path"]
        require(path.is_file() and int(item["bytes"]) == path.stat().st_size and item["sha256"] == sha256(path), f"package hash mismatch: {path}")
    require("Visual QA: PASS" in (root / "GENERATION_AUDIT.md").read_text(encoding="utf-8"), "generation audit is not visually approved")
    print(f"PASS: timestamped figure package is complete ({len(row_index)} row figures; {len(paper)} paper candidates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
