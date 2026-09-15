from __future__ import annotations

import csv
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
V10 = ROOT / "artifacts" / "paper_results_package_v10"
FIGURES_V10 = ROOT / "figures" / "paper_v10"
IMAGE_MANIFEST = V10 / "V10_RERENDER_EXISTING_IMAGE_MANIFEST.csv"

sys.path.insert(0, str(ROOT))
from scripts.build_paper_workflow_artifact_package import EXPERIMENT_PACKAGE_DIRS, make_contact_sheet, manifest_render_fields  # noqa: E402
from sok_llm_orchestrator.agentic.visualise_workflow_artifact import visualise_workflow_artifact  # noqa: E402


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


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def current_manifest_children(row: dict[str, str]) -> list[dict[str, Any]]:
    manifest = V10 / row["experiment_package_dir"] / "rows" / row["row_id"] / "workflow_artifact_manifest.json"
    if not manifest.exists():
        return []
    panels = read_json(manifest).get("panels") or {}
    return list((panels.get("crystal_db_retrieved_corpus") or {}).get("children") or [])


def build_image_manifest(index_rows: list[dict[str, str]]) -> None:
    rows = []
    for row in index_rows:
        row_id = row["row_id"]
        manifest = V10 / row["experiment_package_dir"] / "rows" / row_id / "workflow_artifact_manifest.json"
        if not manifest.exists():
            continue
        panels = read_json(manifest).get("panels") or {}
        final = (panels.get("final_generated_crystal") or {}).get("vesta_render_path") or ""
        if final and Path(final).exists():
            rows.append({"render_status": "rendered", "row_id": row_id, "cif_role": "final_generated", "desired_png_path": final})
        for child in (panels.get("crystal_db_retrieved_corpus") or {}).get("children") or []:
            path = child.get("vesta_render_path") or ""
            if path and Path(path).exists():
                rows.append(
                    {
                        "render_status": "rendered",
                        "row_id": row_id,
                        "cif_role": "semantic_neighbour",
                        "neighbour_rank": child.get("rank") or len(rows) + 1,
                        "desired_png_path": path,
                    }
                )
    write_csv(IMAGE_MANIFEST, rows, ["render_status", "row_id", "cif_role", "neighbour_rank", "desired_png_path"])


def _payload_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    export = result.get("export") if isinstance(result.get("export"), dict) else {}
    return list(export.get("items") or result.get("neighbors") or result.get("semantic_neighbors") or [])


def _replace_payload_items(payload: Any, items: list[dict[str, Any]]) -> None:
    if not isinstance(payload, dict):
        return
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    export = result.setdefault("export", {})
    if isinstance(export, dict):
        export["items"] = items
        export["exported_cif_count"] = len(items)
    result["neighbors"] = items
    result["semantic_neighbors"] = items
    result["neighbor_count"] = result.get("neighbor_count", 0) or len(items)


def trim_bundle_to_manifest_children(row: dict[str, str], bundle: Path) -> int:
    children = current_manifest_children(row)
    if not children:
        return 8
    keys = {
        str(child.get("structure_id") or child.get("source_id") or child.get("formula") or child.get("rank") or "")
        for child in children
    }
    ranks = {_safe_int(child.get("rank")) for child in children}
    ranks.discard(0)
    raw_dir = bundle / "raw"
    for name in ("crystal_csp_pack.json", "crystal_csp_pack_selected_evidence.json"):
        path = raw_dir / name
        if not path.exists():
            continue
        payload = read_json(path)
        selected = []
        for item in _payload_items(payload):
            item_key = str(item.get("structure_id") or item.get("source_id") or item.get("formula") or item.get("rank") or "")
            if item_key in keys or _safe_int(item.get("rank")) in ranks:
                selected.append(item)
        if not selected:
            selected = _payload_items(payload)[: len(children)]
        _replace_payload_items(payload, selected[: len(children)])
        write_json(path, payload)
    return len(children)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def rerender_all() -> None:
    index_path = V10 / "WORKFLOW_ARTIFACTS_INDEX.csv"
    index_rows = read_csv(index_path)
    build_image_manifest(index_rows)
    updated = []
    for row in index_rows:
        exp_id = row["experiment_id"]
        row_id = row["row_id"]
        case_name = f"{exp_id}__{row_id}__{row.get('target_formula', '')}"
        bundle = V10 / "_render_bundles" / exp_id / row_id
        out_dir = V10 / "WORKFLOW_ARTIFACTS" / exp_id / row_id
        row_pkg = V10 / row["experiment_package_dir"] / "rows" / row_id
        display_count = trim_bundle_to_manifest_children(row, bundle)
        result = visualise_workflow_artifact(
            bundle,
            out_dir,
            case_name,
            require_vesta=False,
            no_fallback_structure_rendering=True,
            render_semantic_neighbours_with_vesta=True,
            semantic_neighbour_image_manifest=IMAGE_MANIFEST,
            require_vesta_images=True,
            semantic_neighbour_target_count=max(1, display_count),
            final_crystal_image_path=None,
        )
        for ext, key in [("png", "png_path"), ("pdf", "pdf_path"), ("svg", "svg_path")]:
            src = Path(result[key])
            shutil.copy2(src, row_pkg / f"workflow_artifact.{ext}")
            row[f"row_workflow_artifact_{ext}"] = str((row_pkg / f"workflow_artifact.{ext}").relative_to(V10))
            row[f"workflow_artifact_{ext}"] = str(src.relative_to(V10))
        manifest_src = Path(result["manifest_path"])
        shutil.copy2(manifest_src, row_pkg / "workflow_artifact_manifest.json")
        row["workflow_artifact_manifest"] = str(manifest_src.relative_to(V10))
        row.update(manifest_render_fields(manifest_src))
        updated.append(row)
    write_csv(index_path, updated, list(updated[0].keys()))
    for exp_id, exp_dir in EXPERIMENT_PACKAGE_DIRS.items():
        rows = [r for r in updated if r["experiment_id"] == exp_id]
        make_contact_sheet([V10 / r["row_workflow_artifact_png"] for r in rows], V10 / exp_dir / "WORKFLOW_ARTIFACT_CONTACT_SHEET.png", exp_dir)
    make_contact_sheet([V10 / r["row_workflow_artifact_png"] for r in updated], V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png", "All Paper Workflow Artifacts")
    if FIGURES_V10.exists():
        shutil.rmtree(FIGURES_V10)
    FIGURES_V10.mkdir(parents=True, exist_ok=True)
    for r in updated:
        if int(r.get("semantic_neighbour_vesta_png_count") or 0) >= 3 and int(r.get("semantic_neighbour_fallback_count") or 0) == 0:
            shutil.copy2(V10 / r["row_workflow_artifact_png"], FIGURES_V10 / f"{r['experiment_id']}__{r['row_id']}__workflow_artifact.png")
    shutil.copy2(V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png", FIGURES_V10 / "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png")


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
        raise RuntimeError(f"zip failed at {bad}")


def main() -> int:
    rerender_all()
    zip_v10()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
