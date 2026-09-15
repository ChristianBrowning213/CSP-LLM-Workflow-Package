"""Freeze and visualize the three-level NASICON scaffold ablation before solving."""

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

from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages
from sok_llm_orchestrator.workflow.scaffold_ablation import load_selection


ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("Na3Zr2Si2PO12", "Na3Ti2(PO4)3", "LiZr2(PO4)3")
LOOSE = ROOT / "experiments" / "scaffold_ablation" / "scaffolds" / "loose"
HARD = ROOT / "experiments" / "scaffold_ablation" / "scaffolds" / "hard"
TABLE = ROOT / "experiments" / "scaffold_ablation" / "NASICON_SCAFFOLD_ABLATION.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def _cell_edges(matrix: np.ndarray):
    origin = np.zeros(3)
    corners = {bits: origin + sum((matrix[i] for i, bit in enumerate(bits) if bit), np.zeros(3)) for bits in np.ndindex(2, 2, 2)}
    for bits, start in corners.items():
        for axis in range(3):
            if bits[axis] == 0:
                end_bits = list(bits); end_bits[axis] = 1
                yield start, corners[tuple(end_bits)]


def _plot_space(ax, selection, title: str) -> None:
    if selection.mode == "none":
        density = selection.native_sites["uniform_grid"]["density"]
        coords = np.asarray(list(np.ndindex(density, density, density)), dtype=float) / density
        matrix = np.diag([3.9, 3.9, 3.9]); cart = coords @ matrix
        ax.scatter(cart[:, 0], cart[:, 1], cart[:, 2], s=3, alpha=0.28, color="#65727a")
        subtitle = "No geometry or occupation prior\n512 grid sites; 0 symmetry orbits"
    else:
        assert selection.structure is not None
        matrix = selection.structure.lattice.matrix
        cart = selection.structure.cart_coords
        fixed_indices = {int(i) for orbit in selection.orbits if orbit.get("fixed_species") for i in orbit["site_indices"]}
        variable_indices = set(range(len(cart))) - fixed_indices
        if fixed_indices:
            points = cart[sorted(fixed_indices)]
            ax.scatter(points[:, 0], points[:, 1], points[:, 2], s=18, alpha=0.72, color="#2b6f93", label="species-fixed")
        if variable_indices:
            points = cart[sorted(variable_indices)]
            ax.scatter(points[:, 0], points[:, 1], points[:, 2], s=27, alpha=0.85, facecolors="none", edgecolors="#b66b25", linewidths=0.9, label="variable occupation")
        subtitle = f"Geometry-fixed: {selection.symmetry_orbit_count} orbits\nSpecies-fixed: {selection.species_fixed_orbit_count}; variable: {selection.variable_orbit_count}; feasible: {selection.feasible_state_count:,}"
    for start, end in _cell_edges(matrix):
        ax.plot(*zip(start, end), color="#313b41", linewidth=0.55, alpha=0.55)
    ax.set_title(f"{title}\n{subtitle}", fontsize=8.5, pad=6)
    ax.set_xlabel("x (Å)", fontsize=7); ax.set_ylabel("y (Å)", fontsize=7); ax.set_zlabel("z (Å)", fontsize=7)
    ax.tick_params(labelsize=6); ax.view_init(elev=22, azim=35)
    if selection.mode != "none":
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.17), fontsize=6.5, frameon=False)


