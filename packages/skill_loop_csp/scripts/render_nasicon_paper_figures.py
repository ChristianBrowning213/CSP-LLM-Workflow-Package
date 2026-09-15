"""Render paper-facing NASICON workflow, polyhedral, channel, and SPP figures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from textwrap import fill

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection, PolyCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from pymatgen.core import Structure
from scipy.spatial import ConvexHull

from sok_llm_orchestrator.verification.nasicon_topology import DEFAULT_TOLERANCES


REPO_ROOT = Path(__file__).resolve().parents[1]
COLORS = {"Zr": "#188A9A", "Si": "#E69F00", "P": "#8C62AA", "Na": "#2878B5", "O": "#C7CDD4"}


def _polyhedra(structure: Structure):
    specs = {"Zr": (6, DEFAULT_TOLERANCES["zr_o_cutoff_angstrom"]), "Si": (4, DEFAULT_TOLERANCES["si_o_cutoff_angstrom"]), "P": (4, DEFAULT_TOLERANCES["p_o_cutoff_angstrom"])}
    for site in structure:
        symbol = site.specie.symbol
        if symbol not in specs:
            continue
        expected, cutoff = specs[symbol]
        oxygen = [item for item in structure.get_neighbors(site, cutoff) if item.specie.symbol == "O"]
        if len(oxygen) != expected:
            continue
        vertices = np.asarray([item.coords for item in oxygen], dtype=float)
        hull = ConvexHull(vertices)
        yield symbol, site.coords, vertices, [vertices[face] for face in hull.simplices]


def _style_3d(ax, *, zoom: float = 1.45):
    ax.set_axis_off()
    ax.set_box_aspect((1, 1, 0.8), zoom=zoom)
    ax.view_init(elev=20, azim=38)


def _draw_polyhedral(ax, structure: Structure, *, show_na: bool = True, alpha: float = 0.27):
    for symbol, center, vertices, faces in _polyhedra(structure):
        ax.add_collection3d(Poly3DCollection(faces, facecolor=COLORS[symbol], edgecolor=COLORS[symbol], linewidth=0.45, alpha=alpha))
        ax.scatter(*center, color=COLORS[symbol], s=11, depthshade=False)
    if show_na:
        na = np.asarray([site.coords for site in structure if site.specie.symbol == "Na"])
        if len(na):
            ax.scatter(na[:, 0], na[:, 1], na[:, 2], color=COLORS["Na"], edgecolors="white", linewidths=0.35, s=34, depthshade=False)
    corners = np.asarray([structure.lattice.get_cartesian_coords(point) for point in ([0,0,0],[1,0,0],[0,1,0],[0,0,1],[1,1,0],[1,0,1],[0,1,1],[1,1,1])])
    ax.auto_scale_xyz(corners[:, 0], corners[:, 1], corners[:, 2])
    _style_3d(ax)


def render_polyhedral_hero(structure: Structure, out: Path):
    fig = plt.figure(figsize=(10.0, 5.6), facecolor="white")
    ax = fig.add_subplot(111, projection="3d")
    _draw_polyhedral(ax, structure, show_na=True, alpha=0.30)
    handles = [plt.Line2D([0], [0], marker="s" if key != "Na" else "o", linestyle="", color=value, markersize=8, label={"Zr":"ZrO₆ octahedra","Si":"SiO₄ tetrahedra","P":"PO₄ tetrahedra","Na":"Na sites"}[key]) for key, value in COLORS.items() if key != "O"]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(-0.02, 1.02), frameon=False, fontsize=9)
    ax.set_title("Ordered Na₃Zr₂Si₂PO₁₂ NASICON framework", fontsize=13, pad=2)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=320, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_channel_view(structure: Structure, out: Path):
    fig, ax = plt.subplots(figsize=(7.2, 6.2), facecolor="white")
    lattice = structure.lattice.matrix
    na_frac = np.asarray([site.frac_coords for site in structure if site.specie.symbol == "Na"])
    expanded = []
    labels = []
    for shift_a in (-1, 0, 1):
        for shift_b in (-1, 0, 1):
            for frac in na_frac:
                expanded.append(frac + [shift_a, shift_b, 0])
                labels.append((shift_a, shift_b))
    expanded = np.asarray(expanded)
    cart = expanded @ lattice
    segments = []
    cutoff = DEFAULT_TOLERANCES["na_na_channel_cutoff_angstrom"]
    for i in range(len(cart)):
        for j in range(i + 1, len(cart)):
            distance = np.linalg.norm(cart[i] - cart[j])
            if 0.1 < distance <= cutoff:
                segments.append([cart[i, :2], cart[j, :2]])
    framework_faces: dict[str, list[np.ndarray]] = {"Zr": [], "Si": [], "P": []}
    framework_edges: dict[str, list[list[np.ndarray]]] = {"Zr": [], "Si": [], "P": []}
    for symbol, _center, _vertices, faces in _polyhedra(structure):
        for shift_a in (-1, 0, 1):
            for shift_b in (-1, 0, 1):
                shift = shift_a * lattice[0] + shift_b * lattice[1]
                for face in faces:
                    projected = (face + shift)[:, :2]
                    framework_faces[symbol].append(projected)
                    framework_edges[symbol].extend(
                        [[projected[index], projected[(index + 1) % len(projected)]] for index in range(len(projected))]
                    )
    for symbol in ("Zr", "Si", "P"):
        ax.add_collection(PolyCollection(
            framework_faces[symbol], facecolors=COLORS[symbol], edgecolors="none", alpha=0.055, zorder=0
        ))
        ax.add_collection(LineCollection(
            framework_edges[symbol], colors=COLORS[symbol], linewidths=0.45, alpha=0.16, zorder=1
        ))
    ax.add_collection(LineCollection(segments, colors=COLORS["Na"], linewidths=1.0, alpha=0.38, zorder=3))
    central = np.asarray([label == (0, 0) for label in labels])
    ax.scatter(cart[~central, 0], cart[~central, 1], s=12, color=COLORS["Na"], alpha=0.20, zorder=4)
    ax.scatter(cart[central, 0], cart[central, 1], s=54, color=COLORS["Na"], edgecolors="white", linewidths=0.6, label="Na sites in central cell", zorder=5)
    origin = np.zeros(2); a = lattice[0, :2]; b = lattice[1, :2]
    polygon = np.asarray([origin, a, a+b, b, origin])
    ax.plot(polygon[:,0], polygon[:,1], color="#40464D", lw=1.2, label="unit-cell projection")
    ax.set_aspect("equal"); ax.set_axis_off()
    framework_handles = [
        plt.Line2D([0], [0], marker="s", linestyle="", color=COLORS[symbol], alpha=0.45, markersize=7, label=label)
        for symbol, label in (("Zr", "ZrO₆ framework"), ("Si", "SiO₄ framework"), ("P", "PO₄ framework"))
    ]
    handles, legend_labels = ax.get_legend_handles_labels()
    ax.legend(handles=handles + framework_handles, labels=legend_labels + [item.get_label() for item in framework_handles], frameon=False, loc="upper right", fontsize=8)
    ax.set_title("Geometric Na-site connectivity proxy viewed along c", fontsize=13)
    ax.text(0.01, 0.02, f"Edges connect periodic Na sites within {cutoff:.2f} Å; no conductivity is inferred.", transform=ax.transAxes, fontsize=9, color="#4B5563")
    fig.tight_layout(); out.parent.mkdir(parents=True, exist_ok=True)
    for path in (out, out.with_suffix(".pdf"), out.with_suffix(".svg")):
        fig.savefig(path, dpi=320, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _pot_curve(root: Path, pair: str):
    path = root / pair / f"{pair}.POT"
    points = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) == 2:
                try: points.append((float(fields[0]), float(fields[1])))
                except ValueError: pass
    return np.asarray(points)


def render_spp_comparison(runs_root: Path, out: Path):
    pairs = ["Na-O", "O-Zr", "O-Si", "O-P"]
    fig, axes = plt.subplots(2, 2, figsize=(9.0, 6.3), sharex=True)
    styles = {"full": ("#188A9A", "full specialist"), "leave_target_out": ("#8C62AA", "leave-target-out")}
    for ax, pair in zip(axes.flat, pairs):
        for condition, (color, label) in styles.items():
            curve = _pot_curve(runs_root / condition / "row_specific_spp" / "spp_root", pair)
            if len(curve): ax.plot(curve[:,0], curve[:,1], color=color, lw=1.5, label=label)
        ax.set_title(pair); ax.grid(color="#D6DADE", linewidth=0.5, alpha=0.7); ax.set_ylabel("SPP score")
    axes[1,0].set_xlabel("distance (Å)"); axes[1,1].set_xlabel("distance (Å)")
    axes[0,0].legend(frameon=False, fontsize=8)
    fig.suptitle("Condition-specific NASICON statistical pair potentials", fontsize=13)
    fig.text(0.5, 0.01, "Curves are independently fitted and are not a cross-condition calibrated energy scale.", ha="center", fontsize=8.5)
    fig.tight_layout(rect=[0,0.035,1,0.96]); out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)


def render_workflow(structure: Structure, run_dir: Path, out: Path, *, spp_verdict: str):
    task = json.loads((run_dir / "task.json").read_text(encoding="utf-8"))
    retrieval = json.loads((run_dir / "retrieval.json").read_text(encoding="utf-8"))
    fig = plt.figure(figsize=(13.2, 7.2), facecolor="white")
    grid = fig.add_gridspec(2, 2, hspace=0.22, wspace=0.16)
    ax1 = fig.add_subplot(grid[0,0]); ax1.axis("off")
    ax1.text(0, 0.96, "1  Natural-language request", fontsize=12, weight="bold", va="top")
    ax1.text(0, 0.77, fill(task["natural_language_request"], 62), fontsize=10.2, va="top", linespacing=1.45)
    ax1.text(0, 0.18, "Ordered C2 scaffold • symmetry-closed Si/P orbit choice • 15 required pairs", fontsize=9, color="#4B5563")
    ax2 = fig.add_subplot(grid[0,1]); ax2.axis("off")
    ax2.text(0, 0.96, "2  Retrieved Crystal-DB evidence", fontsize=12, weight="bold", va="top")
    rows = retrieval["selected"][:8]
    for idx, row in enumerate(rows):
        ax2.text(0.02, 0.80-idx*0.085, f"{idx+1:>2}  {row.get('reduced_formula','?'):<20} {row.get('topology_tier') or 'broad chemistry'}", fontsize=8.7)
    ax2.text(0.02, 0.08, f"{retrieval['eligible_internal_spp_count']} CIFs eligible for internal SPP construction", fontsize=9, color="#4B5563")
    ax3 = fig.add_subplot(grid[1,0])
    for pair, color in (("O-Zr", COLORS["Zr"]),("O-Si", COLORS["Si"]),("O-P", COLORS["P"]),("Na-O", COLORS["Na"])):
        curve = _pot_curve(run_dir / "row_specific_spp" / "spp_root", pair)
        if len(curve): ax3.plot(curve[:,0], curve[:,1], lw=1.35, color=color, label=pair)
    ax3.set_title("3  Row-specific SPP curves (diagnostic)", loc="left", fontsize=12, weight="bold")
    ax3.set_xlabel("distance (Å)"); ax3.set_ylabel("SPP score"); ax3.grid(color="#D6DADE", lw=0.5); ax3.legend(frameon=False, ncol=2, fontsize=8)
    ax4 = fig.add_subplot(grid[1,1], projection="3d"); _draw_polyhedral(ax4, structure, show_na=True, alpha=0.32)
    ax4.set_title("4  QLIP-generated candidate", loc="left", fontsize=12, weight="bold")
    fig.text(0.5, 0.012, f"Final SPP verdict: {spp_verdict}. Curves are not a calibrated energy or quality comparison.", ha="center", fontsize=8.5, color="#4B5563")
    fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", default="full", choices=["full", "leave_target_out"])
    parser.add_argument("--runs-root", type=Path, default=REPO_ROOT / "runs" / "paper_nasicon_specialist")
    parser.add_argument("--figures-root", type=Path, default=REPO_ROOT / "figures" / "paper_nasicon")
    args = parser.parse_args()
    run_dir = args.runs_root / args.condition
    structure = Structure.from_file(run_dir / "qlip" / "solution.cif")
    render_polyhedral_hero(structure, args.figures_root / "nasicon_polyhedral_hero_final.png")
    render_channel_view(structure, args.figures_root / "nasicon_channel_view_final.png")
    render_workflow(structure, run_dir, args.figures_root / "nasicon_workflow_artifact_final.png", spp_verdict="DIAGNOSTIC_ONLY")
    render_spp_comparison(args.runs_root, REPO_ROOT / "artifacts" / "nasicon_comparison" / "NASICON_SPP_COMPARISON.png")
    print(json.dumps({"figures_root": str(args.figures_root), "condition": args.condition}, indent=2))


if __name__ == "__main__":
    main()
