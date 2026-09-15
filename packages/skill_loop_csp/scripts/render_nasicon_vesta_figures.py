"""Render and compose paper-facing NASICON figures from archived CIFs with VESTA."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.patches import FancyArrowPatch, Patch
from PIL import Image
from pymatgen.core import Structure


ROOT = Path(__file__).resolve().parents[1]
VESTA_EXE = Path(r"C:\Users\brown\Documents\VESTA-win64\VESTA-win64\VESTA.exe")
VESTA_ROOT = ROOT / "figures" / "paper_nasicon" / "vesta"
FIGURE_ROOT = ROOT / "figures" / "paper_nasicon"
ARTIFACT_ROOT = ROOT / "artifacts" / "nasicon_finalisation"
RUN_ROOT = ROOT / "runs" / "paper_nasicon_specialist" / "leave_target_out"
SOURCE_CIF = RUN_ROOT / "qlip" / "solution.cif"
RETRIEVAL_PATH = RUN_ROOT / "retrieval.json"
SELECTED_RANKS = (1, 3, 4, 8)
COLORS = {
    "Na": (40, 120, 181),
    "O": (205, 211, 218),
    "P": (140, 98, 170),
    "Si": (230, 159, 0),
    "Zr": (24, 138, 154),
    "Sc": (93, 173, 122),
    "Ti": (66, 139, 202),
    "Cr": (117, 112, 179),
    "V": (89, 161, 79),
    "Li": (88, 166, 198),
}
RADII = {"Na": 0.82, "O": 0.26, "P": 0.48, "Si": 0.48, "Zr": 0.58, "Sc": 0.58, "Ti": 0.58}
BOND_CUTOFFS = {"P": 2.05, "Si": 2.05, "Zr": 2.55, "Sc": 2.60, "Ti": 2.60}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def wait_for_file(path: Path, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_size = -1
    stable = 0
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            size = path.stat().st_size
            stable = stable + 1 if size == last_size else 0
            last_size = size
            if stable >= 2:
                with Image.open(path) as image:
                    image.verify()
                return
        time.sleep(0.25)
    raise TimeoutError(f"VESTA output not ready: {path}")


def run_vesta(args: list[str], expected: Path | None = None) -> None:
    if not VESTA_EXE.is_file():
        raise FileNotFoundError(VESTA_EXE)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([str(VESTA_EXE), *args], creationflags=creationflags)
    if expected is not None:
        wait_for_file(expected)


def save_raw_scene(cif_path: Path, scene_path: Path, rotations: tuple[float, float, float]) -> None:
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    if scene_path.exists():
        scene_path.unlink()
    rx, ry, rz = rotations
    run_vesta(
        [
            "-open", norm(cif_path), "-rotate_x", str(rx), "-rotate_y", str(ry), "-rotate_z", str(rz),
            "-save", norm(scene_path), "-close", norm(cif_path),
        ]
    )
    deadline = time.monotonic() + 60.0
    previous_size = -1
    stable_checks = 0
    while time.monotonic() < deadline:
        if scene_path.is_file() and scene_path.stat().st_size > 0:
            current_size = scene_path.stat().st_size
            stable_checks = stable_checks + 1 if current_size == previous_size else 0
            previous_size = current_size
            if stable_checks >= 2:
                scene_path.read_text(encoding="utf-8")
                return
        time.sleep(0.25)
    raise TimeoutError(f"VESTA scene not saved: {scene_path}")


def _style_site_tokens(tokens: list[str], *, section: str) -> list[str]:
    element = tokens[1]
    color = COLORS.get(element, (110, 145, 170))
    radius = RADII.get(element, 0.52)
    if section == "SITET":
        radius_index, colour_index, alpha_index = 3, 4, 10
    else:
        radius_index, colour_index, alpha_index = 2, 3, 9
    tokens[radius_index] = f"{radius:.4f}"
    tokens[colour_index : colour_index + 3] = [str(value) for value in color]
    tokens[colour_index + 3 : colour_index + 6] = [str(value) for value in color]
    tokens[alpha_index] = "255" if element == "Na" else "150" if element == "O" else "190"
    return tokens


def style_scene(
    raw_path: Path,
    out_path: Path,
    *,
    bounds: tuple[float, float, float, float, float, float],
    scene_rotation: np.ndarray | None = None,
) -> None:
    lines = raw_path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    section = ""
    skip_bound_line = False
    scene_rows_left = 0
    for line in lines:
        stripped = line.strip()
        if stripped in {"BOUND", "SBOND", "SITET", "ATOMT", "SCENE"}:
            section = stripped
            out.append(line)
            if section == "BOUND":
                skip_bound_line = True
            elif section == "SCENE" and scene_rotation is not None:
                scene_rows_left = 4
            continue
        if skip_bound_line:
            out.append(" ".join(f"{value:g}" for value in bounds) + " ")
            skip_bound_line = False
            continue
        if scene_rows_left:
            row_index = 4 - scene_rows_left
            if row_index < 3:
                row = list(scene_rotation[row_index]) + [0.0]
            else:
                row = [0.0, 0.0, 0.0, 1.0]
            out.append(" " + " ".join(f"{value:.6f}" for value in row))
            scene_rows_left -= 1
            continue
        if section == "SBOND" and stripped and not stripped.startswith("0 0 0 0"):
            tokens = stripped.split()
            if len(tokens) >= 5:
                left, right = tokens[1], tokens[2]
                pair = {left, right}
                if pair == {"Na", "O"} or "O" not in pair:
                    continue
                central = right if left == "O" else left
                if central in BOND_CUTOFFS:
                    tokens[4] = f"{BOND_CUTOFFS[central]:.5f}"
                out.append("  " + " ".join(tokens))
                continue
        if section in {"SITET", "ATOMT"} and stripped and not stripped.startswith("0 0 0 0"):
            tokens = stripped.split()
            minimum_tokens = 11 if section == "SITET" else 10
            if len(tokens) >= minimum_tokens and tokens[0].isdigit():
                out.append("  " + " ".join(_style_site_tokens(tokens, section=section)))
                continue
        if stripped.startswith("MODEL "):
            out.append("MODEL   2  1  0")
        elif stripped.startswith("LABEL "):
            out.append("LABEL 0    12  1.000 0")
        elif stripped.startswith("POLYP"):
            out.append(line)
        elif section == "" and stripped.startswith("170 "):
            out.append(line)
        elif stripped == "204 1 1.000 180 180 180":
            out.append(" 170 1  1.000 180 180 180")
        elif stripped.startswith("ATOMP"):
            out.append(line)
        elif stripped == "24 24 0 50 2.0 0":
            out.append(" 24  24   0  50  1.25   0")
        elif stripped.startswith("UCOLP"):
            out.append(line)
        elif stripped == "0 1 1.000 0 0 0":
            out.append("  80   1  0.650  70  70  70")
        else:
            out.append(line)
        if section == "SBOND" and stripped.startswith("0 0 0 0"):
            section = ""
        elif section in {"SITET", "ATOMT"} and stripped.startswith("0 0 0 0"):
            section = ""
    out_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def render_scene(scene_path: Path, raw_png: Path, transparent_png: Path, *, canvas: tuple[int, int] = (1200, 900)) -> None:
    for path in (raw_png, transparent_png):
        if path.exists():
            path.unlink()
    run_vesta(["-open", norm(scene_path), "-export_img", "scale=4", norm(raw_png), "-close", norm(scene_path)], expected=raw_png)
    with Image.open(raw_png) as image:
        rgba = image.convert("RGBA")
        data = np.asarray(rgba).copy()
        near_white = np.all(data[:, :, :3] >= 248, axis=2)
        data[near_white, 3] = 0
        # VESTA's export includes its screen-space orientation compass. It is not
        # crystallographic content and is excluded from the publication crop.
        height, width = data.shape[:2]
        data[int(height * 0.65) :, : int(width * 0.25), 3] = 0
        rendered = Image.fromarray(data)
        bbox = rendered.getbbox()
        if bbox:
            rendered = rendered.crop(bbox)
        max_w, max_h = int(canvas[0] * 0.90), int(canvas[1] * 0.90)
        scale = min(max_w / rendered.width, max_h / rendered.height, 1.0)
        rendered = rendered.resize((max(1, int(rendered.width * scale)), max(1, int(rendered.height * scale))), Image.Resampling.LANCZOS)
        composed = Image.new("RGBA", canvas, (255, 255, 255, 0))
        composed.alpha_composite(rendered, ((canvas[0] - rendered.width) // 2, (canvas[1] - rendered.height) // 2))
        composed.save(transparent_png)


def projection_basis(structure: Structure) -> np.ndarray:
    a, _b, c = np.asarray(structure.lattice.matrix, dtype=float)
    z = c / np.linalg.norm(c)
    x_raw = a - np.dot(a, z) * z
    x = x_raw / np.linalg.norm(x_raw)
    y = np.cross(z, x)
    y /= np.linalg.norm(y)
    return np.asarray([x, y, z])


def create_scene_and_render(
    cif_path: Path,
    scene_path: Path,
    png_path: Path,
    *,
    bounds: tuple[float, float, float, float, float, float],
    rotations: tuple[float, float, float] = (18.0, -28.0, 12.0),
    scene_rotation: np.ndarray | None = None,
) -> Path:
    raw_scene = VESTA_ROOT / "_raw" / f"{scene_path.stem}_raw.vesta"
    raw_png = VESTA_ROOT / "_raw" / f"{png_path.stem}_raw.png"
    raw_scene.parent.mkdir(parents=True, exist_ok=True)
    save_raw_scene(cif_path, raw_scene, rotations)
    style_scene(raw_scene, scene_path, bounds=bounds, scene_rotation=scene_rotation)
    render_scene(scene_path, raw_png, png_path)
    return raw_png


def load_pot(pair: str) -> np.ndarray:
    path = RUN_ROOT / "row_specific_spp" / "spp_root" / pair / f"{pair}.POT"
    points = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 2:
            try:
                points.append((float(fields[0]), float(fields[1])))
            except ValueError:
                pass
    return np.asarray(points)


def _save_figure(fig: Any, stem: Path) -> None:
    for suffix in (".png", ".pdf", ".svg"):
        fig.savefig(stem.with_suffix(suffix), dpi=320, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def compose_workflow(retrieved: list[dict[str, Any]], candidate_png: Path) -> list[Path]:
    fig = plt.figure(figsize=(20.0, 4.6), facecolor="white")
    gs = fig.add_gridspec(1, 4, width_ratios=(0.88, 1.15, 1.72, 1.20), wspace=0.29)
    fig.subplots_adjust(left=0.02, right=0.99, bottom=0.06, top=0.89)
    ax1 = fig.add_subplot(gs[0, 0]); ax1.axis("off")
    ax1.set_title("1  Natural-language request", loc="left", fontsize=13, weight="bold")
    ax1.text(0.0, 0.82, "Generate an ordered NASICON-type\nNa₃Zr₂Si₂PO₁₂ candidate with a 3D\nZrO₆/SiO₄/PO₄ framework.", va="top", fontsize=11.2, linespacing=1.35)
    ax1.text(0.0, 0.23, "Ordered C2 scaffold\nSymmetry-closed Si/P orbit choice", fontsize=9.5, color="#59636e", linespacing=1.4)

    panel2 = fig.add_subplot(gs[0, 1]); panel2.axis("off")
    panel2.set_title("2  Retrieved Crystal-DB evidence", loc="left", fontsize=13, weight="bold")
    box = panel2.get_position()
    for index, row in enumerate(retrieved):
        col, rindex = index % 2, index // 2
        ax = fig.add_axes([box.x0 + col * box.width * 0.5, box.y0 + (1 - rindex) * box.height * 0.41 + box.height * 0.085, box.width * 0.50, box.height * 0.405])
        ax.imshow(Image.open(row["image_path"]))
        ax.axis("off")
        ax.text(0.5, -0.02, f"{row['display_formula']}\n{row['source_id'].replace('.cif','')}", transform=ax.transAxes, ha="center", va="top", fontsize=7.8)
    panel2.text(0.5, 0.01, "40 eligible CIFs • leave-target-out", ha="center", fontsize=8.5, color="#59636e")

    panel3 = fig.add_subplot(gs[0, 2]); panel3.axis("off")
    pair_styles = [("Na-O", "Na–O", "#2878B5"), ("O-Zr", "Zr–O", "#188A9A"), ("O-Si", "Si–O", "#E69F00"), ("O-P", "P–O", "#8C62AA")]
    pair_curves = [(pair, label, color, load_pot(pair)) for pair, label, color in pair_styles]
    x_min = min(float(curve[:, 0].min()) for _pair, _label, _color, curve in pair_curves)
    x_max = max(float(curve[:, 0].max()) for _pair, _label, _color, curve in pair_curves)
    y_min = min(float(curve[:, 1].min()) for _pair, _label, _color, curve in pair_curves)
    y_max = max(float(curve[:, 1].max()) for _pair, _label, _color, curve in pair_curves)
    y_pad = max((y_max - y_min) * 0.04, 0.05)
    shared_xlim = (x_min, x_max)
    shared_ylim = (y_min - y_pad, y_max + y_pad)
    panel3.set_title("3  Retrieval-conditioned SPP curves\n     (diagnostic)", loc="left", fontsize=12.5, weight="bold")
    box3 = panel3.get_position()
    grid_left = box3.x0 + box3.width * 0.06
    grid_bottom = box3.y0 + box3.height * 0.18
    grid_width = box3.width * 0.92
    grid_height = box3.height * 0.66
    col_gap = box3.width * 0.10
    row_gap = box3.height * 0.10
    plot_width = (grid_width - col_gap) / 2
    plot_height = (grid_height - row_gap) / 2
    for index, (_pair, label, color, curve) in enumerate(pair_curves):
        row, col = divmod(index, 2)
        left = grid_left + col * (plot_width + col_gap)
        bottom = grid_bottom + (1 - row) * (plot_height + row_gap)
        ax = fig.add_axes([left, bottom, plot_width, plot_height])
        ax.plot(curve[:, 0], curve[:, 1], lw=1.35, color=color)
        ax.set_xlim(shared_xlim); ax.set_ylim(shared_ylim)
        ax.set_title(label, fontsize=9.0, pad=2)
        ax.grid(color="#d7dce1", lw=0.45)
        ax.tick_params(axis="both", labelsize=6.8, length=2.5, pad=1.5)
        ax.xaxis.set_major_locator(plt.MaxNLocator(4))
        ax.yaxis.set_major_locator(plt.MaxNLocator(4))
        if col == 0:
            ax.set_ylabel("SPP score", fontsize=7.5, labelpad=2)
        else:
            ax.tick_params(labelleft=False)
        if row == 1:
            ax.set_xlabel("Distance (Å)", fontsize=7.5, labelpad=2)
        else:
            ax.tick_params(labelbottom=False)
    panel3.text(0.5, 0.015, "Diagnostic only; not a calibrated energy scale.", transform=panel3.transAxes, ha="center", fontsize=8.5, color="#59636e")

    ax4 = fig.add_subplot(gs[0, 3]); ax4.axis("off")
    ax4.set_title("4  QLIP-generated NASICON candidate", loc="left", fontsize=12.5, weight="bold")
    ax4.imshow(Image.open(candidate_png), extent=(0.02, 0.98, 0.24, 1.00), aspect="auto")
    legend = [Patch(facecolor=np.asarray(COLORS[key]) / 255, label=label) for key, label in (("Zr", "ZrO₆"), ("Si", "SiO₄"), ("P", "PO₄"))]
    legend.append(plt.Line2D([0], [0], marker="o", markersize=7.2, linestyle="", color=np.asarray(COLORS["Na"]) / 255, label="Na"))
    ax4.legend(handles=legend, frameon=False, ncol=4, loc="lower center", fontsize=8.2, markerscale=1.12, handlelength=1.5, columnspacing=1.4, bbox_to_anchor=(0.5, 0.025))
    ax4.text(0.5, 0.015, "OPTIMAL  •  Na₃Zr₂Si₂PO₁₂  •  C2  •  topology PASS", ha="center", fontsize=9.0, weight="bold")

    for left, right in zip((ax1, panel2, panel3), (panel2, panel3, ax4)):
        lbox, rbox = left.get_position(), right.get_position()
        arrow = FancyArrowPatch((lbox.x1 + 0.008, (lbox.y0 + lbox.y1) / 2), (rbox.x0 - 0.008, (rbox.y0 + rbox.y1) / 2), transform=fig.transFigure, arrowstyle="-|>", mutation_scale=13, lw=1.0, color="#6b7280")
        fig.add_artist(arrow)
    stem = FIGURE_ROOT / "nasicon_workflow_artifact_vesta"
    _save_figure(fig, stem)
    return [stem.with_suffix(suffix) for suffix in (".png", ".pdf", ".svg")]


def refresh_workflow_only() -> list[Path]:
    """Recompose the workflow figure without invoking VESTA or scientific stages."""
    manifest_path = VESTA_ROOT / "nasicon_workflow_vesta_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    protected_before = manifest["protected_scientific_artifact_hashes_before"]
    if protected_before != manifest["protected_scientific_artifact_hashes_after"]:
        raise RuntimeError("Existing manifest reports mismatched protected scientific hashes")
    actual_before = {path: sha256(Path(path)) for path in protected_before}
    if actual_before != protected_before:
        raise RuntimeError("A protected scientific artifact differs from the recorded frozen hash")

    retrieved = json.loads((VESTA_ROOT / "retrieved_manifest.json").read_text(encoding="utf-8"))
    candidate_png = VESTA_ROOT / "nasicon_candidate.png"
    fixed_visual_inputs = [candidate_png]
    fixed_visual_inputs.extend(Path(row["image_path"]) for row in retrieved)
    visual_hashes_before = {str(path): sha256(path) for path in fixed_visual_inputs}
    outputs = compose_workflow(retrieved, candidate_png)
    visual_hashes_after = {str(path): sha256(path) for path in fixed_visual_inputs}
    if visual_hashes_before != visual_hashes_after:
        raise RuntimeError("A fixed VESTA visual input changed during workflow composition")

    pair_styles = [("Na-O", "Na-O", "Na–O", "#2878B5"), ("Zr-O", "O-Zr", "Zr–O", "#188A9A"), ("Si-O", "O-Si", "Si–O", "#E69F00"), ("P-O", "O-P", "P–O", "#8C62AA")]
    pair_metadata = []
    curves = []
    for canonical_pair, source_key, display_pair, color in pair_styles:
        curve = load_pot(source_key)
        curves.append(curve)
        pot_path = RUN_ROOT / "row_specific_spp" / "spp_root" / source_key / f"{source_key}.POT"
        pair_metadata.append(
            {
                "display_pair": display_pair,
                "canonical_pair": canonical_pair,
                "source_pair_key": source_key,
                "color": color,
                "curve_count": 1,
                "point_count": int(curve.shape[0]),
                "source_artifact": str(pot_path),
                "source_sha256": sha256(pot_path),
            }
        )
    x_limits = [min(float(curve[:, 0].min()) for curve in curves), max(float(curve[:, 0].max()) for curve in curves)]
    y_min = min(float(curve[:, 1].min()) for curve in curves)
    y_max = max(float(curve[:, 1].max()) for curve in curves)
    y_pad = max((y_max - y_min) * 0.04, 0.05)
    y_limits = [y_min - y_pad, y_max + y_pad]
    for row in pair_metadata:
        row["x_limits"] = x_limits
        row["y_limits"] = y_limits

    manifest["workflow_outputs"] = [{"path": str(path), "sha256": sha256(path)} for path in outputs]
    panel3 = next(panel for panel in manifest["workflow_panels"] if panel["panel"] == 3)
    panel3.update(
        {
            "layout": "2x2 pair-specific subplots",
            "pairs": ["Na-O", "Zr-O", "Si-O", "P-O"],
            "subplot_order": ["Na–O", "Zr–O", "Si–O", "P–O"],
            "subplot_curves": pair_metadata,
            "shared_x_limits_angstrom": x_limits,
            "shared_y_limits": y_limits,
            "warning": "Diagnostic only; not a calibrated energy scale.",
        }
    )
    actual_after = {path: sha256(Path(path)) for path in protected_before}
    if actual_after != protected_before:
        raise RuntimeError("A protected scientific artifact changed during workflow composition")
    manifest["protected_scientific_artifact_hashes_after"] = actual_after
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return outputs


def compose_hero(expanded_png: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=(10.5, 6.4), facecolor="white")
    ax.imshow(Image.open(expanded_png)); ax.axis("off")
    ax.set_title("Ordered Na₃Zr₂Si₂PO₁₂ NASICON framework", fontsize=15, pad=8)
    handles = [Patch(facecolor=np.asarray(COLORS[key]) / 255, label=label) for key, label in (("Zr", "ZrO₆ octahedra"), ("Si", "SiO₄ tetrahedra"), ("P", "PO₄ tetrahedra"))]
    handles.append(plt.Line2D([0], [0], marker="o", linestyle="", color=np.asarray(COLORS["Na"]) / 255, label="Na sites"))
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=10)
    stem = FIGURE_ROOT / "nasicon_polyhedral_hero_vesta"
    _save_figure(fig, stem)
    return [stem.with_suffix(suffix) for suffix in (".png", ".pdf", ".svg")]


def compose_channel(structure: Structure, framework_png: Path, basis: np.ndarray) -> tuple[list[Path], dict[str, Any]]:
    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    na_frac = np.asarray([site.frac_coords for site in structure if site.specie.symbol == "Na"])
    shifts = [(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1)]
    expanded_frac = np.asarray([frac + [i, j, 0] for i, j in shifts for frac in na_frac])
    labels = [shift for shift in shifts for _ in na_frac]
    cart = expanded_frac @ lattice
    projected = cart @ basis[:2].T
    segments = []
    for i in range(len(cart)):
        for j in range(i + 1, len(cart)):
            distance = float(np.linalg.norm(cart[i] - cart[j]))
            if 0.1 < distance <= 4.50:
                segments.append([projected[i], projected[j]])

    boundary_frac = np.asarray([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 0]], dtype=float)
    boundary = (boundary_frac @ lattice) @ basis[:2].T
    extent_frac = np.asarray([[i, j, 0] for i in (-1, 2) for j in (-1, 2)], dtype=float)
    extent_xy = (extent_frac @ lattice) @ basis[:2].T
    xpad = (extent_xy[:, 0].max() - extent_xy[:, 0].min()) * 0.04
    ypad = (extent_xy[:, 1].max() - extent_xy[:, 1].min()) * 0.04
    extent = [extent_xy[:, 0].min() - xpad, extent_xy[:, 0].max() + xpad, extent_xy[:, 1].min() - ypad, extent_xy[:, 1].max() + ypad]

    fig, ax = plt.subplots(figsize=(8.0, 7.0), facecolor="white")
    background = Image.open(framework_png).convert("RGBA")
    bg = np.asarray(background).copy(); bg[:, :, 3] = (bg[:, :, 3].astype(float) * 0.24).astype(np.uint8)
    ax.imshow(bg, extent=extent, origin="upper", aspect="equal", zorder=0)
    ax.add_collection(LineCollection(segments, colors="#184f78", linewidths=1.45, alpha=0.80, zorder=3))
    central = np.asarray([label == (0, 0) for label in labels])
    ax.scatter(projected[~central, 0], projected[~central, 1], s=16, color="#246b9f", alpha=0.42, zorder=4)
    ax.scatter(projected[central, 0], projected[central, 1], s=58, color="#0f4c81", edgecolors="white", linewidths=0.7, zorder=5, label="Na sites in central cell")
    ax.plot(boundary[:, 0], boundary[:, 1], color="#303840", lw=1.35, zorder=6, label="central unit cell")
    ax.set_xlim(extent[:2]); ax.set_ylim(extent[2:]); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("Geometric Na-site connectivity proxy viewed along c", fontsize=14)
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    ax.text(0.01, 0.015, "Edges: Na–Na ≤ 4.50 Å. No ionic conductivity is inferred.", transform=ax.transAxes, fontsize=9.2, color="#4b5563")
    stem = FIGURE_ROOT / "nasicon_channel_view_vesta"
    _save_figure(fig, stem)
    outputs = [stem.with_suffix(suffix) for suffix in (".png", ".pdf", ".svg")]
    transform = {
        "projection": "orthographic dot product onto screen basis",
        "screen_basis_rows_cartesian": basis.tolist(),
        "fractional_to_screen_2d": (lattice @ basis[:2].T).tolist(),
        "vesta_scene_rotation_rows": basis.tolist(),
        "vesta_bounds": [-1, 2, -1, 2, 0, 1],
        "imshow_extent": extent,
        "manual_alignment": False,
    }
    return outputs, transform


def main() -> int:
    VESTA_ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    protected_scientific_paths = [
        SOURCE_CIF,
        RETRIEVAL_PATH,
        RUN_ROOT / "task.json",
        RUN_ROOT / "spp_result.json",
        RUN_ROOT / "qlip" / "solve_result.json",
        RUN_ROOT / "nasicon_topology_validation.json",
        RUN_ROOT / "crystallographic_validation.json",
        RUN_ROOT / "row_specific_spp" / "spp_root" / "manifest.json",
    ]
    scientific_hashes_before = {
        str(path): sha256(path) for path in protected_scientific_paths if path.is_file()
    }
    retrieval = json.loads(RETRIEVAL_PATH.read_text(encoding="utf-8"))
    by_rank = {int(row["rank"]): row for row in retrieval["selected"]}
    candidate_scene = VESTA_ROOT / "nasicon_candidate.vesta"
    candidate_png = VESTA_ROOT / "nasicon_candidate.png"
    create_scene_and_render(SOURCE_CIF, candidate_scene, candidate_png, bounds=(0, 1, 0, 1, 0, 1))

    expanded_scene = VESTA_ROOT / "nasicon_framework_expanded.vesta"
    expanded_png = VESTA_ROOT / "nasicon_framework_expanded.png"
    create_scene_and_render(SOURCE_CIF, expanded_scene, expanded_png, bounds=(0, 2, 0, 2, 0, 1))

    structure = Structure.from_file(SOURCE_CIF)
    basis = projection_basis(structure)
    channel_scene = VESTA_ROOT / "nasicon_framework_c_projection.vesta"
    channel_png = VESTA_ROOT / "nasicon_framework_c_projection.png"
    create_scene_and_render(SOURCE_CIF, channel_scene, channel_png, bounds=(-1, 2, -1, 2, 0, 1), rotations=(0, 0, 0), scene_rotation=basis)

    retrieved_manifest = []
    for index, rank in enumerate(SELECTED_RANKS, start=1):
        row = by_rank[rank]
        cif_path = Path(row["internal_spp_cif_path"])
        scene_path = VESTA_ROOT / f"retrieved_{index:02d}.vesta"
        image_path = VESTA_ROOT / f"retrieved_{index:02d}.png"
        create_scene_and_render(cif_path, scene_path, image_path, bounds=(0, 1, 0, 1, 0, 1))
        retrieved_manifest.append(
            {
                "retrieval_rank": rank,
                "internal_id": row["structure_id"],
                "source_id": row["source_id"],
                "formula": row.get("formula") or row.get("reduced_formula"),
                "display_formula": Structure.from_file(cif_path).composition.reduced_formula,
                "topology_tier": row.get("topology_tier"),
                "exact_target_formula": bool(row.get("exact_target_formula")),
                "cif_path": str(cif_path),
                "cif_sha256": sha256(cif_path),
                "image_path": str(image_path),
                "scene_path": str(scene_path),
            }
        )
    (VESTA_ROOT / "retrieved_manifest.json").write_text(json.dumps(retrieved_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    workflow_outputs = compose_workflow(retrieved_manifest, candidate_png)
    hero_outputs = compose_hero(expanded_png)
    channel_outputs, projection_transform = compose_channel(structure, channel_png, basis)
    settings = {
        "vesta_version": "3.5.4",
        "vesta_executable": str(VESTA_EXE),
        "vesta_executable_sha256": sha256(VESTA_EXE),
        "source_cif": str(SOURCE_CIF),
        "source_cif_sha256": sha256(SOURCE_CIF),
        "candidate_camera_rotations_deg_xyz": [18, -28, 12],
        "candidate_projection_mode": "VESTA PROJT 0 (orthographic)",
        "candidate_bounds": [0, 1, 0, 1, 0, 1],
        "expanded_bounds": [0, 2, 0, 2, 0, 1],
        "channel_transform": projection_transform,
        "bond_cutoffs_A": BOND_CUTOFFS,
        "atom_radii_A": RADII,
        "colors_rgb": COLORS,
        "polyhedron_opacity_0_255": 170,
        "oxygen_opacity_0_255": 150,
        "background": "white in VESTA; near-white converted to transparent for composition",
        "anti_aliasing": "VESTA raster export at scale=4 followed by Lanczos panel normalization",
        "vesta_panel_canvas_px": [1200, 900],
    }
    scientific_hashes_after = {
        str(path): sha256(path) for path in protected_scientific_paths if path.is_file()
    }
    if scientific_hashes_before != scientific_hashes_after:
        raise RuntimeError("A protected scientific artifact changed during figure rendering")
    manifest = {
        "schema_version": "nasicon_vesta_figure_manifest.v1",
        "source_cif": str(SOURCE_CIF),
        "source_cif_sha256": sha256(SOURCE_CIF),
        "retrieval_archive": str(RETRIEVAL_PATH),
        "retrieval_archive_sha256": sha256(RETRIEVAL_PATH),
        "retrieved_panels": retrieved_manifest,
        "workflow_panels": [
            {
                "panel": 1,
                "title": "Natural-language request",
                "source_artifact": str(RUN_ROOT / "task.json"),
                "source_sha256": sha256(RUN_ROOT / "task.json"),
            },
            {
                "panel": 2,
                "title": "Retrieved Crystal-DB evidence",
                "source_artifact": str(RETRIEVAL_PATH),
                "source_sha256": sha256(RETRIEVAL_PATH),
                "rendered_records": retrieved_manifest,
            },
            {
                "panel": 3,
                "title": "Retrieval-conditioned SPP curves (diagnostic)",
                "source_artifact": str(RUN_ROOT / "spp_result.json"),
                "source_sha256": sha256(RUN_ROOT / "spp_result.json"),
                "pairs": ["Na-O", "Zr-O", "Si-O", "P-O"],
            },
            {
                "panel": 4,
                "title": "QLIP-generated NASICON candidate",
                "source_artifact": str(SOURCE_CIF),
                "source_sha256": sha256(SOURCE_CIF),
                "vesta_scene": str(candidate_scene),
            },
        ],
        "candidate_scene": str(candidate_scene),
        "expanded_scene": str(expanded_scene),
        "channel_scene": str(channel_scene),
        "workflow_outputs": [{"path": str(path), "sha256": sha256(path)} for path in workflow_outputs],
        "hero_outputs": [{"path": str(path), "sha256": sha256(path)} for path in hero_outputs],
        "channel_outputs": [{"path": str(path), "sha256": sha256(path)} for path in channel_outputs],
        "spp_source_root": str(RUN_ROOT / "row_specific_spp" / "spp_root"),
        "spp_status": "DIAGNOSTIC_ONLY",
        "scientific_artifacts_modified": False,
        "protected_scientific_artifact_hashes_before": scientific_hashes_before,
        "protected_scientific_artifact_hashes_after": scientific_hashes_after,
    }
    (VESTA_ROOT / "nasicon_workflow_vesta_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (VESTA_ROOT / "nasicon_render_settings.json").write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    settings_md = f"""# NASICON VESTA render settings

