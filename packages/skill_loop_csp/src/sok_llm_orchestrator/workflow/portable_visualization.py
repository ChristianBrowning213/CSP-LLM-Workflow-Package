"""Render a workflow figure using only one portable CSV-workflow row bundle."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pymatgen.core import Element, Structure


SPP_DISPLAY_RANGE = (-4.0, 10.0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_pot(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rows: list[tuple[float, float]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if not rows:
        raise ValueError(f"POT contains no numeric curve: {path}")
    values = np.asarray(rows, dtype=float)
    return values[:, 0], values[:, 1]


def _element_color(symbol: str) -> tuple[float, float, float]:
    palette = {
        "O": "#d84a3a",
        "N": "#4467b2",
        "Li": "#7f62b3",
        "Mg": "#62a86f",
        "Al": "#8d9aa3",
        "Ti": "#5e7787",
        "Fe": "#b56a3a",
        "Co": "#476e91",
        "Ba": "#55a9a0",
        "Ca": "#65a85d",
        "Sr": "#4f9b68",
        "Cs": "#885da7",
        "Pb": "#555c67",
        "Cl": "#58a84d",
        "Br": "#9a4039",
        "I": "#6b478c",
        "P": "#d08a32",
        "S": "#d3ad32",
        "Zn": "#728ea6",
        "Zr": "#4fa1a0",
        "Sn": "#718391",
    }
    from matplotlib.colors import to_rgb

    return to_rgb(palette.get(symbol, "#6f7a82"))


def _radius(symbol: str) -> float:
    element = Element(symbol)
    radius = element.atomic_radius or element.atomic_radius_calculated
    return float(radius) if radius is not None else 1.0


def _draw_structure(
    ax: Any,
    structure: Structure,
    *,
    repeat: tuple[int, int, int] = (1, 1, 1),
    legend: bool = False,
) -> None:
    displayed = structure.copy()
    displayed.make_supercell(repeat)
    coords = np.asarray(displayed.cart_coords, dtype=float)
    # A fixed oblique projection keeps layered and periodic motifs legible while
    # remaining independent of VESTA or any external database/tool.
    projected_x = coords[:, 0] + 0.28 * coords[:, 2]
    projected_y = coords[:, 1] + 0.17 * coords[:, 2]
    symbols = [site.specie.symbol for site in displayed]
    order = np.argsort(coords[:, 2])
    for index in order:
        symbol = symbols[int(index)]
        ax.scatter(
            projected_x[index],
            projected_y[index],
            s=22 + 24 * _radius(symbol),
            facecolor=_element_color(symbol),
            edgecolor="white",
            linewidth=0.45,
            alpha=0.94,
            zorder=2 + float(coords[index, 2]) * 1e-3,
        )
    corners = np.array(
        [
            [0, 0, 0],
            displayed.lattice.matrix[0],
            displayed.lattice.matrix[0] + displayed.lattice.matrix[1],
            displayed.lattice.matrix[1],
            [0, 0, 0],
        ],
        dtype=float,
    )
    ax.plot(corners[:, 0] + 0.28 * corners[:, 2], corners[:, 1] + 0.17 * corners[:, 2], color="#9aa6ad", linewidth=0.65, zorder=1)
    ax.set_aspect("equal", adjustable="datalim")
    ax.margins(0.08)
    ax.set_axis_off()
    if legend:
        unique = sorted(set(symbols))
        handles = [
            ax.scatter([], [], s=34, color=_element_color(symbol), edgecolor="white", label=symbol)
            for symbol in unique
        ]
        ax.legend(handles=handles, loc="lower center", ncol=min(5, len(unique)), frameon=False, fontsize=7)


def _panel_header(ax: Any, number: str, title: str) -> None:
    ax.text(0.0, 1.02, number, transform=ax.transAxes, fontsize=11, fontweight="bold", color="#1f5a7a", va="bottom")
    ax.text(0.085, 1.02, title, transform=ax.transAxes, fontsize=10.5, fontweight="bold", color="#17232b", va="bottom")


def render_portable_row(row_root: Path) -> dict[str, Any]:
    row_root = Path(row_root).resolve()
    request_path = row_root / "input" / "request.txt"
    candidate = row_root / "generated" / "candidate.cif"
    retrieval_manifest = row_root / "retrieval" / "retrieval_manifest.csv"
    pair_manifest = row_root / "spp" / "pair_manifest.csv"
    required = [request_path, candidate, retrieval_manifest, pair_manifest]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"portable row is incomplete; missing: {missing}")
    before = {path.relative_to(row_root).as_posix(): _sha256(path) for path in [candidate]}
    request = request_path.read_text(encoding="utf-8")
    task = _read_json(row_root / "structured_task" / "structured_task.json")
    neighbours = [row for row in _read_csv(retrieval_manifest) if row.get("portable_cif_path")][:4]
    pairs = _read_csv(pair_manifest)
    curves: list[tuple[str, Path, np.ndarray, np.ndarray]] = []
    for item in pairs:
        path_text = item.get("selected_pot_path") or ""
        path = row_root / path_text
        if path.is_file():
            xs, ys = _read_pot(path)
            curves.append((item["species_pair"], path, xs, ys))

    curve_count = len(curves)
    fig = plt.figure(figsize=(20, 8.3), facecolor="white")
    outer = fig.add_gridspec(
        1,
        4,
        width_ratios=[1.35, 2.6, 3.15, 2.35],
        left=0.028,
        right=0.982,
        top=0.87,
        bottom=0.075,
        wspace=0.19,
    )
    request_ax = fig.add_subplot(outer[0, 0])
    request_ax.set_axis_off()
    _panel_header(request_ax, "1", "Research request")
    request_ax.text(0.02, 0.86, textwrap.fill(request, 29), va="top", fontsize=11.5, color="#17232b", linespacing=1.35)
    request_ax.text(0.02, 0.18, f"Target\n{task['formula']}", va="top", fontsize=10.5, fontweight="bold", color="#1f5a7a")

    retrieval_grid = outer[0, 1].subgridspec(3, 2, height_ratios=[0.16, 1, 1], hspace=0.28, wspace=0.08)
    retrieval_header = fig.add_subplot(retrieval_grid[0, :])
    retrieval_header.set_axis_off()
    _panel_header(retrieval_header, "2", "Persisted retrieved neighbours")
    for index, item in enumerate(neighbours):
        ax = fig.add_subplot(retrieval_grid[1 + index // 2, index % 2])
        cif = row_root / item["portable_cif_path"]
        structure = Structure.from_file(cif)
        _draw_structure(ax, structure)
        ax.set_title(f"#{item['rank']}  {structure.composition.reduced_formula}\n{item['structure_id']}", fontsize=7.4, pad=1)
    for index in range(len(neighbours), 4):
        fig.add_subplot(retrieval_grid[1 + index // 2, index % 2]).set_axis_off()

    spp_grid = outer[0, 2].subgridspec(2, 1, height_ratios=[0.13, 1], hspace=0.08)
    spp_header = fig.add_subplot(spp_grid[0, 0])
    spp_header.set_axis_off()
    _panel_header(spp_header, "3", "Persisted dmytro_gr_v1 guidance")
    if curves:
        columns = min(3, max(1, math.ceil(math.sqrt(curve_count))))
        rows = math.ceil(curve_count / columns)
        panels = spp_grid[1, 0].subgridspec(rows, columns, hspace=0.45, wspace=0.32)
        for index, (pair, _path, xs, ys) in enumerate(curves):
            ax = fig.add_subplot(panels[index // columns, index % columns])
            ax.plot(xs, ys, color="#2b6f93", linewidth=1.05)
            ax.axhline(0, color="#9ca8ae", linewidth=0.45)
            ax.set_xlim(0, 10)
            ax.set_ylim(*SPP_DISPLAY_RANGE)
            ax.set_title(pair, fontsize=7.4, pad=1)
            ax.grid(color="#d9e0e4", linewidth=0.35, alpha=0.8)
            ax.tick_params(labelsize=5.8, length=2)
            if index // columns == rows - 1:
                ax.set_xlabel("Distance (angstrom)", fontsize=6.2)
            else:
                ax.set_xticklabels([])
            if index % columns == 0:
                ax.set_ylabel("SPP score", fontsize=6.2)
            else:
                ax.set_yticklabels([])
        for index in range(curve_count, rows * columns):
            fig.add_subplot(panels[index // columns, index % columns]).set_axis_off()
        spp_header.text(0.98, 0.10, "shared paper display: -4 to +10; raw POT values unchanged", transform=spp_header.transAxes, ha="right", fontsize=7, color="#52616b")
    else:
        ax = fig.add_subplot(spp_grid[1, 0])
        ax.set_axis_off()
        ax.text(0.5, 0.5, "No persisted POT curves", ha="center", va="center")

    output_grid = outer[0, 3].subgridspec(3, 1, height_ratios=[0.13, 1.35, 0.75], hspace=0.10)
    output_header = fig.add_subplot(output_grid[0, 0])
    output_header.set_axis_off()
    _panel_header(output_header, "4", "QLIP-generated crystal")
    output_ax = fig.add_subplot(output_grid[1, 0])
    generated = Structure.from_file(candidate)
    _draw_structure(output_ax, generated, repeat=(2, 2, 2), legend=True)
    output_ax.set_title(f"{generated.composition.reduced_formula}\n2x2x2 visualisation supercell", fontsize=8.5, pad=2)
    validation_ax = fig.add_subplot(output_grid[2, 0])
    validation_ax.set_axis_off()
    _panel_header(validation_ax, "5", "Result and optional validation")
    solver = _read_json(row_root / "qlip" / "solver_result.json")
    sca_summary = row_root / "sca" / "summary.json"
    sca = _read_json(sca_summary) if sca_summary.is_file() else {"sca_status": "NOT RUN"}
    lines = [
        ("QLIP", solver.get("status", "not recorded")),
        ("Candidate SHA-256", _sha256(candidate)[:12] + "..."),
        ("SCA", sca.get("sca_status", "NOT RUN")),
    ]
    if sca_summary.is_file():
        lines.extend(
            [
                ("Geometry", sca.get("geometry_valid")),
                ("Bad contacts", sca.get("bad_contacts")),
                ("Topology", sca.get("topology_result")),
            ]
        )
    for index, (label, value) in enumerate(lines):
        y = 0.80 - index * 0.12
        validation_ax.text(0.02, y, str(label), fontsize=7, color="#52616b", transform=validation_ax.transAxes)
        validation_ax.text(0.98, y, str(value), fontsize=7.1, fontweight="bold", color="#17232b", ha="right", transform=validation_ax.transAxes)

    for x in (0.18, 0.43, 0.74):
        fig.text(x, 0.49, "->", fontsize=18, color="#83919a", ha="center", va="center")
    fig.suptitle(f"Portable crystal-generation trace  |  {row_root.name}  |  {task['formula']}", fontsize=15, fontweight="bold", color="#17232b", y=0.965)
    fig.text(0.5, 0.917, "request  ->  copied retrieval evidence  ->  persisted SPPs  ->  raw generated CIF  ->  optional SCA", ha="center", fontsize=9, color="#52616b")
    visual_root = row_root / "visualisation"
    visual_root.mkdir(parents=True, exist_ok=True)
    png = visual_root / "workflow.png"
    pdf = visual_root / "workflow.pdf"
    fig.savefig(png, dpi=240, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)

    after = {path.relative_to(row_root).as_posix(): _sha256(path) for path in [candidate]}
    if before != after:
        raise RuntimeError("visualisation changed a raw scientific CIF")
    metadata = {
        "schema_version": "portable_row_visualisation.v1",
        "row_id": row_root.name,
        "request_text": request,
        "formula": str(task["formula"]),
        "input_scope": "row_folder_only",
        "crystal_db_queried": False,
        "retrieval_neighbour_paths": [item["portable_cif_path"] for item in neighbours],
        "spp_pot_paths": [path.relative_to(row_root).as_posix() for _, path, _, _ in curves],
        "candidate_cif_path": "generated/candidate.cif",
        "candidate_sha256": after["generated/candidate.cif"],
        "candidate_hash_unchanged": before == after,
        "generated_display_supercell": [2, 2, 2],
        "visualization_only": True,
        "sca_status": sca.get("sca_status", "NOT RUN"),
        "spp_display_y_range": list(SPP_DISPLAY_RANGE),
        "raw_spp_unchanged": True,
        "workflow_png": str(png),
        "workflow_pdf": str(pdf),
    }
    metadata_path = visual_root / "figure_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


__all__ = ["SPP_DISPLAY_RANGE", "render_portable_row"]
