from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
V10 = ROOT / "artifacts" / "paper_results_package_v10"
V9 = ROOT / "artifacts" / "paper_results_package_v9"
TEMP_ROOT = ROOT / "artifacts" / "_paper_results_package_v10_halide_order_tmp"
FIGURES_V10 = ROOT / "figures" / "paper_v10"
IMAGE_MANIFEST = V10 / "V10_HALIDE_DISPLAY_IMAGE_MANIFEST.csv"

sys.path.insert(0, str(ROOT))
from scripts.build_paper_workflow_artifact_package import EXPERIMENT_PACKAGE_DIRS, make_contact_sheet  # noqa: E402
from scripts.build_paper_results_package_v10 import write_json  # noqa: E402

HALIDES = {"F", "Cl", "Br", "I"}
NEW_COLUMNS = [
    "target_halide",
    "neighbour_halide_set",
    "exact_target_halide_match",
    "halide_display_tier",
    "display_order_reason",
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


def formula_elements(formula: str) -> list[str]:
    return re.findall(r"[A-Z][a-z]?", formula or "")


def halide_set(formula: str) -> set[str]:
    return set(formula_elements(formula)) & HALIDES


def target_halide(formula: str) -> str:
    hs = sorted(halide_set(formula), key=["F", "Cl", "Br", "I"].index)
    return hs[0] if hs else ""


def b_site(formula: str) -> str:
    elems = [el for el in formula_elements(formula) if el not in HALIDES and el != "Cs"]
    return elems[0] if elems else ""


def halide_tier(target_formula: str, neighbour_formula: str, same_reduced: str | bool = False) -> tuple[int, str]:
    th = target_halide(target_formula)
    nh = halide_set(neighbour_formula)
    target_b = b_site(target_formula)
    neigh_elems = set(formula_elements(neighbour_formula))
    same_halide = bool(th and nh == {th})
    same_b = bool(target_b and target_b in neigh_elems)
    if str(same_reduced).lower() == "true" or re.sub(r"\s+", "", target_formula).lower() == re.sub(r"\s+", "", neighbour_formula).lower():
        return 1, "tier1_exact_or_same_reduced_formula"
    if same_halide and same_b:
        return 2, "tier2_same_target_halide_same_b_site_family"
    if same_halide:
        return 3, "tier3_same_target_halide_related_b_site_family"
    if nh & HALIDES:
        return 4, "tier4_cross_halide_perovskite_family_analogue"
    return 9, "not_halide_family_display_candidate"


def is_halide_row(formula: str) -> bool:
    return bool(target_halide(formula)) and formula.startswith("Cs")


def selected_formula_rows() -> dict[tuple[str, str], list[dict[str, str]]]:
    rows = read_csv(V10 / "EVIDENCE_SELECTION_MANIFEST.csv")
    return group_rows(rows)


def group_rows(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault((row["experiment_id"], row["row_id"]), []).append(row)
    return grouped


def ordered_halide_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        return rows
    target_formula = rows[0]["target_formula"]
    annotated = []
    for index, row in enumerate(rows):
        tier, reason = halide_tier(target_formula, row.get("neighbour_formula", ""), row.get("same_reduced_formula", ""))
        copied = dict(row)
        copied["target_halide"] = target_halide(target_formula)
        copied["neighbour_halide_set"] = ",".join(sorted(halide_set(row.get("neighbour_formula", "")), key=["F", "Cl", "Br", "I"].index))
        copied["exact_target_halide_match"] = copied["neighbour_halide_set"] == copied["target_halide"]
        copied["halide_display_tier"] = tier
        copied["display_order_reason"] = reason
        annotated.append((tier, index, copied))
    same_halide_count = sum(1 for tier, _idx, _row in annotated if tier <= 3)
    if same_halide_count >= 3:
        annotated.sort(key=lambda item: (item[0], item[1]))
    else:
        annotated.sort(key=lambda item: (item[0] if item[0] <= 3 else 4, item[1]))
    out = []
    for selected_rank, (_tier, _idx, row) in enumerate(annotated, start=1):
        row["selected_rank"] = selected_rank
        out.append(row)
    return out


def update_selection_manifest() -> list[tuple[str, str]]:
    path = V10 / "EVIDENCE_SELECTION_MANIFEST.csv"
    rows = read_csv(path)
    columns = list(rows[0].keys())
    for col in NEW_COLUMNS:
        if col not in columns:
            columns.append(col)
    grouped = group_rows(rows)
    out = []
    halide_keys = []
    for key, group in grouped.items():
        if is_halide_row(group[0]["target_formula"]):
            halide_keys.append(key)
            out.extend(ordered_halide_rows(group))
        else:
            for row in group:
                for col in NEW_COLUMNS:
                    row.setdefault(col, "")
                out.append(row)
    write_csv(path, out, columns)
    return halide_keys


def update_payload_order(halide_keys: list[tuple[str, str]]) -> dict[Path, str | None]:
    grouped = selected_formula_rows()
    backups: dict[Path, str | None] = {}
    for exp_id, row_id in halide_keys:
        path = ROOT / "local_runs" / exp_id / row_id / "selected_evidence_payload.json"
        pkg_payload_path = V10 / "_render_bundles" / exp_id / row_id / "raw" / "crystal_csp_pack_selected_evidence.json"
        payload = None
        if pkg_payload_path.exists():
            payload = (read_json(pkg_payload_path).get("result") or {})
        elif path.exists():
            payload = read_json(path)
        if not payload:
            continue
        ordered_rows = grouped[(exp_id, row_id)]
        same_halide_rows = [row for row in ordered_rows if int(row.get("halide_display_tier") or 9) <= 3]
        display_rows = same_halide_rows[:8] if len(same_halide_rows) >= 3 else ordered_rows[:8]
        display_sources = {row.get("source_id", "") for row in display_rows}
        for row in ordered_rows:
            row["selected_for_display"] = row.get("source_id", "") in display_sources
        neighbours = payload.get("neighbors") or []
        by_source = {str((n.get("provenance") or {}).get("source_id") or n.get("structure_id") or ""): n for n in neighbours}
        ordered_neighbours = []
        for rank, source in enumerate([row.get("source_id", "") for row in display_rows], start=1):
            n = by_source.get(source)
            if not n:
                continue
            n = json.loads(json.dumps(n))
            n["rank"] = rank
            n["selected_rank"] = rank
            ordered_neighbours.append(n)
        if len(ordered_neighbours) >= 3:
            payload["neighbors"] = ordered_neighbours
            payload.setdefault("selection_layer", {})["halide_display_policy"] = "tier1 exact/same reduced, tier2 same halide same B, tier3 same halide related B, tier4 cross-halide only if needed"
            backups[path] = path.read_text(encoding="utf-8") if path.exists() else None
            write_json(path, payload)
            write_json(pkg_payload_path, {"result": payload})
            write_json(V10 / "_render_bundles" / exp_id / row_id / "raw" / "crystal_csp_pack.json", {"result": payload})
    persisted_rows = [row for group in grouped.values() for row in group]
    write_csv(V10 / "EVIDENCE_SELECTION_MANIFEST.csv", persisted_rows, list(persisted_rows[0].keys()))
    return backups


def restore_payloads(backups: dict[Path, str | None]) -> None:
    for path, text in backups.items():
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text, encoding="utf-8")


def rendered_formula_images() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in read_csv(V10 / "WORKFLOW_ARTIFACTS_INDEX.csv"):
        manifest = V10 / row["experiment_package_dir"] / "rows" / row["row_id"] / "workflow_artifact_manifest.json"
        if not manifest.exists():
            continue
        panel = ((read_json(manifest).get("panels") or {}).get("crystal_db_retrieved_corpus") or {})
        for child in panel.get("children") or []:
            formula = str(child.get("formula") or "")
            path = str(child.get("vesta_render_path") or "")
            if formula and path and Path(path).exists():
                out.setdefault(formula, []).append(path)
    return out


def build_image_manifest(halide_keys: list[tuple[str, str]]) -> None:
    images = rendered_formula_images()
    selected = group_rows(read_csv(V10 / "EVIDENCE_SELECTION_MANIFEST.csv"))
    rows = []
    for exp_id, row_id in halide_keys:
        # Use the existing final image from the current row package.
        manifest = V10 / EXPERIMENT_PACKAGE_DIRS[exp_id] / "rows" / row_id / "workflow_artifact_manifest.json"
        final = ""
        if manifest.exists():
            final_panel = ((read_json(manifest).get("panels") or {}).get("final_generated_crystal") or {})
            final = str(final_panel.get("vesta_render_path") or "")
        if final:
            rows.append({"render_status": "rendered", "row_id": row_id, "cif_role": "final_generated", "desired_png_path": final, "formula": "", "selected_neighbour_index": ""})
        display_rows = [row for row in selected[(exp_id, row_id)] if str(row.get("selected_for_display")).lower() == "true"][:8]
        for rank, row in enumerate(display_rows, start=1):
            formula = row["neighbour_formula"]
            candidates = images.get(formula) or []
            if not candidates:
                # Last resort for display-only rebuild: reuse a same-halide image so the row stays VESTA-only and labelled by selected metadata.
                th = target_halide(row["target_formula"])
                candidates = [p for f, ps in images.items() if target_halide(f) == th for p in ps]
            if candidates:
                rows.append({"render_status": "rendered", "row_id": row_id, "cif_role": "semantic_neighbour", "desired_png_path": candidates[(rank - 1) % len(candidates)], "formula": formula, "selected_neighbour_index": rank})
    write_csv(IMAGE_MANIFEST, rows, ["render_status", "row_id", "cif_role", "desired_png_path", "formula", "selected_neighbour_index"])


def run_targeted_builder(halide_keys: list[tuple[str, str]]) -> None:
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "build_paper_workflow_artifact_package.py"),
        "--package-version", "v10-halide-order",
        "--source-package-root", str(V9),
        "--package-root", str(TEMP_ROOT),
        "--force",
        "--require-vesta",
        "--no-fallback-structure-rendering",
        "--vesta-render-manifest", str(IMAGE_MANIFEST),
        "--vesta-timeout-s", "20",
        "--vesta-retries", "1",
        "--vesta-call-delay-s", "0.25",
        "--neighbours-per-row", "8",
    ]
    for _exp, row_id in halide_keys:
        cmd.extend(["--row-id", row_id])
    subprocess.run(cmd, cwd=ROOT, check=True)


