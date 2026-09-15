from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sok_llm_orchestrator.agentic.visualise_workflow_artifact import _render_cif_with_vesta  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_").lower()


def parse_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    return "_atom_site" in text and ("_cell_length_a" in text or "_cell_angle_alpha" in text)


def validate_png(path: Path) -> dict[str, Any]:
    from PIL import Image

    if not path.is_file():
        return {"png_exists": False, "png_valid": False, "png_size_bytes": 0, "png_width": 0, "png_height": 0, "png_nonblank": False}
    size = path.stat().st_size
    try:
        with Image.open(path) as image:
            loaded = image.convert("RGB")
            width, height = loaded.size
            extrema = loaded.getextrema()
            nonblank = any(low != high for low, high in extrema)
    except Exception as exc:
        return {"png_exists": True, "png_valid": False, "png_size_bytes": size, "png_width": 0, "png_height": 0, "png_nonblank": False, "png_validation_error": str(exc)}
    return {"png_exists": True, "png_valid": True, "png_size_bytes": size, "png_width": width, "png_height": height, "png_nonblank": nonblank}


def retrieval_neighbours(row_run_dir: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = read_json(row_run_dir / "crystaldb_retrieval_results.json")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    retrieved = payload.get("neighbors") or []
    candidates: list[dict[str, Any]] = []
    for neighbour in retrieved:
        cif_info = neighbour.get("cif_export") if isinstance(neighbour.get("cif_export"), dict) else {}
        source_text = str(cif_info.get("path") or neighbour.get("cif_path") or "")
        if not source_text:
            continue
        source = resolve_path(source_text)
        if not source.is_file():
            source = row_run_dir / source_text
        candidates.append(
            {
                "rank": int(neighbour.get("rank") or len(rows) + 1),
                "score": neighbour.get("score", ""),
                "structure_id": neighbour.get("structure_id", ""),
                "formula": neighbour.get("formula") or (neighbour.get("metadata") or {}).get("formula") or "",
                "source_cif_path": str(source),
                "source_trace_path": str(row_run_dir / "crystaldb_retrieval_results.json"),
                "exists": source.is_file(),
                "parse_ok": parse_ok(source),
            }
        )
    for candidate in candidates:
        key = str(candidate.get("structure_id") or "") or str(Path(str(candidate["source_cif_path"])).resolve()).lower()
        if key in seen or not candidate["exists"] or not candidate["parse_ok"]:
            continue
        seen.add(key)
        rows.append(candidate)
        if len(rows) >= limit:
            break
    audit = {
        "retrieved_result_count": len(retrieved),
        "retrieved_cif_count": sum(1 for item in candidates if item["exists"]),
        "parseable_retrieved_cif_count": sum(1 for item in candidates if item["parse_ok"]),
        "selected_neighbour_count_target": limit,
        "selected_neighbour_count": len(rows),
        "selected_neighbour_ranks": ";".join(str(item["rank"]) for item in rows),
        "selected_neighbour_formulas": ";".join(str(item.get("formula") or item.get("structure_id") or "") for item in rows),
        "selected_neighbour_cif_paths": ";".join(str(item["source_cif_path"]) for item in rows),
        "missing_neighbour_reason": "fewer_than_target_unique_parseable_neighbours" if len(rows) < limit else "",
    }
    return rows, audit


def build_manifest(rows: list[dict[str, str]], out_root: Path, neighbour_limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for row in rows:
        experiment_id = row["experiment_id"]
        row_id = row["row_id"]
        formula = row.get("target_formula", "")
        row_run_dir = ROOT / "local_runs" / experiment_id / row_id
        entries = [
            {
                "render_id": f"{experiment_id}__{row_id}__final_generated",
                "experiment_id": experiment_id,
                "row_id": row_id,
                "formula": formula,
                "cif_role": "final_generated",
                "source_cif_path": row["generated_cif_path"],
                "staged_cif_path": str(out_root / "staged_cifs" / experiment_id / row_id / "final_generated.cif"),
                "desired_png_path": str(out_root / "pngs" / experiment_id / row_id / "final_generated.png"),
                "material_label": formula,
                "neighbour_rank": "",
                "retrieval_score": "",
                "source_trace_path": row.get("qlip_solution_path", ""),
            }
        ]
        neighbours, neighbour_audit = retrieval_neighbours(row_run_dir, neighbour_limit)
        audits.append(
            {
                "experiment_id": experiment_id,
                "row_id": row_id,
                "formula": formula,
                "retrieval_results_path": str(row_run_dir / "crystaldb_retrieval_results.json"),
                "evidence_manifest_path": str(row_run_dir / "retrieved_evidence_manifest.jsonl") if (row_run_dir / "retrieved_evidence_manifest.jsonl").is_file() else "",
                "selected_neighbour_count_current_v5": 1,
                **neighbour_audit,
            }
        )
        for selected_index, neighbour in enumerate(neighbours, start=1):
            rank = int(neighbour["rank"])
            entries.append(
                {
                    "render_id": f"{experiment_id}__{row_id}__neighbour_{selected_index:02d}",
                    "experiment_id": experiment_id,
                    "row_id": row_id,
                    "formula": formula,
                    "cif_role": "semantic_neighbour",
                    "source_cif_path": neighbour["source_cif_path"],
                    "staged_cif_path": str(out_root / "staged_cifs" / experiment_id / row_id / f"neighbour_{selected_index:02d}.cif"),
                    "desired_png_path": str(out_root / "pngs" / experiment_id / row_id / f"neighbour_{selected_index:02d}.png"),
                    "material_label": neighbour.get("formula") or neighbour.get("structure_id") or formula,
                    "neighbour_rank": rank,
                    "selected_neighbour_index": selected_index,
                    "retrieval_score": neighbour.get("score", ""),
                    "source_trace_path": neighbour.get("source_trace_path", ""),
                }
            )
        manifest.extend(entries)
    return manifest, audits


def kill_vesta() -> None:
    subprocess.run(["taskkill", "/IM", "VESTA.exe", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def stage_and_render(entry: dict[str, Any], vesta_path: str, timeout_s: float, force: bool) -> dict[str, Any]:
    source = resolve_path(str(entry["source_cif_path"]))
    staged = Path(str(entry["staged_cif_path"]))
    png = Path(str(entry["desired_png_path"]))
    log_path = Path(str(png).replace("\\pngs\\", "\\logs\\")).with_name(f"{Path(str(entry['staged_cif_path'])).stem}_vesta.log")
    entry["cif_exists"] = source.is_file()
    entry["cif_parse_ok"] = parse_ok(source)
    entry["vesta_error_text"] = ""
    entry["render_status"] = "not_attempted"
    if not entry["cif_exists"] or not entry["cif_parse_ok"]:
        entry["render_status"] = "missing_or_unparseable_cif"
        return entry
    staged.parent.mkdir(parents=True, exist_ok=True)
    png.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if force or not staged.is_file():
        shutil.copy2(source, staged)
    if force and png.exists():
        png.unlink()
    try:
        status = _render_cif_with_vesta(staged, png, vesta_path, timeout_s=timeout_s, call_delay_s=0.2, retries=0, stabilization_poll_interval_s=0.25)
        entry.update(status)
        entry["render_status"] = "rendered"
        entry.update(validate_png(png))
    except Exception as exc:
        entry["render_status"] = "failed"
        entry["vesta_error_text"] = str(exc)
        entry.update(validate_png(png))
    log_path.write_text(json.dumps(entry, indent=2, default=str), encoding="utf-8")
    kill_vesta()
    return entry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-source", default="artifacts/paper_results_package_v4")
    parser.add_argument("--experiment-root", default="local_runs")
    parser.add_argument("--out-root", default="artifacts/paper_results_package_v5_vesta_renders")
    parser.add_argument("--vesta-path", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--neighbour-limit", type=int, default=0)
    parser.add_argument("--neighbours-per-row", type=int, default=10)
    parser.add_argument("--min-neighbours-per-row", type=int, default=3)
    parser.add_argument("--allow-fewer-neighbours-if-unavailable", action="store_true")
    parser.add_argument("--neighbour-selection", default="top-ranked", choices=["top-ranked"])
    parser.add_argument("--row-limit", type=int, default=0)
    parser.add_argument("--row-id", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out_root = resolve_path(args.out_root)
    if args.force and out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    rows = read_csv(ROOT / "artifacts" / "PAPER_EXPERIMENTS_FULL_SCA_MANIFEST.csv")
    if args.row_id:
        wanted = set(args.row_id)
        rows = [row for row in rows if row["row_id"] in wanted]
    if args.row_limit:
        rows = rows[: args.row_limit]
    neighbour_limit = args.neighbour_limit or args.neighbours_per_row
    manifest, audits = build_manifest(rows, out_root, neighbour_limit)
    for entry in manifest:
        stage_and_render(entry, args.vesta_path, args.timeout_seconds, force=args.force)
    write_csv(out_root / "VESTA_CIF_RENDER_MANIFEST.csv", manifest)
    write_json(out_root / "VESTA_CIF_RENDER_MANIFEST.json", manifest)
    audit_root = ROOT / "artifacts" / f"{Path(args.out_root).name}_neighbour_audit"
    if args.force and audit_root.exists():
        shutil.rmtree(audit_root)
    write_csv(audit_root / "RETRIEVED_NEIGHBOUR_COUNT_AUDIT.csv", audits)
    write_json(audit_root / "RETRIEVED_NEIGHBOUR_COUNT_AUDIT.json", audits)
    rendered = [entry for entry in manifest if entry.get("render_status") == "rendered" and entry.get("png_valid") is True]
    failed = [entry for entry in manifest if entry not in rendered]
    summary = {
        "generated_row_count": len(rows),
        "neighbours_per_row_target": neighbour_limit,
        "total_final_generated_cifs": sum(1 for entry in manifest if entry["cif_role"] == "final_generated"),
        "total_semantic_neighbour_cifs_selected": sum(1 for entry in manifest if entry["cif_role"] == "semantic_neighbour"),
        "total_cifs": len(manifest),
        "total_cifs_staged": len(manifest),
        "total_cifs_rendered": len(rendered),
        "rendered_count": len(rendered),
        "failed_count": len(failed),
        "failed_vesta_render_count": len(failed),
        "final_generated_rendered_count": sum(1 for entry in rendered if entry["cif_role"] == "final_generated"),
        "semantic_neighbour_rendered_count": sum(1 for entry in rendered if entry["cif_role"] == "semantic_neighbour"),
        "failed_render_ids": [entry["render_id"] for entry in failed],
        "out_root": str(out_root),
        "vesta_path": args.vesta_path,
        "neighbour_limit": args.neighbour_limit,
        "rows_with_10_neighbours": sum(1 for audit in audits if int(audit["selected_neighbour_count"]) >= 10),
        "rows_with_5_to_9_neighbours": sum(1 for audit in audits if 5 <= int(audit["selected_neighbour_count"]) <= 9),
        "rows_with_3_to_4_neighbours": sum(1 for audit in audits if 3 <= int(audit["selected_neighbour_count"]) <= 4),
        "rows_with_2_or_fewer_neighbours": sum(1 for audit in audits if int(audit["selected_neighbour_count"]) <= 2),
        "rows_with_missing_neighbour_cifs": sum(1 for audit in audits if audit["missing_neighbour_reason"]),
    }
    write_json(out_root / "VESTA_RENDER_SUMMARY.json", summary)
    lines = [
        "# VESTA CIF Render Report",
        "",
        f"- VESTA executable: `{args.vesta_path}`",
        f"- Total CIFs staged: {len(manifest)}",
        f"- Rendered PNGs: {len(rendered)}",
        f"- Failed renders: {len(failed)}",
        "",
    ]
    if failed:
        lines.append("## Failed CIFs")
        for entry in failed:
            lines.append(f"- `{entry['render_id']}`: {entry.get('vesta_error_text') or entry.get('render_status')}")
    (out_root / "VESTA_RENDER_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    kill_vesta()
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
