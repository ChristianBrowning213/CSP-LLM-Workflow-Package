"""Render the NaTi2O4 paper workflow v2 from frozen v4 artifacts.

This is a figure-only operation. It does not run retrieval, SPP fitting, QLIP,
CIF generation, or SCA. All four structure images are exported by VESTA from
the persisted retrieved/generated CIFs and recorded in an auditable manifest.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image


ROOT = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
RESULTS = ROOT / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed" / "results"
WORKFLOW = RESULTS / "paper_workflow_example"
OUTPUT = RESULTS / "paper_figures" / "figure_1_workflow_v2"
VESTA_ASSETS = OUTPUT / "vesta_renders"
STAGED_CIFS = VESTA_ASSETS / "staged_cifs"
SCENES = VESTA_ASSETS / "scenes"
RAW_EXPORTS = VESTA_ASSETS / "raw_exports"
POLISHED_RENDERS = VESTA_ASSETS / "polished"
VESTA_EXE = Path(r"C:\Users\brown\Documents\VESTA-win64\VESTA-win64\VESTA.exe")

FINAL_PDF = OUTPUT / "FIGURE_1_NATI2O4_WORKFLOW_V2.pdf"
FINAL_PNG = OUTPUT / "FIGURE_1_NATI2O4_WORKFLOW_V2.png"
CAPTION_FACTS = OUTPUT / "FIGURE_1_CAPTION_FACTS_V2.md"
RENDER_MANIFEST = OUTPUT / "FIGURE_1_VESTA_RENDER_MANIFEST.json"
SOURCE_MANIFEST = OUTPUT / "FIGURE_1_SOURCE_ARTIFACTS_V2.csv"

NAVY = "#173B57"
BLUE = "#2C6E9F"
TEAL = "#258B87"
GOLD = "#D39B2A"
GREEN = "#34865A"
INK = "#18252E"
MUTED = "#60717D"
GRID = "#DCE4E8"
CARD = "#F6F8F9"
REQUEST_COLOR = TEAL
GLOBAL_COLOR = GOLD
FINAL_COLOR = NAVY


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "pass"}


def norm(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def wait_for_stable_file(path: Path, *, timeout_s: float, image: bool = False) -> None:
    deadline = time.monotonic() + timeout_s
    previous_size = -1
    stable_checks = 0
    last_error = ""
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            size = path.stat().st_size
            stable_checks = stable_checks + 1 if size == previous_size else 0
            previous_size = size
            if stable_checks >= 2:
                if image:
                    try:
                        with Image.open(path) as opened:
                            opened.verify()
                    except Exception as exc:  # pragma: no cover - timing dependent
                        last_error = str(exc)
                    else:
                        return
                else:
                    path.read_bytes()[:1]
                    return
        time.sleep(0.25)
    raise TimeoutError(f"VESTA output did not stabilize: {path}; last error: {last_error}")


def launch_vesta(arguments: list[str]) -> int:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(VESTA_EXE), *arguments],
        cwd=str(VESTA_EXE.parent),
        creationflags=creationflags,
    )
    return int(process.pid)


def polish_vesta_export(raw_png: Path, polished_png: Path) -> dict[str, Any]:
    with Image.open(raw_png) as opened:
        rgba = opened.convert("RGBA")
    data = np.asarray(rgba).copy()
    height, width = data.shape[:2]
    near_white = np.all(data[:, :, :3] >= 247, axis=2)
    data[near_white, 3] = 0
    # Remove VESTA's screen-space orientation compass from the publication crop.
    data[int(height * 0.62) :, : int(width * 0.27), 3] = 0
    rendered = Image.fromarray(data, mode="RGBA")
    bbox = rendered.getbbox()
    if bbox is None:
        raise RuntimeError(f"VESTA export became blank after background cleanup: {raw_png}")
    rendered = rendered.crop(bbox)
    canvas_size = (1400, 1000)
    max_width = int(canvas_size[0] * 0.92)
    max_height = int(canvas_size[1] * 0.92)
    scale = min(max_width / rendered.width, max_height / rendered.height)
    rendered = rendered.resize(
        (max(1, round(rendered.width * scale)), max(1, round(rendered.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", canvas_size, (255, 255, 255, 0))
    canvas.alpha_composite(
        rendered,
        ((canvas_size[0] - rendered.width) // 2, (canvas_size[1] - rendered.height) // 2),
    )
    polished_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(polished_png, dpi=(300, 300))
    return {
        "raw_dimensions_px": [width, height],
        "polished_dimensions_px": list(canvas_size),
        "background": "transparent after near-white removal",
        "orientation_compass": "excluded from publication crop",
    }


def render_cif_with_vesta(
    source_cif: Path,
    *,
    render_id: str,
    role: str,
    formula: str,
    rotation: tuple[float, float, float] = (18.0, -28.0, 8.0),
) -> dict[str, Any]:
    if not VESTA_EXE.is_file():
        raise FileNotFoundError(f"VESTA executable unavailable: {VESTA_EXE}")
    if not source_cif.is_file():
        raise FileNotFoundError(source_cif)
    STAGED_CIFS.mkdir(parents=True, exist_ok=True)
    SCENES.mkdir(parents=True, exist_ok=True)
    RAW_EXPORTS.mkdir(parents=True, exist_ok=True)
    POLISHED_RENDERS.mkdir(parents=True, exist_ok=True)
    staged_cif = STAGED_CIFS / f"{render_id}.cif"
    scene = SCENES / f"{render_id}.vesta"
    raw_png = RAW_EXPORTS / f"{render_id}.png"
    polished_png = POLISHED_RENDERS / f"{render_id}.png"
    source_hash = sha256(source_cif)
    shutil.copy2(source_cif, staged_cif)
    if sha256(staged_cif) != source_hash:
        raise RuntimeError(f"Staged CIF hash mismatch: {source_cif}")
    for output in (scene, raw_png, polished_png):
        if output.exists():
            output.unlink()
    rx, ry, rz = rotation
    save_pid = launch_vesta(
        [
            "-open", norm(staged_cif),
            "-rotate_x", str(rx), "-rotate_y", str(ry), "-rotate_z", str(rz),
            "-save", norm(scene), "-close", norm(staged_cif),
        ]
    )
    wait_for_stable_file(scene, timeout_s=60.0)
    export_pid = launch_vesta(
        ["-open", norm(scene), "-export_img", "scale=3", norm(raw_png), "-close", norm(scene)]
    )
    wait_for_stable_file(raw_png, timeout_s=90.0, image=True)
    polish_meta = polish_vesta_export(raw_png, polished_png)
    with Image.open(polished_png) as opened:
        opened.verify()
    if sha256(source_cif) != source_hash:
        raise RuntimeError(f"Source CIF changed while rendering: {source_cif}")
    return {
        "render_id": render_id,
        "role": role,
        "formula": formula,
        "renderer_used": "VESTA",
        "vesta_executable": str(VESTA_EXE.resolve()),
        "vesta_executable_sha256": sha256(VESTA_EXE),
        "source_cif": str(source_cif.resolve()),
        "source_cif_sha256": source_hash,
        "staged_cif": str(staged_cif.resolve()),
        "staged_cif_sha256": sha256(staged_cif),
        "scene": str(scene.resolve()),
        "scene_sha256": sha256(scene),
        "raw_export": str(raw_png.resolve()),
        "raw_export_sha256": sha256(raw_png),
        "polished_render": str(polished_png.resolve()),
        "polished_render_sha256": sha256(polished_png),
        "rotation_degrees": {"x": rx, "y": ry, "z": rz},
        "vesta_save_pid": save_pid,
        "vesta_export_pid": export_pid,
        **polish_meta,
    }


def add_card(ax: Axes, *, facecolor: str = CARD, edgecolor: str = GRID) -> None:
    ax.set_axis_off()
    ax.add_patch(
        FancyBboxPatch(
            (0.0, 0.0), 1.0, 1.0,
            transform=ax.transAxes,
            boxstyle="round,pad=0.016,rounding_size=0.025",
            linewidth=0.8,
            edgecolor=edgecolor,
            facecolor=facecolor,
            zorder=-10,
            clip_on=False,
        )
    )


def panel_heading(ax: Axes, letter: str, title: str) -> None:
    ax.text(0.0, 1.04, letter, transform=ax.transAxes, fontsize=11.2,
            fontweight="bold", color=BLUE, va="bottom")
    ax.text(0.10, 1.04, title, transform=ax.transAxes, fontsize=10.0,
            fontweight="bold", color=INK, va="bottom")


def add_flow_arrows(fig: Figure, axes: list[Axes]) -> None:
    boxes = [axis.get_position() for axis in axes]
    for left, right in zip(boxes, boxes[1:]):
        fig.add_artist(
            FancyArrowPatch(
                (left.x1 + 0.002, 0.48),
                (right.x0 - 0.002, 0.48),
                transform=fig.transFigure,
                arrowstyle="-|>",
                mutation_scale=12,
                linewidth=1.1,
                color="#80909A",
                shrinkA=0,
                shrinkB=0,
                clip_on=False,
            )
        )


def draw_grid_icon(ax: Axes) -> None:
    points = np.asarray([(i, j, k) for i in range(4) for j in range(4) for k in range(4)], dtype=float)
    points -= 1.5
    azimuth = math.radians(35.0)
    elevation = math.radians(22.0)
    rz = np.asarray([
        [math.cos(azimuth), -math.sin(azimuth), 0.0],
        [math.sin(azimuth), math.cos(azimuth), 0.0],
        [0.0, 0.0, 1.0],
    ])
    rx = np.asarray([
        [1.0, 0.0, 0.0],
        [0.0, math.cos(elevation), -math.sin(elevation)],
        [0.0, math.sin(elevation), math.cos(elevation)],
    ])
    rotated = points @ (rx @ rz).T
    order = np.argsort(rotated[:, 2])
    ax.scatter(rotated[order, 0], rotated[order, 1], s=8.5,
               c=np.linspace(0.30, 0.88, len(points))[order], cmap="Blues",
               edgecolors="none", alpha=0.9)
    ax.set_xlim(-3.1, 3.1)
    ax.set_ylim(-2.7, 2.7)
    ax.set_aspect("equal")
    ax.set_axis_off()


def style_curve_axis(ax: Axes) -> None:
    ax.grid(True, color=GRID, linewidth=0.45, alpha=0.88)
    ax.tick_params(labelsize=6.5, colors=MUTED, length=2.2, pad=1.5)
    for spine in ax.spines.values():
        spine.set_color("#B8C5CB")
        spine.set_linewidth(0.65)
    ax.axhline(0.0, color="#AAB6BC", linewidth=0.55, zorder=0)


def curve_plot(ax: Axes, path: Path, *, pair: str, provenance_label: str) -> dict[str, Any]:
    rows = read_csv(path)
    distance = np.asarray([float(row["distance_A"]) for row in rows])
    request = np.asarray([float(row["request_component"]) for row in rows])
    global_prior = np.asarray([float(row["global_component"]) for row in rows])
    final = np.asarray([float(row["final_potential"]) for row in rows])
    request_nonzero = bool(np.any(np.abs(request) > 1e-14))
    if request_nonzero:
        ax.plot(distance, request, color=REQUEST_COLOR, linewidth=1.35,
                linestyle=(0, (4, 2)), label="Retrieved-neighbour SPP")
    ax.plot(distance, global_prior, color=GLOBAL_COLOR, linewidth=1.75,
            label="Global prior")
    ax.plot(distance, final, color=FINAL_COLOR, linewidth=1.45,
            linestyle=(0, (3, 1.7)), label="QLIP objective SPP")
    main_mask = (distance >= 1.75) & (distance <= 6.0)
    main_values = np.concatenate((global_prior[main_mask], final[main_mask], request[main_mask] if request_nonzero else np.asarray([])))
    ymin = float(np.min(main_values))
    ymax = float(np.max(main_values))
    padding = max((ymax - ymin) * 0.10, 0.25)
    ax.set_xlim(1.75, 6.0)
    ax.set_ylim(ymin - padding, ymax + padding)
    style_curve_axis(ax)
    ax.set_xlabel("Distance (Å)", fontsize=7.2, color=INK, labelpad=1.5)
    ax.set_title(pair, fontsize=9.0, fontweight="bold", color=INK, pad=13)
    ax.text(0.5, 1.025, provenance_label, transform=ax.transAxes,
            ha="center", va="bottom", fontsize=6.4, color=TEAL, fontweight="bold")
    inset = ax.inset_axes([0.55, 0.52, 0.41, 0.39])
    if request_nonzero:
        inset.plot(distance, request, color=REQUEST_COLOR, linewidth=0.75, linestyle=(0, (3, 2)))
    inset.plot(distance, global_prior, color=GLOBAL_COLOR, linewidth=0.9)
    inset.plot(distance, final, color=FINAL_COLOR, linewidth=0.8, linestyle=(0, (3, 1.7)))
    inset.set_xlim(float(distance.min()), 1.75)
    inset.set_yscale("symlog", linthresh=0.05, linscale=0.7)
    inset.grid(True, color=GRID, linewidth=0.3, alpha=0.75)
    inset.tick_params(labelsize=4.5, colors=MUTED, length=1.5, pad=0.8)
    inset.set_title("short-range wall", fontsize=5.2, color=MUTED, pad=1.5)
    for spine in inset.spines.values():
        spine.set_color("#B8C5CB")
        spine.set_linewidth(0.45)
    return {
        "pair": pair,
        "source_path": str(path.resolve()),
        "source_sha256": sha256(path),
        "row_count": len(rows),
        "request_nonzero": request_nonzero,
        "series_labels": (
            ["Retrieved-neighbour SPP"] if request_nonzero else []
        ) + ["Global prior", "QLIP objective SPP"],
        "main_display_range_angstrom": [1.75, 6.0],
        "main_y_range": [ymin - padding, ymax + padding],
        "inset_display_range_angstrom": [float(distance.min()), 1.75],
        "inset_scale": "symmetric log; raw tabulated values unchanged",
        "quantity_label": "SPP value (stored units; no energy unit asserted)",
    }


def image_on_axis(ax: Axes, path: Path) -> None:
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    ax.imshow(image)
    ax.set_axis_off()


def write_caption_facts(
    request: dict[str, Any],
    neighbours: list[dict[str, str]],
    solver: dict[str, Any],
    sca: dict[str, Any],
    generated: Path,
    renders: list[dict[str, Any]],
) -> None:
    lines = [
        "# Figure 1 caption facts v2",
        "",
        "## Case study",
        "",
        "- Target: NaTi2O4 (spinel oxide)",
        "- Benchmark experiment: spinel-repaired-046",
        f"- Request: {request['text_request']}",
        "",
        "## Retrieved crystal evidence",
        "",
    ]
    for row in neighbours:
        lines.append(
            f"- {row['formula']}: retrieval rank {row['rank']}; score {row['similarity_score']}; "
            f"source ID {str(row['source_id']).removesuffix('.cif')}; CIF `{row['source_cif_path']}`; "
            f"SHA-256 `{sha256(Path(row['source_cif_path']))}`."
        )
    lines.extend([
        "",
        "## SPP guidance",
        "",
        "- O-O: retrieval-informed; the QLIP objective combines the persisted retrieved-neighbour SPP component (weight 1.0) with the frozen global prior (weight 2.0).",
        "- O-Ti: global-supported; the persisted request component is identically zero and is not drawn; the QLIP objective is the frozen global prior contribution (global weight 2.0).",
        "- Required pairs: Na-Na, Na-O, Na-Ti, O-O, O-Ti, Ti-Ti.",
        "- The stored artifact contract does not assert an energy unit for these tabulated SPP values.",
        "",
        "## QLIP CSP",
        "",
        f"- Native grid: {solver['native_grid_density']}^3 = {solver['native_grid_site_count']} sites.",
        f"- Status: {solver['terminal_status']}.",
        f"- Objective: {float(solver['solver_objective']):.4f}.",
        f"- Runtime: {float(solver['runtime_seconds']):.3f} s.",
        "",
        "## Generated crystal and SCA validation",
        "",
        f"- Raw generated CIF: `{generated.resolve()}`.",
        f"- Generated CIF SHA-256: `{sha256(generated)}`.",
        f"- Topology: {sca['topology_status']}.",
        f"- CIF/composition valid: {bool(sca['parse_ok'] and sca['chemical_species_valid'] and sca['target_formula_match'])}.",
        f"- Bad contacts: {sca['num_bad_contacts']}.",
        f"- Minimum distance: {float(sca['min_distance']):.3f} angstrom.",
        "",
        "## Renderer confirmation",
        "",
        "- Renderer used for all four structure images: VESTA.",
        f"- VESTA executable: `{VESTA_EXE.resolve()}`.",
        f"- VESTA executable SHA-256: `{sha256(VESTA_EXE)}`.",
        f"- VESTA render asset directory: `{VESTA_ASSETS.resolve()}`.",
        f"- Confirmed VESTA renders: {len(renders)} of 4.",
        "- Each render record preserves its exact source CIF, staged byte-identical CIF, VESTA scene, raw VESTA PNG, polished transparent PNG, and hashes in `FIGURE_1_VESTA_RENDER_MANIFEST.json`.",
        "",
    ])
    CAPTION_FACTS.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    request_path = WORKFLOW / "REQUEST.json"
    neighbours_path = WORKFLOW / "RETRIEVAL_NEIGHBOURS.csv"
    provenance_path = WORKFLOW / "SPP_PAIR_PROVENANCE.csv"
    solver_path = WORKFLOW / "QLIP_SOLVER_SUMMARY.json"
    sca_path = WORKFLOW / "SCA_SUMMARY.json"
    generated = WORKFLOW / "GENERATED_RAW.cif"
    oo_path = WORKFLOW / "spp_curves" / "O-O.csv"
    oti_path = WORKFLOW / "spp_curves" / "O-Ti.csv"
    required_paths = (request_path, neighbours_path, provenance_path, solver_path, sca_path, generated, oo_path, oti_path)
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Required workflow artifacts missing: {missing}")
    before_hashes = {path: sha256(path) for path in required_paths}
    request = read_json(request_path)
    solver = read_json(solver_path)
    sca = read_json(sca_path)
    neighbours = [row for row in read_csv(neighbours_path) if truth(row["ILLUSTRATIVE_NEIGHBOUR"])]
    if [row["formula"] for row in neighbours] != ["Na2WO4", "NaCr2O4", "NaV2O4"]:
        raise RuntimeError("Illustrative neighbour selection differs from the approved v4 example")
    if sha256(generated) != solver["generated_cif_sha256"]:
        raise RuntimeError("Raw generated CIF hash does not match QLIP_SOLVER_SUMMARY.json")
    if solver["terminal_status"] != "OPTIMAL" or int(solver["native_grid_site_count"]) != 64:
        raise RuntimeError("Persisted QLIP solver facts differ from the approved v4 example")
    if sca["topology_status"] != "PASS" or int(sca["num_bad_contacts"]) != 0:
        raise RuntimeError("Persisted SCA facts differ from the approved v4 example")
    if not (sca["parse_ok"] and sca["chemical_species_valid"] and sca["target_formula_match"]):
        raise RuntimeError("Persisted CIF/composition validation facts are not all true")

    render_specs = [
        (Path(neighbours[0]["source_cif_path"]), "neighbour_na2wo4", "retrieved_neighbour", "Na2WO4"),
        (Path(neighbours[1]["source_cif_path"]), "neighbour_nacr2o4", "retrieved_neighbour", "NaCr2O4"),
        (Path(neighbours[2]["source_cif_path"]), "neighbour_nav2o4", "retrieved_neighbour", "NaV2O4"),
        (generated, "generated_nati2o4", "raw_generated", "NaTi2O4"),
    ]
    renders = [
        render_cif_with_vesta(path, render_id=render_id, role=role, formula=formula)
        for path, render_id, role, formula in render_specs
    ]
    if len(renders) != 4 or any(row["renderer_used"] != "VESTA" for row in renders):
        raise RuntimeError("All four structure images were not successfully rendered by VESTA")

    fig = plt.figure(figsize=(20.8, 6.75), facecolor="white")
    outer = fig.add_gridspec(
        1, 6,
        width_ratios=(1.45, 3.65, 3.85, 1.90, 2.25, 1.95),
        left=0.018, right=0.988, top=0.82, bottom=0.11, wspace=0.28,
    )
    fig.suptitle("Traceable retrieval-to-optimisation workflow", fontsize=18.0,
                 fontweight="bold", color=INK, y=0.965)
    fig.text(0.5, 0.905, "Actual NaTi$_2$O$_4$ case study from the final benchmark",
             ha="center", fontsize=9.4, color=MUTED)

    request_ax = fig.add_subplot(outer[0, 0])
    add_card(request_ax, facecolor="#F4F8FB")
    panel_heading(request_ax, "A", "Request")
    request_ax.text(0.5, 0.76, "NaTi$_2$O$_4$", transform=request_ax.transAxes,
                    ha="center", va="center", fontsize=19.0, fontweight="bold", color=NAVY)
    request_ax.text(0.5, 0.62, "spinel oxide", transform=request_ax.transAxes,
                    ha="center", fontsize=10.0, color=TEAL, fontweight="bold")
    request_ax.text(0.5, 0.38, request["text_request"], transform=request_ax.transAxes,
                    ha="center", va="center", fontsize=8.0, color=INK, wrap=True,
                    linespacing=1.35)

    neighbour_outer = fig.add_subplot(outer[0, 1])
    add_card(neighbour_outer, facecolor="#FBFCFD")
    panel_heading(neighbour_outer, "B", "Retrieved crystal evidence")
    neighbour_grid = outer[0, 1].subgridspec(1, 3, wspace=0.08)
    for index, (row, render) in enumerate(zip(neighbours, renders[:3], strict=True)):
        ax = fig.add_subplot(neighbour_grid[0, index])
        ax.set_axis_off()
        image_ax = ax.inset_axes([0.02, 0.23, 0.96, 0.67])
        image_on_axis(image_ax, Path(render["polished_render"]))
        ax.text(0.5, 0.96, f"$\\mathrm{{{row['formula'].replace('2', '_2').replace('4', '_4')}}}$",
                transform=ax.transAxes, ha="center", va="top", fontsize=9.4,
                fontweight="bold", color=INK)
        ax.text(0.5, 0.145, f"rank {row['rank']}  |  score {float(row['similarity_score']):.3f}",
                transform=ax.transAxes, ha="center", va="bottom", fontsize=6.4, color=BLUE)
        ax.text(0.5, 0.075, str(row["source_id"]).removesuffix(".cif"),
                transform=ax.transAxes, ha="center", va="bottom", fontsize=5.8, color=MUTED)

    spp_outer = fig.add_subplot(outer[0, 2])
    add_card(spp_outer, facecolor="#FCFBF7")
    panel_heading(spp_outer, "C", "SPP / solver guidance")
    oo_ax = spp_outer.inset_axes([0.055, 0.23, 0.40, 0.65])
    oti_ax = spp_outer.inset_axes([0.545, 0.23, 0.40, 0.65])
    oo_meta = curve_plot(oo_ax, oo_path, pair="O-O", provenance_label="retrieval-informed")
    oti_meta = curve_plot(oti_ax, oti_path, pair="O-Ti", provenance_label="global-supported")
    oo_ax.set_ylabel("SPP value (stored units)", fontsize=7.1, color=INK, labelpad=1.2)
    handles, labels = oo_ax.get_legend_handles_labels()
    spp_outer.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.105),
                     ncol=3, frameon=False, fontsize=6.3, handlelength=2.1,
                     columnspacing=1.1)
    spp_outer.text(0.5, 0.045, "Required pairs: Na-Na, Na-O, Na-Ti, O-O, O-Ti, Ti-Ti",
                   transform=spp_outer.transAxes, ha="center", va="center",
                   fontsize=6.2, color=MUTED)

    qlip_ax = fig.add_subplot(outer[0, 3])
    add_card(qlip_ax, facecolor="#F7F8FC")
    panel_heading(qlip_ax, "D", "QLIP CSP")
    grid_ax = qlip_ax.inset_axes([0.18, 0.59, 0.64, 0.29])
    draw_grid_icon(grid_ax)
    qlip_ax.text(0.5, 0.52, "4$^3$ = 64 sites", transform=qlip_ax.transAxes,
                 ha="center", fontsize=10.4, fontweight="bold", color=NAVY)
    qlip_ax.text(0.5, 0.415, "min pair-SPP terms", transform=qlip_ax.transAxes,
                 ha="center", fontsize=7.6, color=INK)
    qlip_ax.text(0.5, 0.335, "exact species counts", transform=qlip_ax.transAxes,
                 ha="center", fontsize=7.1, color=MUTED)
    qlip_ax.text(0.5, 0.265, "one state per site", transform=qlip_ax.transAxes,
                 ha="center", fontsize=7.1, color=MUTED)
    qlip_ax.text(0.5, 0.165, solver["terminal_status"], transform=qlip_ax.transAxes,
                 ha="center", fontsize=10.0, fontweight="bold", color=GREEN)
    qlip_ax.text(0.5, 0.090, f"Objective  {float(solver['solver_objective']):.4f}",
                 transform=qlip_ax.transAxes, ha="center", fontsize=7.0, color=INK)
    qlip_ax.text(0.5, 0.035, f"Runtime  {float(solver['runtime_seconds']):.3f} s",
                 transform=qlip_ax.transAxes, ha="center", fontsize=6.7, color=MUTED)

    generated_ax = fig.add_subplot(outer[0, 4])
    add_card(generated_ax, facecolor="#FBFCFD")
    panel_heading(generated_ax, "E", "Generated crystal")
    generated_image_ax = generated_ax.inset_axes([0.04, 0.18, 0.92, 0.72])
    image_on_axis(generated_image_ax, Path(renders[3]["polished_render"]))
    generated_ax.text(0.5, 0.105, "QLIP-generated NaTi$_2$O$_4$",
                      transform=generated_ax.transAxes, ha="center", fontsize=9.0,
                      fontweight="bold", color=INK)
    generated_ax.text(0.5, 0.045, "raw CIF  |  OPTIMAL", transform=generated_ax.transAxes,
                      ha="center", fontsize=6.9, color=MUTED)

    sca_ax = fig.add_subplot(outer[0, 5])
    add_card(sca_ax, facecolor="#F5FAF7", edgecolor="#CFE1D6")
    panel_heading(sca_ax, "F", "SCA validation")
    sca_ax.text(0.5, 0.78, "TOPOLOGY PASS", transform=sca_ax.transAxes,
                ha="center", fontsize=11.0, fontweight="bold", color=GREEN)
    sca_ax.text(0.5, 0.69, "Independent validation", transform=sca_ax.transAxes,
                ha="center", fontsize=7.0, color=TEAL)
    metrics = (
        ("CIF / composition", "valid"),
        ("Bad contacts", "0"),
        ("Min. distance", f"{float(sca['min_distance']):.3f} Å"),
    )
    for index, (label, value) in enumerate(metrics):
        y = 0.53 - index * 0.15
        sca_ax.text(0.08, y, label, transform=sca_ax.transAxes,
                    fontsize=7.0, color=MUTED)
        sca_ax.text(0.92, y, value, transform=sca_ax.transAxes,
                    fontsize=7.7, ha="right", fontweight="bold", color=INK)
        if index < len(metrics) - 1:
            sca_ax.plot([0.08, 0.92], [y - 0.05, y - 0.05], transform=sca_ax.transAxes,
                        color=GRID, linewidth=0.6)

    add_flow_arrows(fig, [request_ax, neighbour_outer, spp_outer, qlip_ax, generated_ax, sca_ax])
    fig.savefig(FINAL_PDF, facecolor="white", metadata={"Title": "NaTi2O4 traceable retrieval-to-optimisation workflow"})
    fig.savefig(FINAL_PNG, dpi=300, facecolor="white")
    plt.close(fig)

    curves = {"O-O": oo_meta, "O-Ti": oti_meta}
    write_caption_facts(request, neighbours, solver, sca, generated, renders)
    source_rows: list[dict[str, str]] = [
        {"panel": "A", "role": "request", "source_path": str(request_path.resolve()), "sha256": sha256(request_path)},
        *[
            {"panel": "B", "role": f"retrieved_neighbour_{index}", "source_path": row["source_cif_path"], "sha256": sha256(Path(row["source_cif_path"]))}
            for index, row in enumerate(neighbours, 1)
        ],
        {"panel": "C", "role": "O-O_curve", "source_path": str(oo_path.resolve()), "sha256": sha256(oo_path)},
        {"panel": "C", "role": "O-Ti_curve", "source_path": str(oti_path.resolve()), "sha256": sha256(oti_path)},
        {"panel": "D", "role": "solver_summary", "source_path": str(solver_path.resolve()), "sha256": sha256(solver_path)},
        {"panel": "E", "role": "raw_generated_cif", "source_path": str(generated.resolve()), "sha256": sha256(generated)},
        {"panel": "F", "role": "sca_summary", "source_path": str(sca_path.resolve()), "sha256": sha256(sca_path)},
    ]
    with SOURCE_MANIFEST.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("panel", "role", "source_path", "sha256"))
        writer.writeheader()
        writer.writerows(source_rows)
    RENDER_MANIFEST.write_text(
        json.dumps(
            {
                "schema_version": "spp_only_oxide_workflow_figure_v2.v1",
                "figure_only": True,
                "renderer_used": "VESTA",
                "vesta_confirmed": True,
                "vesta_executable": str(VESTA_EXE.resolve()),
                "vesta_executable_sha256": sha256(VESTA_EXE),
                "renders": renders,
                "curves": curves,
                "pdf": str(FINAL_PDF.resolve()),
                "png": str(FINAL_PNG.resolve()),
                "caption_facts": str(CAPTION_FACTS.resolve()),
                "retrieval_rerun": False,
                "spp_fit_rerun": False,
                "qlip_rerun": False,
                "generation_rerun": False,
                "sca_rerun": False,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    if any(sha256(path) != digest for path, digest in before_hashes.items()):
        raise RuntimeError("Frozen workflow source artifact changed during figure rendering")
    with Image.open(FINAL_PNG) as final_image:
        final_image.verify()
        dpi = final_image.info.get("dpi", (0.0, 0.0))
    if min(float(value) for value in dpi) < 299.0:
        raise RuntimeError(f"Final PNG DPI is below 300: {dpi}")
    print(json.dumps({
        "pdf": str(FINAL_PDF.resolve()),
        "png": str(FINAL_PNG.resolve()),
        "caption_facts": str(CAPTION_FACTS.resolve()),
        "vesta_assets": str(VESTA_ASSETS.resolve()),
        "renderer_used": "VESTA",
        "render_count": len(renders),
        "png_dpi": dpi,
    }, indent=2))


if __name__ == "__main__":
    main()
