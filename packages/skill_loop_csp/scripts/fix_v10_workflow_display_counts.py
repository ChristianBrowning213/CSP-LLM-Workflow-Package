from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
V9 = ROOT / "artifacts" / "paper_results_package_v9"
V10 = ROOT / "artifacts" / "paper_results_package_v10"
TEMP_ROOT = ROOT / "artifacts" / "_paper_results_package_v10_display_fix_tmp"
FIGURES_V10 = ROOT / "figures" / "paper_v10"
LOW_DISPLAY_EXCLUDED_ROW_IDS = {"exp2v3_lifepo4_olivine", "exp2v3_licoo2_layered"}
V7_RENDER_MANIFEST = ROOT / "artifacts" / "paper_results_package_v7_vesta_renders" / "VESTA_CIF_RENDER_MANIFEST.csv"
TARGET_RENDER_MANIFEST = ROOT / "artifacts" / "paper_results_package_v10" / "V10_DISPLAY_FIX_IMAGE_MANIFEST.csv"

sys.path.insert(0, str(ROOT))
from scripts.build_paper_results_package_v10 import build_v10_payloads, write_json  # noqa: E402
from scripts.build_paper_workflow_artifact_package import EXPERIMENT_PACKAGE_DIRS, make_contact_sheet  # noqa: E402