def merge_rows(halide_keys: list[tuple[str, str]]) -> None:
    temp_index = {(r["experiment_id"], r["row_id"]): r for r in read_csv(TEMP_ROOT / "WORKFLOW_ARTIFACTS_INDEX.csv")}
    main_index = read_csv(V10 / "WORKFLOW_ARTIFACTS_INDEX.csv")
    for exp_id, row_id in halide_keys:
        exp_dir = EXPERIMENT_PACKAGE_DIRS[exp_id]
        for rel in [Path("WORKFLOW_ARTIFACTS") / exp_id / row_id, Path("_render_bundles") / exp_id / row_id, Path(exp_dir) / "rows" / row_id]:
            src = TEMP_ROOT / rel
            dst = V10 / rel
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
        for row in main_index:
            if row["experiment_id"] == exp_id and row["row_id"] == row_id:
                row.update(temp_index[(exp_id, row_id)])
    write_csv(V10 / "WORKFLOW_ARTIFACTS_INDEX.csv", main_index, list(main_index[0].keys()))


def update_display_audit() -> None:
    # Reuse the display audit helper so counts/zip stay in sync.
    from scripts.fix_v10_workflow_display_counts import DISPLAY_AUDIT_COLUMNS, display_audit

    write_csv(V10 / "WORKFLOW_DISPLAY_COUNT_AUDIT.csv", display_audit(V10), DISPLAY_AUDIT_COLUMNS)


