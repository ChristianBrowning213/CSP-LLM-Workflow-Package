"""Evaluation-only Stability, Uniqueness, Novelty benchmarking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Structure

from sca.evaluators.cif_parse import parse_cif
from sca.io import discover_cif_files, load_manifest_frame, resolve_manifest_path


STABILITY_THRESHOLDS = (0.00, 0.05, 0.10, 0.15)


def run_sun_benchmark(
    *,
    manifest: str | Path,
    out_dir: str | Path,
    reference_folder: str | Path | None = None,
    reference_manifest: str | Path | None = None,
    path_col: str = "cif_path",
    reference_path_col: str = "cif_path",
    reference_id_col: str | None = None,
    anonymous: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(manifest)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = load_manifest_frame(manifest_path, path_col)
    generated = _load_generated(frame, path_col)
    references = _load_references(
        reference_folder=reference_folder,
        reference_manifest=reference_manifest,
        path_col=reference_path_col,
        id_col=reference_id_col,
    )
    matcher = _matcher()
    _assign_uniqueness(generated, matcher)
    _assign_novelty(generated, references, matcher, anonymous=anonymous)
    _assign_stability(generated, frame)
    rows = [_result_row(item) for item in generated]
    cluster_rows = _cluster_rows(rows)
    results_csv = out / "sun_results.csv"
    clusters_csv = out / "sun_duplicate_clusters.csv"
    summary_json = out / "sun_summary.json"
    report_md = out / "sun_report.md"
    pd.DataFrame(rows).to_csv(results_csv, index=False)
    pd.DataFrame(cluster_rows).to_csv(clusters_csv, index=False)
    summary = _summary(rows, references, frame)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report_md.write_text(_markdown(summary, rows, cluster_rows, anonymous=anonymous), encoding="utf-8")
    return {
        "rows": len(rows),
        "results_csv": str(results_csv),
        "clusters_csv": str(clusters_csv),
        "summary_json": str(summary_json),
        "report_md": str(report_md),
    }


def build_reference_manifest(
    *,
    cif_dir: str | Path,
    out: str | Path,
    reference_set_name: str,
) -> dict[str, Any]:
    root = Path(cif_dir)
    paths = discover_cif_files(root)
    rows = []
    for index, path in enumerate(paths, start=1):
        _, parsed = parse_cif(path)
        rows.append(
            {
                "reference_id": f"{reference_set_name}_{index:05d}",
                "reference_set_name": reference_set_name,
                "cif_path": str(path.resolve()),
                "file_name": path.name,
                "parse_ok": parsed.parse_ok,
                "formula": parsed.formula,
                "reduced_formula": parsed.reduced_formula,
                "error_type": parsed.error_type,
                "error_message": parsed.error_message,
            }
        )
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)
    return {"rows": len(rows), "out": str(out_path)}


def _load_generated(frame: pd.DataFrame, path_col: str) -> list[dict[str, Any]]:
    generated = []
    for index, row in frame.iterrows():
        path = Path(str(row[path_col]))
        structure, parsed = parse_cif(path)
        generated.append(
            {
                "row_index": index,
                "manifest_row": row.to_dict(),
                "path": path,
                "structure": structure,
                "parse_ok": bool(parsed.parse_ok),
                "parse_error": parsed.error_message,
                "formula": parsed.reduced_formula,
            }
        )
    return generated


def _load_references(
    *,
    reference_folder: str | Path | None,
    reference_manifest: str | Path | None,
    path_col: str,
    id_col: str | None,
) -> dict[str, Structure]:
    references: dict[str, Structure] = {}
    paths: list[tuple[str, Path]] = []
    if reference_folder:
        for path in discover_cif_files(reference_folder):
            paths.append((str(path), path))
    if reference_manifest:
        manifest = Path(reference_manifest)
        frame = pd.read_csv(manifest, dtype=str).fillna("")
        if path_col not in frame.columns:
            raise ValueError(f"Reference manifest path column '{path_col}' not found")
        for index, row in frame.iterrows():
            path = resolve_manifest_path(row[path_col], manifest)
            ref_id = row[id_col] if id_col and id_col in frame.columns and row[id_col] else str(path)
            paths.append((str(ref_id), path))
    for ref_id, path in paths:
        structure, parsed = parse_cif(path)
        if parsed.parse_ok and structure is not None:
            references[ref_id] = structure
    return references


def _assign_uniqueness(generated: list[dict[str, Any]], matcher: StructureMatcher) -> None:
    clusters: list[list[dict[str, Any]]] = []
    representatives: list[Structure] = []
    for item in generated:
        structure = item["structure"]
        if structure is None:
            item["unique_cluster_id"] = None
            item["is_duplicate"] = None
            item["is_unique_representative"] = None
            item["uniqueness_error"] = item["parse_error"] or "not_computable"
            continue
        placed = False
        for cluster_index, representative in enumerate(representatives):
            same_composition = structure.composition.reduced_composition.almost_equals(
                representative.composition.reduced_composition
            )
            if same_composition and matcher.fit(structure, representative):
                clusters[cluster_index].append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
            representatives.append(structure)
    for index, cluster in enumerate(clusters, start=1):
        cluster_id = f"sun-dup-{index:04d}"
        for member_index, item in enumerate(cluster):
            item["unique_cluster_id"] = cluster_id
            item["duplicate_cluster_size"] = len(cluster)
            item["is_duplicate"] = len(cluster) > 1
            item["is_unique_representative"] = member_index == 0
            item["uniqueness_error"] = None


def _assign_novelty(
    generated: list[dict[str, Any]],
    references: dict[str, Structure],
    matcher: StructureMatcher,
    *,
    anonymous: bool,
) -> None:
    for item in generated:
        structure = item["structure"]
        if structure is None:
            item["novelty_checked"] = bool(references)
            item["novel"] = None
            item["known_match"] = None
            item["matched_reference_id"] = None
            item["novelty_error"] = item["parse_error"] or "not_computable"
            continue
        if not references:
            item["novelty_checked"] = False
            item["novel"] = None
            item["known_match"] = None
            item["matched_reference_id"] = None
            item["novelty_error"] = "not_computable: no reference set supplied"
            continue
        matched = None
        try:
            for ref_id, reference in references.items():
                is_match = matcher.fit_anonymous(structure, reference) if anonymous else matcher.fit(structure, reference)
                if is_match:
                    matched = ref_id
                    break
            item["novelty_checked"] = True
            item["known_match"] = matched is not None
            item["novel"] = matched is None
            item["matched_reference_id"] = matched
            item["novelty_error"] = None
        except Exception as exc:
            item["novelty_checked"] = True
            item["known_match"] = None
            item["novel"] = None
            item["matched_reference_id"] = None
            item["novelty_error"] = f"{type(exc).__name__}: {exc}"


def _assign_stability(generated: list[dict[str, Any]], frame: pd.DataFrame) -> None:
    hull_col = _first_present(frame, ("predicted_energy_above_hull", "energy_above_hull", "e_above_hull"))
    formation_col = _first_present(frame, ("formation_energy_per_atom", "formation_energy", "predicted_formation_energy_per_atom"))
    static_col = _first_present(frame, ("chgnet_energy_per_atom", "mlip_energy_mean", "static_energy_per_atom"))
    for item in generated:
        row = item["manifest_row"]
        hull = _float(row.get(hull_col)) if hull_col else None
        formation = _float(row.get(formation_col)) if formation_col else None
        static = _float(row.get(static_col)) if static_col else None
        item["predicted_energy_above_hull"] = hull
        item["formation_energy_per_atom"] = formation
        item["static_energy_per_atom"] = static
        item["stability_computable"] = hull is not None or formation is not None or static is not None
        item["stability_error"] = None if item["stability_computable"] else "not_computable: provide predicted_energy_above_hull, formation_energy_per_atom, or a real static-energy column such as chgnet_energy_per_atom"
        for threshold in STABILITY_THRESHOLDS:
            item[f"stable_under_{threshold:.2f}ev_per_atom"] = hull <= threshold if hull is not None else None


def _result_row(item: dict[str, Any]) -> dict[str, Any]:
    row = {
        "cif_path": str(item["path"]),
        "parse_ok": item["parse_ok"],
        "formula": item["formula"],
        "unique_cluster_id": item.get("unique_cluster_id"),
        "duplicate_cluster_size": item.get("duplicate_cluster_size"),
        "is_duplicate": item.get("is_duplicate"),
        "is_unique_representative": item.get("is_unique_representative"),
        "uniqueness_error": item.get("uniqueness_error"),
        "novelty_checked": item.get("novelty_checked"),
        "novel": item.get("novel"),
        "known_match": item.get("known_match"),
        "matched_reference_id": item.get("matched_reference_id"),
        "novelty_error": item.get("novelty_error"),
        "predicted_energy_above_hull": item.get("predicted_energy_above_hull"),
        "formation_energy_per_atom": item.get("formation_energy_per_atom"),
        "static_energy_per_atom": item.get("static_energy_per_atom"),
        "stability_computable": item.get("stability_computable"),
        "stability_error": item.get("stability_error"),
    }
    for threshold in STABILITY_THRESHOLDS:
        row[f"stable_under_{threshold:.2f}ev_per_atom"] = item.get(f"stable_under_{threshold:.2f}ev_per_atom")
    for key, value in item["manifest_row"].items():
        row.setdefault(str(key), value)
    return row


def _summary(rows: list[dict[str, Any]], references: dict[str, Structure], frame: pd.DataFrame) -> dict[str, Any]:
    valid = [row for row in rows if _as_bool(row.get("parse_ok")) is True]
    unique_reps = [row for row in rows if _as_bool(row.get("is_unique_representative")) is True]
    novelty_rows = [row for row in rows if _as_bool(row.get("novelty_checked")) is True and row.get("novel") is not None]
    hull_col = _first_present(frame, ("predicted_energy_above_hull", "energy_above_hull", "e_above_hull"))
    formation_col = _first_present(frame, ("formation_energy_per_atom", "formation_energy", "predicted_formation_energy_per_atom"))
    static_col = _first_present(frame, ("chgnet_energy_per_atom", "mlip_energy_mean", "static_energy_per_atom"))
    summary = {
        "benchmark_name": "S.U.N. evaluation-only benchmark",
        "leaderboard_claim": False,
        "mp20_training_or_test_benchmark": False,
        "num_generated": len(rows),
        "num_parseable": len(valid),
        "num_unique_structures": len(unique_reps),
        "uniqueness_rate": _rate(len(unique_reps), len(valid)),
        "num_duplicate_clusters": len({row["unique_cluster_id"] for row in rows if row.get("is_duplicate") is True}),
        "reference_count": len(references),
        "novelty_checked_count": len(novelty_rows),
        "novelty_rate": _rate(sum(1 for row in novelty_rows if row.get("novel") is True), len(novelty_rows)),
        "stability_status": "computable" if hull_col or formation_col or static_col else "not_computable",
        "stability_required_inputs": None if hull_col or formation_col or static_col else "predicted_energy_above_hull, formation_energy_per_atom, or a real static-energy column such as chgnet_energy_per_atom",
        "predicted_energy_above_hull_column": hull_col,
        "formation_energy_per_atom_column": formation_col,
        "static_energy_per_atom_column": static_col,
    }
    for threshold in STABILITY_THRESHOLDS:
        column = f"stable_under_{threshold:.2f}ev_per_atom"
        values = [_as_bool(row.get(column)) for row in rows]
        values = [value for value in values if value is not None]
        summary[column + "_rate"] = _rate(sum(values), len(values)) if values else None
    formation_values = [_float(row.get("formation_energy_per_atom")) for row in rows]
    formation_values = [value for value in formation_values if value is not None]
    summary["formation_energy_per_atom_mean"] = sum(formation_values) / len(formation_values) if formation_values else None
    summary["formation_energy_per_atom_min"] = min(formation_values) if formation_values else None
    static_values = [_float(row.get("static_energy_per_atom")) for row in rows]
    static_values = [value for value in static_values if value is not None]
    summary["static_energy_per_atom_mean"] = sum(static_values) / len(static_values) if static_values else None
    summary["static_energy_per_atom_min"] = min(static_values) if static_values else None
    return summary


def _markdown(summary: dict[str, Any], rows: list[dict[str, Any]], cluster_rows: list[dict[str, Any]], *, anonymous: bool) -> str:
    duplicate_rows = [row for row in rows if row.get("is_duplicate") is True]
    matched_rows = [row for row in rows if row.get("known_match") is True]
    lines = [
        "# S.U.N. Evaluation-Only Benchmark Report",
        "",
        "This report evaluates generated CIF quality after generation. It is not an MP-20 training/test leaderboard claim.",
        "Reference sets are used only for novelty, nearest-neighbour, and optional reference matching unless explicitly configured otherwise.",
        "",
        "## Summary",
        "",
        f"- Generated CIFs: {summary['num_generated']}",
        f"- Parseable CIFs: {summary['num_parseable']}",
        f"- Unique structures: {summary['num_unique_structures']}",
        f"- Uniqueness rate: {_fmt(summary['uniqueness_rate'])}",
        f"- Reference structures loaded: {summary['reference_count']}",
        f"- Novelty checked rows: {summary['novelty_checked_count']}",
        f"- Novelty rate: {_fmt(summary['novelty_rate'])}",
        f"- Novelty mode: {'anonymous' if anonymous else 'exact species'}",
        f"- Stability status: {summary['stability_status']}",
        "",
        "## Stability",
        "",
    ]
    if summary["stability_status"] == "not_computable":
        lines.append(f"- Not computable. Required inputs: {summary['stability_required_inputs']}.")
    else:
        for threshold in STABILITY_THRESHOLDS:
            key = f"stable_under_{threshold:.2f}ev_per_atom_rate"
            lines.append(f"- E_hull <= {threshold:.2f} eV/atom: {_fmt(summary.get(key))}")
        lines.append(f"- Mean formation energy per atom: {_fmt(summary.get('formation_energy_per_atom_mean'))}")
        lines.append(f"- Mean static energy per atom: {_fmt(summary.get('static_energy_per_atom_mean'))}")
        if summary.get("predicted_energy_above_hull_column") is None:
            lines.append("- Hull-threshold rates are not computable without an actual energy-above-hull column.")
    lines.extend(["", "## Uniqueness", ""])
    lines.append(f"- Duplicate clusters: {summary['num_duplicate_clusters']}")
    lines.append(f"- Duplicate rows: {len(duplicate_rows)}")
    lines.extend(["", "### Duplicate Clusters", ""])
    if cluster_rows:
        lines.extend(_cluster_table(cluster_rows))
    else:
        lines.append("No parseable duplicate clusters were computed.")
    lines.extend(["", "## Novelty", ""])
    lines.append(f"- Reference matches: {len(matched_rows)}")
    lines.append("- Novelty is evaluation-only and does not imply the reference set was used for generation.")
    lines.extend(["", "## Caveats", ""])
    lines.append("- S.U.N. is a generated-CIF quality screen, not an exact MP-20 reproduction.")
    lines.append("- Exact MP-20 comparison requires MP-20 split metadata and reference CIF paths in the input manifest.")
    lines.append("- Stability is not computable unless predicted hull or formation-energy columns are supplied.")
    return "\n".join(lines) + "\n"


def _cluster_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        cluster_id = row.get("unique_cluster_id")
        if cluster_id:
            clusters.setdefault(str(cluster_id), []).append(row)
    cluster_rows = []
    for cluster_id, members in sorted(clusters.items()):
        representative = next((row for row in members if row.get("is_unique_representative") is True), members[0])
        cluster_rows.append(
            {
                "cluster_id": cluster_id,
                "cluster_size": len(members),
                "representative_cif_path": representative.get("cif_path"),
                "formulas": ";".join(sorted({str(row.get("formula") or "") for row in members if row.get("formula")})),
                "prompts": " || ".join(_unique_nonempty(row.get("input_text") or row.get("prompt") for row in members)),
                "benchmark_ids": ";".join(_unique_nonempty(row.get("benchmark_id") for row in members)),
                "prompt_ids": ";".join(_unique_nonempty(row.get("prompt_id") for row in members)),
            }
        )
    return cluster_rows


def _cluster_table(cluster_rows: list[dict[str, Any]]) -> list[str]:
    columns = ["cluster_id", "cluster_size", "representative_cif_path", "formulas", "prompt_ids"]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in cluster_rows[:50]:
        lines.append("| " + " | ".join(_markdown_cell(row.get(column)) for column in columns) + " |")
    return lines


def _unique_nonempty(values) -> list[str]:
    seen = []
    for value in values:
        text = "" if value is None else str(value).strip()
        if text and text.lower() != "nan" and text not in seen:
            seen.append(text)
    return seen


def _markdown_cell(value: Any) -> str:
    return ("" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")


def _matcher() -> StructureMatcher:
    return StructureMatcher(
        ltol=0.2,
        stol=0.3,
        angle_tol=5,
        primitive_cell=True,
        scale=True,
        attempt_supercell=True,
    )


def _first_present(frame: pd.DataFrame, columns: tuple[str, ...]) -> str | None:
    for column in columns:
        if column in frame.columns and frame[column].astype(str).str.strip().ne("").any():
            return column
    return None


def _float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _fmt(value: Any) -> str:
    parsed = _float(value)
    return "not_computable" if parsed is None else f"{parsed:.3f}"