These settings reproduce the genuine VESTA structure layers used in the NASICON paper figures. Plot annotations and the Na-channel graph are composed outside VESTA; all crystallographic framework imagery comes from the recorded VESTA scenes.

## Renderer and source

- VESTA scene format/version: 3.5.4
- Executable: `{VESTA_EXE}`
- Executable SHA-256: `{sha256(VESTA_EXE)}`
- Candidate CIF: `{SOURCE_CIF}`
- Candidate CIF SHA-256: `{sha256(SOURCE_CIF)}`
- Projection: `PROJT 0` (orthographic)
- Candidate rotations (x, y, z): 18 deg, -28 deg, 12 deg

## Scene geometry

- Candidate bounds: `[0, 1] x [0, 1] x [0, 1]`
- Expanded-framework bounds: `[0, 2] x [0, 2] x [0, 1]`
- Channel-background bounds: `[-1, 2] x [-1, 2] x [0, 1]`
- Channel view direction: crystallographic c axis; the exact Cartesian screen basis and fractional-to-screen transform are recorded in `nasicon_render_settings.json` and `nasicon_workflow_vesta_manifest.json`.

## Structural styling

- Polyhedral model (`MODEL 2`); labels and axes disabled.
- Bond/polyhedron cutoffs (angstrom): Zr-O {BOND_CUTOFFS['Zr']:.2f}, Si-O {BOND_CUTOFFS['Si']:.2f}, P-O {BOND_CUTOFFS['P']:.2f}.
- Atom radii (angstrom): Zr {RADII['Zr']:.2f}, Si {RADII['Si']:.2f}, P {RADII['P']:.2f}, Na {RADII['Na']:.2f}, O {RADII['O']:.2f}.
- Colours (RGB): Zr teal {COLORS['Zr']}, Si orange {COLORS['Si']}, P purple {COLORS['P']}, Na blue {COLORS['Na']}, O gray {COLORS['O']}.
- Polyhedron opacity: 170/255; oxygen opacity: 150/255.
- VESTA exports at 4x scale; panels are normalized with Lanczos resampling. The screen-space orientation compass is excluded from the publication crop; no crystallographic pixels are edited.

## Reproducibility

Run `python scripts/render_nasicon_vesta_figures.py` from the repository root. The `.vesta` files preserve structure, camera, bounds, bonds, colours, radii, and polyhedral display settings. Output and source hashes are recorded in the manifests and figure audit.
"""
    (VESTA_ROOT / "NASICON_VESTA_RENDER_SETTINGS.md").write_text(settings_md, encoding="utf-8")
    (ARTIFACT_ROOT / "NASICON_VESTA_RENDER_SETTINGS.md").write_text(settings_md, encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
