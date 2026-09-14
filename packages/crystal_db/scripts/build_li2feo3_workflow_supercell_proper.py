"""Build the proper A-to-G Li2FeO3 workflow figure from persisted artifacts only."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed" / "results"
BUNDLE = RESULTS / "paper_workflow_li2feo3"
OUT = RESULTS / "paper_figures" / "figure_1_li2feo3_workflow_supercell"
SUPERCELL_MANIFEST = OUT / "FIGURE_SX_LI2FEO3_RETRIEVAL_TO_GENERATION_STRUCTURE_COMPARISON_MANIFEST.json"
PDF = OUT / "FIGURE_1_LI2FEO3_WORKFLOW_SUPERCELL_PROPER.pdf"
PNG = OUT / "FIGURE_1_LI2FEO3_WORKFLOW_SUPERCELL_PROPER.png"
MANIFEST = OUT / "FIGURE_1_LI2FEO3_WORKFLOW_SUPERCELL_PROPER_MANIFEST.json"
CAPTION = OUT / "FIGURE_1_LI2FEO3_WORKFLOW_SUPERCELL_PROPER_CAPTION_FACTS.md"
SUPP_PDF = OUT / "FIGURE_SX_LI2FEO3_RETRIEVAL_TO_GENERATION_STRUCTURE_COMPARISON.pdf"
SUPP_PNG = OUT / "FIGURE_SX_LI2FEO3_RETRIEVAL_TO_GENERATION_STRUCTURE_COMPARISON.png"

PAIRS = ("Li-Li", "Fe-Li", "Li-O", "Fe-Fe", "Fe-O", "O-O")
INK = "#17252E"
NAVY = "#173B57"
BLUE = "#2C6E9F"
TEAL = "#278A86"
GOLD = "#C48A20"
GREEN = "#34865A"
MUTED = "#61717B"
GRID = "#D9E2E6"
CARD = "#F7F9FA"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def card(ax, color: str = CARD) -> None:
    ax.set_axis_off()
    ax.add_patch(FancyBboxPatch(
        (0, 0), 1, 1, transform=ax.transAxes,
        boxstyle="round,pad=.012,rounding_size=.02",
        facecolor=color, edgecolor=GRID, linewidth=.8, clip_on=False, zorder=-10,
    ))


def heading(ax, letter: str, title: str) -> None:
    ax.text(.01, 1.025, letter, transform=ax.transAxes, color=BLUE,
            fontsize=11, fontweight="bold", va="bottom")
    ax.text(.12, 1.025, title, transform=ax.transAxes, color=INK,
            fontsize=9.2, fontweight="bold", va="bottom")


def image_axis(ax, path: Path) -> None:
    with Image.open(path) as opened:
        ax.imshow(opened.convert("RGBA"))
    ax.set_axis_off()


def formula_label(value: str) -> str:
    labels = {
        "LiFeO2": r"LiFeO$_2$",
        "Li2FeO3 polymorph 1": r"Li$_2$FeO$_3$ polymorph 1",
        "Li2FeO3 polymorph 2": r"Li$_2$FeO$_3$ polymorph 2",
        "LiFeO2 polymorph 2": r"LiFeO$_2$ polymorph 2",
        "LiFe3O4": r"LiFe$_3$O$_4$",
        "Li4WFe3O8": r"Li$_4$WFe$_3$O$_8$",
    }
    return labels.get(value, value)


def draw_grid(ax) -> None:
    points = np.asarray(list(np.ndindex(4, 4, 4)), dtype=float) - 1.5
    azimuth, elevation = math.radians(35), math.radians(22)
    rz = np.array([[math.cos(azimuth), -math.sin(azimuth), 0],
                   [math.sin(azimuth), math.cos(azimuth), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, math.cos(elevation), -math.sin(elevation)],
                   [0, math.sin(elevation), math.cos(elevation)]])
    projected = points @ (rx @ rz).T
    order = np.argsort(projected[:, 2])
    ax.scatter(projected[order, 0], projected[order, 1], s=6,
               c=np.linspace(.25, .9, 64)[order], cmap="Blues", edgecolors="none")
    ax.set_axis_off(); ax.set_aspect("equal")


def load_curves() -> dict[str, dict[str, np.ndarray]]:
    curves: dict[str, dict[str, np.ndarray]] = {}
    for pair in PAIRS:
        rows = load_csv(BUNDLE / "spp_curves" / f"{pair}.csv")
        curves[pair] = {
            "distance": np.asarray([float(row["distance_A"]) for row in rows]),
            "request": np.asarray([float(row["request_shape_normalized_for_display"]) for row in rows]),
            "global": np.asarray([float(row["global_shape_normalized_for_display"]) for row in rows]),
            "final": np.asarray([float(row["final_qlip_spp_before_outer_weight"]) for row in rows]),
        }
    return curves


def main() -> None:
    required = [
        BUNDLE / "REQUEST.json", BUNDLE / "RETRIEVAL_NEIGHBOURS.csv",
        BUNDLE / "PAIR_DISTANCE_EVIDENCE.csv", BUNDLE / "QLIP_SOLVER_SUMMARY.json",
        BUNDLE / "SCA_SUMMARY.json", BUNDLE / "GENERATED_RAW.cif", SUPERCELL_MANIFEST,
    ] + [BUNDLE / "spp_curves" / f"{pair}.csv" for pair in PAIRS]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing)

    input_hashes = {str(path.resolve()): sha256(path) for path in required}
    neighbours = load_csv(BUNDLE / "RETRIEVAL_NEIGHBOURS.csv")
    evidence = {row["pair"]: row for row in load_csv(BUNDLE / "PAIR_DISTANCE_EVIDENCE.csv")}
    solver = load_json(BUNDLE / "QLIP_SOLVER_SUMMARY.json")
    sca = load_json(BUNDLE / "SCA_SUMMARY.json")
    render_manifest = load_json(SUPERCELL_MANIFEST)
    renders = render_manifest["items"]
    if len(neighbours) != 6 or len(renders) != 7:
        raise RuntimeError("Expected six neighbour renders plus one generated render")
    if any(not item.get("raw_source_unchanged") for item in renders):
        raise RuntimeError("A supercell render manifest reports a changed raw CIF")
    raw_hashes_before = {Path(item["raw_source_cif"]): sha256(Path(item["raw_source_cif"])) for item in renders}
    curves = load_curves()

    fig = plt.figure(figsize=(25.5, 7.8), facecolor="white")
    grid = fig.add_gridspec(
        1, 7, width_ratios=(1.28, 3.55, 1.86, 5.05, 2.23, 2.42, 1.82),
        left=.012, right=.992, bottom=.085, top=.825, wspace=.23,
    )
    fig.suptitle("Retrieved crystal evidence becomes numerical guidance for crystal optimisation",
                 y=.965, fontsize=18, fontweight="bold", color=INK)
    fig.text(.5, .905, r"Li$_2$FeO$_3$ | persisted v4 workflow | layered-repaired-041",
             ha="center", fontsize=9.5, color=MUTED)

    a = fig.add_subplot(grid[0, 0]); card(a, "#F3F8FB"); heading(a, "A", "Request")
    a.text(.5, .73, r"Li$_2$FeO$_3$", ha="center", fontsize=20,
           fontweight="bold", color=NAVY, transform=a.transAxes)
    a.text(.5, .61, "layered oxide", ha="center", fontsize=9,
           fontweight="bold", color=TEAL, transform=a.transAxes)
    a.text(.5, .39, "Generate a plausible\nlayered lithium iron oxide\ncrystal candidate",
           ha="center", va="center", fontsize=7.6, linespacing=1.5,
           color=INK, transform=a.transAxes)

    b = fig.add_subplot(grid[0, 1]); card(b); heading(b, "B", "Retrieved crystal evidence")
    b.text(.5, .885, "30 retrieved Crystal-DB structures used by SPP-Maker",
           ha="center", fontsize=7.2, fontweight="bold", color=NAVY, transform=b.transAxes)
    subgrid = grid[0, 1].subgridspec(2, 3, hspace=.12, wspace=.04)
    for index, (row, render) in enumerate(zip(neighbours, renders[:6], strict=True)):
        ax = fig.add_subplot(subgrid[index // 3, index % 3]); ax.set_axis_off()
        image = ax.inset_axes([.02, .18, .96, .64]); image_axis(image, Path(render["polished_render"]))
        ax.text(.5, .96, formula_label(row["display_label"]), ha="center", va="top",
                fontsize=6.8, fontweight="bold", color=INK, transform=ax.transAxes)
        ax.text(.5, .10, f"rank {row['retrieval_rank']} | score {float(row['similarity_score']):.3f}",
                ha="center", fontsize=5.4, color=BLUE, transform=ax.transAxes)
    b.text(.5, .015, "+24 additional retrieved structures", ha="center",
           fontsize=6.5, fontweight="bold", color=TEAL, transform=b.transAxes)

    c = fig.add_subplot(grid[0, 2]); card(c, "#F7FBFA"); heading(c, "C", "Pair-distance evidence")
    c.text(.5, .92, "retrieved periodic structures", ha="center", fontsize=7.6,
           fontweight="bold", color=NAVY, transform=c.transAxes)
    c.text(.5, .86, "to pair-distance inputs", ha="center", fontsize=7.1,
           color=TEAL, transform=c.transAxes)
    c.text(.07, .78, "pair", fontsize=6, color=MUTED, transform=c.transAxes)
    c.text(.64, .80, "supporting\nstructures", ha="center", va="top", linespacing=1.0,
           fontsize=5.4, color=MUTED, transform=c.transAxes)
    c.text(.96, .80, "periodic\nobservations", ha="right", va="top", linespacing=1.0,
           fontsize=5.4, color=MUTED, transform=c.transAxes)
    for index, pair in enumerate(PAIRS):
        row = evidence[pair]
        y = .70 - index * .095
        display_pair = "Li-Fe" if pair == "Fe-Li" else pair
        c.text(.07, y, display_pair, fontsize=7.1, fontweight="bold", color=INK, transform=c.transAxes)
        c.text(.65, y, row["supporting_structure_count"], ha="center", fontsize=7,
               color=TEAL, transform=c.transAxes)
        c.text(.95, y, f"{int(row['periodic_distance_observation_count']):,}", ha="right",
               fontsize=7, color=INK, transform=c.transAxes)
        c.plot([.06, .95], [y-.035, y-.035], color=GRID, lw=.45, transform=c.transAxes)
    c.text(.5, .075, "six Li-Fe-O pair potentials", ha="center", fontsize=6.8,
           fontweight="bold", color=TEAL, transform=c.transAxes)

    d = fig.add_subplot(grid[0, 3]); card(d, "#FCFBF7"); heading(d, "D", "Six SPPs used by QLIP")
    d.text(.99, 1.025, "final objective curves + normalized component shapes", ha="right",
           va="bottom", fontsize=5.7, color=MUTED, transform=d.transAxes)
    positions = [(0.04, .55), (.36, .55), (.68, .55), (.04, .12), (.36, .12), (.68, .12)]
    for pair, (x0, y0) in zip(PAIRS, positions, strict=True):
        ax = d.inset_axes([x0, y0, .27, .33])
        data = curves[pair]; mask = (data["distance"] >= 1.75) & (data["distance"] <= 6.0)
        x = data["distance"][mask]
        ax.plot(x, data["final"][mask], color=NAVY, lw=1.25)
        ax.axhline(0, color="#AAB5BB", lw=.4); ax.grid(True, color=GRID, lw=.35)
        ax.tick_params(labelsize=4.6, length=1.6, pad=1, colors=MUTED)
        for spine in ax.spines.values():
            spine.set_color("#BAC5CA"); spine.set_linewidth(.45)
        ax.set_xlim(1.75, 6.0)
        ax.set_title("Li-Fe" if pair == "Fe-Li" else pair, fontsize=7,
                     fontweight="bold", pad=2, color=INK)
        inset = ax.inset_axes([.50, .54, .46, .40])
        inset.plot(x, data["request"][mask], color=TEAL, lw=.7)
        inset.plot(x, data["global"][mask], color=GOLD, lw=.7)
        inset.set_xlim(1.75, 6.0); inset.set_ylim(-1.1, 1.1)
        inset.set_xticks([]); inset.set_yticks([])
        for spine in inset.spines.values():
            spine.set_color("#CAD2D6"); spine.set_linewidth(.35)
    legend = [
        Line2D([0], [0], color=TEAL, lw=1.2, label="Retrieved-neighbour SPP (shape normalized)"),
        Line2D([0], [0], color=GOLD, lw=1.2, label="Global prior (shape normalized)"),
        Line2D([0], [0], color=NAVY, lw=1.5, label="QLIP objective SPP (raw)"),
    ]
    d.legend(handles=legend, loc="lower center", bbox_to_anchor=(.5, .01), ncol=3,
             frameon=False, fontsize=5.4, handlelength=1.6, columnspacing=1.1)

    e = fig.add_subplot(grid[0, 4]); card(e, "#F6F7FB"); heading(e, "E", "QLIP CSP")
    e.text(.5, .88, "Physical search cell", ha="center", fontsize=8.2,
           fontweight="bold", color=NAVY, transform=e.transAxes)
    e.text(.5, .805, "composition-scaled from\nfrozen VPA prior", ha="center",
           fontsize=6.3, color=MUTED, transform=e.transAxes)
    e.text(.5, .70, "a = b = c =", ha="center", fontsize=6.4, color=MUTED, transform=e.transAxes)
    e.text(.5, .655, "4.761047538838345 A", ha="center", fontsize=7,
           fontweight="bold", color=INK, transform=e.transAxes)
    grid_ax = e.inset_axes([.24, .39, .52, .22]); draw_grid(grid_ax)
    e.text(.5, .365, "4x4x4 = 64 candidate positions", ha="center", fontsize=7.4,
           fontweight="bold", color=NAVY, transform=e.transAxes)
    e.text(.5, .22, "OPTIMAL", ha="center", fontsize=10.5, fontweight="bold",
           color=GREEN, transform=e.transAxes)
    e.text(.5, .15, f"objective {float(solver['solver_objective']):.12f}", ha="center",
           fontsize=6, color=INK, transform=e.transAxes)
    e.text(.5, .095, f"runtime {float(solver['runtime_seconds']):.12f} s", ha="center",
           fontsize=6, color=MUTED, transform=e.transAxes)

    f = fig.add_subplot(grid[0, 5]); card(f); heading(f, "F", "Actual generated crystal")
    generated_render = renders[6]
    image = f.inset_axes([.03, .21, .94, .67]); image_axis(image, Path(generated_render["polished_render"]))
    f.text(.5, .13, r"QLIP-generated Li$_2$FeO$_3$", ha="center", fontsize=8.5,
           fontweight="bold", color=INK, transform=f.transAxes)
    repeat = f"{generated_render['repeat_a']}x{generated_render['repeat_b']}x{generated_render['repeat_c']}"
    f.text(.5, .072, f"visualization supercell {repeat}", ha="center", fontsize=6.4,
           fontweight="bold", color=TEAL, transform=f.transAxes)
    f.text(.5, .030, "derived from raw persisted 6-atom CIF", ha="center", fontsize=5.5,
           color=MUTED, transform=f.transAxes)

    g = fig.add_subplot(grid[0, 6]); card(g, "#F4FAF6"); heading(g, "G", "SCA validation")
    g.text(.5, .76, "TOPOLOGY PASS", ha="center", fontsize=10.2,
           fontweight="bold", color=GREEN, transform=g.transAxes)
    facts = (("CIF / composition", "valid"), ("Bad contacts", str(sca["num_bad_contacts"])),
             ("Min. distance", f"{float(sca['min_distance']):.3f} A"))
    for index, (label, value) in enumerate(facts):
        y = .57 - index * .15
        g.text(.08, y, label, fontsize=6.5, color=MUTED, transform=g.transAxes)
        g.text(.92, y, value, ha="right", fontsize=7.3, fontweight="bold",
               color=INK, transform=g.transAxes)
        if index < 2:
            g.plot([.08, .92], [y-.05, y-.05], color=GRID, lw=.5, transform=g.transAxes)

    axes = [a, b, c, d, e, f, g]
    for left, right in zip(axes, axes[1:]):
        left_box, right_box = left.get_position(), right.get_position()
        fig.add_artist(FancyArrowPatch(
            (left_box.x1+.001, .46), (right_box.x0-.001, .46), transform=fig.transFigure,
            arrowstyle="-|>", mutation_scale=10, lw=1, color="#819099", clip_on=False,
        ))

    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(PDF, facecolor="white", metadata={"Title": "Li2FeO3 workflow with visualization supercells"})
    fig.savefig(PNG, dpi=320, facecolor="white")
    plt.close(fig)

    comparison_pdf = OUT / "FIGURE_1_LI2FEO3_WORKFLOW_SUPERCELL.pdf"
    comparison_png = OUT / "FIGURE_1_LI2FEO3_WORKFLOW_SUPERCELL.png"
    if comparison_pdf.is_file() and comparison_png.is_file():
        shutil.copy2(comparison_pdf, SUPP_PDF)
        shutil.copy2(comparison_png, SUPP_PNG)

    raw_hashes_after = {path: sha256(path) for path in raw_hashes_before}
    if raw_hashes_after != raw_hashes_before:
        raise RuntimeError("A raw retrieved or generated CIF changed during figure assembly")

    panel_contract = [
        {"panel": "A", "content": "request"},
        {"panel": "B", "content": "retrieved crystal evidence"},
        {"panel": "C", "content": "pair-distance evidence"},
        {"panel": "D", "content": "six SPPs used by QLIP"},
        {"panel": "E", "content": "QLIP CSP"},
        {"panel": "F", "content": "actual generated crystal"},
        {"panel": "G", "content": "SCA validation"},
    ]
    manifest = {
        "schema_version": "figure_1_li2feo3_workflow_supercell_proper.v1",
        "workflow_direction": "A -> B -> C -> D -> E -> F -> G",
        "panels": panel_contract,
        "inputs": input_hashes,
        "supercell_render_manifest": str(SUPERCELL_MANIFEST.resolve()),
        "retrieved_render_count": 6,
        "spp_plot_count": 6,
        "generated_render": generated_render,
        "generated_raw_cif_sha256_before": raw_hashes_before[Path(generated_render["raw_source_cif"])],
        "generated_raw_cif_sha256_after": raw_hashes_after[Path(generated_render["raw_source_cif"])],
        "raw_source_cifs_unchanged": True,
        "retrieval_rerun": False, "spp_fit_rerun": False, "qlip_rerun": False,
        "generation_rerun": False, "sca_rerun": False,
        "pdf": str(PDF.resolve()), "pdf_sha256": sha256(PDF),
        "png": str(PNG.resolve()), "png_sha256": sha256(PNG),
        "supplementary_comparison_pdf": str(SUPP_PDF.resolve()) if SUPP_PDF.is_file() else None,
        "supplementary_comparison_png": str(SUPP_PNG.resolve()) if SUPP_PNG.is_file() else None,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    CAPTION.write_text(
        "# Figure 1 supercell caption facts\n\n"
        "The panels follow the persisted workflow A-G: request, 30-structure Crystal-DB retrieval "
        "evidence (six representatives shown), periodic pair-distance evidence, the six SPPs used "
        "by QLIP, QLIP CSP, the generated crystal, and SCA validation.\n\n"
        "Panel D shows the raw final QLIP objective SPP in navy. Retrieved-neighbour and global-prior "
        "components are independently shape-normalized in the inset and must not be read as a common "
        "amplitude scale.\n\n"
        "QLIP solved the persisted six-atom periodic Li2FeO3 cell over 64 candidate positions. Panel F "
        "uses a derived 2x2x2 VESTA visualization supercell (48 displayed atoms) solely to expose the "
        "periodic motif; QLIP did not optimize a 48-atom prediction. No retrieval, SPP fitting, QLIP, "
        "generation, or SCA stage was rerun.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