def build_figure(path: Path, selections: dict[str, Any]) -> None:
    fig = plt.figure(figsize=(15.5, 5.2), facecolor="white")
    grid = fig.add_gridspec(1, 4, width_ratios=[1.2, 1, 1, 1], left=0.03, right=0.98, top=0.83, bottom=0.08, wspace=0.24)
    math_ax = fig.add_subplot(grid[0, 0]); math_ax.set_axis_off()
    math_ax.set_title("QLIP occupation model", fontsize=11, fontweight="bold", loc="left")
    math_ax.text(0.01, 0.88,
        "$x_{i,s} \\in \\{0,1\\}$\n\n"
        "$\\sum_s x_{i,s} + v_i = 1$\n\n"
        "$\\sum_i x_{i,s} = n_s$  (exact composition)\n\n"
        "$x_{i,s}=x_{j,s}$  within a closed orbit\n\n"
        "$x_{i,s}=0$  outside each allowlist\n\n"
        "HARD additionally fixes selected $x_{i,s}=1$.\n\n"
        "Minimize the exact solver-effective SPP objective\nover the remaining feasible allocation.",
        va="top", fontsize=9.2, linespacing=1.25)
    for index, mode in enumerate(("none", "loose", "hard"), start=1):
        ax = fig.add_subplot(grid[0, index], projection="3d")
        _plot_space(ax, selections[mode], mode.upper())
    fig.suptitle("Geometry prior and chemical/occupation prior are distinct", fontsize=14, fontweight="bold", y=0.96)
    fig.savefig(path.with_suffix(".png"), dpi=260, facecolor="white")
    fig.savefig(path.with_suffix(".pdf"), facecolor="white")
    plt.close(fig)


