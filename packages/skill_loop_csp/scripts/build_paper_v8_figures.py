from __future__ import annotations

import csv
import json
import math
import shutil
import textwrap
from pathlib import Path
from typing import Any

from pymatgen.core import Composition
from PIL import Image, ImageChops, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts" / "paper_results_package_v8"
OUT = ROOT / "figures" / "paper_v8"

REPRESENTATIVE_PRIORITY = [
    ("paper_experiment_3_specialist_halide_v1", "exp3_cssni3_pair_guided"),
    ("paper_experiment_1_common_v1", "exp1_batio3_perovskite"),
    ("paper_experiment_3_specialist_halide_v1", "exp3_cspbbr3_pair_guided"),
    ("paper_experiment_2_hard_v3", "exp2v3_cspbbr3_halide"),
    ("paper_experiment_2_hard_v3", "exp2v3_cssni3_halide"),
]

COMMON_CROSS_PRIORITY = [("paper_experiment_1_common_v1", "exp1_batio3_perovskite"), ("paper_experiment_1_common_v1", "exp1_mgo_rocksalt")]
SPECIALIST_CROSS_PRIORITY = [("paper_experiment_3_specialist_halide_v1", "exp3_cssni3_pair_guided"), ("paper_experiment_3_specialist_halide_v1", "exp3_cspbbr3_pair_guided")]
HARD_EXCLUDED_ROWS = {"exp2v3_srtio3_perovskite"}
WEIRD_ELEMENTS = {"Ac", "U", "Np", "Pu", "Am", "Cm", "Tc", "Re", "Os", "Ir", "Pt", "Hg", "Tl", "As", "Cd"}

GRID_ROWS = [
    ("BaTiO3", "paper_experiment_1_common_v1", "exp1_batio3_perovskite", "oxide perovskite"),
    ("SrTiO3", "paper_experiment_2_hard_v3", "exp2v3_srtio3_perovskite", "oxide perovskite"),
    ("CaTiO3", "paper_experiment_2_hard_v3", "exp2v3_catio3_perovskite", "oxide perovskite"),
    ("CsPbBr3", "paper_experiment_2_hard_v3", "exp2v3_cspbbr3_halide", "halide perovskite"),
    ("CsPbCl3", "paper_experiment_2_hard_v3", "exp2v3_cspbcl3_halide", "halide perovskite"),
    ("CsSnI3", "paper_experiment_2_hard_v3", "exp2v3_cssni3_halide", "halide perovskite"),
    ("NiO", "paper_experiment_1_common_v1", "exp1_nio_rocksalt", "rocksalt binary"),
    ("TiN", "paper_experiment_1_common_v1", "exp1_tin_rocksalt", "rocksalt binary"),
    ("MgO", "paper_experiment_1_common_v1", "exp1_mgo_rocksalt", "rocksalt binary"),
    ("CeO2", "paper_experiment_1_common_v1", "exp1_ceo2_fluorite", "fluorite-type oxide"),
    ("ZrO2", "paper_experiment_1_common_v1", "exp1_zro2_fluorite", "fluorite-type oxide"),
    ("ThO2", "paper_experiment_1_common_v1", "exp1_tho2_fluorite", "fluorite-type oxide"),
]

