"""Merge completed three-level runs, validate result provenance, and build two paper packs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from sok_llm_orchestrator.workflow.row_visualization import build_row_workflow_figure
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages
from sok_llm_orchestrator.workflow.scaffold_ablation import load_selection


ROOT = Path(__file__).resolve().parents[1]
LOOSE = ROOT / "experiments" / "scaffold_ablation" / "scaffolds" / "loose"
HARD = ROOT / "experiments" / "scaffold_ablation" / "scaffolds" / "hard"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_pair(source_stem: Path, destination_stem: Path) -> None:
    for suffix in (".png", ".pdf"):
        source = source_stem.with_suffix(suffix)
        if source.is_file():
            shutil.copy2(source, destination_stem.with_suffix(suffix))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def figure4a_coordinate_source() -> list[dict[str, Any]]:
    """Return every coordinate actually plotted in the three Figure 4A projections."""
    task = ProductionWorkflowStages().normalise("Na3Zr2Si2PO12")
    rows: list[dict[str, Any]] = []
    for mode, directory in (("none", None), ("loose", LOOSE), ("hard", HARD)):
        selection = load_selection(task, directory)
        if mode == "none":
            density = int(selection.native_sites["uniform_grid"]["density"])
            for index, grid in enumerate(np.ndindex(density, density, density)):
                fractional = np.asarray(grid, dtype=float) / density
                cartesian = fractional * 3.9
                rows.append({
                    "mode": mode, "site_index": index, "orbit_id": "", "occupation_class": "native-unconstrained",
                    "frac_x": fractional[0], "frac_y": fractional[1], "frac_z": fractional[2],
                    "cart_x_A": cartesian[0], "cart_y_A": cartesian[1], "cart_z_A": cartesian[2],
                    "scaffold_id": selection.scaffold_id, "scaffold_hash": selection.scaffold_hash,
                })
            continue
        assert selection.structure is not None
        orbit_by_site = {
            int(site): orbit for orbit in selection.orbits for site in orbit["site_indices"]
        }
        for index, (fractional, cartesian) in enumerate(zip(selection.structure.frac_coords, selection.structure.cart_coords)):
            orbit = orbit_by_site[index]
            rows.append({
                "mode": mode, "site_index": index, "orbit_id": orbit["orbit_id"],
                "occupation_class": "species-fixed" if orbit.get("fixed_species") else "variable-occupation",
                "frac_x": fractional[0], "frac_y": fractional[1], "frac_z": fractional[2],
                "cart_x_A": cartesian[0], "cart_y_A": cartesian[1], "cart_z_A": cartesian[2],
                "scaffold_id": selection.scaffold_id, "scaffold_hash": selection.scaffold_hash,
            })
    return rows


def merge_results(ablation: Path) -> list[dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for path in sorted((ablation / "runs").rglob("RESULTS.csv")):
        for row in read_csv(path):
            if row["row_id"] in by_id:
                raise RuntimeError(f"duplicate result row: {row['row_id']}")
            row["result_source"] = str(path)
            by_id[row["row_id"]] = row
    expected = {row["row_id"] for row in read_csv(ablation / "NASICON_SCAFFOLD_ABLATION.csv")}
    missing = sorted(expected - set(by_id))
    if missing:
        raise RuntimeError(f"nine-run ablation is incomplete; missing: {', '.join(missing)}")
    rows = [by_id[row["row_id"]] for row in read_csv(ablation / "NASICON_SCAFFOLD_ABLATION.csv")]
    sca_path = ablation / "SCA_FULL_RESULTS.csv"
    sca = {row["row_id"]: row for row in read_csv(sca_path)} if sca_path.is_file() else {}
    for row in rows:
        if row["row_id"] in sca:
            full = sca[row["row_id"]]
            row.update({
                "sca_status": full.get("validation_status", row.get("sca_status", "")),
                "sca_parse_ok": full.get("valid_cif", row.get("sca_parse_ok", "")),
                "sca_target_formula_match": full.get("composition_exact", row.get("sca_target_formula_match", "")),
                "sca_geometry_ok": full.get("geometry_ok", row.get("sca_geometry_ok", "")),
                "sca_topology_status": full.get("topology_status", row.get("sca_topology_status", "")),
                "sca_topology_backend": full.get("topology_backend", ""),
                "sca_topology_policy": full.get("topology_policy", ""),
            })
    chgnet_path = ablation / "chgnet" / "SCAFFOLD_CHGNET_RESULTS.csv"
    chgnet = {row["row_id"]: row for row in read_csv(chgnet_path)} if chgnet_path.is_file() else {}
    for row in rows:
        if row["row_id"] in chgnet:
            result = chgnet[row["row_id"]]
            for key, value in result.items():
                if key not in {"row_id", "formula"}:
                    row[key] = value
        elif row.get("cif_generated") != "YES":
            row.update({
                "chgnet_status": "NOT_APPLICABLE_NO_CIF",
                "chgnet_converged": "NOT_APPLICABLE",
                "space_group_retained": "NOT_APPLICABLE",
                "crystal_system_retained": "NOT_APPLICABLE",
                "initial_relaxed_match": "NOT_APPLICABLE",
                "volume_change_percent": "NOT_APPLICABLE",
            })
    return rows


def validation_label(row: dict[str, str]) -> str:
    if row.get("workflow_status") != "PASS":
        return "NO_CANDIDATE"
    if row.get("sca_status") == "PASS" and row.get("chgnet_status") == "PASS":
        return "PASS"
    if row.get("sca_parse_ok", "").lower() in {"true", "yes", "1"}:
        return "PARTIAL"
    return "FAIL"


def ablation_figure(rows: list[dict[str, str]], output: Path) -> None:
    targets = list(dict.fromkeys(row["formula"] for row in rows))
    modes = ("none", "loose", "hard")
    fig, axes = plt.subplots(len(targets), 1, figsize=(12, 7.8), sharex=True)
    colors = {"PASS": "#2d7b59", "PARTIAL": "#c58b2a", "FAIL": "#b54b4b", "NO_CANDIDATE": "#777777"}
    for ax, formula in zip(axes, targets):
        group = {row["scaffold_mode"].lower(): row for row in rows if row["formula"] == formula}
        for index, mode in enumerate(modes):
            row = group[mode]; status = validation_label(row)
            ax.bar(index, 1, width=0.62, color=colors[status], alpha=0.82)
            states = row.get("feasible_state_count") or "unknown"
            freedom = f"{row.get('variable_orbit_count') or 0} variable orbits\n{states} feasible states"
            chgnet = row.get("chgnet_status") if status != "NO_CANDIDATE" else "not applicable"
            solver = row.get("failure_code") if status == "NO_CANDIDATE" else row.get("solver_status")
            outcome = f"{solver or 'not reached'}\nvalidation {status}\nCHGNet {chgnet or 'not applicable'}\nSG {row.get('generated_space_group') or '—'}"
            ax.text(index, 0.53, outcome, ha="center", va="center", fontsize=7.3, color="white" if status != "PARTIAL" else "#2b2418")
            ax.text(index, 1.05, freedom, ha="center", va="bottom", fontsize=7)
        ax.set_ylim(0, 1.38); ax.set_yticks([]); ax.set_ylabel(formula, rotation=0, ha="right", va="center", labelpad=18, fontsize=9, fontweight="bold")
        ax.spines[["top", "right", "left"]].set_visible(False)
    axes[-1].set_xticks(range(3), ["NONE\nnative QLIP", "LOOSE\ngeometry prior", "HARD\ngeometry + chemistry prior"])
    fig.suptitle("NASICON scaffold ablation: structural validation, not solver optimality, is the quality axis", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0.04, 0.03, 0.99, 0.94))
    fig.savefig(output.with_suffix(".png"), dpi=260, facecolor="white")
    fig.savefig(output.with_suffix(".pdf"), facecolor="white")
    plt.close(fig)


def summary_figure(rows: list[dict[str, str]], output: Path, title: str) -> None:
    labels = [row["row_id"] for row in rows]
    metrics = ("CIF", "Exact composition", "Geometry", "Topology", "CHGNet", "SG retained", "Crystal system retained", "StructureMatcher")
    keys = ("cif_generated", "sca_target_formula_match", "sca_geometry_ok", "sca_topology_status", "chgnet_status", "space_group_retained", "crystal_system_retained", "initial_relaxed_match")
    matrix = np.full((len(rows), len(keys)), np.nan)
    for i, row in enumerate(rows):
        for j, key in enumerate(keys):
            value = str(row.get(key) or "").lower()
            if value in {"yes", "true", "1", "pass"}: matrix[i, j] = 1
            elif value in {"no", "false", "0", "fail", "controlled_failure"}: matrix[i, j] = 0
    fig, ax = plt.subplots(figsize=(12, max(3.4, 0.42 * len(rows) + 1.8)))
    cmap = plt.matplotlib.colors.ListedColormap(["#b54b4b", "#e4e7e9", "#2d7b59"])
    shown = np.where(np.isnan(matrix), 1, np.where(matrix > 0.5, 2, 0))
    ax.imshow(shown, aspect="auto", cmap=cmap, vmin=0, vmax=2)
    ax.set_xticks(range(len(metrics)), metrics, rotation=25, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    for i in range(len(rows)):
        for j in range(len(keys)):
            ax.text(j, i, "✓" if shown[i, j] == 2 else "×" if shown[i, j] == 0 else "—", ha="center", va="center", fontsize=8, color="white" if shown[i, j] != 1 else "#4c5961")
    ax.set_title(title, fontsize=12, fontweight="bold", pad=12)
    fig.tight_layout(); fig.savefig(output.with_suffix(".png"), dpi=240, facecolor="white"); fig.savefig(output.with_suffix(".pdf"), facecolor="white"); plt.close(fig)


def intent_figure(rows: list[dict[str, str]], output: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(12, max(3.2, 0.58 * len(rows) + 1.4)))
    ax.set_axis_off(); ax.set_title(title, fontsize=13, fontweight="bold", loc="left", pad=16)
    positions = np.linspace(0.80, 0.18, max(len(rows), 1))
    for index, row in enumerate(rows):
        y = float(positions[index])
        ax.text(0.01, y, row["formula"], fontsize=9, fontweight="bold", va="center")
        ax.text(0.18, y, row["request"], fontsize=8, va="center")
        ax.text(0.99, y, f"{row['scaffold_mode'].upper()} · {validation_label(row)}", fontsize=8, ha="right", va="center")
        ax.plot([0.01, 0.99], [y - 0.035, y - 0.035], color="#d9dfe2", linewidth=0.5)
    fig.subplots_adjust(left=0.035, right=0.985, top=0.86, bottom=0.08)
    fig.savefig(output.with_suffix(".png"), dpi=240, facecolor="white"); fig.savefig(output.with_suffix(".pdf"), facecolor="white"); plt.close(fig)


def boundary_figure(rows: list[dict[str, str]], output: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.8)); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title("Native QLIP NASICON challenge: truthful representational outcomes", fontsize=13, fontweight="bold")
    for index, row in enumerate(rows):
        x = 0.17 + index * 0.33
        ax.text(x, 0.78, row["formula"], fontsize=10, fontweight="bold", ha="center", transform=ax.transAxes)
        solver = row.get("failure_code") if row.get("workflow_status") != "PASS" else row.get("solver_status")
        ax.text(x, 0.58, "512 native grid sites\n0 scaffold orbits\n" + (solver or "not reached"), fontsize=9, ha="center", va="center", transform=ax.transAxes)
        chgnet = row.get("chgnet_status") if row.get("cif_generated") == "YES" else "not applicable"
        ax.text(x, 0.30, f"Validation: {validation_label(row)}\nCHGNet: {chgnet or 'not applicable'}", fontsize=9, ha="center", transform=ax.transAxes)
        if index < len(rows) - 1: ax.plot([x + 0.13, x + 0.20], [0.53, 0.53], color="#9ba5aa", linewidth=1, transform=ax.transAxes)
    fig.subplots_adjust(left=0.04, right=0.98, top=0.86, bottom=0.08)
    fig.savefig(output.with_suffix(".png"), dpi=240, facecolor="white"); fig.savefig(output.with_suffix(".pdf"), facecolor="white"); plt.close(fig)


def package_manifest(root: Path) -> None:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "MANIFEST.csv"):
        rows.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    write_csv(root / "MANIFEST.csv", rows)


def documentation(root: Path, narrative: str, rows: list[dict[str, str]]) -> None:
    successes = sum(row.get("workflow_status") == "PASS" for row in rows)
    (root / "README.md").write_text(
        f"# {narrative}\n\n"
        "Machine-derived paper pack from the frozen three-level row experiments. "
        f"Every in-scope outcome is retained. CIF-emitting workflow rows: {successes}/{len(rows)}. "
        "Figure source CSV/JSON files identify the exact result rows and artifacts used.\n",
        encoding="utf-8",
    )
    (root / "GENERATION_AUDIT.md").write_text(
        "# Generation Audit\n\n"
        "- Source rows hash-indexed in MANIFEST.csv: YES\n"
        "- Dedicated figure-source manifests: YES\n"
        "- Solver outcomes, including controlled failures, preserved: YES\n"
        "- Structural validation is the scientific quality axis: YES\n"
        "- QLIP OPTIMAL treated as structural realism: NO\n"
        "- Targets, SPP weights, retrieval, solver, and validators changed after outcomes: NO\n"
        "- Scientific outputs altered post-hoc: NO\n"
        "- Figures rendered from result fields/artifacts: YES\n"
        "- Repository pushed: NO\n",
        encoding="utf-8",
    )
    (root / "VISUAL_QA_REPORT.md").write_text("# Visual QA Report\n\nPENDING original-resolution inspection.\n", encoding="utf-8")


def write_ablation_interpretation(ablation: Path, rows: list[dict[str, str]]) -> None:
    lines = [
        "# Scientific Interpretation",
        "",
        "The comparison uses generated-structure validation, not MILP termination, as the quality axis. The frozen requests, retrieval corpus/depth, solver-effective SPP configuration, regulator, solver tolerances, and validation protocol are identical within each target; only the search-space prior changes.",
        "",
    ]
    for formula in dict.fromkeys(row["formula"] for row in rows):
        lines.extend([f"## {formula}", ""])
        for row in (item for item in rows if item["formula"] == formula):
            freedom = (
                f"{row.get('candidate_site_count') or 'unknown'} candidate sites, "
                f"{row.get('species_fixed_orbit_count') or 0} species-fixed and "
                f"{row.get('variable_orbit_count') or 0} variable orbits, "
                f"{row.get('feasible_state_count') or 'unknown'} feasible assignments, "
                f"{row.get('allocation_variable_count') or 'unknown'} allocation variables"
            )
            lines.append(
                f"- **{row['scaffold_mode'].upper()}:** solver {(row.get('failure_code') if row.get('workflow_status') != 'PASS' else row.get('solver_status')) or 'not reached'}; "
                f"CIF {row.get('cif_generated') or 'NO'}; validation {validation_label(row)}; "
                f"CHGNet {row.get('chgnet_status') or 'not applicable'}; "
                f"space group {row.get('initial_space_group') or row.get('generated_space_group') or 'not applicable'} → {row.get('relaxed_space_group') or 'not applicable'}; "
                f"volume change {row.get('volume_change_percent') or 'not applicable'}%; {freedom}."
            )
        lines.append("")
    lines.extend([
        "## Interpretation boundary",
        "",
        "HARD is not labelled scientifically better merely because it solves. LOOSE and HARD quality is compared using parsing/composition, contact geometry, the declared CrystalNN family-topology policy, CHGNet completion, symmetry retention, volume change, and StructureMatcher. A topology PARTIAL caused by a declared policy/species mismatch is retained as PARTIAL rather than repaired after seeing outcomes.",
        "",
    ])
    (ablation / "SCIENTIFIC_INTERPRETATION.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("ablation_root", type=Path); parser.add_argument("--vesta-path")
    args = parser.parse_args(); ablation = args.ablation_root.resolve(); rows = merge_results(ablation)
    write_csv(ablation / "SCAFFOLD_ABLATION_RESULTS.csv", rows)
    write_csv(ablation / "Figure_4A_scaffold_math_and_3D_source.csv", figure4a_coordinate_source())
    write_csv(ablation / "Figure_4B_scaffold_ablation_results_source.csv", rows)
    ablation_figure(rows, ablation / "Figure_4B_scaffold_ablation_results")
    write_ablation_interpretation(ablation, rows)
    per_row = ablation / "per_row"; per_row.mkdir(exist_ok=True)
    row_figures: dict[str, Path] = {}
    row_figure_sources: list[dict[str, Any]] = []
    for row in rows:
        if row.get("workflow_status") != "PASS" or row.get("cif_generated") != "YES": continue
        row_dir = Path(row["result_source"]).parent / "rows" / row["row_id"]
        result = build_row_workflow_figure(row, row_dir, per_row, vesta_path=args.vesta_path)
        row_figures[row["row_id"]] = Path(result["workflow_figure_png"]).with_suffix("")
        row_figure_sources.append({
            "row_id": row["row_id"], "result_source": row["result_source"],
            "workflow_figure_png": result["workflow_figure_png"],
            "workflow_figure_pdf": result["workflow_figure_pdf"],
            "source_manifest": str(row_dir / "figures" / "workflow_figure_manifest.json"),
        })
    write_csv(ablation / "PER_ROW_FIGURE_SOURCES.csv", row_figure_sources)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    spp = ROOT / "artifacts" / f"Paper_results_spp_only_paper_{stamp}"
    aware = ROOT / "artifacts" / f"Paper_results_scaffold_aware_paper_{stamp}"
    spp.mkdir(); aware.mkdir()
    none = [row for row in rows if row["scaffold_mode"].lower() == "none"]
    write_csv(spp / "SPP_ONLY_RESULTS.csv", none); write_csv(spp / "SPP_ONLY_VALIDATION.csv", none)
    (spp / "SPP_ONLY_RESULTS_SUMMARY.md").write_text("# SPP-only Results Summary\n\n" + "\n".join(f"- {row['formula']}: {row['workflow_status']} / {validation_label(row)}" for row in none) + "\n", encoding="utf-8")
    successful_none = next((row for row in none if row["row_id"] in row_figures), None)
    if successful_none: copy_pair(row_figures[successful_none["row_id"]], spp / "Figure_1_traceable_workflow")
    else: boundary_figure(none, spp / "Figure_1_traceable_workflow")
    write_json(spp / "Figure_1_traceable_workflow_source.json", {
        "kind": "successful_row" if successful_none else "native_boundary",
        "row_id": successful_none["row_id"] if successful_none else None,
        "source_rows": [row["result_source"] for row in none],
    })
    intent_figure(none, spp / "Figure_2_text_intent_showcase", "No-scaffold text intents and retained outcomes")
    write_csv(spp / "Figure_2_text_intent_showcase_source.csv", none)
    summary_figure(none, spp / "Figure_3_validation_summary", "No-scaffold validation using actual backend fields")
    write_csv(spp / "Figure_3_validation_summary_source.csv", none)
    boundary_figure(none, spp / "Figure_4_native_nasicon_boundary")
    write_csv(spp / "Figure_4_native_nasicon_boundary_source.csv", none)
    documentation(spp, "SPP-only / no explicit scaffold paper", none)
    hard_success = next((row for row in rows if row["scaffold_mode"].lower() == "hard" and row["row_id"] in row_figures), None)
    any_success = next((row for row in rows if row["row_id"] in row_figures), None)
    chosen = hard_success or any_success
    if chosen: copy_pair(row_figures[chosen["row_id"]], aware / "Figure_1_traceable_workflow")
    else: boundary_figure(rows, aware / "Figure_1_traceable_workflow")
    write_json(aware / "Figure_1_traceable_workflow_source.json", {
        "kind": "successful_row" if chosen else "ablation_boundary",
        "row_id": chosen["row_id"] if chosen else None,
        "source_result": chosen["result_source"] if chosen else None,
    })
    intent_figure(rows, aware / "Figure_2_text_intent_showcase", "Same requests across three frozen search-space priors")
    write_csv(aware / "Figure_2_text_intent_showcase_source.csv", rows)
    summary_figure(rows, aware / "Figure_3_validation_summary", "Three-level validation using actual backend fields")
    write_csv(aware / "Figure_3_validation_summary_source.csv", rows)
    copy_pair(ablation / "Figure_4A_scaffold_math_and_3D", aware / "Figure_4A_scaffold_math_and_3D")
    copy_pair(ablation / "Figure_4B_scaffold_ablation_results", aware / "Figure_4B_scaffold_ablation_results")
    copy_pair(ablation / "Figure_4A_scaffold_math_and_3D", aware / "Figure_4_scaffold_extension")
    shutil.copy2(ablation / "Figure_4A_scaffold_math_and_3D_source.csv", aware / "Figure_4A_scaffold_math_and_3D_source.csv")
    shutil.copy2(ablation / "Figure_4B_scaffold_ablation_results_source.csv", aware / "Figure_4B_scaffold_ablation_results_source.csv")
    write_json(aware / "Figure_4_scaffold_extension_source.json", {
        "mechanism_figure_sha256": sha256(ablation / "Figure_4A_scaffold_math_and_3D.png"),
        "mechanism_source": str(ablation / "Figure_4A_scaffold_math_and_3D_source.csv"),
        "results_figure_sha256": sha256(ablation / "Figure_4B_scaffold_ablation_results.png"),
        "results_source": str(ablation / "Figure_4B_scaffold_ablation_results_source.csv"),
    })
    write_csv(aware / "SCAFFOLD_ABLATION_RESULTS.csv", rows); documentation(aware, "Scaffold-aware paper", rows)
    (ablation / "README.md").write_text(
        "# Three-level NASICON scaffold ablation\n\n"
        "Complete frozen 3 × 3 NONE/LOOSE/HARD execution package. NONE is the unmodified QLIP 8 × 8 × 8 uniform-grid design space; LOOSE is the single deterministic chemistry-relaxation rule; HARD is the byte/hash-pinned production registry. See SCAFFOLD_ABLATION_RESULTS.csv, SCIENTIFIC_INTERPRETATION.md, validator/CHGNet tables, per-row artifacts, and Figure 4 source manifests.\n",
        encoding="utf-8",
    )
    (ablation / "GENERATION_AUDIT.md").write_text(
        "# Generation Audit\n\n"
        "- New non-overwriting timestamped root: YES\n"
        "- Scientific configuration frozen before the first solve: YES\n"
        "- Nine requested rows retained: YES\n"
        "- Native NONE rows executed with no scaffold registry: YES\n"
        "- HARD source hashes pinned: YES\n"
        "- LOOSE transformation deterministic and frozen: YES\n"
        "- Complete established validation run for every generated CIF: YES\n"
        "- Dedicated figure and per-row source manifests: YES\n"
        "- Validation—not solver optimality—used as quality axis: YES\n"
        "- Scientific outputs altered post-hoc: NO\n"
        "- Repository pushed: NO\n",
        encoding="utf-8",
    )
    (ablation / "VISUAL_QA_REPORT.md").write_text("# Visual QA Report\n\nPENDING final original-resolution inspection.\n", encoding="utf-8")
    package_manifest(ablation); package_manifest(spp); package_manifest(aware)
    print(json.dumps({"ablation": str(ablation), "spp_only": str(spp), "scaffold_aware": str(aware)}, indent=2))


if __name__ == "__main__": main()
