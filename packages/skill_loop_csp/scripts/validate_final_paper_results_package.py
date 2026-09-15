"""Fail closed when the final LLM-CSP paper-results package is incomplete."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "final_paper_results"
MANIFEST = ROOT / "experiments" / "paper_results" / "RESULTS_EXPERIMENTS.csv"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def truth(value: str) -> bool:
    return str(value).strip().lower() in {"true", "yes", "1", "pass"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    required = [
        "MASTER_RESULTS.csv", "MASTER_RESULTS.md", "PAPER_RESULTS_TABLES.md",
        "PAPER_RESULTS_SUMMARY_TEXT.md", "PROVENANCE_COMPLETENESS.csv",
        "REPEATABILITY_RESULTS.csv", "SCA_CHGNET_RESULTS.csv",
        "SCAFFOLD_EXTENSION_RESULTS.csv", "FINAL_RESULTS_AUDIT.md",
        "PROVENANCE_INDEX.md", "TRACEABILITY_AUDIT.csv",
        "TRACEABILITY_AUDIT.md", "TABLE_1_BREADTH.csv",
        "TABLE_2_SCA_CHGNET.csv", "TABLE_3_SCAFFOLD_EXTENSION.csv",
        "MANIFEST_FREEZE.json", "OUTPUT_HASH_MANIFEST.csv",
    ]
    for name in required:
        path = OUT / name
        require(path.is_file() and path.stat().st_size > 0, f"missing or empty: {path}")

    manifest = rows(MANIFEST)
    master = rows(OUT / "MASTER_RESULTS.csv")
    dry = rows(OUT / "dry_run" / "RESULTS.csv")
    executed = rows(OUT / "table_run" / "RESULTS.csv")
    provenance = rows(OUT / "PROVENANCE_COMPLETENESS.csv")
    repeats = rows(OUT / "REPEATABILITY_RESULTS.csv")
    manifest_ids = [row["row_id"] for row in manifest if truth(row.get("enabled", "yes"))]
    require(len(manifest_ids) == 36, f"expected 36 enabled manifest rows, got {len(manifest_ids)}")
    for label, data in (("master", master), ("dry run", dry), ("table run", executed), ("provenance", provenance)):
        ids = [row["row_id"] for row in data]
        require(ids == manifest_ids, f"{label} is not a one-to-one ordered projection of the manifest")
        require(len(ids) == len(set(ids)), f"{label} contains duplicate row IDs")

    blocks = Counter(row["experiment_block"] for row in master)
    require(blocks == {"TRACE": 1, "BREADTH": 20, "REPEATABILITY": 9, "SCAFFOLD": 3, "ABSTENTION": 3}, f"unexpected blocks: {blocks}")
    require(not any(row["workflow_terminal_status"] in {"SOFTWARE_FAILURE", "ROW_INPUT_ERROR"} for row in master), "unresolved software/input failure in master")

    breadth = [row for row in master if row["experiment_block"] == "BREADTH"]
    require(all(row["cif_emitted"] == "YES" and truth(row["exact_composition"]) for row in breadth), "breadth CIF/composition coverage incomplete")
    require(all(row["sca_status"] in {"PASS", "PARTIAL", "FAIL"} for row in breadth), "breadth SCA coverage incomplete")
    require(all(row["chgnet_status"] in {"PASS", "FAIL"} for row in breadth), "breadth CHGNet coverage incomplete")
    require(all(row["chgnet_status"] == "PASS" for row in breadth), "breadth contains a non-completed CHGNet result")
    require(all(row["sca_failed_check_count"] != "" and row["sca_failed_check_names"] != "" for row in breadth), "SCA failure fields missing")

    require(len(repeats) == 9, "repeatability table must contain 9 executions")
    repeat_flags = ["identical_solver_objective", "identical_selected_occupation", "identical_canonical_cif", "identical_evidence_ids", "identical_request_spp_hash"]
    require(all(truth(row[field]) for row in repeats for field in repeat_flags), "repeatability identity mismatch")

    positives = [row for row in master if row["experiment_block"] == "SCAFFOLD"]
    abstentions = [row for row in master if row["experiment_block"] == "ABSTENTION"]
    require(all(row["cif_emitted"] == "YES" and row["sca_status"] == "PASS" and row["chgnet_status"] == "PASS" for row in positives), "positive scaffold QC incomplete")
    require(all(row["cif_emitted"] == "NO" and row["solver_status"] == "NOT_REACHED" and row["failure_code"] for row in abstentions), "controlled abstention invariant failed")

    trace = next(row for row in master if row["experiment_block"] == "TRACE")
    require(trace["provenance_complete"] == "YES", "flagship trace provenance is incomplete")
    require(len(provenance) == 36 and all(float(row["completeness_percent"]) >= 0 for row in provenance), "provenance audit incomplete")
    require(all(row["complete"] == "YES" or row["missing_fields"] == '["objective_parity"]' for row in provenance), "unexpected provenance omission")

    figure_specs = {
        "Figure_1_trace": ("png", "pdf", "svg"),
        "Figure_2_structure_montage": ("png", "pdf"),
        "Figure_3_quality_control": ("png", "pdf", "svg"),
        "Figure_4_scaffold_extension": ("png", "pdf", "svg"),
    }
    for stem, suffixes in figure_specs.items():
        for suffix in suffixes:
            path = OUT / "figures" / f"{stem}.{suffix}"
            require(path.is_file() and path.stat().st_size > 0, f"missing figure: {path}")
    require(len(rows(OUT / "figures" / "Figure_2_structure_montage_source.csv")) == 12, "Figure 2 source must identify exactly 12 displayed structures")
    fig3 = rows(OUT / "figures" / "Figure_3_quality_control_source.csv")
    require([row["row_id"] for row in fig3] == [row["row_id"] for row in breadth], "Figure 3 source is not the breadth set")
    require(len(rows(OUT / "figures" / "Figure_4_scaffold_extension_source.csv")) == 2, "Figure 4 source row count is not 2")

    figures_root = OUT / "figures"
    row_figures = rows(figures_root / "ROW_WORKFLOW_FIGURES.csv")
    require(len(row_figures) == 33, f"expected 33 successful row workflow figures, got {len(row_figures)}")
    require(all(row["visual_QA_status"] == "PASS" for row in row_figures), "row workflow visual QA is incomplete")
    for record in row_figures:
        row_dir = OUT / "table_run" / "rows" / record["row_id"]
        figure_manifest_path = row_dir / "figures" / "workflow_figure_manifest.json"
        require(figure_manifest_path.is_file(), f"missing row figure manifest: {record['row_id']}")
        figure_manifest = json.loads(figure_manifest_path.read_text(encoding="utf-8"))
        require(figure_manifest["visual_qa_status"] == "PASS", f"row figure not approved: {record['row_id']}")
        generated = Path(figure_manifest["generated_cif_path"])
        require(generated.is_file() and digest(generated) == figure_manifest["generated_cif_sha256"], f"generated CIF mismatch: {record['row_id']}")
        require(figure_manifest["generated_vesta_provenance"]["renderer"] == "VESTA", f"non-VESTA output: {record['row_id']}")
        trace_path = row_dir / "workflow_trace.json"
        if trace_path.is_file():
            trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))
            require(figure_manifest["retrieval_ids"] == trace_payload["retrieved_ids"][:4], f"retrieval order mismatch: {record['row_id']}")
            require(figure_manifest["spp_pairs"] == trace_payload["qlip_adapter"]["required_pairs"], f"required SPP pairs mismatch: {record['row_id']}")
        curve_path = Path(figure_manifest["spp_curve_source_csv"])
        curve_rows = rows(curve_path) if curve_path.stat().st_size else []
        for curve in curve_rows:
            regulator = Path(curve["regulator_pot_path"])
            require(regulator.is_file() and digest(regulator) == curve["regulator_pot_sha256"], f"regulator POT mismatch: {record['row_id']}")
            if curve["request_pot_path"]:
                request_pot = Path(curve["request_pot_path"])
                require(request_pot.is_file() and digest(request_pot) == curve["request_pot_sha256"], f"request POT mismatch: {record['row_id']}")

    new_figure_specs = {
        "Figure_1_trace": ("png", "pdf"),
        "Figure_2_text_intent_showcase": ("png", "pdf"),
        "Figure_3_validation_quality": ("png", "pdf"),
        "Figure_4A_scaffold_concise": ("png", "pdf"),
        "Figure_4B_scaffold_explained": ("png", "pdf"),
    }
    for stem, suffixes in new_figure_specs.items():
        for suffix in suffixes:
            require((figures_root / f"{stem}.{suffix}").is_file(), f"missing final paper figure: {stem}.{suffix}")
    source_manifest = rows(figures_root / "FIGURE_SOURCE_MANIFEST.csv")
    require(len(source_manifest) == 5 and all(row["visual_QA_status"] == "PASS" for row in source_manifest), "paper figure source manifest/QA incomplete")
    require((figures_root / "VISUAL_QA_REPORT.md").is_file(), "visual QA report missing")
    figure1_source = json.loads((figures_root / "Figure_1_trace_source.json").read_text(encoding="utf-8"))
    require(Path(figure1_source["source_workflow_figure"]).is_file(), "Figure 1 does not reference a row figure")
    figure2_source = rows(figures_root / "Figure_2_text_intent_showcase_source.csv")
    master_by_id = {row["row_id"]: row for row in master}
    require(all(row["actual_request"] == master_by_id[row["row_id"]]["request"] for row in figure2_source), "Figure 2 request differs from master")
    require(rows(figures_root / "Figure_3_validation_quality_source.csv") == breadth, "Figure 3 data differs from master breadth rows")
    scaffold_source = json.loads((figures_root / "Figure_4_scaffold_source.json").read_text(encoding="utf-8"))
    require(scaffold_source["scaffold_id"] == "nasicon_na3zr2si2po12_c2_ordered", "Figure 4 scaffold source mismatch")
    final_figure_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in figures_root.glob("*source*"))
    require("not a calibrated energy scale" not in final_figure_text.lower(), "provisional SPP wording remains")

    freeze = json.loads((OUT / "MANIFEST_FREEZE.json").read_text(encoding="utf-8"))
    require(freeze["manifest_sha256"] == digest(MANIFEST), "manifest hash changed after freeze")
    require(freeze["ordered_row_ids"] == manifest_ids, "frozen row order differs from manifest")
    require(freeze["master_sha256"] == digest(OUT / "MASTER_RESULTS.csv"), "master hash changed after freeze")
    for item in rows(OUT / "OUTPUT_HASH_MANIFEST.csv"):
        path = OUT / item["path"]
        require(path.is_file() and int(item["bytes"]) == path.stat().st_size and item["sha256"] == digest(path), f"output hash mismatch: {path}")

    summary = (OUT / "PAPER_RESULTS_SUMMARY_TEXT.md").read_text(encoding="utf-8")
    forbidden = ("thermodynamically stable", "ground-state proof", "synthesizability proof", "realism score")
    require(not any(term.lower() in summary.lower() for term in forbidden), "unsupported claim language in summary")
    print("PASS: final paper-results package is internally complete and hash-consistent (36/36 rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
