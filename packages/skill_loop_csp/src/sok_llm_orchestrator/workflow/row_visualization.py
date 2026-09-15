"""Reproducible workflow figures sourced only from row and solver artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageChops
from pymatgen.core import Structure

from sok_llm_orchestrator.agentic.visualise_workflow_artifact import (
    _parse_pot_file,
    _render_cif_with_vesta,
    _resolve_vesta_executable,
)


ROOT = Path(__file__).resolve().parents[3]
AXIS_X = "Distance (Å)"
AXIS_Y = "SPP score (lower preferred)"
TOP_K = 4


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, separators=(",", ":")) if isinstance(value, (list, dict)) else value for key, value in row.items()})


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _resolve(path_text: str, *, base: Path = ROOT) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else (base / path).resolve()


def _truth(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"yes", "true", "1", "pass"}


def shorten_request(request: str, width: int = 38) -> str:
    compact = " ".join(str(request).split())
    compact = re.sub(
        r"\s+(?:using|from)\s+retrieved\s+(?:[A-Za-z-]+\s+){0,3}evidence\.?$",
        ".",
        compact,
        flags=re.IGNORECASE,
    )
    compact = re.sub(r"\s+using\s+retrieved\s+evidence\.?$", ".", compact, flags=re.IGNORECASE)
    if len(compact) <= 105:
        return compact
    first = compact[:102].rsplit(" ", 1)[0]
    return first + "…"


def _formula(path: Path) -> str:
    return Structure.from_file(path).composition.reduced_formula.replace(" ", "")


@dataclass(frozen=True)
class Neighbour:
    rank: int
    structure_id: str
    formula: str
    cif_path: Path
    score: str


@dataclass(frozen=True)
class Curve:
    pair: str
    mode: str
    xs: tuple[float, ...]
    ys: tuple[float, ...]
    request_path: str
    request_hash: str
    regulator_path: str
    regulator_hash: str
    outer_weight: float
    regulator_weight: float


@dataclass
class RowFigureData:
    master: dict[str, str]
    row_dir: Path
    trace: dict[str, Any]
    generated_cif: Path
    neighbours: list[Neighbour]
    curves: list[Curve]
    spp_status: str
    spp_reason: str
    source_paths: list[str]


def _selected_source_record(master: dict[str, str]) -> dict[str, str]:
    source = _resolve(master.get("source_artifact", ""))
    if source.suffix.lower() != ".csv" or not source.is_file():
        return {}
    key, separator, value = master.get("source_artifact_key", "").partition("=")
    matches = [row for row in read_csv(source) if separator and row.get(key) == value]
    return matches[0] if len(matches) == 1 else {}


def _canonical_trace(row_dir: Path, master: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    direct = row_dir / "workflow_trace.json"
    if direct.is_file():
        return _json(direct), [str(direct)]
    source = _resolve(master.get("source_artifact", ""))
    if source.suffix.lower() == ".json" and source.is_file():
        payload = _json(source)
        if "retrieved_ids" in payload and "qlip_adapter" in payload:
            return payload, [str(source)]
    return {}, []


def _legacy_archive(master: dict[str, str]) -> tuple[Path | None, dict[str, str]]:
    record = _selected_source_record(master)
    group, task = record.get("experiment_group", ""), record.get("source_task_id", "")
    archive = ROOT / "local_runs" / group / task
    return (archive if group and task and archive.is_dir() else None), record


def _canonical_neighbours(trace: dict[str, Any], top_k: int) -> list[Neighbour]:
    ids = [str(value) for value in trace.get("retrieved_ids", [])][:top_k]
    attempt = _resolve(str(trace.get("attempt_workspace") or ""))
    cif_root = attempt / "retrieved_cifs"
    result: list[Neighbour] = []
    scores = list(trace.get("retrieval_scores") or [])
    for index, structure_id in enumerate(ids, start=1):
        path = cif_root / f"{structure_id}.cif"
        if not path.is_file():
            raise FileNotFoundError(f"top retrieved CIF missing for rank {index}: {path}")
        score = scores[index - 1] if index <= len(scores) else ""
        result.append(Neighbour(index, structure_id, _formula(path), path, str(score)))
    return result


def _legacy_neighbours(archive: Path, top_k: int) -> list[Neighbour]:
    path = archive / "crystaldb_retrieval_results.json"
    payload = _json(path)
    result: list[Neighbour] = []
    for index, row in enumerate(list(payload.get("neighbors") or [])[:top_k], start=1):
        export = str((row.get("cif_export") or {}).get("path") or "")
        cif_path = _resolve(export)
        if not cif_path.is_file():
            raise FileNotFoundError(f"top retrieved CIF missing for rank {index}: {cif_path}")
        metadata = row.get("metadata") or {}
        structure_id = str(row.get("structure_id") or (row.get("provenance") or {}).get("source_id") or cif_path.stem)
        formula = str(metadata.get("formula") or _formula(cif_path)).replace(" ", "")
        result.append(Neighbour(index, structure_id, formula, cif_path, str(row.get("score") or "")))
    return result


def _read_pot(path_text: str) -> tuple[Path, np.ndarray, np.ndarray]:
    path = _resolve(path_text)
    parsed = _parse_pot_file(path)
    if not path.is_file() or not parsed:
        raise FileNotFoundError(f"solver POT artifact missing or unparseable: {path}")
    return path, np.asarray(parsed[0], dtype=float), np.asarray(parsed[1], dtype=float)


def _attempt_config(trace: dict[str, Any]) -> dict[str, Any]:
    attempt = _resolve(str(trace.get("attempt_workspace") or ""))
    path = attempt / "attempt_manifest.json"
    return (_json(path).get("scientific_config") or {}) if path.is_file() else {}


def solver_curves(trace: dict[str, Any]) -> list[Curve]:
    adapter = trace.get("qlip_adapter") or {}
    required = [str(pair) for pair in adapter.get("required_pairs") or []]
    if not required:
        return []
    by_pair = {str(row.get("species_pair")): row for row in trace.get("request_pair_results") or []}
    config = _attempt_config(trace)
    outer = float(config.get("outer_objective_scale", adapter.get("guidance_weight")))
    regulator_weight = float(config.get("regulator_coefficient", 2.0))
    representation = str(adapter.get("representation") or "")
    result: list[Curve] = []
    for pair in required:
        row = by_pair.get(pair)
        if row is None:
            raise ValueError(f"required solver pair has no guidance record: {pair}")
        mode = str(row.get("guidance_mode") or "")
        regulator_path, regulator_x, regulator_y = _read_pot(str(row.get("regulator_pot_path") or ""))
        request_path_text = str(row.get("request_pot_path") or "")
        if mode == "REQUEST_PLUS_REGULATOR":
            request_path, request_x, request_y = _read_pot(request_path_text)
            xs = request_x
            regulator_interp = np.interp(xs, regulator_x, regulator_y)
            ys = outer * (request_y + regulator_weight * regulator_interp)
            request_hash = sha256(request_path)
            request_path_value = str(request_path)
        elif representation == "REGULATOR_AS_PRIMARY_WEIGHTED":
            xs, ys = regulator_x, float(adapter["guidance_weight"]) * regulator_y
            request_hash, request_path_value = "", ""
        else:
            xs, ys = regulator_x, outer * regulator_weight * regulator_y
            request_hash, request_path_value = "", ""
        result.append(Curve(
            pair=pair, mode=mode, xs=tuple(float(value) for value in xs), ys=tuple(float(value) for value in ys),
            request_path=request_path_value, request_hash=request_hash,
            regulator_path=str(regulator_path), regulator_hash=sha256(regulator_path),
            outer_weight=outer, regulator_weight=regulator_weight,
        ))
    return result


def resolve_row_figure_data(master: dict[str, str], table_root: Path, *, top_k: int = TOP_K) -> RowFigureData:
    row_dir = table_root / "rows" / master["row_id"]
    trace, sources = _canonical_trace(row_dir, master)
    archive, source_record = _legacy_archive(master)
    generated_cif = _resolve(master["cif_path"])
    if not generated_cif.is_file():
        raise FileNotFoundError(f"generated CIF missing: {generated_cif}")
    if trace:
        neighbours = _canonical_neighbours(trace, top_k)
        curves = solver_curves(trace)
        spp_status = "FINAL_SOLVER_GUIDANCE" if curves else "NO_SOLVER_POT"
        reason = "" if curves else "No required-pair POT artifacts were recorded."
        sources.extend([str(_resolve(str(trace.get("attempt_workspace") or "")) / "attempt_manifest.json")])
    elif archive is not None:
        neighbours = _legacy_neighbours(archive, top_k)
        curves = []
        solution_path = archive / "qlip_solution.json"
        solution = _json(solution_path)
        scoring = str((solution.get("selection") or {}).get("spp_scoring_status") or solution.get("spp_scoring_status") or "unavailable")
        pot_dir = (solution.get("selection") or {}).get("spp_pot_dir") or solution.get("spp_pot_dir")
        if scoring != "unavailable" or pot_dir not in {None, ""}:
            raise ValueError(f"legacy SPP boundary changed unexpectedly for {master['row_id']}: status={scoring}, pot_dir={pot_dir}")
        spp_status = "HISTORICAL_SOLVER_POT_UNAVAILABLE"
        reason = "Historical solver record: spp_scoring_status=unavailable; spp_pot_dir=null."
        sources.extend([str(archive / "crystaldb_retrieval_results.json"), str(solution_path), str(_resolve(source_record.get("generated_cif_path", "")))])
    else:
        raise ValueError(f"cannot resolve workflow artifacts for {master['row_id']}")
    if not neighbours:
        raise ValueError(f"no exportable ranked retrieval neighbours for {master['row_id']}")
    return RowFigureData(master, row_dir, trace, generated_cif, neighbours, curves, spp_status, reason, sources)


def _trim_image(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    background = Image.new("RGB", image.size, (255, 255, 255))
    difference = ImageChops.difference(image, background).convert("L")
    difference = difference.point(lambda value: 255 if value > 12 else 0)
    box = difference.getbbox()
    if box is None:
        return image
    left, top, right, bottom = box
    pad_x, pad_y = max(8, int((right - left) * 0.04)), max(8, int((bottom - top) * 0.04))
    return image.crop((max(0, left - pad_x), max(0, top - pad_y), min(image.width, right + pad_x), min(image.height, bottom + pad_y)))


def render_vesta(cif_path: Path, cache_root: Path, vesta_path: str) -> tuple[Path, dict[str, Any]]:
    cif_hash = sha256(cif_path)
    output = cache_root / f"{cif_hash}.png"
    provenance_path = cache_root / f"{cif_hash}.json"
    cache_root.mkdir(parents=True, exist_ok=True)
    if output.is_file() and output.stat().st_size > 0 and provenance_path.is_file():
        provenance = _json(provenance_path)
        if provenance.get("source_cif_sha256") == cif_hash and provenance.get("renderer") == "VESTA":
            return output, provenance
    status = _render_cif_with_vesta(cif_path, output, vesta_path, timeout_s=120, call_delay_s=0.5, retries=2)
    provenance = {
        "renderer": "VESTA", "vesta_executable": vesta_path,
        "source_cif_path": str(cif_path), "source_cif_sha256": cif_hash,
        "render_png": str(output), "render_png_sha256": sha256(output), "render_status": "PASS",
        "diagnostics": status,
    }
    provenance_path.write_text(json.dumps(provenance, indent=2, default=str) + "\n", encoding="utf-8")
    return output, provenance


def _panel_header(ax: Any, number: str, title: str) -> None:
    ax.text(0.0, 1.03, number, transform=ax.transAxes, ha="left", va="bottom", fontsize=11, fontweight="bold", color="#1f5a7a")
    ax.text(0.10, 1.03, title, transform=ax.transAxes, ha="left", va="bottom", fontsize=10.5, fontweight="bold", color="#17232b")


def _show_vesta(ax: Any, path: Path) -> None:
    ax.imshow(_trim_image(path))
    ax.set_axis_off()


def _validation_lines(row: dict[str, str]) -> list[tuple[str, str]]:
    geometry = row.get("sca_status") or "NOT AVAILABLE"
    topology = row.get("sca_topology") or "NOT AVAILABLE"
    chgnet = "converged" if _truth(row.get("chgnet_converged")) else row.get("chgnet_status") or "NOT AVAILABLE"
    symmetry = "retained" if _truth(row.get("space_group_retained")) else "changed" if row.get("space_group_retained") not in {"", "NOT_APPLICABLE"} else "NOT AVAILABLE"
    crystal_retention = "retained" if _truth(row.get("crystal_system_retained")) else "changed" if row.get("crystal_system_retained") not in {"", "NOT_APPLICABLE"} else "NOT AVAILABLE"
    volume = row.get("volume_change_percent")
    volume_text = f"{float(volume):+.2f}%" if volume not in {None, "", "NOT_APPLICABLE"} else "NOT AVAILABLE"
    lines = [
        ("QLIP solver", row.get("solver_status") or "NOT AVAILABLE"),
        ("Objective parity", row.get("objective_parity") or "NOT AVAILABLE"),
        ("pymatgen CIF / composition", "valid / exact" if row.get("cif_emitted") == "YES" and _truth(row.get("exact_composition")) else "NOT AVAILABLE"),
        ("pymatgen geometry/contact checks", geometry),
        ("CrystalNN family-topology checks", topology),
        ("CHGNet relaxation", chgnet),
        ("pymatgen SpacegroupAnalyzer", f"{row.get('initial_space_group') or 'n/a'} → {row.get('relaxed_space_group') or 'n/a'} ({symmetry})"),
        ("pymatgen crystal system", f"{row.get('initial_crystal_system') or 'n/a'} → {row.get('relaxed_crystal_system') or 'n/a'} ({crystal_retention})"),
        ("CHGNet volume change", volume_text),
        ("pymatgen StructureMatcher", row.get("initial_relaxed_match") or "NOT AVAILABLE"),
    ]
    return [item for item in lines if item[1] != "NOT AVAILABLE"]


def _write_curve_source(path: Path, curves: list[Curve]) -> None:
    rows: list[dict[str, Any]] = []
    for curve in curves:
        for x, y in zip(curve.xs, curve.ys):
            rows.append({
                "species_pair": curve.pair, "distance_A": x, "solver_weighted_spp_score": y,
                "guidance_mode": curve.mode, "request_pot_path": curve.request_path,
                "request_pot_sha256": curve.request_hash, "regulator_pot_path": curve.regulator_path,
                "regulator_pot_sha256": curve.regulator_hash, "outer_weight": curve.outer_weight,
                "regulator_weight": curve.regulator_weight,
            })
    write_csv(path, rows)


def finite_curve_ylim(values: Iterable[float], *, padding_fraction: float = 0.08) -> tuple[float, float]:
    """Return limits that strictly contain every finite solver-effective value."""
    finite = np.asarray([float(value) for value in values if np.isfinite(float(value))], dtype=float)
    if finite.size == 0:
        raise ValueError("solver-effective SPP curve contains no finite values")
    lower, upper = float(finite.min()), float(finite.max())
    span = upper - lower
    if span <= 0.0:
        span = max(abs(lower), 1.0)
    padding = span * float(padding_fraction)
    limits = (lower - padding, upper + padding)
    if not (lower > limits[0] and upper < limits[1]):
        raise AssertionError("finite solver-effective curve is not strictly inside its y-axis limits")
    return limits


def draw_row_figure(data: RowFigureData, output_dir: Path, cache_root: Path, vesta_path: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    final_render, final_provenance = render_vesta(data.generated_cif, cache_root, vesta_path)
    neighbour_records: list[dict[str, Any]] = []
    for neighbour in data.neighbours:
        render, provenance = render_vesta(neighbour.cif_path, cache_root, vesta_path)
        neighbour_records.append({"neighbour": neighbour, "render": render, "provenance": provenance})

    curve_count = len(data.curves)
    figure_height = 9.4 if curve_count > 8 else 7.2
    fig = plt.figure(figsize=(20, figure_height), facecolor="white")
    outer = fig.add_gridspec(1, 4, width_ratios=[1.35, 2.55, 3.35 if curve_count > 8 else 2.8, 2.35], left=0.025, right=0.985, top=0.87, bottom=0.07, wspace=0.18)

    request_ax = fig.add_subplot(outer[0, 0]); request_ax.set_axis_off(); _panel_header(request_ax, "1", "Research request")
    request_ax.text(0.02, 0.83, textwrap.fill(shorten_request(data.master["request"]), 28), va="top", fontsize=12, color="#17232b", linespacing=1.35)
    request_ax.text(0.02, 0.18, f"Target\n{data.master['formula']}", va="top", fontsize=10.5, fontweight="bold", color="#1f5a7a")

    neighbour_count = len(neighbour_records)
    retrieval_rows = 1 if neighbour_count <= 2 else 2
    retrieval_cols = 1 if neighbour_count == 1 else 2
    retrieval_spec = outer[0, 1].subgridspec(retrieval_rows + 1, retrieval_cols, height_ratios=[0.18] + [1] * retrieval_rows, hspace=0.24, wspace=0.10)
    retrieval_header = fig.add_subplot(retrieval_spec[0, :]); retrieval_header.set_axis_off(); _panel_header(retrieval_header, "2", "Top retrieved Crystal-DB neighbours")
    for index, record in enumerate(neighbour_records):
        neighbour = record["neighbour"]
        ax = fig.add_subplot(retrieval_spec[1 + index // retrieval_cols, index % retrieval_cols]); _show_vesta(ax, record["render"])
        ax.set_title(f"#{neighbour.rank}  {neighbour.formula}\n{neighbour.structure_id}", fontsize=7.8, pad=1.5)

    spp_spec = outer[0, 2].subgridspec(2, 1, height_ratios=[0.14, 1.0], hspace=0.08)
    spp_header = fig.add_subplot(spp_spec[0, 0]); spp_header.set_axis_off(); _panel_header(spp_header, "3", "SPP guidance")
    if data.curves:
        cols = min(4, max(2, math.ceil(math.sqrt(curve_count))))
        rows = math.ceil(curve_count / cols)
        curve_grid = spp_spec[1, 0].subgridspec(rows, cols, hspace=0.46, wspace=0.34)
        curve_axis_qa: dict[str, dict[str, float | bool]] = {}
        for index, curve in enumerate(data.curves):
            ax = fig.add_subplot(curve_grid[index // cols, index % cols])
            ax.plot(curve.xs, curve.ys, color="#2b6f93" if curve.mode == "REQUEST_PLUS_REGULATOR" else "#9a5d1f", linewidth=1.0)
            ylim = finite_curve_ylim(curve.ys)
            ax.set_xlim(1.5, max(curve.xs)); ax.set_ylim(*ylim); ax.set_title(curve.pair, fontsize=7.2, pad=1.5)
            finite_values = [float(value) for value in curve.ys if np.isfinite(float(value))]
            curve_min, curve_max = min(finite_values), max(finite_values)
            inside = curve_min > ylim[0] and curve_max < ylim[1]
            if not inside:
                raise AssertionError(f"{curve.pair} solver-effective SPP curve is clipped")
            curve_axis_qa[curve.pair] = {
                "curve_min": curve_min, "curve_max": curve_max,
                "axis_lower": float(ylim[0]), "axis_upper": float(ylim[1]),
                "all_finite_points_strictly_inside": inside,
            }
            ax.grid(color="#d9e0e4", linewidth=0.35, alpha=0.8); ax.tick_params(labelsize=5.6, length=2)
            if index // cols == rows - 1: ax.set_xlabel(AXIS_X, fontsize=6.2)
            else: ax.set_xticklabels([])
            if index % cols == 0: ax.set_ylabel(AXIS_Y, fontsize=6.0)
            else: ax.set_yticklabels([])
        for index in range(curve_count, rows * cols):
            ax = fig.add_subplot(curve_grid[index // cols, index % cols]); ax.set_axis_off()
        spp_header.text(0.98, 0.12, f"{curve_count} required pairs • per-pair full finite range • 8% padding • no clipping", transform=spp_header.transAxes, ha="right", fontsize=7.2, color="#44545e")
    else:
        curve_axis_qa = {}
        empty = fig.add_subplot(spp_spec[1, 0]); empty.set_axis_off()
        empty.text(0.5, 0.57, "No POT/SPP curve was passed\nto this historical solver execution", ha="center", va="center", fontsize=12, fontweight="bold", color="#7a3f18")
        empty.text(0.5, 0.40, textwrap.fill(data.spp_reason, 55), ha="center", va="center", fontsize=8.5, color="#44545e")

    output_spec = outer[0, 3].subgridspec(3, 1, height_ratios=[0.13, 1.25, 0.85], hspace=0.12)
    output_header = fig.add_subplot(output_spec[0, 0]); output_header.set_axis_off(); _panel_header(output_header, "4", "Generated crystal")
    output_ax = fig.add_subplot(output_spec[1, 0]); _show_vesta(output_ax, final_render)
    output_ax.set_title(f"{data.master['formula']}  •  {data.master.get('initial_space_group') or 'space group n/a'}", fontsize=9, pad=2)
    validation_ax = fig.add_subplot(output_spec[2, 0]); validation_ax.set_axis_off(); _panel_header(validation_ax, "5", "Result and validation")
    lines = _validation_lines(data.master)
    step = min(0.092, 0.78 / max(len(lines), 1))
    for index, (label, value) in enumerate(lines):
        y = 0.86 - index * step
        validation_ax.text(0.02, y, label, fontsize=6.7, color="#52616b", va="center", transform=validation_ax.transAxes)
        validation_ax.text(0.98, y, str(value), fontsize=6.8, fontweight="bold", color="#17232b", ha="right", va="center", transform=validation_ax.transAxes)
        validation_ax.plot([0.02, 0.98], [y - step * 0.48, y - step * 0.48], color="#e2e6e9", linewidth=0.45, transform=validation_ax.transAxes)

    for x in (0.178, 0.425, 0.735):
        fig.text(x, 0.49, "→", fontsize=21, color="#83919a", ha="center", va="center")
    fig.suptitle(f"Traceable row workflow  |  {data.master['row_id']}  |  {data.master['formula']}", fontsize=15, fontweight="bold", color="#17232b", y=0.965)
    fig.text(0.5, 0.915, "request  →  ranked evidence  →  solver-consumed guidance  →  VESTA-rendered output  →  measured validation", ha="center", fontsize=9, color="#52616b")
    png, pdf = output_dir / "workflow_full.png", output_dir / "workflow_full.pdf"
    fig.savefig(png, dpi=240, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)
    curve_csv = output_dir / "spp_solver_guidance.csv"
    _write_curve_source(curve_csv, data.curves)
    manifest = {
        "schema_version": "row_workflow_figure.v1", "row_id": data.master["row_id"],
        "formula": data.master["formula"], "request": data.master["request"],
        "request_short": shorten_request(data.master["request"]),
        "retrieval_top_k_requested": TOP_K,
        "retrieval_count_displayed": len(neighbour_records),
        "retrieval_ids": [item["neighbour"].structure_id for item in neighbour_records],
        "retrieval_formulas": [item["neighbour"].formula for item in neighbour_records],
        "retrieval_cif_paths": [str(item["neighbour"].cif_path) for item in neighbour_records],
        "retrieval_cif_hashes": [sha256(item["neighbour"].cif_path) for item in neighbour_records],
        "retrieval_vesta_renders": [str(item["render"]) for item in neighbour_records],
        "spp_status": data.spp_status, "spp_reason": data.spp_reason,
        "spp_pairs": [curve.pair for curve in data.curves],
        "spp_pair_modes": {curve.pair: curve.mode for curve in data.curves},
        "spp_axis_qa": curve_axis_qa,
        "spp_curve_source_csv": str(curve_csv), "spp_x_axis": AXIS_X, "spp_y_axis": AXIS_Y,
        "generated_cif_path": str(data.generated_cif), "generated_cif_sha256": sha256(data.generated_cif),
        "generated_vesta_render": str(final_render), "generated_vesta_provenance": final_provenance,
        "validation_summary": dict(lines), "source_artifacts": sorted(set(data.source_paths)),
        "workflow_figure_png": str(png), "workflow_figure_pdf": str(pdf),
        "visual_qa_status": "PENDING",
    }
    manifest_path = output_dir / "workflow_figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest


def build_row_workflow_figure(
    summary: dict[str, Any],
    row_dir: Path,
    figures_root: Path,
    *,
    top_k: int = TOP_K,
    vesta_path: str | None = None,
) -> dict[str, Any]:
    """Build one canonical row figure directly after a successful table run."""
    if summary.get("cif_generated") != "YES" or summary.get("workflow_status") not in {
        "PASS", "OBJECTIVE_PARITY_FAILURE",
    }:
        raise ValueError("success workflow figures require a CIF-emitting canonical row")
    vesta = _resolve_vesta_executable(vesta_path)
    if not vesta:
        established = ROOT.parent.parent / "VESTA-win64" / "VESTA-win64" / "VESTA.exe"
        vesta = str(established.resolve()) if established.is_file() else ""
    if not vesta:
        raise FileNotFoundError("VESTA executable is required for row workflow figures")
    master = {str(key): str(value if value is not None else "") for key, value in summary.items()}
    master.update({
        "cif_emitted": "YES",
        "exact_composition": master.get("sca_target_formula_match", ""),
        "initial_space_group": master.get("generated_space_group", ""),
        "sca_topology": master.get("sca_topology_status", ""),
        "space_group_retained": (
            "YES" if master.get("generated_space_group") and
            master.get("generated_space_group") == master.get("relaxed_space_group") else "NO"
        ),
    })
    data = resolve_row_figure_data(master, row_dir.parent.parent, top_k=top_k)
    return draw_row_figure(data, row_dir / "figures", figures_root / "vesta_cache", vesta)


def build_row_workflow_figures(
    master_path: Path,
    table_root: Path,
    figures_root: Path,
    *,
    only: Iterable[str] | None = None,
    top_k: int = TOP_K,
    vesta_path: str | None = None,
    row_output_root: Path | None = None,
) -> list[dict[str, Any]]:
    selected = set(only or [])
    vesta = _resolve_vesta_executable(vesta_path)
    if not vesta:
        established = ROOT.parent.parent / "VESTA-win64" / "VESTA-win64" / "VESTA.exe"
        vesta = str(established.resolve()) if established.is_file() else ""
    if not vesta:
        raise FileNotFoundError("VESTA executable is required for row workflow figures")
    master_rows = read_csv(master_path)
    eligible = [row for row in master_rows if row.get("cif_emitted") == "YES" and (not selected or row["row_id"] in selected)]
    records: list[dict[str, Any]] = []
    cache_root = figures_root / "vesta_cache"
    for row in eligible:
        data = resolve_row_figure_data(row, table_root, top_k=top_k)
        row_output = Path(row_output_root) / row["row_id"] if row_output_root else table_root / "rows" / row["row_id"] / "figures"
        manifest = draw_row_figure(data, row_output, cache_root, vesta)
        records.append({
            "row_id": row["row_id"], "formula": row["formula"], "request_short": manifest["request_short"],
            "workflow_figure_png": str(Path(manifest["workflow_figure_png"]).relative_to(ROOT)).replace("\\", "/"),
            "workflow_figure_pdf": str(Path(manifest["workflow_figure_pdf"]).relative_to(ROOT)).replace("\\", "/"),
            "retrieval_count_displayed": len(manifest["retrieval_ids"]), "retrieval_ids": manifest["retrieval_ids"],
            "SPP_pair_count": len(manifest["spp_pairs"]), "SPP_status": manifest["spp_status"],
            "VESTA_render": "PASS", "validation_summary_present": "YES",
            "visual_QA_status": "PENDING", "notes": manifest["spp_reason"],
        })
    write_csv(figures_root / "ROW_WORKFLOW_FIGURES.csv", records)
    build_contact_sheet(records, figures_root / "ROW_WORKFLOW_FIGURES_CONTACT_SHEET.png")
    return records


def build_contact_sheet(records: list[dict[str, Any]], output: Path, *, columns: int = 3) -> None:
    thumbs: list[tuple[dict[str, Any], Image.Image]] = []
    for record in records:
        image = Image.open(_resolve(str(record["workflow_figure_png"]))).convert("RGB")
        image.thumbnail((720, 380), Image.Resampling.LANCZOS)
        thumbs.append((record, image.copy()))
    cell_width, cell_height = 740, 430
    rows = math.ceil(len(thumbs) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    for index, (record, thumb) in enumerate(thumbs):
        x, y = (index % columns) * cell_width, (index // columns) * cell_height
        sheet.paste(thumb, (x + (cell_width - thumb.width) // 2, y + 34))
        draw.text((x + 12, y + 8), f"{record['row_id']} | {record['formula']} | SPP pairs {record['SPP_pair_count']}", fill="#17232b", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, dpi=(180, 180))


def approve_visual_qa(figures_root: Path, table_root: Path | None = None) -> None:
    manifest_path = figures_root / "ROW_WORKFLOW_FIGURES.csv"
    records = read_csv(manifest_path)
    for record in records:
        png = _resolve(record["workflow_figure_png"])
        pdf = _resolve(record["workflow_figure_pdf"])
        if not png.is_file() or not pdf.is_file():
            raise FileNotFoundError(f"cannot approve missing row figure: {record['row_id']}")
        record["visual_QA_status"] = "PASS"
        row_manifest_path = png.parent / "workflow_figure_manifest.json"
        row_manifest = _json(row_manifest_path); row_manifest["visual_qa_status"] = "PASS"
        row_manifest_path.write_text(json.dumps(row_manifest, indent=2, default=str) + "\n", encoding="utf-8")
    write_csv(manifest_path, records)