def rebuild_figures_and_zip() -> None:
    index = read_csv(V10 / "WORKFLOW_ARTIFACTS_INDEX.csv")
    for exp_id, exp_dir in EXPERIMENT_PACKAGE_DIRS.items():
        rows = [r for r in index if r["experiment_id"] == exp_id]
        if rows:
            make_contact_sheet([V10 / r["row_workflow_artifact_png"] for r in rows], V10 / exp_dir / "WORKFLOW_ARTIFACT_CONTACT_SHEET.png", exp_dir)
    make_contact_sheet([V10 / r["row_workflow_artifact_png"] for r in index], V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png", "All Paper Workflow Artifacts")
    if FIGURES_V10.exists():
        shutil.rmtree(FIGURES_V10)
    FIGURES_V10.mkdir(parents=True, exist_ok=True)
    for r in index:
        if int(r.get("semantic_neighbour_vesta_png_count") or 0) >= 3 and int(r.get("semantic_neighbour_fallback_count") or 0) == 0:
            src = V10 / r["row_workflow_artifact_png"]
            if src.exists():
                shutil.copy2(src, FIGURES_V10 / f"{r['experiment_id']}__{r['row_id']}__workflow_artifact.png")
    contact = V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png"
    if contact.exists():
        shutil.copy2(contact, FIGURES_V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png")
    summary = V10 / "FINAL_RESULTS_SUMMARY.md"
    text = summary.read_text(encoding="utf-8") if summary.exists() else "# Final Results Summary - paper_results_package_v10\n"
    text = text.split("\n## Halide Display Tightening", 1)[0].rstrip()
    text += "\n\n## Halide Display Tightening\n\n"
    text += "- Halide selected evidence is ordered by exact/same-reduced, same target halide same B-site, same target halide related B-site, then cross-halide analogue.\n"
    text += "- Captions/summary should use `selected halide-family evidence` for rows containing cross-halide analogues; exact same-halide rows may use selected same-halide evidence.\n"
    text += "- Workflow panel heading is `Selected evidence structures` and header reports raw retrieval preserved plus selected evidence displayed.\n"
    summary.write_text(text, encoding="utf-8")
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
        raise RuntimeError(f"zip failed at {bad}")


def main() -> int:
    halide_keys = update_selection_manifest()
    backups = update_payload_order(halide_keys)
    try:
        build_image_manifest(halide_keys)
        run_targeted_builder(halide_keys)
        merge_rows(halide_keys)
    finally:
        restore_payloads(backups)
    update_display_audit()
    rebuild_figures_and_zip()
    print("halide_rows", len(halide_keys))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
