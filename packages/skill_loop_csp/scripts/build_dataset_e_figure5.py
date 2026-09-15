"""Build Figure 5 from genuine VESTA renders of frozen Dataset E outputs."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import matplotlib.pyplot as plt
from PIL import Image, ImageChops
from pymatgen.io.cif import CifWriter


REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sok_llm_orchestrator.workflow.dataset_e_validation import (  # noqa: E402
    load_development_references,
)
from sok_llm_orchestrator.workflow.row_visualization import render_vesta  # noqa: E402


ARTIFACT = REPO / "artifacts" / "Paper_scaffolds_september" / "Dataset_E_complex_topology_showcase"
RESULTS = ARTIFACT / "FINAL_DATASET_E_RESULTS.csv"
FIGURE_ROOT = ARTIFACT / "figure5"
VESTA = Path(r"C:\Users\brown\Documents\VESTA-win64\VESTA-win64\VESTA.exe")
PUBLICATION = REPO / "artifacts" / "Paper_scaffolds_september" / "publication_figures_v2" / "main"
SELECTION = {
    "NASICON / NZP": [
        "E_NASICON_R3_PHOSPHATE_01",
        "E_NASICON_R3_PHOSPHATE_02",
        "E_NASICON_R3_PHOSPHATE_03",
    ],
    "Ruddlesden-Popper": ["E_RP_N1_01", "E_RP_N2_01", "E_RP_N2_02"],
    "Garnet": ["E_GARNET_IA3D_01", "E_GARNET_IA3D_02", "E_GARNET_I41ACD_01"],
    "Argyrodite": [
        "E_ARGYRODITE_F43M_01",
        "E_ARGYRODITE_PNA21_01",
        "E_ARGYRODITE_CC_01",
    ],
}
SCAFFOLDS = {
    "NASICON / NZP": ["NASICON_R3_PHOSPHATE"],
    "Ruddlesden-Popper": ["RP_N1", "RP_N2"],
    "Garnet": ["GARNET_IA3D", "GARNET_I41ACD"],
    "Argyrodite": ["ARGYRODITE_F43M", "ARGYRODITE_PNA21", "ARGYRODITE_CC"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows() -> dict[str, dict[str, str]]:
    with RESULTS.open(newline="", encoding="utf-8-sig") as handle:
        values = {row["row_id"]: row for row in csv.DictReader(handle)}
    for row_id in [item for group in SELECTION.values() for item in group]:
        row = values[row_id]
        if row["post_topology_status"] != "PASS" or row["chgnet_converged"].lower() != "true":
            raise RuntimeError(f"Figure 5 selection is not post-CHGNet PASS: {row_id}")
    return values


def trim(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    background = Image.new("RGB", image.size, (255, 255, 255))
    box = ImageChops.difference(image, background).convert("L").point(
        lambda value: 255 if value > 12 else 0
    ).getbbox()
    if box is None:
        return image
    left, top, right, bottom = box
    pad = 18
    return image.crop(
        (
            max(0, left - pad),
            max(0, top - pad),
            min(image.width, right + pad),
            min(image.height, bottom + pad),
        )
    )


def main() -> int:
    if not VESTA.is_file():
        raise FileNotFoundError(f"VESTA executable is required: {VESTA}")
    data = rows()
    cache = FIGURE_ROOT / "vesta_cache"
    scaffold_cifs = FIGURE_ROOT / "scaffold_cifs"
    scaffold_cifs.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": "dataset_e.figure5_manifest.v1",
        "title": "Scaffold-guided generation extends to complex crystal topologies",
        "results_sha256": sha256(RESULTS),
        "vesta_executable": str(VESTA),
        "vesta_executable_sha256": sha256(VESTA),
        "panels": [],
    }
    rendered_scaffolds: dict[str, list[tuple[str, Path]]] = {}
    for family, subtypes in SCAFFOLDS.items():
        rendered_scaffolds[family] = []
        for subtype in subtypes:
            reference_id, structure = load_development_references(subtype)[0]
            cif = scaffold_cifs / f"{subtype}.cif"
            CifWriter(structure).write_file(cif)
            png, provenance = render_vesta(cif, cache, str(VESTA))
            rendered_scaffolds[family].append((subtype, png))
            manifest["panels"].append(
                {
                    "panel_type": "reusable_development_scaffold",
                    "family": family,
                    "subtype": subtype,
                    "development_reference_id": reference_id,
                    "source_cif": str(cif),
                    "source_cif_sha256": sha256(cif),
                    "vesta": provenance,
                }
            )
    rendered_outputs: dict[str, Path] = {}
    for family, row_ids in SELECTION.items():
        for row_id in row_ids:
            row = data[row_id]
            cif = Path(row["relaxed_cif"])
            png, provenance = render_vesta(cif, cache, str(VESTA))
            rendered_outputs[row_id] = png
            manifest["panels"].append(
                {
                    "panel_type": "post_chgnet_generated_candidate",
                    "family": family,
                    "row_id": row_id,
                    "formula": row["formula"],
                    "subtype": row["subtype"],
                    "post_topology_status": row["post_topology_status"],
                    "source_cif": str(cif),
                    "source_cif_sha256": sha256(cif),
                    "vesta": provenance,
                }
            )

    figure = plt.figure(figsize=(14.2, 13.2), facecolor="white")
    grid = figure.add_gridspec(4, 4, left=0.055, right=0.985, top=0.90, bottom=0.075, wspace=0.10, hspace=0.31)
    colors = ["#0f6b78", "#9a5b13", "#6c4c91", "#37794d"]
    for row_index, (family, row_ids) in enumerate(SELECTION.items()):
        scaffold_axis = figure.add_subplot(grid[row_index, 0])
        scaffold_axis.set_axis_off()
        items = rendered_scaffolds[family]
        heights = [1 / len(items)] * len(items)
        y = 1.0
        for (subtype, png), height in zip(items, heights, strict=True):
            inset = scaffold_axis.inset_axes([0.01, y - height + 0.01, 0.98, height - 0.035])
            inset.imshow(trim(png))
            inset.set_axis_off()
            inset.text(
                0.02,
                0.04,
                subtype.replace("ARGYRODITE_", "").replace("GARNET_", "").replace("RP_", ""),
                transform=inset.transAxes,
                fontsize=7.5,
                color="#33444d",
                bbox={"facecolor": "white", "alpha": 0.84, "edgecolor": "none", "pad": 1.5},
            )
            y -= height
        scaffold_axis.set_title("Reusable topology scaffold(s)", fontsize=9.2, fontweight="bold", pad=8)
        scaffold_axis.text(
            -0.05,
            1.14,
            family,
            transform=scaffold_axis.transAxes,
            fontsize=13,
            fontweight="bold",
            color=colors[row_index],
        )
        scaffold_axis.text(
            1.025,
            0.5,
            "→",
            transform=scaffold_axis.transAxes,
            ha="center",
            va="center",
            fontsize=24,
            fontweight="bold",
            color=colors[row_index],
            clip_on=False,
        )
        for column, row_id in enumerate(row_ids, start=1):
            axis = figure.add_subplot(grid[row_index, column])
            axis.imshow(trim(rendered_outputs[row_id]))
            axis.set_axis_off()
            row = data[row_id]
            short_subtype = row["subtype"].replace("ARGYRODITE_", "").replace("GARNET_", "").replace("RP_", "")
            axis.set_title(row["formula"].replace(" ", ""), fontsize=10, fontweight="bold", pad=5)
            axis.text(
                0.5,
                -0.055,
                f"{short_subtype}  •  post-CHGNet {row['post_topology_status']}",
                transform=axis.transAxes,
                ha="center",
                va="top",
                fontsize=7.8,
                color="#33444d",
            )
    figure.suptitle(
        "Scaffold-guided generation extends to complex crystal topologies",
        fontsize=18,
        fontweight="bold",
        y=0.965,
        color="#17232b",
    )
    figure.text(
        0.5,
        0.925,
        "Development-derived reusable ordered scaffolds  →  target-excluded SPP-guided QLIP  →  relaxed generated crystals",
        ha="center",
        fontsize=10,
        color="#52616b",
    )
    figure.text(
        0.5,
        0.025,
        "Full frozen denominator: generation 18/18; exact composition 18/18; pre-topology PASS 18/18; CHGNet converged 18/18; post-topology PASS 18/18. All crystal panels are genuine VESTA renders.",
        ha="center",
        fontsize=9,
        color="#33444d",
    )
    FIGURE_ROOT.mkdir(parents=True, exist_ok=True)
    outputs = []
    for suffix in ("png", "pdf", "svg"):
        path = FIGURE_ROOT / f"Figure5_complex_topology_showcase.{suffix}"
        figure.savefig(path, dpi=300 if suffix == "png" else None, bbox_inches="tight", facecolor="white")
        outputs.append({"path": str(path), "sha256": sha256(path)})
    plt.close(figure)
    PUBLICATION.mkdir(parents=True, exist_ok=True)
    for item in outputs:
        source = Path(item["path"])
        destination = PUBLICATION / source.name
        destination.write_bytes(source.read_bytes())
    selection_rows = [
        {"family_panel": family, **data[row_id]} for family, row_ids in SELECTION.items() for row_id in row_ids
    ]
    with (FIGURE_ROOT / "FIGURE5_SELECTED_ROWS.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(selection_rows[0]))
        writer.writeheader()
        writer.writerows(selection_rows)
    manifest["outputs"] = outputs
    manifest["full_denominator"] = 18
    manifest["displayed_generated_rows"] = 12
    manifest["scientific_inputs_changed"] = False
    (FIGURE_ROOT / "FIGURE5_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
