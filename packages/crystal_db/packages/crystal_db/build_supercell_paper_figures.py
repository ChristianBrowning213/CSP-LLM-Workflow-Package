"""Render display-only supercell editions of the workflow and crystal gallery."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ase.io import read as ase_read
from ase.io import write as ase_write
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed" / "results"
WORKFLOW_SOURCE = RESULTS / "paper_workflow_li2feo3"
WORKFLOW_OUT = RESULTS / "paper_figures" / "figure_1_li2feo3_workflow_supercell"
GALLERY_OUT = RESULTS / "paper_figures" / "figure_2_gallery_supercell"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_li2feo3_workflow_figure as vesta_tools  # noqa: E402


GALLERY = (
    (1, "layered", "Na3Ni2O5", "layered-repaired-021"),
    (2, "layered", "Na4Mg(NiO2)5", "layered-repaired-013"),
    (3, "layered", "NaV2O5", "layered-repaired-020"),
    (4, "layered", "Li2FeO3", "layered-repaired-041"),
    (5, "spinel", "Mn2NiO4", "spinel-repaired-041"),
    (6, "spinel", "Zn(IrO2)2", "spinel-repaired-015"),
    (7, "spinel", "NaMn2O4", "spinel-repaired-040"),
    (8, "spinel", "NaTi2O4", "spinel-repaired-046"),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def select_repeat(atom_count: int, family: str) -> tuple[int, int, int]:
    candidates = ((1, 1, 1), (1, 1, 2), (1, 1, 3), (2, 2, 1), (2, 2, 2)) if family == "layered" else (
        (1, 1, 1), (2, 2, 1), (2, 2, 2)
    )
    valid = [repeat for repeat in candidates if 36 <= atom_count * repeat[0] * repeat[1] * repeat[2] <= 96]
    pool = valid or list(candidates)
    return min(pool, key=lambda repeat: (abs(atom_count * repeat[0] * repeat[1] * repeat[2] - 48), candidates.index(repeat)))


def prepare_and_render(*, source: Path, out_dir: Path, render_id: str, role: str,
                       formula: str, family: str) -> dict[str, Any]:
    source_hash = sha(source)
    atoms = ase_read(source)
    repeat = select_repeat(len(atoms), family)
    derived = out_dir / "display_supercells" / f"{render_id}_{repeat[0]}x{repeat[1]}x{repeat[2]}.cif"
    derived.parent.mkdir(parents=True, exist_ok=True)
    ase_write(derived, atoms.repeat(repeat), format="cif")
    vesta_tools.VESTA_ASSETS = out_dir / "vesta_renders"
    render = vesta_tools.render_vesta(derived, render_id, role, formula)
    if sha(source) != source_hash:
        raise RuntimeError(f"raw CIF changed during supercell visualization: {source}")
    return {
        "render_id": render_id, "role": role, "family": family, "formula": formula,
        "raw_source_cif": str(source.resolve()), "raw_source_sha256_before": source_hash,
        "raw_source_sha256_after": sha(source), "raw_source_unchanged": True,
        "source_atom_count": len(atoms), "repeat_a": repeat[0], "repeat_b": repeat[1], "repeat_c": repeat[2],
        "display_atom_count": len(atoms) * repeat[0] * repeat[1] * repeat[2],
        "derived_supercell_cif": str(derived.resolve()), "derived_supercell_sha256": sha(derived),
        "renderer": "VESTA", "polished_render": render["polished_render"],
        "polished_render_sha256": render["polished_render_sha256"],
        "rotation_x_deg": 18, "rotation_y_deg": -28, "rotation_z_deg": 8,
    }


def image_panel(ax, row: dict[str, Any], label: str) -> None:
    with Image.open(row["polished_render"]) as image:
        ax.imshow(image.convert("RGBA"))
    ax.set_axis_off()
    repeat = f"{row['repeat_a']}×{row['repeat_b']}×{row['repeat_c']}"
    ax.text(0.5, -0.02, label, transform=ax.transAxes, ha="center", va="top", fontsize=9.5, fontweight="bold")
    ax.text(0.5, -0.105, f"VESTA supercell {repeat} · {row['display_atom_count']} atoms",
            transform=ax.transAxes, ha="center", va="top", fontsize=5.8, color="#61717B")


def save_figure(rows: list[dict[str, Any]], *, pdf: Path, png: Path, title: str, layout: tuple[int, int]) -> None:
    fig, axes = plt.subplots(*layout, figsize=(12.4, 8.2 if layout[0] == 2 else 9.0), facecolor="white")
    axes_flat = list(axes.flat)
    for ax, row in zip(axes_flat, rows, strict=False):
        image_panel(ax, row, str(row["formula"]))
    for ax in axes_flat[len(rows):]:
        ax.set_axis_off()
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.97)
    fig.text(0.5, 0.925, "Derived display-only supercells; raw persisted CIFs unchanged",
             ha="center", fontsize=8.5, color="#61717B")
    fig.subplots_adjust(left=0.035, right=0.985, top=0.88, bottom=0.075, wspace=0.08, hspace=0.43)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(pdf, metadata={"Title": title})
    fig.savefig(png, dpi=320)
    plt.close(fig)


def main() -> None:
    neighbours = read_csv(WORKFLOW_SOURCE / "RETRIEVAL_NEIGHBOURS.csv")
    workflow_specs = [(Path(row["source_cif_path"]), f"neighbour_{int(row['display_index']):02d}",
                       "retrieved_neighbour", row["display_label"], "layered") for row in neighbours]
    workflow_specs.append((WORKFLOW_SOURCE / "GENERATED_RAW.cif", "generated_li2feo3",
                           "generated_candidate", "Li2FeO3 generated", "layered"))
    workflow_rows = [prepare_and_render(source=source, out_dir=WORKFLOW_OUT, render_id=render_id,
                                        role=role, formula=formula, family=family)
                     for source, render_id, role, formula, family in workflow_specs]
    workflow_pdf = WORKFLOW_OUT / "FIGURE_1_LI2FEO3_WORKFLOW_SUPERCELL.pdf"
    workflow_png = WORKFLOW_OUT / "FIGURE_1_LI2FEO3_WORKFLOW_SUPERCELL.png"
    save_figure(workflow_rows, pdf=workflow_pdf, png=workflow_png,
                title="Li2FeO3 retrieval-to-generation structures", layout=(2, 4))
    write_json(WORKFLOW_OUT / "FIGURE_1_LI2FEO3_WORKFLOW_SUPERCELL_MANIFEST.json", {
        "policy": "DISPLAY_SUPERCELL_POLICY_V1", "renderer": "VESTA", "items": workflow_rows,
        "pdf": str(workflow_pdf.resolve()), "png": str(workflow_png.resolve()),
    })
    (WORKFLOW_OUT / "FIGURE_1_SUPERCELL_CAPTION_FACTS.md").write_text(
        "# Caption facts\n\nSeven persisted structures are shown: the six ranked non-target retrieval "
        "neighbours used by SPP-Maker and the generated Li2FeO3 candidate. Each panel is a derived "
        "display-only VESTA supercell selected by `DISPLAY_SUPERCELL_POLICY_V1`; raw CIF bytes and "
        "the frozen v4 method are unchanged. Supercell dimensions and hashes are recorded in the JSON manifest.\n",
        encoding="utf-8",
    )

    manifest = {row["experiment_id"]: row for row in read_csv(RESULTS / "PAPER_GENERATED_CIF_MANIFEST.csv")}
    gallery_rows = []
    for panel, family, formula, experiment_id in GALLERY:
        source = Path(manifest[experiment_id]["candidate_original_path"])
        row = prepare_and_render(source=source, out_dir=GALLERY_OUT,
                                 render_id=f"{panel:02d}_{re.sub(r'[^A-Za-z0-9]+', '', formula)}_{experiment_id}",
                                 role="generated_gallery", formula=formula, family=family)
        row.update({"panel": panel, "experiment_id": experiment_id,
                    "qlip_status": manifest[experiment_id]["qlip_status"],
                    "topology_status": manifest[experiment_id]["family_topology_status"],
                    "raw_cif_path": str(source.resolve()), "raw_cif_sha256": sha(source),
                    "visualization_supercell": f"{row['repeat_a']}x{row['repeat_b']}x{row['repeat_c']}",
                    "render_path": row["polished_render"],
                    "topology": manifest[experiment_id]["family_topology_status"],
                    "notes": "derived display-only supercell; QLIP solved the raw periodic cell"})
        gallery_rows.append(row)
    gallery_pdf = GALLERY_OUT / "FIGURE_2_GENERATED_CRYSTAL_GALLERY_SUPERCELL.pdf"
    gallery_png = GALLERY_OUT / "FIGURE_2_GENERATED_CRYSTAL_GALLERY_SUPERCELL.png"
    save_figure(gallery_rows, pdf=gallery_pdf, png=gallery_png,
                title="Scaffold-free crystals generated by QLIP", layout=(2, 4))
    write_csv(GALLERY_OUT / "FIGURE_2_GALLERY_SUPERCELL_MANIFEST.csv", gallery_rows)
    write_json(GALLERY_OUT / "FIGURE_2_GALLERY_SUPERCELL_RENDER_MANIFEST.json", {
        "policy": "DISPLAY_SUPERCELL_POLICY_V1", "renderer": "VESTA", "items": gallery_rows,
        "pdf": str(gallery_pdf.resolve()), "png": str(gallery_png.resolve()),
    })
    (GALLERY_OUT / "FIGURE_2_SUPERCELL_CAPTION_FACTS.md").write_text(
        "# Caption facts\n\nEight scaffold-free generated crystals are shown: four layered oxides and "
        "four spinel oxides, each from a distinct pre-audited StructureMatcher group with topology "
        "status PASS. Panels use derived display-only VESTA supercells. Raw generated CIF bytes, "
        "candidate identities, solver outcomes, and frozen v4 artifacts are unchanged.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