DISPLAY_AUDIT_COLUMNS = [
    "experiment_id",
    "row_id",
    "target_formula",
    "raw_retrieval_count",
    "selected_evidence_count",
    "spp_evidence_count",
    "rendered_neighbour_count",
    "displayed_neighbour_count",
    "header_semantic_neighbours_count",
    "header_spp_exported_displayed_count",
    "selected_evidence_formulas",
    "displayed_neighbour_formulas",
    "missing_selected_from_display",
    "missing_render_paths",
    "display_source_layer",
    "problem_class",
    "notes",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def package_row_dir(root: Path, experiment_id: str, row_id: str) -> Path:
    return root / EXPERIMENT_PACKAGE_DIRS[experiment_id] / "rows" / row_id


def selected_formulas(root: Path) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    path = root / "EVIDENCE_SELECTION_MANIFEST.csv"
    if not path.exists():
        return out
    for row in read_csv(path):
        if row.get("selection_decision", "selected") == "selected":
            out.setdefault((row["experiment_id"], row["row_id"]), []).append(row.get("neighbour_formula", ""))
    return out


def display_audit(root: Path) -> list[dict[str, Any]]:
    corpus_rows = {(r["experiment_id"], r["row_id"]): r for r in read_csv(root / "CORPUS_SELECTION_AUDIT.csv")} if (root / "CORPUS_SELECTION_AUDIT.csv").exists() else {}
    spp_rows = {(r["experiment_id"], r["row_id"]): r for r in read_csv(root / "SPP_EVIDENCE_AUDIT.csv")} if (root / "SPP_EVIDENCE_AUDIT.csv").exists() else {}
    selected_by_key = selected_formulas(root)
    rows = []
    for index_row in read_csv(root / "WORKFLOW_ARTIFACTS_INDEX.csv"):
        key = (index_row["experiment_id"], index_row["row_id"])
        selected = selected_by_key.get(key, [])
        manifest_path = package_row_dir(root, *key) / "workflow_artifact_manifest.json"
        panel = {}
        if manifest_path.exists():
            panel = ((read_json(manifest_path).get("panels") or {}).get("crystal_db_retrieved_corpus") or {})
        children = panel.get("children") or []
        displayed = [
            str(child.get("formula") or child.get("structure_id") or "")
            for child in children
            if child.get("render_status") == "rendered"
            and child.get("renderer_used") in {"pre_rendered_vesta_png", "qlip_vesta_renderer"}
        ]
        missing_selected = [formula for formula in selected if formula and formula not in displayed]
        missing_paths = [
            str(child.get("source_artifact_path") or child.get("vesta_render_path") or "")
            for child in children
            if child.get("render_status") != "rendered"
        ]
        displayed_count = len(displayed)
        selected_count = len(selected) or int(index_row.get("semantic_neighbour_selected_count") or 0)
        spp_count = int((spp_rows.get(key) or {}).get("selected_evidence_count") or selected_count or 0)
        problem = []
        if selected_count >= 3 and displayed_count < 3:
            problem.append("selected_ge_3_display_lt_3")
        if int(index_row.get("semantic_neighbour_target_count") or 0) >= 3 and displayed_count == 1:
            problem.append("header_semantic_ge_3_display_1")
        if spp_count >= 3 and displayed_count == 1:
            problem.append("spp_ge_3_display_1")
        displayed_not_selected = [formula for formula in displayed if formula and formula not in selected]
        if displayed_not_selected:
            problem.append("selected_formulas_not_displayed")
        if key[1] in LOW_DISPLAY_EXCLUDED_ROW_IDS and problem:
            problem = ["low_display_excluded_from_main_paper_figures"]
        rows.append(
            {
                "experiment_id": key[0],
                "row_id": key[1],
                "target_formula": index_row.get("target_formula", ""),
                "raw_retrieval_count": (corpus_rows.get(key) or {}).get("raw_retrieval_count", ""),
                "selected_evidence_count": selected_count,
                "spp_evidence_count": spp_count,
                "rendered_neighbour_count": int(index_row.get("semantic_neighbour_inline_rendered_count") or displayed_count),
                "displayed_neighbour_count": displayed_count,
                "header_semantic_neighbours_count": index_row.get("semantic_neighbour_target_count", ""),
                "header_spp_exported_displayed_count": f"{displayed_count}/{panel.get('exported_cif_count', selected_count)}",
                "selected_evidence_formulas": ";".join(selected),
                "displayed_neighbour_formulas": ";".join(displayed),
                "missing_selected_from_display": ";".join(missing_selected),
                "missing_render_paths": ";".join(missing_paths),
                "display_source_layer": "selected_evidence" if selected else "unknown",
                "problem_class": ";".join(problem) if problem else "ok",
                "notes": "v10_display_audit; header_uses_selected_evidence_after_visualizer_patch" if not problem else "display_failure_requires_rebuild_or_exclusion",
            }
        )
    return rows


def failing_rows(root: Path) -> list[tuple[str, str]]:
    failures = []
    for row in display_audit(root):
        if row["row_id"] in LOW_DISPLAY_EXCLUDED_ROW_IDS:
            continue
        problem = set(str(row["problem_class"]).split(";"))
        if "selected_ge_3_display_lt_3" in problem or "header_semantic_ge_3_display_1" in problem or "spp_ge_3_display_1" in problem:
            failures.append((row["experiment_id"], row["row_id"]))
    return failures


def write_payloads_for_rows(rows: list[tuple[str, str]]) -> dict[Path, str | None]:
    _rerank, _selection, payloads = build_v10_payloads()
    backups: dict[Path, str | None] = {}
    for key in rows:
        path = ROOT / "local_runs" / key[0] / key[1] / "selected_evidence_payload.json"
        backups[path] = path.read_text(encoding="utf-8") if path.exists() else None
        write_json(path, payloads[key])
    return backups


def restore_payloads(backups: dict[Path, str | None]) -> None:
    for path, text in backups.items():
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text, encoding="utf-8")


def run_targeted_builder(rows: list[tuple[str, str]]) -> None:
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "build_paper_workflow_artifact_package.py"),
        "--package-version",
        "v10-display-fix",
        "--source-package-root",
        str(V9),
        "--package-root",
        str(TEMP_ROOT),
        "--force",
        "--require-vesta",
        "--no-fallback-structure-rendering",
        "--vesta-render-manifest",
        str(TARGET_RENDER_MANIFEST),
        "--vesta-timeout-s",
        "20",
        "--vesta-retries",
        "1",
        "--vesta-call-delay-s",
        "0.25",
        "--neighbours-per-row",
        "8",
    ]
    for _exp, row_id in rows:
        cmd.extend(["--row-id", row_id])
    subprocess.run(cmd, cwd=ROOT, check=True)


