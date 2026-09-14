"""Render the two approved main-paper figures from frozen v4 artifacts only.

The script performs no retrieval, SPP fitting, QLIP solve, generation, or SCA
evaluation. Every structure panel is derived from an existing raw/generated or
retrieved CIF whose SHA-256 is checked before and after rendering.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from ase.data import covalent_radii
from ase.data.colors import jmol_colors
from ase.neighborlist import natural_cutoffs, neighbor_list
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image
from pymatgen.core import Structure
from pymatgen.io.ase import AseAtomsAdaptor


ROOT = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
RESULTS = ROOT / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed" / "results"
WORKFLOW = RESULTS / "paper_workflow_example"
OUTPUT = RESULTS / "paper_figures"
FIGURE_1_DIR = OUTPUT / "figure_1_workflow"
FIGURE_2_DIR = OUTPUT / "figure_2_gallery"
RENDERS = FIGURE_2_DIR / "renders"

FIGURE_1_PDF = FIGURE_1_DIR / "FIGURE_1_NATI2O4_WORKFLOW.pdf"
FIGURE_1_PNG = FIGURE_1_DIR / "FIGURE_1_NATI2O4_WORKFLOW.png"
FIGURE_2_PDF = FIGURE_2_DIR / "FIGURE_2_GENERATED_CRYSTAL_GALLERY.pdf"
FIGURE_2_PNG = FIGURE_2_DIR / "FIGURE_2_GENERATED_CRYSTAL_GALLERY.png"

NAVY = "#173B57"
BLUE = "#2C6E9F"
TEAL = "#258B87"
GOLD = "#D39B2A"
GREEN = "#34865A"
RED = "#B64A4A"
INK = "#18252E"
MUTED = "#60717D"
GRID = "#DCE4E8"
CARD = "#F6F8F9"

CAMERA_AZIMUTH_DEG = 36.0
CAMERA_ELEVATION_DEG = 22.0
RENDERER = (
    "pymatgen Structure.from_file + pymatgen AseAtomsAdaptor + ASE "
    "natural_cutoffs/Jmol colours + deterministic Matplotlib orthographic projection"
)


@dataclass(frozen=True)
class GalleryItem:
    panel: int
    family: str
    formula: str
    experiment_id: str


GALLERY = (
    GalleryItem(1, "layered", "Na3Ni2O5", "layered-repaired-021"),
    GalleryItem(2, "layered", "Na4Mg(NiO2)5", "layered-repaired-013"),
    GalleryItem(3, "layered", "NaV2O5", "layered-repaired-020"),
    GalleryItem(4, "layered", "Li2FeO3", "layered-repaired-041"),
    GalleryItem(5, "spinel", "Mn2NiO4", "spinel-repaired-041"),
    GalleryItem(6, "spinel", "Zn(IrO2)2", "spinel-repaired-015"),
    GalleryItem(7, "spinel", "NaMn2O4", "spinel-repaired-040"),
    GalleryItem(8, "spinel", "NaTi2O4", "spinel-repaired-046"),
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "pass"}


def formula_mathtext(formula: str) -> str:
    return formula.translate(str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"))


def repeat_rule(site_count: int) -> tuple[int, int, int]:
    if site_count <= 8:
        return (2, 2, 2)
    if site_count <= 16:
        return (2, 2, 1)
    return (1, 1, 1)


def rotation_matrix() -> np.ndarray:
    az = math.radians(CAMERA_AZIMUTH_DEG)
    el = math.radians(CAMERA_ELEVATION_DEG)
    rz = np.asarray([
        [math.cos(az), -math.sin(az), 0.0],
        [math.sin(az), math.cos(az), 0.0],
        [0.0, 0.0, 1.0],
    ])
    rx = np.asarray([
        [1.0, 0.0, 0.0],
        [0.0, math.cos(el), -math.sin(el)],
        [0.0, math.sin(el), math.cos(el)],
    ])
    return rx @ rz


def cell_segments(cell: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    corners = {
        bits: bits[0] * cell[0] + bits[1] * cell[1] + bits[2] * cell[2]
        for bits in (
            (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1),
            (1, 1, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1),
        )
    }
    segments = []
    for bits, start in corners.items():
        for axis in range(3):
            other = list(bits)
            other[axis] += 1
            key = tuple(other)
            if key in corners:
                segments.append((start, corners[key]))
    return segments


def draw_structure(
    ax: Axes,
    cif_path: Path,
    *,
    show_cell: bool = True,
    atom_scale: float = 1.0,
) -> dict[str, Any]:
    structure = Structure.from_file(cif_path)
    repeat = repeat_rule(len(structure))
    atoms = AseAtomsAdaptor.get_atoms(structure).repeat(repeat)
    atoms.set_pbc(False)
    positions = np.asarray(atoms.get_positions(), dtype=float)
    cell = np.asarray(atoms.get_cell(), dtype=float)
    center = 0.5 * np.sum(cell, axis=0)
    rotated = (positions - center) @ rotation_matrix().T
    projected = rotated[:, :2]
    depth = rotated[:, 2]

    cutoffs = natural_cutoffs(atoms, mult=1.12)
    left, right = neighbor_list("ij", atoms, cutoffs, self_interaction=False)
    bonds = sorted(
        {(int(i), int(j)) for i, j in zip(left, right, strict=True) if int(i) < int(j)},
        key=lambda pair: float((depth[pair[0]] + depth[pair[1]]) / 2.0),
    )
    for i, j in bonds:
        ax.plot(
            projected[[i, j], 0], projected[[i, j], 1],
            color="#85939B", linewidth=0.75, alpha=0.68, zorder=1,
            solid_capstyle="round",
        )

    if show_cell:
        for start, end in cell_segments(cell):
            values = (np.asarray([start, end]) - center) @ rotation_matrix().T
            ax.plot(
                values[:, 0], values[:, 1], color="#52656F", linewidth=0.65,
                alpha=0.56, linestyle=(0, (2.2, 2.2)), zorder=2,
            )

    numbers = np.asarray(atoms.get_atomic_numbers(), dtype=int)
    count_factor = min(1.2, (48.0 / max(len(atoms), 1)) ** 0.22)
    order = np.argsort(depth)
    for index in order:
        number = numbers[index]
        radius = float(covalent_radii[number] or 1.0)
        size = atom_scale * count_factor * (62.0 + 62.0 * radius ** 1.45)
        ax.scatter(
            [projected[index, 0]], [projected[index, 1]], s=size,
            color=jmol_colors[number], edgecolors="white", linewidths=0.62,
            zorder=3 + float(depth[index] - depth.min()) / max(float(np.ptp(depth)), 1e-8),
        )
        ax.scatter(
            [projected[index, 0] - 0.035], [projected[index, 1] + 0.035],
            s=size * 0.18, color="white", alpha=0.26, edgecolors="none", zorder=5,
        )

    all_points = projected
    if show_cell:
        corners = []
        for start, end in cell_segments(cell):
            corners.extend((start, end))
        corner_values = (np.asarray(corners) - center) @ rotation_matrix().T
        all_points = np.vstack((projected, corner_values[:, :2]))
    xmin, ymin = np.min(all_points, axis=0)
    xmax, ymax = np.max(all_points, axis=0)
    span = max(float(xmax - xmin), float(ymax - ymin), 1.0)
    margin = 0.10 * span
    ax.set_xlim((xmin + xmax) / 2.0 - span / 2.0 - margin, (xmin + xmax) / 2.0 + span / 2.0 + margin)
    ax.set_ylim((ymin + ymax) / 2.0 - span / 2.0 - margin, (ymin + ymax) / 2.0 + span / 2.0 + margin)
    ax.set_aspect("equal")
    ax.set_axis_off()
    return {
        "site_count": len(structure),
        "displayed_atom_count": len(atoms),
        "repeat": "x".join(str(value) for value in repeat),
        "bond_count": len(bonds),
        "camera_azimuth_deg": CAMERA_AZIMUTH_DEG,
        "camera_elevation_deg": CAMERA_ELEVATION_DEG,
    }


def add_card(ax: Axes, *, facecolor: str = CARD) -> None:
    ax.set_axis_off()
    ax.add_patch(FancyBboxPatch(
        (0.0, 0.0), 1.0, 1.0, transform=ax.transAxes,
        boxstyle="round,pad=0.018,rounding_size=0.025",
        linewidth=0.75, edgecolor=GRID, facecolor=facecolor, zorder=-10,
        clip_on=False,
    ))


def panel_heading(ax: Axes, letter: str, title: str) -> None:
    ax.text(0.0, 1.04, letter, transform=ax.transAxes, fontsize=10.5,
            fontweight="bold", color=BLUE, va="bottom")
    ax.text(0.12, 1.04, title, transform=ax.transAxes, fontsize=9.2,
            fontweight="bold", color=INK, va="bottom")


def curve_plot(ax: Axes, path: Path, *, pair: str, source_label: str) -> dict[str, Any]:
    rows = read_csv(path)
    x = np.asarray([float(row["distance_A"]) for row in rows])
    request = np.asarray([float(row["request_component"]) for row in rows])
    global_component = np.asarray([float(row["global_component"]) for row in rows])
    final = np.asarray([float(row["final_potential"]) for row in rows])
    if np.any(np.abs(request) > 1e-14):
        ax.plot(x, request, color=TEAL, linewidth=1.15, linestyle=(0, (3, 2)), label="request")
    ax.plot(x, global_component, color=GOLD, linewidth=1.15, label="global")
    ax.plot(x, final, color=NAVY, linewidth=1.15, linestyle="--", label="final")
    ax.set_yscale("symlog", linthresh=0.02, linscale=0.8)
    ax.set_xlim(float(x.min()), float(x.max()))
    ax.grid(True, color=GRID, linewidth=0.42, alpha=0.8)
    ax.tick_params(labelsize=6.5, colors=MUTED, length=2)
    for spine in ax.spines.values():
        spine.set_color("#B8C5CB")
        spine.set_linewidth(0.6)
    ax.set_xlabel("Distance (Å)", fontsize=7.0, color=INK, labelpad=1.5)
    ax.set_title(f"{pair}\n{source_label}", fontsize=8.0, fontweight="bold", color=INK, pad=4)
    ax.legend(frameon=False, fontsize=5.9, loc="upper right", handlelength=1.7, borderaxespad=0.2)
    return {
        "source_path": str(path.resolve()),
        "source_sha256": sha256(path),
        "row_count": len(rows),
        "request_nonzero": bool(np.any(np.abs(request) > 1e-14)),
        "distance_min": float(x.min()),
        "distance_max": float(x.max()),
        "axis_scale": "symmetric_log_linthresh_0.02",
        "y_axis_label": "Weighted SPP value (unit not specified by persisted POT contract)",
    }


def draw_grid_icon(ax: Axes) -> None:
    points = np.asarray([(i, j, k) for i in range(4) for j in range(4) for k in range(4)], dtype=float)
    points -= 1.5
    rotated = points @ rotation_matrix().T
    order = np.argsort(rotated[:, 2])
    ax.scatter(
        rotated[order, 0], rotated[order, 1], s=6.5,
        c=np.linspace(0.25, 0.85, len(points))[order], cmap="Blues",
        edgecolors="none", alpha=0.88,
    )
    ax.set_xlim(-3.1, 3.1)
    ax.set_ylim(-2.7, 2.7)
    ax.set_aspect("equal")
    ax.set_axis_off()


def add_flow_arrows(fig: Figure, boxes: list[Any]) -> None:
    for left, right in zip(boxes, boxes[1:]):
        start = (left.x1 + 0.004, 0.48)
        end = (right.x0 - 0.004, 0.48)
        fig.add_artist(FancyArrowPatch(
            start, end, transform=fig.transFigure, arrowstyle="-|>",
            mutation_scale=11, linewidth=1.0, color="#80909A",
            shrinkA=0, shrinkB=0, clip_on=False,
        ))


def render_figure_1(source_hashes: dict[Path, str]) -> dict[str, Any]:
    request = read_json(WORKFLOW / "REQUEST.json")
    solver = read_json(WORKFLOW / "QLIP_SOLVER_SUMMARY.json")
    sca = read_json(WORKFLOW / "SCA_SUMMARY.json")
    reference = read_json(WORKFLOW / "REFERENCE_COMPARISON.json")
    neighbours = [row for row in read_csv(WORKFLOW / "RETRIEVAL_NEIGHBOURS.csv") if truth(row["ILLUSTRATIVE_NEIGHBOUR"])]
    if [row["formula"] for row in neighbours] != ["Na2WO4", "NaCr2O4", "NaV2O4"]:
        raise RuntimeError("FIGURE_1_NEIGHBOUR_SELECTION_MISMATCH")
    generated = WORKFLOW / "GENERATED_RAW.cif"
    if sha256(generated) != solver["generated_cif_sha256"]:
        raise RuntimeError("FIGURE_1_GENERATED_HASH_MISMATCH")
    if solver["terminal_status"] != "OPTIMAL" or int(solver["native_grid_site_count"]) != 64:
        raise RuntimeError("FIGURE_1_SOLVER_FACT_MISMATCH")
    if sca["topology_status"] != "PASS" or int(sca["num_bad_contacts"]) != 0:
        raise RuntimeError("FIGURE_1_SCA_FACT_MISMATCH")

    fig = plt.figure(figsize=(14.8, 5.35), facecolor="white")
    outer = fig.add_gridspec(
        1, 6, width_ratios=(1.18, 2.18, 2.65, 1.42, 1.70, 1.49),
        left=0.025, right=0.985, top=0.84, bottom=0.12, wspace=0.42,
    )
    fig.suptitle("Traceable scaffold-free generation of NaTi$_2$O$_4$", fontsize=15.0,
                 fontweight="bold", color=INK, y=0.965)
    fig.text(0.5, 0.905, "Research intent to retrieval evidence, pair guidance, integer-programming CSP, and independent validation",
             ha="center", fontsize=8.2, color=MUTED)

    request_ax = fig.add_subplot(outer[0, 0])
    add_card(request_ax, facecolor="#F4F8FB")
    panel_heading(request_ax, "A", "Request")
    request_ax.text(0.5, 0.76, "NaTi$_2$O$_4$", transform=request_ax.transAxes,
                    ha="center", va="center", fontsize=16, fontweight="bold", color=NAVY)
    request_ax.text(0.5, 0.57, "spinel oxide", transform=request_ax.transAxes,
                    ha="center", fontsize=9.2, color=INK)
    request_ax.text(0.5, 0.42, "scaffold-free", transform=request_ax.transAxes,
                    ha="center", fontsize=8.3, fontweight="bold", color=TEAL)
    request_ax.text(0.5, 0.22, request["text_request"], transform=request_ax.transAxes,
                    ha="center", va="center", fontsize=7.2, color=MUTED, wrap=True)

    neighbour_outer = fig.add_subplot(outer[0, 1])
    neighbour_outer.set_axis_off()
    panel_heading(neighbour_outer, "B", "Retrieved evidence")
    neighbour_grid = outer[0, 1].subgridspec(3, 1, hspace=0.20)
    neighbour_meta = []
    for index, row in enumerate(neighbours):
        ax = fig.add_subplot(neighbour_grid[index, 0])
        render_meta = draw_structure(ax, Path(row["source_cif_path"]), atom_scale=0.62)
        ax.text(0.02, 0.97, formula_mathtext(row["formula"]), transform=ax.transAxes,
                va="top", fontsize=8.4, fontweight="bold", color=INK)
        source_id = str(row["source_id"]).removesuffix(".cif")
        ax.text(0.98, 0.97, f"r{row['rank']}  {float(row['similarity_score']):.3f}",
                transform=ax.transAxes, va="top", ha="right", fontsize=6.7, color=BLUE)
        ax.text(0.02, 0.04, source_id, transform=ax.transAxes, va="bottom",
                fontsize=6.1, color=MUTED)
        source_path = Path(row["source_cif_path"])
        neighbour_meta.append({**row, **render_meta, "source_cif_sha256": sha256(source_path)})

    spp_outer = fig.add_subplot(outer[0, 2])
    spp_outer.set_axis_off()
    panel_heading(spp_outer, "C", "Pair SPPs")
    spp_grid = outer[0, 2].subgridspec(1, 2, wspace=0.35)
    oo_ax = fig.add_subplot(spp_grid[0, 0])
    oti_ax = fig.add_subplot(spp_grid[0, 1])
    oo_meta = curve_plot(oo_ax, WORKFLOW / "spp_curves" / "O-O.csv", pair="O-O", source_label="request + global")
    oti_meta = curve_plot(oti_ax, WORKFLOW / "spp_curves" / "O-Ti.csv", pair="O-Ti", source_label="global regulator")
    oo_ax.set_ylabel("Weighted SPP value", fontsize=7.0, color=INK, labelpad=1)
    oti_ax.text(0.98, 0.04, "final = global", transform=oti_ax.transAxes,
                ha="right", va="bottom", fontsize=5.8, color=MUTED)
    spp_outer.text(0.5, -0.105, "symmetric-log display; tabulated values unchanged",
                   transform=spp_outer.transAxes, ha="center", fontsize=5.9, color=MUTED)

    qlip_ax = fig.add_subplot(outer[0, 3])
    add_card(qlip_ax, facecolor="#F7F8FC")
    panel_heading(qlip_ax, "D", "QLIP CSP")
    grid_ax = qlip_ax.inset_axes([0.12, 0.56, 0.76, 0.35])
    draw_grid_icon(grid_ax)
    qlip_ax.text(0.5, 0.51, "4$^3$ = 64 sites", transform=qlip_ax.transAxes,
                 ha="center", fontsize=9.3, fontweight="bold", color=NAVY)
    qlip_ax.text(0.5, 0.37, "min  pair-SPP terms", transform=qlip_ax.transAxes,
                 ha="center", fontsize=7.3, color=INK)
    qlip_ax.text(0.5, 0.27, "exact species counts", transform=qlip_ax.transAxes,
                 ha="center", fontsize=6.8, color=MUTED)
    qlip_ax.text(0.5, 0.19, "one state per site", transform=qlip_ax.transAxes,
                 ha="center", fontsize=6.8, color=MUTED)
    qlip_ax.text(0.5, 0.095, solver["terminal_status"], transform=qlip_ax.transAxes,
                 ha="center", fontsize=8.5, fontweight="bold", color=GREEN)
    qlip_ax.text(0.5, 0.025, f"obj. {float(solver['solver_objective']):.4f}  |  {float(solver['runtime_seconds']):.3f} s",
                 transform=qlip_ax.transAxes, ha="center", fontsize=6.3, color=MUTED)

    generated_ax = fig.add_subplot(outer[0, 4])
    panel_heading(generated_ax, "E", "Generated crystal")
    generated_meta = draw_structure(generated_ax, generated, atom_scale=0.94)
    generated_ax.text(0.5, 0.025, "QLIP-generated NaTi$_2$O$_4$",
                      transform=generated_ax.transAxes, ha="center", fontsize=8.2,
                      fontweight="bold", color=INK)
    generated_ax.text(0.5, -0.03, "raw CIF  |  OPTIMAL", transform=generated_ax.transAxes,
                      ha="center", fontsize=6.6, color=MUTED)

    sca_ax = fig.add_subplot(outer[0, 5])
    add_card(sca_ax, facecolor="#F5FAF7")
    panel_heading(sca_ax, "F", "SCA validation")
    sca_ax.text(0.5, 0.78, "TOPOLOGY PASS", transform=sca_ax.transAxes,
                ha="center", fontsize=10.2, fontweight="bold", color=GREEN)
    metrics = (
        ("CIF / composition", "valid"),
        ("Bad contacts", "0"),
        ("Min. distance", f"{float(sca['min_distance']):.3f} Å"),
        ("Held-out match", "No" if not reference["structure_match"] else "Yes"),
    )
    for index, (label, value) in enumerate(metrics):
        y = 0.59 - index * 0.13
        sca_ax.text(0.08, y, label, transform=sca_ax.transAxes, fontsize=6.8, color=MUTED)
        sca_ax.text(0.92, y, value, transform=sca_ax.transAxes, fontsize=7.5,
                    ha="right", fontweight="bold", color=INK)
        if index < len(metrics) - 1:
            sca_ax.plot([0.08, 0.92], [y - 0.045, y - 0.045], transform=sca_ax.transAxes,
                        color=GRID, linewidth=0.55)
    sca_ax.text(0.5, 0.055, "post-generation only", transform=sca_ax.transAxes,
                ha="center", fontsize=6.1, color=TEAL)

    stage_boxes = [
        request_ax.get_position(), neighbour_outer.get_position(), spp_outer.get_position(),
        qlip_ax.get_position(), generated_ax.get_position(), sca_ax.get_position(),
    ]
    add_flow_arrows(fig, stage_boxes)
    fig.savefig(FIGURE_1_PDF, facecolor="white", metadata={"Title": "NaTi2O4 traceable workflow"})
    fig.savefig(FIGURE_1_PNG, dpi=320, facecolor="white")
    plt.close(fig)

    source_rows = [
        {"panel": "A", "role": "request", "source_path": str((WORKFLOW / "REQUEST.json").resolve()), "sha256": source_hashes[WORKFLOW / "REQUEST.json"]},
        *({"panel": "B", "role": f"retrieved_neighbour_{index}", "source_path": row["source_cif_path"], "sha256": row["source_cif_sha256"]} for index, row in enumerate(neighbour_meta, 1)),
        {"panel": "C", "role": "O-O_curve", "source_path": oo_meta["source_path"], "sha256": oo_meta["source_sha256"]},
        {"panel": "C", "role": "O-Ti_curve", "source_path": oti_meta["source_path"], "sha256": oti_meta["source_sha256"]},
        {"panel": "D", "role": "solver_summary", "source_path": str((WORKFLOW / "QLIP_SOLVER_SUMMARY.json").resolve()), "sha256": source_hashes[WORKFLOW / "QLIP_SOLVER_SUMMARY.json"]},
        {"panel": "E", "role": "raw_generated_cif", "source_path": str(generated.resolve()), "sha256": sha256(generated)},
        {"panel": "F", "role": "sca_summary", "source_path": str((WORKFLOW / "SCA_SUMMARY.json").resolve()), "sha256": source_hashes[WORKFLOW / "SCA_SUMMARY.json"]},
        {"panel": "F", "role": "reference_comparison", "source_path": str((WORKFLOW / "REFERENCE_COMPARISON.json").resolve()), "sha256": source_hashes[WORKFLOW / "REFERENCE_COMPARISON.json"]},
    ]
    write_csv(FIGURE_1_DIR / "FIGURE_1_SOURCE_ARTIFACTS.csv", source_rows, ("panel", "role", "source_path", "sha256"))
    facts = [
        "# Figure 1 caption facts", "",
        "- Target: NaTi2O4", "- Experiment ID: spinel-repaired-046",
        f"- Actual request: {request['text_request']}",
        "- Generation mode: scaffold-free", "",
        "## Illustrative retrieved neighbours", "",
        *(f"- {row['formula']}: {str(row['source_id']).removesuffix('.cif')}; retrieval rank {row['rank']}; score {row['similarity_score']}" for row in neighbours),
        "", "## Pair SPPs", "",
        "- O-O: request-specific component plus frozen global regulator; local weight 1.0; global weight 2.0.",
        "- O-Ti: global-regulator support; request component is identically zero; local weight 0.0; global weight 2.0.",
        "", "## QLIP", "",
        f"- Grid: {solver['native_grid_density']}^3 = {solver['native_grid_site_count']} candidate sites",
        f"- Status: {solver['terminal_status']}", f"- Objective: {solver['solver_objective']}",
        f"- Runtime: {solver['runtime_seconds']} s", "", "## Validation", "",
        f"- SCA topology: {sca['topology_status']}", f"- Bad contacts: {sca['num_bad_contacts']}",
        f"- Minimum distance: {sca['min_distance']} angstrom", f"- Generated CIF SHA-256: {sha256(generated)}",
        f"- Held-out reference match: {'Yes' if reference['structure_match'] else 'No'}",
        "- Reference data were used only after generation for comparison.", "",
    ]
    (FIGURE_1_DIR / "FIGURE_1_CAPTION_FACTS.md").write_text("\n".join(facts), encoding="utf-8")
    write_json(FIGURE_1_DIR / "FIGURE_1_RENDER_MANIFEST.json", {
        "renderer": RENDERER,
        "camera": {"azimuth_deg": CAMERA_AZIMUTH_DEG, "elevation_deg": CAMERA_ELEVATION_DEG},
        "generated_structure": generated_meta,
        "neighbours": neighbour_meta,
        "curves": {"O-O": oo_meta, "O-Ti": oti_meta},
        "pdf": str(FIGURE_1_PDF.resolve()), "png": str(FIGURE_1_PNG.resolve()),
    })
    return {"pdf": FIGURE_1_PDF, "png": FIGURE_1_PNG, "source_rows": source_rows}


def render_individual(path: Path, item: GalleryItem, destination: Path) -> dict[str, Any]:
    fig, ax = plt.subplots(figsize=(4.5, 4.1), facecolor="white")
    meta = draw_structure(ax, path, atom_scale=1.18)
    ax.set_title(formula_mathtext(item.formula), fontsize=15, fontweight="bold", color=INK, pad=4)
    fig.savefig(destination, dpi=400, facecolor="white", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return meta


def render_figure_2() -> dict[str, Any]:
    manifest = {row["experiment_id"]: row for row in read_csv(RESULTS / "PAPER_GENERATED_CIF_MANIFEST.csv")}
    duplicate = {row["experiment_id"]: row for row in read_csv(RESULTS / "GENERATED_CIF_DUPLICATE_AUDIT.csv")}
    result_rows = {row["experiment_id"]: row for row in read_csv(RESULTS / "PAPER_SPP_ONLY_100_RESULTS.csv")}
    selected_groups: set[str] = set()
    rows: list[dict[str, Any]] = []
    source_before: dict[Path, str] = {}
    for item in GALLERY:
        if item.experiment_id not in manifest or item.experiment_id not in duplicate:
            raise RuntimeError(f"GALLERY_EXPERIMENT_MISSING: {item.experiment_id}")
        row = manifest[item.experiment_id]
        result = result_rows[item.experiment_id]
        source = Path(row["candidate_original_path"])
        actual_hash = sha256(source)
        group = duplicate[item.experiment_id]["structurematcher_group"]
        checks = {
            "candidate_generated": truth(result["candidate_generated"]),
            "candidate_valid": truth(result["candidate_valid"]),
            "source_exists": source.is_file(),
            "hash_matches_manifest": actual_hash == row["candidate_sha256"],
            "no_scaffold": not truth(result["SCAFFOLD_USED"]),
            "no_leakage": truth(result["NO_TARGET_LEAKAGE"]),
            "topology_pass": row["family_topology_status"] == "PASS",
            "new_diversity_group": group not in selected_groups,
            "formula_matches": row["formula"] == item.formula,
        }
        if not all(checks.values()):
            raise RuntimeError(f"GALLERY_PREFLIGHT_FAILED: {item.experiment_id}: {checks}")
        selected_groups.add(group)
        source_before[source] = actual_hash
        rows.append({
            "panel": item.panel, "family": item.family, "formula": item.formula,
            "experiment_id": item.experiment_id, "qlip_status": row["qlip_status"],
            "topology": row["family_topology_status"], "source_cif": str(source.resolve()),
            "source_cif_sha256": actual_hash, "duplicate_group": group,
        })
    if len(selected_groups) != 8:
        raise RuntimeError("GALLERY_DIVERSITY_GROUP_COUNT_MISMATCH")

    RENDERS.mkdir(parents=True, exist_ok=True)
    for item, row in zip(GALLERY, rows, strict=True):
        safe_formula = re.sub(r"[^A-Za-z0-9]+", "", item.formula)
        render_path = RENDERS / f"{item.panel:02d}_{safe_formula}_{item.experiment_id}.png"
        render_meta = render_individual(Path(row["source_cif"]), item, render_path)
        row.update({"render_path": str(render_path.resolve()), **render_meta})

    fig = plt.figure(figsize=(12.2, 6.8), facecolor="white")
    grid = fig.add_gridspec(2, 4, left=0.075, right=0.985, top=0.88, bottom=0.08,
                            wspace=0.13, hspace=0.31)
    fig.suptitle("Actual scaffold-free crystals generated by QLIP", fontsize=16,
                 fontweight="bold", color=INK, y=0.965)
    fig.text(0.53, 0.912, "Raw generated CIFs; deterministic camera and rendering rules",
             ha="center", fontsize=8.3, color=MUTED)
    fig.text(0.018, 0.655, "Layered\noxides", ha="left", va="center", fontsize=9.2,
             fontweight="bold", color=BLUE, rotation=90)
    fig.text(0.018, 0.255, "Spinel\noxides", ha="left", va="center", fontsize=9.2,
             fontweight="bold", color=TEAL, rotation=90)
    for item, row in zip(GALLERY, rows, strict=True):
        ax = fig.add_subplot(grid[(item.panel - 1) // 4, (item.panel - 1) % 4])
        draw_structure(ax, Path(row["source_cif"]), atom_scale=0.91)
        ax.text(0.5, -0.02, formula_mathtext(item.formula), transform=ax.transAxes,
                ha="center", va="top", fontsize=11.5, fontweight="bold", color=INK)
        status = "FTL" if row["qlip_status"] == "FEASIBLE_TIME_LIMIT" else row["qlip_status"]
        ax.text(0.5, -0.115, f"{status} · topology PASS", transform=ax.transAxes,
                ha="center", va="top", fontsize=7.2, color=MUTED)
        ax.text(0.015, 0.98, chr(96 + item.panel), transform=ax.transAxes,
                va="top", fontsize=9.5, fontweight="bold", color=BLUE)
    fig.savefig(FIGURE_2_PDF, facecolor="white", metadata={"Title": "Generated crystal gallery"})
    fig.savefig(FIGURE_2_PNG, dpi=320, facecolor="white")
    plt.close(fig)

    for source, digest in source_before.items():
        if sha256(source) != digest:
            raise RuntimeError(f"GALLERY_SOURCE_CIF_MUTATED: {source}")
    fields = (
        "panel", "family", "formula", "experiment_id", "qlip_status", "topology",
        "source_cif", "source_cif_sha256", "render_path", "duplicate_group",
        "site_count", "displayed_atom_count", "repeat", "bond_count",
        "camera_azimuth_deg", "camera_elevation_deg",
    )
    write_csv(FIGURE_2_DIR / "FIGURE_2_GALLERY_MANIFEST.csv", rows, fields)
    write_json(FIGURE_2_DIR / "FIGURE_2_RENDER_MANIFEST.json", {
        "renderer": RENDERER,
        "camera": {"azimuth_deg": CAMERA_AZIMUTH_DEG, "elevation_deg": CAMERA_ELEVATION_DEG},
        "replication_rule": "site_count <= 8: 2x2x2; <= 16: 2x2x1; otherwise 1x1x1",
        "items": rows, "pdf": str(FIGURE_2_PDF.resolve()), "png": str(FIGURE_2_PNG.resolve()),
    })
    return {"pdf": FIGURE_2_PDF, "png": FIGURE_2_PNG, "rows": rows}


def png_dpi(path: Path) -> tuple[float, float]:
    with Image.open(path) as image:
        dpi = image.info.get("dpi", (0.0, 0.0))
        return float(dpi[0]), float(dpi[1])


def main() -> None:
    FIGURE_1_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_2_DIR.mkdir(parents=True, exist_ok=True)
    fixed_sources = (
        WORKFLOW / "REQUEST.json", WORKFLOW / "QLIP_SOLVER_SUMMARY.json",
        WORKFLOW / "SCA_SUMMARY.json", WORKFLOW / "REFERENCE_COMPARISON.json",
        WORKFLOW / "GENERATED_RAW.cif", WORKFLOW / "spp_curves" / "O-O.csv",
        WORKFLOW / "spp_curves" / "O-Ti.csv",
    )
    source_hashes = {path: sha256(path) for path in fixed_sources}
    figure_1 = render_figure_1(source_hashes)
    figure_2 = render_figure_2()
    if any(sha256(path) != digest for path, digest in source_hashes.items()):
        raise RuntimeError("FIGURE_1_SOURCE_ARTIFACT_MUTATION")
    dpi = {str(path): png_dpi(path) for path in (FIGURE_1_PNG, FIGURE_2_PNG)}
    if any(min(values) < 300.0 for values in dpi.values()):
        raise RuntimeError(f"FINAL_PNG_DPI_TOO_LOW: {dpi}")
    summary = {
        "schema_version": "spp_only_oxide_main_paper_figures.v1",
        "renderer": RENDERER,
        "figure_1": {"pdf": str(figure_1["pdf"]), "png": str(figure_1["png"])},
        "figure_2": {"pdf": str(figure_2["pdf"]), "png": str(figure_2["png"])},
        "gallery_render_count": len(list(RENDERS.glob("*.png"))),
        "final_png_dpi": dpi,
        "qlip_rerun": False, "retrieval_rerun": False, "spp_fit_rerun": False,
        "generation_rerun": False, "sca_rerun": False,
    }
    write_json(OUTPUT / "MAIN_PAPER_FIGURE_AUDIT.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