def manifest(root: Path) -> None:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "MANIFEST.csv"):
        rows.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    write_csv(root / "MANIFEST.csv", rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = (args.output or ROOT / "artifacts" / f"Paper_results_scaffold_ablation_{stamp}").resolve()
    out.mkdir(parents=True, exist_ok=False)
    stages = ProductionWorkflowStages()
    modes = {"none": None, "loose": LOOSE, "hard": HARD}
    selections: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    audit = ["# Current NASICON Scaffold Degree-of-Freedom Audit", "", "Geometry-fixed means coordinates, orbit membership, and multiplicity are supplied. Species-fixed means `fixed_species` is populated after the production task adapter. These are not interchangeable.", ""]
    for formula in TARGETS:
        task = stages.normalise(formula)
        selections[formula] = {mode: load_selection(task, directory) for mode, directory in modes.items()}
        hard = selections[formula]["hard"]
        audit.extend([f"## {formula}", "", f"- Candidate sites: {hard.candidate_site_count}", f"- Geometry-fixed orbits: {hard.symmetry_orbit_count}/{hard.symmetry_orbit_count}", f"- Species-fixed orbits: {hard.species_fixed_orbit_count}", f"- Variable-occupation orbits: {hard.variable_orbit_count}", f"- Vacancy-bearing orbits: {sum(bool(o.get('vacancy_allowed')) for o in hard.orbits)}", f"- Exact symmetry-closed feasible assignments: {hard.feasible_state_count}", f"- Chemically meaningful HARD decisions: {'one of ' + str(hard.feasible_state_count) + ' feasible full-orbit assignments' if hard.feasible_state_count != 1 else 'none; orbit multiplicities plus exact composition determine the sole assignment'}", "", "| Orbit | Multiplicity | Geometry fixed | Species fixed | Allowed choices | Vacancy | Required occupancy |", "|---|---:|---|---|---|---|---|"])
        for orbit in hard.orbits:
            audit.append(f"| {orbit['orbit_id']} | {len(orbit['site_indices'])} | YES | {'YES' if orbit.get('fixed_species') else 'NO'} | {', '.join(orbit.get('allowed_species', []))} | {'YES' if orbit.get('vacancy_allowed') else 'NO'} | YES |")
        audit.extend(["", "Orbit closure applies one occupation choice to every member site of an orbit. Exact composition is enforced at the candidate-cell scale.", ""])
        for mode in modes:
            item = selections[formula][mode]
            rows.append({"formula": formula, **item.provenance(), "geometry_fixed_orbit_count": item.symmetry_orbit_count if mode != "none" else 0})
    audit.extend(["## Loose-rule boundary", "", "The single frozen rule expands every occupancy-bearing orbit to all target-composition species while retaining geometry, orbit closure, multiplicity, vacancy semantics, and exact composition. For LiZr2(PO4)3 this changes 0 to 5 formally variable orbits and 5 to 20 occupation binaries, but the preserved multiplicities (2, 4, 6, 12, 12) and exact counts still admit only one complete assignment. Increasing that count would require violating at least one frozen preservation rule; no target-specific exception was introduced.", ""])
    (out / "CURRENT_NASICON_SCAFFOLD_DOF_AUDIT.md").write_text("\n".join(audit), encoding="utf-8")
    write_csv(out / "SEARCH_SPACE_COUNTS.csv", rows)
    shutil.copy2(TABLE, out / "NASICON_SCAFFOLD_ABLATION.csv")
    shutil.copy2(LOOSE / "registry.json", out / "LOOSE_REGISTRY.json")
    shutil.copy2(HARD / "registry.json", out / "HARD_REGISTRY.json")
    frozen = {
        "schema_version": "nasicon_three_level_ablation_freeze.v1",
        "frozen_before_first_solve": True, "targets": list(TARGETS),
        "requests": {row["row_id"]: row["request"] for row in csv.DictReader(TABLE.open(encoding="utf-8"))},
        "retrieval": {"depth": 40, "corpus": "nasicon_specialist_v3", "method": "canonical row workflow"},
        "spp": {"request_mode": "enabled", "cutoff_A": 11.0, "request_coefficient": 1.0, "regulator_coefficient": 2.0, "outer_objective_scale": 10.0, "regulator_id": "icsd_broad_regulator_v1"},
        "solver": {"name": "gurobi", "time_limit_s": 300, "mip_gap": 0.0, "threads": 1, "seed": 0},
        "native_qlip": {"template": "cubic", "lattice_A": [3.9, 3.9, 3.9], "grid_density": 8, "candidate_sites": 512, "constraint": "proximity.atomic_radii(scale=1.0)", "ordered_orbits": 0},
        "loose_rule_sha256": sha256(LOOSE / "registry.json"), "hard_registry_sha256": sha256(HARD / "registry.json"),
        "validation": ["pymatgen parse/composition", "SCA geometry and topology", "pymatgen SpacegroupAnalyzer", "CHGNet relaxation", "pymatgen StructureMatcher initial-relaxed"],
        "post_hoc_tuning_allowed": False,
    }
    (out / "FROZEN_SCIENTIFIC_CONFIG.json").write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "ANALYSIS_PLAN.md").write_text("# Frozen Analysis Plan\n\nCompare NONE, LOOSE, and HARD per target using solver outcome, valid/exact CIF, geometry/contact checks, topology, CHGNet completion, initial/relaxed symmetry retention, StructureMatcher, and volume change. QLIP OPTIMAL is never a structural-quality score. Keep every controlled failure. Do not modify inputs after outcomes.\n", encoding="utf-8")
    build_figure(out / "Figure_4A_scaffold_math_and_3D", selections["Na3Zr2Si2PO12"])
    (out / "README.md").write_text("# Three-level NASICON scaffold ablation\n\nThis new timestamped package freezes NONE/native QLIP, deterministic LOOSE, and current-production HARD search spaces before the first solve. Execution results and Figure 4B are added only after the frozen nine-run experiment.\n", encoding="utf-8")
    (out / "GENERATION_AUDIT.md").write_text("# Generation Audit\n\n- New non-overwriting timestamped root: YES\n- Current QLIP registry inspected: YES\n- HARD source hashes pinned: YES\n- LOOSE transformation frozen before outcomes: YES\n- NONE uses QLIP CLI-native cubic 3.9 Å, 8×8×8 uniform grid: YES\n- Scientific solves executed during preparation: 0\n- Scientific outputs altered: NO\n", encoding="utf-8")
    (out / "VISUAL_QA_REPORT.md").write_text("# Visual QA Report\n\n- Figure_4A_scaffold_math_and_3D: PENDING INSPECTION\n", encoding="utf-8")
    manifest(out)
    print(out)


if __name__ == "__main__":
    main()