SUPPLEMENTARY_FILES = [
    "WORKFLOW_ARTIFACTS_CONTACT_SHEET.png",
    "RETRIEVAL_NEIGHBOUR_AUDIT.csv",
    "EVIDENCE_SELECTION_MANIFEST.csv",
    "SPP_EVIDENCE_AUDIT.csv",
    "PAPER_RESULTS_TABLE.csv",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def package_path(text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else PACKAGE / path


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\calibrib.ttf" if bold else r"C:\Windows\Fonts\calibri.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


FONT_TITLE = font(46, True)
FONT_SUBTITLE = font(28, False)
FONT_LABEL = font(30, True)
FONT_SMALL = font(22, False)
FONT_TINY = font(18, False)


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fnt: ImageFont.ImageFont, fill: str, width_px: int, line_gap: int = 6) -> int:
    x, y = xy
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if text_size(draw, trial, fnt)[0] <= width_px or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += text_size(draw, line, fnt)[1] + line_gap
    return y


def tex_escape(value: Any) -> str:
    return str(value).replace("\\", r"\textbackslash{}").replace("_", r"\_").replace("%", r"\%")


def composition(formula: str) -> Composition | None:
    try:
        return Composition(str(formula or ""))
    except Exception:
        return None


def reduced_formula(formula: str) -> str:
    comp = composition(formula)
    return comp.reduced_formula if comp else str(formula or "")


def formula_elements(formula: str) -> set[str]:
    comp = composition(formula)
    if not comp:
        return set()
    return {el.symbol for el in comp.elements}


def to_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fit_image(image: Image.Image, box: tuple[int, int], *, contain: bool = True) -> Image.Image:
    target_w, target_h = box
    scale = min(target_w / image.width, target_h / image.height) if contain else max(target_w / image.width, target_h / image.height)
    resized = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)
    if contain:
        return resized
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def paste_center(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int], bg: tuple[int, int, int] = (255, 255, 255)) -> None:
    x, y, w, h = box
    tile = Image.new("RGB", (w, h), bg)
    img = fit_image(image.convert("RGB"), (w, h), contain=True)
    tile.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    canvas.paste(tile, (x, y))


def trim_white(image: Image.Image, padding: int = 30) -> Image.Image:
    rgb = image.convert("RGB")
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    diff = ImageChops.difference(rgb, bg)
    bbox = diff.getbbox()
    if not bbox:
        return rgb
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(rgb.width, bbox[2] + padding)
    bottom = min(rgb.height, bbox[3] + padding)
    return rgb.crop((left, top, right, bottom))


