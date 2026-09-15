"""Build a provenance-complete spinel scaffold-generalisation figure.

This is a read-only scientific visualisation step: it consumes frozen v2
artifacts and persisted CIFs, invokes VESTA only for raster rendering, and does
not run generation, SPP, QLIP, SCA, or CHGNet.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image, ImageChops


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sok_llm_orchestrator.workflow.row_visualization import render_vesta  # noqa: E402


V2 = ROOT / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2"
PUB = ROOT / "artifacts" / "Paper_scaffolds_september" / "publication_figures_v2"
MAIN = PUB / "main"
FIGURE_DATA = PUB / "figure_data"
WORK = PUB / "scaffold_generalisation_visual"
VESTA = Path(r"C:\Users\brown\Documents\VESTA-win64\VESTA-win64\VESTA.exe")
OUT_STEM = MAIN / "Figure_scaffold_generalisation_visual"
DATA_OUT = FIGURE_DATA / "Figure_scaffold_generalisation_visual_data.csv"
SOURCE_MAP = FIGURE_DATA / "FIGURE_SOURCE_MAP.csv"
AUDIT = PUB / "FIGURE_AUDIT.md"

SOURCE_HASHES = {
    ROOT / "src" / "sok_llm_orchestrator" / "workflow" / "paper_scaffolds_library_v2.py":
        "80430d1620b344b147658598bb99f1e6df191fd4d4c7821c6dc648abb7f46f29",
    V2 / "spp_ablation" / "SPP_V2_ABLATION_RESULTS.csv":
        "c3975138a89241ce6aacfe770fb95fdb2a68df011535959b6e769a368cec22c4",
    V2 / "final_holdout" / "V2_HOLDOUT_RESULTS.csv":
        "11063f77ddb912405403bd4c6187a13fa3fd09b5989f932ad7d5bb6c80f476ac",
}

DEV_KEYS = [
    ("S01_SP_Zn_SbO2_2", "request"),
    ("S01_SP_Zn_SbO2_2", "global"),
    ("S06_SP_MgMn2O4", "request"),
    ("S06_SP_MgMn2O4", "global"),
]
HOLDOUT_IDS = [
    "V2H_SPINEL_01", "V2H_SPINEL_02", "V2H_SPINEL_03", "V2H_SPINEL_04",
    "V2H_SPINEL_05", "V2H_SPINEL_07", "V2H_SPINEL_08", "V2H_SPINEL_10",
]

INK = "#172a34"
MUTED = "#586a73"
TEAL = "#0d6f78"
BLUE = "#2a678c"
GOLD = "#b47a18"
GREEN = "#2e7d5a"
RED = "#aa4b46"
PAPER = "#fbfcfc"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def trim(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    background = Image.new("RGB", image.size, "white")
    mask = ImageChops.difference(image, background).convert("L").point(
        lambda value: 255 if value > 12 else 0
    )
    box = mask.getbbox()
    if box is None:
        return image
    left, top, right, bottom = box
    pad = 16
    return image.crop((max(0, left - pad), max(0, top - pad),
                       min(image.width, right + pad), min(image.height, bottom + pad)))


def formula_text(value: str) -> str:
    subs = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
    return value.translate(subs)


def image_axis(ax: Any, image_path: Path, title: str, subtitle: str, *, status: str = "") -> None:
    ax.imshow(trim(image_path))
    ax.set_axis_off()
    ax.set_title(title, fontsize=9.1, color=INK, fontweight="bold", pad=2.5)
    ax.text(0.5, -0.025, subtitle, transform=ax.transAxes, ha="center", va="top",
            fontsize=6.7, color=MUTED, linespacing=1.15)
    if status:
        color = GREEN if status == "PASS" else GOLD
        ax.text(0.98, 0.96, status, transform=ax.transAxes, ha="right", va="top",
                fontsize=6.5, fontweight="bold", color="white",
                bbox={"boxstyle": "round,pad=0.25", "facecolor": color,
                      "edgecolor": "none", "alpha": 0.95})


def panel_label(fig: Any, x: float, text: str, color: str) -> None:
    fig.text(x, 0.895, text, fontsize=9.5, fontweight="bold", color="white",
             ha="left", va="center",
             bbox={"boxstyle": "round,pad=0.42", "facecolor": color, "edgecolor": "none"})


def render_records() -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]]:
    for path, expected in SOURCE_HASHES.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"frozen source hash mismatch: {path} ({actual})")
    if not VESTA.is_file():
        raise FileNotFoundError(f"VESTA executable is required: {VESTA}")

    scaffold_cif = PUB / "vesta" / "scaffold_prototypes" / "spinel_scaffold.cif"
    scaffold_png = PUB / "vesta_renders" / "scaffold_prototypes" / "spinel_scaffold.png"
    scaffold_prov = scaffold_png.with_suffix(".json")
    if not scaffold_cif.is_file() or not scaffold_png.is_file() or not scaffold_prov.is_file():
        raise FileNotFoundError("frozen VESTA spinel scaffold render/provenance is incomplete")
    if json.loads(scaffold_prov.read_text(encoding="utf-8"))["renderer"].split()[0] != "genuine":
        raise RuntimeError("spinel scaffold is not a genuine VESTA render")

    ablation_rows = read_csv(V2 / "spp_ablation" / "SPP_V2_SCA_CHGNET_RESULTS.csv")
    dev: list[dict[str, Any]] = []
    cache = WORK / "vesta_renders"
    for row_id, condition in DEV_KEYS:
        row = next(row for row in ablation_rows if row["row_id"] == row_id
                   and row["condition"] == condition and row["stage"] == "pre_chgnet")
        condition_result = json.loads((ROOT / "outputs" / "Paper_scaffolds_september" /
                                       "scaffold_v2_ablation" / row_id / condition / "result.json").read_text(encoding="utf-8"))
        winner = condition_result["winner"]
        if winner["alternative_id"] != row["selected_alternative"]:
            raise RuntimeError(f"development selection mismatch: {row_id}/{condition}")
        cif = Path(row["cif_path"])
        if sha256(cif) != row["cif_sha256"]:
            raise RuntimeError(f"development CIF hash mismatch: {row_id}/{condition}")
        png, provenance = render_vesta(cif, cache, str(VESTA))
        dev.append({**row, "selected_internal_parameter": winner["internal_parameter"],
                    "selected_vpa_A3_per_atom": winner["vpa_A3_per_atom"],
                    "render_path": str(png), "render_sha256": sha256(png),
                    "renderer": provenance["renderer"], "source_role": "development_ablation"})

    holdout_rows = read_csv(V2 / "final_holdout" / "V2_HOLDOUT_RESULTS.csv")
    spinel_post = [row for row in holdout_rows if row["policy"] == "SPINEL"
                   and row["stage"] == "post_chgnet"]
    if len(spinel_post) != 10:
        raise RuntimeError(f"expected 10 post-CHGNet spinel rows, found {len(spinel_post)}")
    verdicts = {name: sum(row["sca_topology_status"] == name for row in spinel_post)
                for name in ("PASS", "PARTIAL")}
    if verdicts != {"PASS": 9, "PARTIAL": 1}:
        raise RuntimeError(f"unexpected frozen spinel denominator: {verdicts}")
    if any(row["chgnet_converged"].lower() != "true" for row in spinel_post):
        raise RuntimeError("not all frozen spinel holdout relaxations converged")

    holdout: list[dict[str, Any]] = []
    by_id = {row["row_id"]: row for row in spinel_post}
    for row_id in HOLDOUT_IDS:
        row = by_id[row_id]
        cif = Path(row["cif_path"])
        if sha256(cif) != row["cif_sha256"]:
            raise RuntimeError(f"holdout CIF hash mismatch: {row_id}")
        png, provenance = render_vesta(cif, cache, str(VESTA))
        holdout.append({**row, "render_path": str(png), "render_sha256": sha256(png),
                        "renderer": provenance["renderer"], "source_role": "unseen_holdout_post_chgnet"})
    return scaffold_png, dev, holdout


def build_figure(scaffold_png: Path, dev: list[dict[str, Any]], holdout: list[dict[str, Any]]) -> None:
    MAIN.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(20, 10.4), facecolor=PAPER)
    outer = fig.add_gridspec(1, 3, width_ratios=[2.7, 4.9, 9.6], left=0.035, right=0.985,
                             top=0.85, bottom=0.105, wspace=0.13)

    fig.suptitle("One frozen spinel scaffold generalises across unseen chemistries",
                 x=0.035, y=0.972, ha="left", fontsize=20, fontweight="bold", color=INK)
    fig.text(0.035, 0.928,
             "Fixed topology envelope → discrete chemistry-dependent realisations → final relaxed unseen holdout",
             ha="left", fontsize=11.2, color=MUTED)
    panel_label(fig, 0.035, "1  FROZEN SCAFFOLD", TEAL)
    panel_label(fig, 0.196, "2  DEVELOPMENT: REAL PERSISTED SELECTIONS", BLUE)
    panel_label(fig, 0.444, "3  UNSEEN CHEMISTRY (AFTER METHOD FREEZE)", GREEN)

    left = outer[0, 0].subgridspec(2, 1, height_ratios=[1.42, 1.0], hspace=0.06)
    ax = fig.add_subplot(left[0, 0])
    ax.imshow(trim(scaffold_png)); ax.set_axis_off()
    ax.set_title("SPINEL  •  56-site Fd-3m envelope", fontsize=11, fontweight="bold", color=INK, pad=5)
    ax.text(0.02, 0.03, "VESTA rendering of the frozen\nZn–Fe–O visibility prototype",
            transform=ax.transAxes, fontsize=6.8, color=MUTED,
            bbox={"facecolor": "white", "alpha": 0.88, "edgecolor": "none", "pad": 2})
    notes = fig.add_subplot(left[1, 0]); notes.set_axis_off()
    notes.add_patch(FancyBboxPatch((0.0, 0.05), 1.0, 0.91, boxstyle="round,pad=0.018",
                                  transform=notes.transAxes, facecolor="#eef7f7", edgecolor="#a9ced0"))
    notes.text(0.055, 0.86, "HARD — fixed by construction", fontsize=9, fontweight="bold", color=TEAL,
               transform=notes.transAxes)
    notes.text(0.055, 0.77,
               "tet₈ₐ  8 sites\noct ordered a  8 sites\noct ordered b  8 sites\nanion₃₂ₑ  32 sites",
               fontsize=8.1, color=INK, va="top", linespacing=1.45, transform=notes.transAxes)
    notes.text(0.055, 0.42, "FREE — selected discretely", fontsize=9, fontweight="bold", color=GOLD,
               transform=notes.transAxes)
    notes.text(0.055, 0.33,
               "3 evidence-derived cell scales\n3 oxygen u values: .375 / .386 / .397\n3 ordered occupations",
               fontsize=8.1, color=INK, va="top", linespacing=1.45, transform=notes.transAxes)
    notes.text(0.055, 0.08, "27 topology-valid realisations per composition",
               fontsize=8.2, fontweight="bold", color=TEAL, transform=notes.transAxes)

    middle = outer[0, 1].subgridspec(2, 2, hspace=0.33, wspace=0.08)
    for index, row in enumerate(dev):
        ax = fig.add_subplot(middle[index // 2, index % 2])
        cond = row["condition"].upper()
        order = "normal" if row["spinel_ordering"] == "NORMAL" else "ordered inverse"
        subtitle = (f"{cond} SPP  •  {order}\n{row['selected_alternative']}  •  "
                    f"u {float(row['selected_internal_parameter']):.3f}  •  {row['space_group']}  •  {row['sca_topology_status']}")
        image_axis(ax, Path(row["render_path"]), formula_text(row["formula"]), subtitle)
    fig.text(0.311, 0.11,
             "Frozen 12-row ablation: request SPP selected normal while global SPP selected ordered inverse in 3/3 spinels.",
             ha="center", va="bottom", fontsize=7.2, color=MUTED)

    right = outer[0, 2].subgridspec(2, 4, hspace=0.31, wspace=0.05)
    for index, row in enumerate(holdout):
        ax = fig.add_subplot(right[index // 4, index % 4])
        order = "normal" if row["spinel_ordering"] == "NORMAL" else "ordered inverse"
        subtitle = (f"{row['row_id']}  •  {order}\n"
                    f"{row['space_group']}  •  ΔV {float(row['volume_change_percent']):+.1f}%")
        image_axis(ax, Path(row["render_path"]), formula_text(row["formula"]), subtitle,
                   status=row["sca_topology_status"])

    boundary_x = 0.424
    fig.add_artist(plt.Line2D([boundary_x, boundary_x], [0.095, 0.875], transform=fig.transFigure,
                              color="#314955", linewidth=2.2, linestyle=(0, (4, 3))))
    fig.text(boundary_x, 0.87, "METHOD FREEZE", rotation=90, ha="center", va="top", fontsize=7.5,
             color="white", fontweight="bold",
             bbox={"boxstyle": "round,pad=0.35", "facecolor": "#314955", "edgecolor": "none"})
    for x0, x1 in ((0.17, 0.19), (0.402, 0.423), (0.425, 0.445)):
        fig.add_artist(FancyArrowPatch((x0, 0.50), (x1, 0.50), transform=fig.transFigure,
                                      arrowstyle="-|>", mutation_scale=15, linewidth=1.5,
                                      color="#71858e"))

    fig.text(0.714, 0.054, "FULL FROZEN SPINEL DENOMINATOR  •  10/10 CHGNet converged  •  9 PASS + 1 PARTIAL",
             ha="center", fontsize=10.3, fontweight="bold", color=INK,
             bbox={"boxstyle": "round,pad=0.50", "facecolor": "#e8f4ed", "edgecolor": "#aad0b9"})
    fig.text(0.714, 0.019,
             "Gallery shows 8/10 final relaxed CIFs. EuY₂O₄ is retained as PARTIAL: ordered-inverse Imma hard network; the frozen SCA policy assumes minority-cation tetrahedral exclusivity.",
             ha="center", fontsize=7.4, color=MUTED)
    fig.text(0.035, 0.019,
             "Topology is guaranteed only at scaffold construction; post-CHGNet retention is empirical. No disorder, partial occupancy, target coordinates, or target lattice constants were used.",
             ha="left", fontsize=7.2, color=MUTED)

    for suffix in ("png", "pdf", "svg"):
        kwargs = {"dpi": 360} if suffix == "png" else {}
        fig.savefig(OUT_STEM.with_suffix(f".{suffix}"), facecolor=PAPER, bbox_inches="tight", **kwargs)
    plt.close(fig)


def write_data(scaffold_png: Path, dev: list[dict[str, Any]], holdout: list[dict[str, Any]]) -> None:
    FIGURE_DATA.mkdir(parents=True, exist_ok=True)
    scaffold_cif = PUB / "vesta" / "scaffold_prototypes" / "spinel_scaffold.cif"
    records: list[dict[str, Any]] = [{
        "visual_role": "frozen_scaffold", "cohort": "development", "row_id": "SPINEL_V2_SCAFFOLD",
        "formula": "Zn(FeO2)2 visibility prototype", "condition": "not_applicable", "stage": "scaffold",
        "alternative": "paper_scaffolds_library.v2", "oxygen_u": "0.375 visibility prototype",
        "selected_vpa_A3_per_atom": "not_applicable_visibility_prototype",
        "ordering": "site-class envelope", "space_group": "Fd-3m", "topology_status": "construction envelope",
        "chgnet_converged": "not_applicable", "source_cif": str(scaffold_cif),
        "source_cif_sha256": sha256(scaffold_cif), "vesta_render": str(scaffold_png),
        "vesta_render_sha256": sha256(scaffold_png), "renderer": "genuine VESTA 3.x",
        "display_note": "prototype species provide VESTA visibility; labels report actual frozen orbit classes",
    }]
    for row in dev:
        records.append({
            "visual_role": "persisted_development_selection", "cohort": "development",
            "row_id": row["row_id"], "formula": row["formula"], "condition": row["condition"],
            "stage": row["stage"], "alternative": row["selected_alternative"],
            "oxygen_u": row["selected_internal_parameter"],
            "selected_vpa_A3_per_atom": row["selected_vpa_A3_per_atom"],
            "ordering": row["spinel_ordering"], "space_group": row["space_group"],
            "topology_status": row["sca_topology_status"], "chgnet_converged": "not_applicable_pre_chgnet",
            "source_cif": row["cif_path"], "source_cif_sha256": row["cif_sha256"],
            "vesta_render": row["render_path"], "vesta_render_sha256": row["render_sha256"],
            "renderer": row["renderer"], "display_note": "frozen request-versus-global ablation selection",
        })
    for row in holdout:
        records.append({
            "visual_role": "unseen_holdout_example", "cohort": "unseen_holdout",
            "row_id": row["row_id"], "formula": row["formula"], "condition": "request_spp",
            "stage": row["stage"], "alternative": row["selected_alternative"],
            "oxygen_u": row["selected_internal_parameter"], "ordering": row["spinel_ordering"],
            "selected_vpa_A3_per_atom": row["selected_vpa_A3_per_atom"],
            "space_group": row["space_group"], "topology_status": row["sca_topology_status"],
            "chgnet_converged": row["chgnet_converged"], "source_cif": row["cif_path"],
            "source_cif_sha256": row["cif_sha256"], "vesta_render": row["render_path"],
            "vesta_render_sha256": row["render_sha256"], "renderer": row["renderer"],
            "display_note": f"final CHGNet-relaxed CIF; volume change {row['volume_change_percent']}%",
        })
    fields = list(records[0])
    with DATA_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(records)


def update_source_map() -> None:
    rows = read_csv(SOURCE_MAP)
    # A legacy source-map row can contain an unquoted comma, which DictReader
    # preserves under the None key. Fold such overflow back into notes. If an
    # interrupted prior write left an incomplete map, restore the complete v1
    # map (the v2 package is its superset) before adding v2-only entries.
    if len(rows) < 10:
        seed = ROOT / "artifacts" / "Paper_scaffolds_september" / "publication_figures" / "figure_data" / "FIGURE_SOURCE_MAP.csv"
        rows = read_csv(seed)
    for row in rows:
        overflow = row.pop(None, None)
        if overflow:
            row["notes"] = ",".join([row.get("notes", ""), *overflow]).strip(",")
    if not any(row["figure"] == "Figure 5" for row in rows):
        rows.append({
            "figure": "Figure 5", "panel": "A-D",
            "visual_element": "complex-topology scaffold-to-candidate showcase",
            "dataset": "Dataset E frozen audited outputs",
            "row_ids": "E_NASICON_R3_PHOSPHATE_01;E_ARGYRODITE_F43M_01; audited RP and garnet families",
            "source_artifact": "Dataset_E_complex_topology_showcase/FINAL_DATASET_E_RESULTS.csv; DATASET_E_FINAL_REPORT.md",
            "source_columns": "row_id; family; formula; final_topology_status; relaxed_cif; chgnet_converged",
            "transformation": "genuine VESTA renders for shown structures; audited-not-shown notices retained",
            "notes": "Dataset E publication figure; no scientific rerun",
        })
    figure_name = "Figure scaffold generalisation visual"
    rows = [row for row in rows if row["figure"] != figure_name]
    rows.extend([
        {"figure": figure_name, "panel": "1", "visual_element": "frozen v2 spinel scaffold VESTA render + orbit/freedom labels",
         "dataset": "v2 method freeze", "row_ids": "SPINEL_V2_SCAFFOLD",
         "source_artifact": "scaffold_v2/V2_METHOD_FREEZE.json; src/sok_llm_orchestrator/workflow/paper_scaffolds_library_v2.py; publication_figures_v2/vesta/scaffold_prototypes/spinel_scaffold.cif",
         "source_columns": "geometry_candidates; source hash; tet_8a/oct_ordered_a/oct_ordered_b/anion_32e",
         "transformation": "genuine VESTA render; matplotlib labels only",
         "notes": "56 sites; 3 cell scales x 3 u values x 3 occupations = 27"},
        {"figure": figure_name, "panel": "2", "visual_element": "four persisted development request/global selections",
         "dataset": "v2 frozen SPP ablation", "row_ids": "S01_SP_Zn_SbO2_2 request/global; S06_SP_MgMn2O4 request/global",
         "source_artifact": "scaffold_v2/spp_ablation/SPP_V2_SCA_CHGNET_RESULTS.csv; persisted selected CIFs",
         "source_columns": "condition; selected_alternative; spinel_ordering; cif_path; cif_sha256; sca_topology_status",
         "transformation": "genuine VESTA renders; no scientific recomputation",
         "notes": "request normal versus global ordered inverse; PARTIAL verdicts retained in data"},
        {"figure": figure_name, "panel": "3", "visual_element": "eight final relaxed unseen spinel examples + full denominator",
         "dataset": "v2 unseen holdout", "row_ids": ";".join(HOLDOUT_IDS),
         "source_artifact": "scaffold_v2/final_holdout/V2_HOLDOUT_RESULTS.csv; final CHGNet-relaxed CIFs",
         "source_columns": "row_id; formula; cif_path; cif_sha256; spinel_ordering; space_group; sca_topology_status; chgnet_converged",
         "transformation": "genuine VESTA renders; deterministic 8-of-10 display selection",
         "notes": "full denominator printed: 10/10 converged; 9 PASS + 1 PARTIAL; EuY2O4 PARTIAL shown"},
    ])
    fields = list(rows[0])
    temporary = SOURCE_MAP.with_suffix(".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(SOURCE_MAP)


def update_audit() -> None:
    marker = "## 11. Scaffold-generalisation visual"
    text = AUDIT.read_text(encoding="utf-8")
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    section = f"""