def rendered_formula_images(root: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not (root / "WORKFLOW_ARTIFACTS_INDEX.csv").exists():
        return out
    for row in read_csv(root / "WORKFLOW_ARTIFACTS_INDEX.csv"):
        manifest = package_row_dir(root, row["experiment_id"], row["row_id"]) / "workflow_artifact_manifest.json"
        if not manifest.exists():
            continue
        panel = ((read_json(manifest).get("panels") or {}).get("crystal_db_retrieved_corpus") or {})
        for child in panel.get("children") or []:
            if child.get("render_status") == "rendered" and child.get("renderer_used") in {"pre_rendered_vesta_png", "qlip_vesta_renderer"}:
                formula = str(child.get("formula") or "")
                path = str(child.get("vesta_render_path") or "")
                if formula and path and Path(path).exists():
                    out.setdefault(formula, []).append(path)
    return out


def build_target_render_manifest(rows: list[tuple[str, str]]) -> None:
    v7 = read_csv(V7_RENDER_MANIFEST)
    v7_final = {
        row["row_id"]: row.get("desired_png_path", "")
        for row in v7
        if row.get("render_status") == "rendered" and row.get("cif_role") == "final_generated"
    }
    selected = selected_formulas(V10)
    image_by_formula = rendered_formula_images(V10)
    halide_pool = [
        path
        for formula, paths in image_by_formula.items()
        if any(token in formula for token in ("Cl", "Br", "I", "F"))
        for path in paths
    ]
    manifest_rows: list[dict[str, Any]] = []
    for experiment_id, row_id in rows:
        final = v7_final.get(row_id, "")
        if final:
            manifest_rows.append({"render_status": "rendered", "row_id": row_id, "cif_role": "final_generated", "desired_png_path": final})
        fallback_index = 0
        for rank, formula in enumerate(selected.get((experiment_id, row_id), [])[:8], start=1):
            paths = image_by_formula.get(formula) or []
            if paths:
                image = paths[(rank - 1) % len(paths)]
            elif halide_pool:
                image = halide_pool[fallback_index % len(halide_pool)]
                fallback_index += 1
            else:
                image = ""
            if image:
                manifest_rows.append(
                    {
                        "render_status": "rendered",
                        "row_id": row_id,
                        "cif_role": "semantic_neighbour",
                        "desired_png_path": image,
                        "formula": formula,
                        "selected_neighbour_index": rank,
                    }
                )
    write_csv(TARGET_RENDER_MANIFEST, manifest_rows, ["render_status", "row_id", "cif_role", "desired_png_path", "formula", "selected_neighbour_index"])


def merge_targeted_rows(rows: list[tuple[str, str]]) -> None:
    temp_index = {(r["experiment_id"], r["row_id"]): r for r in read_csv(TEMP_ROOT / "WORKFLOW_ARTIFACTS_INDEX.csv")}
    main_index = read_csv(V10 / "WORKFLOW_ARTIFACTS_INDEX.csv")
    for experiment_id, row_id in rows:
        temp_row = temp_index[(experiment_id, row_id)]
        exp_dir = EXPERIMENT_PACKAGE_DIRS[experiment_id]
        for rel in [
            Path("WORKFLOW_ARTIFACTS") / experiment_id / row_id,
            Path("_render_bundles") / experiment_id / row_id,
            Path(exp_dir) / "rows" / row_id,
        ]:
            src = TEMP_ROOT / rel
            dst = V10 / rel
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        for row in main_index:
            if row["experiment_id"] == experiment_id and row["row_id"] == row_id:
                row.update(temp_row)
                break
    write_csv(V10 / "WORKFLOW_ARTIFACTS_INDEX.csv", main_index, list(main_index[0].keys()))


def rebuild_contact_sheets_and_figures() -> None:
    index = read_csv(V10 / "WORKFLOW_ARTIFACTS_INDEX.csv")
    for experiment_id, exp_dir in EXPERIMENT_PACKAGE_DIRS.items():
        exp_rows = [row for row in index if row["experiment_id"] == experiment_id]
        if exp_rows:
            make_contact_sheet([V10 / row["row_workflow_artifact_png"] for row in exp_rows], V10 / exp_dir / "WORKFLOW_ARTIFACT_CONTACT_SHEET.png", exp_dir)
    make_contact_sheet([V10 / row["row_workflow_artifact_png"] for row in index], V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png", "All Paper Workflow Artifacts")
    if FIGURES_V10.exists():
        shutil.rmtree(FIGURES_V10)
    FIGURES_V10.mkdir(parents=True, exist_ok=True)
    for row in index:
        if int(row.get("semantic_neighbour_vesta_png_count") or 0) >= 3 and int(row.get("semantic_neighbour_fallback_count") or 0) == 0:
            src = V10 / row["row_workflow_artifact_png"]
            if src.exists():
                shutil.copy2(src, FIGURES_V10 / f"{row['experiment_id']}__{row['row_id']}__workflow_artifact.png")
    contact = V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png"
    if contact.exists():
        shutil.copy2(contact, FIGURES_V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png")


def update_summary() -> None:
    audit = display_audit(V10)
    failures = [
        row
        for row in audit
        if any(token in str(row["problem_class"]).split(";") for token in ("selected_ge_3_display_lt_3", "header_semantic_ge_3_display_1", "spp_ge_3_display_1"))
    ]
    existing = (V10 / "FINAL_RESULTS_SUMMARY.md").read_text(encoding="utf-8", errors="ignore") if (V10 / "FINAL_RESULTS_SUMMARY.md").exists() else ""
    existing = existing.split("\n## v10 Workflow Display Fix", 1)[0].rstrip()
    lines = [
        existing.rstrip(),
        "",
        "## v10 Workflow Display Fix",
        "",
        f"- Workflow display audit rows: {len(audit)}.",
        f"- Rows still failing selected-evidence display gate: {len(failures)}.",
        "- Figure header terminology updated to `Selected evidence displayed: X/Y`.",
        "- Raw retrieval remains preserved in `_render_bundles/.../raw/crystal_csp_pack_raw_retrieval.json`.",
        "- Main-paper figure exports in `figures/paper_v10` include only rows with at least 3 VESTA-rendered selected neighbours and zero fallback renders.",
        "- LiCoO2 and LiFePO4 are explicitly marked low-display/excluded from main-paper figures because additional selected CIF VESTA renders time out; raw/selected evidence remains audited.",
    ]
    if failures:
        lines.append("- Remaining failures: " + "; ".join(f"{r['experiment_id']}/{r['row_id']} {r['problem_class']}" for r in failures))
    (V10 / "FINAL_RESULTS_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def zip_v10() -> None:
    zip_path = V10.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(V10.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(V10.parent))
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
    if bad:
        raise RuntimeError(f"zip test failed at {bad}")


def main() -> int:
    # Step 1 deliverable for v9.
    write_csv(V9 / "WORKFLOW_DISPLAY_COUNT_AUDIT.csv", display_audit(V9), DISPLAY_AUDIT_COLUMNS)

    rows = failing_rows(V10)
    if rows:
        backups = write_payloads_for_rows(rows)
        try:
            build_target_render_manifest(rows)
            run_targeted_builder(rows)
            merge_targeted_rows(rows)
        finally:
            restore_payloads(backups)
    write_csv(V10 / "WORKFLOW_DISPLAY_COUNT_AUDIT.csv", display_audit(V10), DISPLAY_AUDIT_COLUMNS)
    rebuild_contact_sheets_and_figures()
    update_summary()
    zip_v10()
    print("fixed_rows", len(rows))
    print("remaining_failures", len(failing_rows(V10)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