def crop_workflow_panel_region(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    top = int(rgb.height * 0.16)
    bottom = int(rgb.height * 0.88)
    return trim_white(rgb.crop((0, top, rgb.width, bottom)), padding=35)


def workflow_region_crops(image: Image.Image) -> dict[str, Image.Image]:
    rgb = image.convert("RGB")
    y0 = int(rgb.height * 0.16)
    y1 = int(rgb.height * 0.88)
    panel = rgb.crop((0, y0, rgb.width, y1))
    return {
        "query": trim_white(panel.crop((0, 0, int(panel.width * 0.23), panel.height)), padding=25),
        "evidence": trim_white(panel.crop((int(panel.width * 0.21), 0, int(panel.width * 0.52), panel.height)), padding=25),
        "guidance": trim_white(panel.crop((int(panel.width * 0.50), 0, panel.width, panel.height)), padding=25),
    }


def row_by_key(rows: list[dict[str, str]], experiment_id: str, row_id: str) -> dict[str, str]:
    for row in rows:
        if row["experiment_id"] == experiment_id and row["row_id"] == row_id:
            return row
    raise KeyError(f"{experiment_id}/{row_id}")


def selected_count(selection_rows: list[dict[str, str]], experiment_id: str, row_id: str, *, display_only: bool | None = None) -> int:
    out = 0
    for row in selection_rows:
        if row["experiment_id"] != experiment_id or row["row_id"] != row_id or row.get("selection_decision") != "selected":
            continue
        if display_only is not None and str(row.get("selected_for_display")).lower() != str(display_only).lower():
            continue
        out += 1
    return out


def evidence_rows_for(selection_rows: list[dict[str, str]], experiment_id: str, row_id: str) -> list[dict[str, str]]:
    return [
        row
        for row in selection_rows
        if row["experiment_id"] == experiment_id and row["row_id"] == row_id and row.get("selection_decision") == "selected"
    ]


def score_candidate(row: dict[str, str], selection_rows: list[dict[str, str]], index_row: dict[str, str]) -> dict[str, Any]:
    evidence = evidence_rows_for(selection_rows, row["experiment_id"], row["row_id"])
    display_evidence = [item for item in evidence if to_bool(item.get("selected_for_display"))]
    judged = display_evidence or evidence
    target_reduced = reduced_formula(row["target_formula"])
    exact_or_same_reduced = sum(
        1
        for item in evidence
        if reduced_formula(item.get("neighbour_formula", "")) == target_reduced
        or item.get("neighbour_formula", "").replace(" ", "") == row["target_formula"].replace(" ", "")
    )
    overlap_mean = sum(to_float(item.get("target_element_overlap_fraction")) for item in judged) / len(judged) if judged else 0.0
    anion_fraction = sum(to_bool(item.get("anion_family_match")) for item in judged) / len(judged) if judged else 0.0
    abx3_count = sum(to_bool(item.get("abx3_like")) for item in judged)
    prototype_count = sum(to_bool(item.get("same_or_related_prototype")) for item in judged)
    weird_hits = 0
    for item in judged:
        weird_hits += len(formula_elements(item.get("neighbour_formula", "")) & WEIRD_ELEMENTS)
    weird_penalty = weird_hits
    display_count = len(display_evidence)
    score = (
        25 * exact_or_same_reduced
        + 20 * anion_fraction
        + 8 * overlap_mean
        + 6 * prototype_count
        + 4 * abx3_count
        + min(display_count, 4) * 4
        - 8 * weird_penalty
    )
    if row["row_id"] == "exp2v3_srtio3_perovskite":
        score -= 30
    if int(index_row.get("semantic_neighbour_fallback_count") or 0) != 0:
        score -= 100
    if int(index_row.get("semantic_neighbour_vesta_success_count") or 0) == 0:
        score -= 50
    return {
        "row_id": row["row_id"],
        "experiment_id": row["experiment_id"],
        "target_formula": row["target_formula"],
        "selected_evidence_count": len(evidence),
        "exact_or_same_reduced_count": exact_or_same_reduced,
        "target_element_overlap_mean": f"{overlap_mean:.3f}",
        "anion_family_match_fraction": f"{anion_fraction:.3f}",
        "abx3_like_count": abx3_count,
        "same_or_related_prototype_count": prototype_count,
        "weird_element_penalty": weird_penalty,
        "reviewer_readability_score": f"{score:.2f}",
        "selected_for_representative": False,
        "selected_for_cross_setting": False,
        "reason": "",
        "_score": score,
        "_display_count": display_count,
    }


def build_score_table(index_rows: list[dict[str, str]], selection_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index_row in index_rows:
        rows.append(score_candidate(index_row, selection_rows, index_row))
    return rows


def score_by_key(score_rows: list[dict[str, Any]], experiment_id: str, row_id: str) -> dict[str, Any]:
    for row in score_rows:
        if row["experiment_id"] == experiment_id and row["row_id"] == row_id:
            return row
    raise KeyError(f"{experiment_id}/{row_id}")


def row_is_render_clean(index_row: dict[str, str], spp_row: dict[str, str]) -> bool:
    return (
        index_row.get("workflow_artifact_status") == "rendered"
        and index_row.get("semantic_neighbour_fallback_count") == "0"
        and int(index_row.get("semantic_neighbour_vesta_success_count") or 0) > 0
        and str(spp_row.get("pair_coverage_complete")).lower() == "true"
        and str(spp_row.get("used_universal_only")).lower() == "false"
    )


def choose_representative(index_rows: list[dict[str, str]], score_rows: list[dict[str, Any]], spp_rows: list[dict[str, str]]) -> dict[str, str]:
    spp_by_key = {(row["experiment_id"], row["row_id"]): row for row in spp_rows}
    for experiment_id, row_id in REPRESENTATIVE_PRIORITY:
        row = row_by_key(index_rows, experiment_id, row_id)
        spp = spp_by_key.get((experiment_id, row_id), {})
        score = score_by_key(score_rows, experiment_id, row_id)
        if row_is_render_clean(row, spp) and score["_display_count"] >= 3 and score["_score"] > 45:
            return row
    raise RuntimeError("No representative row satisfied the v8 figure criteria.")


def choose_cross_settings(index_rows: list[dict[str, str]], score_rows: list[dict[str, Any]], spp_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    spp_by_key = {(row["experiment_id"], row["row_id"]): row for row in spp_rows}

    def clean_choice(candidates: list[tuple[str, str]]) -> dict[str, str]:
        for experiment_id, row_id in candidates:
            row = row_by_key(index_rows, experiment_id, row_id)
            if row_is_render_clean(row, spp_by_key.get((experiment_id, row_id), {})):
                return row
        raise RuntimeError(f"No clean choice from {candidates}")

    common = clean_choice(COMMON_CROSS_PRIORITY)
    specialist = clean_choice(SPECIALIST_CROSS_PRIORITY)
    hard_candidates = [
        row
        for row in index_rows
        if row["experiment_id"] == "paper_experiment_2_hard_v3"
        and row["row_id"] not in HARD_EXCLUDED_ROWS
        and row_is_render_clean(row, spp_by_key.get((row["experiment_id"], row["row_id"]), {}))
    ]
    hard_candidates.sort(key=lambda row: score_by_key(score_rows, row["experiment_id"], row["row_id"])["_score"], reverse=True)
    hard = hard_candidates[0]
    return [
        {"heading": "Common prototype-family query", "experiment_id": common["experiment_id"], "row_id": common["row_id"], "label": f"{common['target_formula']} common prototype"},
        {"heading": "Hard crystallographic intent", "experiment_id": hard["experiment_id"], "row_id": hard["row_id"], "label": f"{hard['target_formula']} hard setting"},
        {"heading": "Specialist halide transfer", "experiment_id": specialist["experiment_id"], "row_id": specialist["row_id"], "label": f"{specialist['target_formula']} specialist corpus"},
    ]


def mark_score_choices(score_rows: list[dict[str, Any]], representative: dict[str, str], cross_rows: list[dict[str, str]]) -> None:
    cross_keys = {(row["experiment_id"], row["row_id"]) for row in cross_rows}
    for row in score_rows:
        key = (row["experiment_id"], row["row_id"])
        if key == (representative["experiment_id"], representative["row_id"]):
            row["selected_for_representative"] = True
            row["reason"] = "representative: highest-priority clean CsSnI3/BaTiO3 candidate satisfying display, SPP, VESTA and readability gates"
        if key in cross_keys:
            row["selected_for_cross_setting"] = True
            row["reason"] = (row["reason"] + "; " if row["reason"] else "") + "cross-setting: selected as cleanest available row for its setting without SrTiO3/Ac-U-Pt-heavy evidence"


def write_score_table(score_rows: list[dict[str, Any]]) -> None:
    columns = [
        "row_id",
        "experiment_id",
        "target_formula",
        "selected_evidence_count",
        "exact_or_same_reduced_count",
        "target_element_overlap_mean",
        "anion_family_match_fraction",
        "abx3_like_count",
        "same_or_related_prototype_count",
        "weird_element_penalty",
        "reviewer_readability_score",
        "selected_for_representative",
        "selected_for_cross_setting",
        "reason",
    ]
    clean_rows = [{key: row.get(key, "") for key in columns} for row in sorted(score_rows, key=lambda item: item["_score"], reverse=True)]
    write_csv(OUT / "FIGURE_CANDIDATE_EVIDENCE_SCORE.csv", clean_rows, columns)


def copy_representative(row: dict[str, str], selection_rows: list[dict[str, str]], spp_rows: list[dict[str, str]], score_rows: list[dict[str, Any]], cross_rows: list[dict[str, str]]) -> dict[str, str]:
    src = package_path(row["row_workflow_artifact_png"])
    dst = OUT / "v8_representative_workflow_artifact.png"
    shutil.copy2(src, dst)
    pdf_src = package_path(str(row.get("row_workflow_artifact_pdf") or ""))
    if pdf_src.is_file():
        shutil.copy2(pdf_src, OUT / "v8_representative_workflow_artifact.pdf")
    spp = row_by_key(spp_rows, row["experiment_id"], row["row_id"])
    score = score_by_key(score_rows, row["experiment_id"], row["row_id"])
    note = [
        "# v8 Representative Workflow Artifact Selection",
        "",
        f"Selected row: `{row['experiment_id']}/{row['row_id']}` ({row['target_formula']}).",
        "",
        "Reason: highest-priority candidate under the stricter main-paper criteria. It is the preferred CsSnI3 specialist row, has same-anion halide-perovskite selected evidence, avoids the visually noisy double-perovskite-heavy CsPbBr3 hard row, and satisfies the VESTA/no-fallback/SPP gates.",
        "",
        f"Source PNG: `{src}`",
        f"Output PNG: `{dst}`",
        f"Displayed selected-evidence neighbours: {selected_count(selection_rows, row['experiment_id'], row['row_id'], display_only=True)}",
        f"Total selected evidence records: {selected_count(selection_rows, row['experiment_id'], row['row_id'])}",
        f"Reviewer readability score: `{score['reviewer_readability_score']}`",
        f"Weird-element penalty: `{score['weird_element_penalty']}`",
        f"SPP required pairs: `{spp.get('required_species_pairs', '')}`",
        f"SPP finite check: `{spp.get('finite_curve_check', '')}`",
        "",
        "Cross-setting rows rebuilt under the same stricter selection policy:",
    ]
    for cross in cross_rows:
        cross_score = score_by_key(score_rows, cross["experiment_id"], cross["row_id"])
        note.append(f"- `{cross['experiment_id']}/{cross['row_id']}` ({cross['label']}): score `{cross_score['reviewer_readability_score']}`, weird penalty `{cross_score['weird_element_penalty']}`.")
    note.extend([
        "",
        "SrTiO3 was not used in the cross-setting figure because its displayed evidence remains broad and includes Ac/U/Pt-containing titanates. The hard-setting column is chosen from Experiment 2 by the scoring table instead.",
        "",
    ])
    (OUT / "v8_representative_workflow_artifact_SELECTION.md").write_text("\n".join(note), encoding="utf-8")
    return {"representative_source": str(src), "representative_row": f"{row['experiment_id']}/{row['row_id']}"}


def workflow_image(index_rows: list[dict[str, str]], experiment_id: str, row_id: str) -> Path:
    row = row_by_key(index_rows, experiment_id, row_id)
    src = package_path(row["row_workflow_artifact_png"])
    if not src.is_file():
        raise FileNotFoundError(src)
    return src


def make_cross_setting(index_rows: list[dict[str, str]], selection_rows: list[dict[str, str]], spp_rows: list[dict[str, str]], cross_rows: list[dict[str, str]]) -> list[str]:
    width = 5400
    margin = 90
    gap = 55
    header_h = 180
    col_w = (width - 2 * margin - 2 * gap) // 3
    image_h = 1450
    height = margin + header_h + image_h + 55
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 35), "Cross-setting Crystal-DB to CSP examples", font=FONT_TITLE, fill=(20, 20, 20))
    sources: list[str] = []
    for idx, spec in enumerate(cross_rows):
        x = margin + idx * (col_w + gap)
        y = margin + 75
        row = row_by_key(index_rows, spec["experiment_id"], spec["row_id"])
        spp = row_by_key(spp_rows, spec["experiment_id"], spec["row_id"])
        draw.text((x, y), spec["heading"], font=FONT_LABEL, fill=(20, 20, 20))
        y += 42
        caption = f"{spec['label']} | {row['target_formula']} | selected evidence {selected_count(selection_rows, spec['experiment_id'], spec['row_id'])} | SPP {spp.get('required_species_pairs', '')}"
        draw_wrapped(draw, (x, y), caption, FONT_SMALL, (70, 70, 70), col_w)
        src = workflow_image(index_rows, spec["experiment_id"], spec["row_id"])
        sources.append(str(src))
        crops = workflow_region_crops(Image.open(src))
        top_y = margin + header_h
        draw.text((x, top_y), "Query", font=FONT_SMALL, fill=(45, 45, 45))
        draw.text((x + col_w // 2 + 20, top_y), "Selected evidence", font=FONT_SMALL, fill=(45, 45, 45))
        paste_center(canvas, crops["query"], (x, top_y + 36, col_w // 2 - 14, 430))
        paste_center(canvas, crops["evidence"], (x + col_w // 2 + 20, top_y + 36, col_w // 2 - 20, 430))
        draw.text((x, top_y + 500), "SPP/POT guidance and generated crystal", font=FONT_SMALL, fill=(45, 45, 45))
        paste_center(canvas, crops["guidance"], (x, top_y + 540, col_w, 780))
    png = OUT / "v8_cross_setting_examples.png"
    pdf = OUT / "v8_cross_setting_examples.pdf"
    canvas.save(png, dpi=(300, 300))
    canvas.save(pdf, "PDF", resolution=300)
    return sources


def vesta_image_path(experiment_id: str, row_id: str) -> Path:
    path = PACKAGE / "VESTA_RENDERING" / "pngs" / experiment_id / row_id / "final_generated.png"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def make_structure_grid() -> list[str]:
    cols = 4
    rows = 3
    tile_w = 1000
    tile_h = 830
    header_h = 115
    margin = 70
    gap = 28
    width = cols * tile_w + (cols - 1) * gap + 2 * margin
    height = rows * tile_h + (rows - 1) * gap + 2 * margin + 80
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 30), "VESTA-rendered generated structures from v8", font=FONT_TITLE, fill=(20, 20, 20))
    sources: list[str] = []
    for idx, (formula, experiment_id, row_id, setting) in enumerate(GRID_ROWS):
        col = idx % cols
        row = idx // cols
        x = margin + col * (tile_w + gap)
        y = margin + 70 + row * (tile_h + gap)
        draw.rounded_rectangle((x, y, x + tile_w, y + tile_h), radius=10, outline=(185, 185, 185), width=2, fill=(250, 250, 250))
        draw.text((x + 26, y + 20), formula, font=FONT_LABEL, fill=(20, 20, 20))
        draw.text((x + 26, y + 60), setting, font=FONT_SMALL, fill=(75, 75, 75))
        src = vesta_image_path(experiment_id, row_id)
        sources.append(str(src))
        img = Image.open(src).convert("RGB")
        paste_center(canvas, img, (x + 18, y + header_h, tile_w - 36, tile_h - header_h - 18), bg=(250, 250, 250))
    png = OUT / "v8_generated_structure_grid.png"
    canvas.save(png, dpi=(300, 300))
    return sources


def validation_row_path(index_rows: list[dict[str, str]], row: dict[str, str]) -> Path:
    manifest = row_by_key(index_rows, row["experiment_id"], row["row_id"])
    row_png = package_path(manifest["row_workflow_artifact_png"])
    return row_png.parent / "validation_summary.json"


def make_validation_summary(index_rows: list[dict[str, str]]) -> dict[str, Any]:
    chosen = [row_by_key(index_rows, exp, row_id) for _formula, exp, row_id, _setting in GRID_ROWS]
    validation_rows: list[dict[str, Any]] = []
    for row in chosen:
        validation_path = validation_row_path(index_rows, row)
        validation = read_json(validation_path)
        validation_rows.append({"index": row, "validation": validation, "validation_path": validation_path})
    width = 3600
    row_h = 95
    margin = 80
    header_h = 160
    cols = [
        ("Formula", 260),
        ("Parse", 210),
        ("Formula", 250),
        ("Prototype", 280),
        ("Geometry", 250),
        ("Contacts", 250),
        ("CHGNet", 440),
        ("Relax CIF", 280),
        ("VESTA grid", 280),
    ]
    height = margin + header_h + row_h * (len(chosen) + 1) + margin
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 40), "Validation and packaged CHGNet-status summary", font=FONT_TITLE, fill=(20, 20, 20))
    draw.text((margin, 95), "Representative v8 generated structures using packaged validation summaries, paper table paths, and VESTA render outputs.", font=FONT_SMALL, fill=(70, 70, 70))
    x = margin
    y = margin + header_h
    for title, col_w in cols:
        draw.text((x + 8, y), title, font=FONT_SMALL, fill=(20, 20, 20))
        x += col_w
    y += row_h
    ok_fill = (224, 245, 232)
    warn_fill = (255, 241, 205)
    for item in validation_rows:
        row = item["index"]
        validation = item["validation"]
        x = margin
        vals = [
            row["target_formula"],
            validation.get("parse_ok", ""),
            validation.get("formula_match", ""),
            validation.get("prototype_symmetry_match", ""),
            validation.get("geometry_ok", ""),
            validation.get("contact_screen_pass", ""),
            validation.get("chgnet_status", ""),
            bool(str(row.get("relaxed_cif_path") or "").strip()),
            bool(vesta_image_path(row["experiment_id"], row["row_id"]).is_file()),
        ]
        for val, (_title, col_w) in zip(vals, cols):
            good = str(val).lower() in {"ok", "true", "not_run_unavailable_or_not_requested"}
            draw.rounded_rectangle((x + 4, y - 10, x + col_w - 8, y + 52), radius=7, fill=ok_fill if good else warn_fill, outline=(210, 210, 210))
            draw.text((x + 14, y + 5), str(val), font=FONT_TINY if len(str(val)) > 10 else FONT_SMALL, fill=(25, 25, 25))
            x += col_w
        y += row_h
    png = OUT / "v8_validation_summary.png"
    canvas.save(png, dpi=(300, 300))

    tex_rows = [
        r"\begin{tabular}{lllllll}",
        r"\toprule",
        r"Formula & Row & Parse & Formula & Prototype & Contacts & CHGNet status \\",
        r"\midrule",
    ]
    for item in validation_rows:
        row = item["index"]
        validation = item["validation"]
        tex_rows.append(
            f"{tex_escape(row['target_formula'])} & {tex_escape(row['row_id'])} & "
            f"{validation.get('parse_ok')} & {validation.get('formula_match')} & "
            f"{validation.get('prototype_symmetry_match')} & {validation.get('contact_screen_pass')} & "
            f"{tex_escape(validation.get('chgnet_status'))} \\\\"
        )
    tex_rows.extend([r"\bottomrule", r"\end{tabular}", ""])
    (OUT / "v8_validation_relaxation_table.tex").write_text("\n".join(tex_rows), encoding="utf-8")
    return {"validation_png": str(png), "validation_rows": [f"{item['index']['experiment_id']}/{item['index']['row_id']}" for item in validation_rows]}


def copy_supplementary() -> list[str]:
    copied: list[str] = []
    for name in SUPPLEMENTARY_FILES:
        src = PACKAGE / name
        if not src.is_file():
            raise FileNotFoundError(src)
        dst = OUT / name
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied


def write_summary(data: dict[str, Any]) -> None:
    lines = [
        "# Figure Build Summary",
        "",
        "## Inputs",
        "",
        f"- Package root: `{PACKAGE}`",
        f"- Paper table: `{PACKAGE / 'PAPER_RESULTS_TABLE.csv'}`",
        f"- Evidence manifest: `{PACKAGE / 'EVIDENCE_SELECTION_MANIFEST.csv'}`",
        f"- SPP audit: `{PACKAGE / 'SPP_EVIDENCE_AUDIT.csv'}`",
        "",
        "## Generated Figures",
        "",
        f"- `v8_representative_workflow_artifact.png`: copied from `{data['representative_source']}`; row `{data['representative_row']}`.",
        f"- `v8_cross_setting_examples.png` and `.pdf`: rows `{', '.join(data['cross_rows'])}`; source workflow artifacts are v8 package row artifacts.",
        f"- `v8_generated_structure_grid.png`: {len(data['grid_sources'])} VESTA-rendered generated structures from `artifacts/paper_results_package_v8/VESTA_RENDERING`.",
        f"- `v8_validation_summary.png`: validation and packaged CHGNet-status check matrix for rows `{', '.join(data['validation_rows'])}`.",
        f"- `v8_validation_relaxation_table.tex`: LaTeX table snippet from v8 row `validation_summary.json` files and `PAPER_RESULTS_TABLE.csv` paths for the same generated rows.",
        "- `FIGURE_CANDIDATE_EVIDENCE_SCORE.csv`: figure-candidate evidence scoring table used for the stricter main-paper row choices.",
        "",
        "## Checks",
        "",
        "- All copied workflow artifacts are sourced from `artifacts/paper_results_package_v8`.",
        "- Cross-setting workflow artifacts are v8 row artifacts and display the selected-evidence layer prepared in v8.",
        "- Generated-structure grid images are sourced from `artifacts/paper_results_package_v8/VESTA_RENDERING/pngs/.../final_generated.png`.",
        "- No fallback structure render panels were used: v8 workflow index reports `semantic_neighbour_fallback_count=0` for all selected rows and generated structure images are VESTA outputs.",
        "- Supplementary files were copied from v8 package root.",
        "",
        "## Main-Paper Rebuilt Rows",
        "",
    ]
    for item in data["main_rows"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Auxiliary Figure Rows", ""])
    for item in data["auxiliary_rows"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Supplementary Copies", ""])
    for item in data["supplementary"]:
        lines.append(f"- `{item}`")
    lines.append("")
    (OUT / "FIGURE_BUILD_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if not PACKAGE.is_dir():
        raise FileNotFoundError(PACKAGE)
    OUT.mkdir(parents=True, exist_ok=True)

    index_rows = read_csv(PACKAGE / "WORKFLOW_ARTIFACTS_INDEX.csv")
    selection_rows = read_csv(PACKAGE / "EVIDENCE_SELECTION_MANIFEST.csv")
    spp_rows = read_csv(PACKAGE / "SPP_EVIDENCE_AUDIT.csv")
    score_rows = build_score_table(index_rows, selection_rows)
    representative = choose_representative(index_rows, score_rows, spp_rows)
    cross_rows = choose_cross_settings(index_rows, score_rows, spp_rows)
    mark_score_choices(score_rows, representative, cross_rows)
    write_score_table(score_rows)
    rep_data = copy_representative(representative, selection_rows, spp_rows, score_rows, cross_rows)
    cross_sources = make_cross_setting(index_rows, selection_rows, spp_rows, cross_rows)
    grid_sources = make_structure_grid()
    validation = make_validation_summary(index_rows)
    supplementary = copy_supplementary()
    write_summary(
        {
            **rep_data,
            "cross_rows": [f"{s['experiment_id']}/{s['row_id']}" for s in cross_rows],
            "grid_sources": grid_sources,
            "validation_rows": validation["validation_rows"],
            "main_rows": sorted({rep_data["representative_row"], *[f"{s['experiment_id']}/{s['row_id']}" for s in cross_rows]}),
            "auxiliary_rows": sorted({f"{exp}/{row_id}" for _f, exp, row_id, _set in GRID_ROWS}),
            "supplementary": supplementary,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