{marker}

- Exact object: frozen flexible v2 SPINEL scaffold, `paper_scaffolds_library.v2`;
  source SHA-256 `80430d1620b344b147658598bb99f1e6df191fd4d4c7821c6dc648abb7f46f29`.
- Scaffold panel is the genuine VESTA render of the frozen 56-site visibility
  prototype. Its labels are derived from the real orbit definition: 8 `tet_8a`,
  8 `oct_ordered_a`, 8 `oct_ordered_b`, and 32 `anion_32e` sites.
- Development panel uses four real persisted selected CIFs from the frozen SPP
  ablation (Zn(SbO2)2 and MgMn2O4, request/global). No structure was reconstructed.
- Unseen panel uses eight authoritative final CHGNet-relaxed CIFs. It includes
  `V2H_SPINEL_08` EuY2O4 as `PARTIAL`; the full outcome is printed as 10/10
  converged, 9 `PASS` + 1 `PARTIAL`.
- Every crystal/scaffold image was produced by genuine VESTA. Matplotlib is used
  only for composition, text, arrows, badges, and the method-freeze boundary.
- Frozen input hashes were asserted before rendering. No generation, SPP, QLIP,
  SCA, CHGNet, DFT, or other scientific calculation was rerun; no frozen
  scientific artifact was modified.
- Figure files: `main/Figure_scaffold_generalisation_visual.{{png,pdf,svg}}`.
- Figure data: `figure_data/Figure_scaffold_generalisation_visual_data.csv`.
"""
    AUDIT.write_text(text.rstrip() + section + "\n", encoding="utf-8")


def main() -> int:
    before = {str(path): sha256(path) for path in SOURCE_HASHES}
    scaffold_png, dev, holdout = render_records()
    build_figure(scaffold_png, dev, holdout)
    write_data(scaffold_png, dev, holdout)
    update_source_map()
    update_audit()
    after = {str(path): sha256(path) for path in SOURCE_HASHES}
    if before != after:
        raise RuntimeError("a frozen scientific input changed during figure construction")
    print(json.dumps({
        "outputs": [str(OUT_STEM.with_suffix(f".{suffix}")) for suffix in ("png", "pdf", "svg")],
        "data": str(DATA_OUT), "development_renders": [row["render_path"] for row in dev],
        "holdout_renders": [row["render_path"] for row in holdout],
        "frozen_hashes_unchanged": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
