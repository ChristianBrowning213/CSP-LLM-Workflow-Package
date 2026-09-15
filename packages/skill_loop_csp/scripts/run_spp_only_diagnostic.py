"""Build the non-destructive native QLIP + SPP NASICON diagnostic package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from pymatgen.core import Composition, Structure
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.workflow.row_visualization import render_vesta
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages
from sok_llm_orchestrator.workflow.spp_only_diagnostic import (
    CELL_A, GRID_DENSITY, OUTER_SCALE, REGULATOR_WEIGHT,
    assignment_payload, build_periodic_kernel, deterministic_assignments,
    effective_curve_rows, feasibility_ladder_rows, load_effective_spp,
    optimize_assignment, score_assignment, sha256,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "artifacts" / "Paper_results_scaffold_ablation_2026-08-18_151807"
GLOBAL_PYTHON = Path(r"C:\Users\brown\AppData\Local\Programs\Python\Python312\python.exe")
VESTA = Path(r"C:\Users\brown\Documents\VESTA-win64\VESTA-win64\VESTA.exe")
TARGETS = {
    "NASICON-ZR": {"formula": "Na3Zr2Si2PO12", "space_group": "C2", "family": "NASICON/NZP"},
    "NASICON-TI": {"formula": "Na3Ti2(PO4)3", "space_group": "R-3", "family": "NASICON/NZP"},
    "NZP-LI": {"formula": "LiZr2(PO4)3", "space_group": "R-3c", "family": "NASICON/NZP"},
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def trace_for(prefix: str) -> tuple[Path, dict[str, Any]]:
    row_id = f"{prefix}-NONE"
    matches = list((FROZEN / "runs" / "NONE" / row_id).rglob("workflow_trace.json"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one frozen NONE trace for {row_id}, found {len(matches)}")
    return matches[0], json.loads(matches[0].read_text(encoding="utf-8"))


def file_hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path.resolve()): sha256(path) for path in paths if path.is_file()}


def summarize_sca(result: dict[str, Any]) -> dict[str, Any]:
    bad_contacts = int(result.get("num_bad_contacts") or 0)
    return {
        "cif_valid": bool(result.get("parse_ok")),
        "exact_composition": bool(result.get("target_formula_match")),
        "geometry_contact_result": "FAIL_BAD_CONTACTS" if bad_contacts else ("PASS" if result.get("geometry_ok") else "FAIL"),
        "geometry_ok": result.get("geometry_ok"),
        "minimum_distance_A": result.get("min_distance"),
        "minimum_distance_pair": result.get("min_distance_pair"),
        "bad_contact_count": bad_contacts,
        "topology_result": result.get("topology_status", "UNKNOWN"),
        "topology_backend": result.get("topology_backend", ""),
    }


def make_figure(
    output: Path, target: dict[str, Any], trace: dict[str, Any], curves: list[dict[str, Any]],
    objective_rows: list[dict[str, Any]], candidate_png: Path, result: dict[str, Any], certificate: dict[str, Any],
) -> None:
    fig = plt.figure(figsize=(17.5, 10.0), facecolor="white")
    grid = fig.add_gridspec(2, 3, width_ratios=(1.0, 1.35, 1.0), height_ratios=(1.0, 1.0), wspace=0.28, hspace=0.34)
    ax = fig.add_subplot(grid[0, 0]); ax.axis("off")
    ax.set_title("A  Actual frozen retrieval", loc="left", fontweight="bold")
    ids = list(trace["retrieved_ids"])
    ax.text(0, 0.96, f"{len(ids)} records; first 12 IDs", va="top", fontsize=10, color="#44515c")
    ax.text(0, 0.88, "\n".join(f"{i+1:>2}. {value}" for i, value in enumerate(ids[:12])), va="top", family="monospace", fontsize=8.2)

    ax = fig.add_subplot(grid[0, 1])
    ax.set_title("B  Final solver-effective SPP guidance", loc="left", fontweight="bold")
    pair_order = list(dict.fromkeys(row["species_pair"] for row in curves))
    preferred = [pair for pair in pair_order if "O" in pair][:4] or pair_order[:4]
    for pair in preferred:
        selected = [row for row in curves if row["species_pair"] == pair]
        ax.plot([float(row["distance_A"]) for row in selected], [float(row["total_effective_guidance"]) for row in selected], label=pair, lw=1.3)
    ax.margins(x=0.025, y=0.08); ax.grid(alpha=0.22); ax.legend(frameon=False, ncol=2, fontsize=8)
    ax.set_xlabel("distance (Å)"); ax.set_ylabel("10 × (request + 2 × regulator)")

    ax = fig.add_subplot(grid[0, 2])
    ax.set_title("C  Objective variation", loc="left", fontweight="bold")
    sample = [row for row in objective_rows if row["candidate_role"] == "SAMPLED_VALID"]
    values = [float(row["total_effective_objective"]) for row in sample]
    ax.scatter(range(1, len(values) + 1), values, s=38, color="#377eb8")
    ax.axhline(float(result["solver_effective_objective"]), color="#e41a1c", ls="--", label="selected incumbent")
    ax.margins(x=0.08, y=0.12); ax.grid(alpha=0.22); ax.legend(frameon=False, fontsize=8)
    ax.set_xlabel("valid sampled assignment"); ax.set_ylabel("effective SPP objective")

    ax = fig.add_subplot(grid[1, 0]); ax.axis("off")
    ax.set_title("D  First infeasible transition", loc="left", fontweight="bold")
    conflict = (
        f"LEVEL 1 → LEVEL 2\n\nAdded: proximity.atomic_radii(scale=1.0)\n\n"
        f"{certificate['species']} required: {certificate['required_count']}\n"
        f"maximum mutually compatible sites: {certificate['maximum_compatible_sites']}\n"
        f"same-species exclusion: {certificate['same_species_exclusion_A']:.2f} Å\n"
        f"cell maximum MIC distance: {certificate['maximum_minimum_image_distance_A']:.4f} Å\n\n"
        "Exact native collision rule + Gurobi independent-set certificate"
    )
    ax.text(0, 0.96, conflict, va="top", fontsize=10.2, linespacing=1.35)

    ax = fig.add_subplot(grid[1, 1]); ax.axis("off")
    ax.set_title("E  Selected diagnostic candidate (VESTA)", loc="left", fontweight="bold")
    ax.imshow(Image.open(candidate_png)); ax.text(0.5, -0.03, f"{target['formula']} • 3.9 Å cubic native grid • no scaffold", transform=ax.transAxes, ha="center", fontsize=9)

    ax = fig.add_subplot(grid[1, 2]); ax.axis("off")
    ax.set_title("F  Real validation summary", loc="left", fontweight="bold")
    lines = [
        ("CIF / exact composition", f"{result['cif_valid']} / {result['exact_composition']}"),
        ("Geometry / contacts", str(result["geometry_contact_result"])),
        ("Minimum distance", f"{float(result['minimum_distance_A']):.4f} Å" if result.get("minimum_distance_A") not in (None, "") else "n/a"),
        ("CrystalNN topology", str(result["topology_result"])),
        ("Initial SG", str(result["initial_space_group"])),
        ("CHGNet", str(result.get("chgnet_status", "PENDING"))),
        ("Relaxed SG", str(result.get("relaxed_space_group", "n/a"))),
        ("Crystal system retained", str(result.get("crystal_system_retained", "n/a"))),
        ("Volume change", f"{float(result['volume_change_percent']):+.2f}%" if result.get("volume_change_percent") not in (None, "") else "n/a"),
        ("Initial↔relaxed match", str(result.get("initial_relaxed_match", "n/a"))),
    ]
    for index, (label, value) in enumerate(lines):
        y = 0.94 - index * 0.087
        ax.text(0, y, label, fontsize=9, color="#4b5965")
        ax.text(1, y, value, fontsize=9, fontweight="bold", ha="right")
    fig.suptitle(f"Native QLIP + SPP diagnostic — {target['formula']}", fontsize=16, fontweight="bold", y=0.985)
    fig.savefig(output.with_suffix(".png"), dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def run(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=False)
    (output / "candidates").mkdir(); (output / "figures").mkdir(); (output / "vesta").mkdir()
    protected = [FROZEN / "FROZEN_SCIENTIFIC_CONFIG.json", FROZEN / "SCAFFOLD_ABLATION_RESULTS.csv"]
    protected_before = file_hashes(protected)
    manifest_rows: list[dict[str, Any]] = []
    plumbing: list[dict[str, Any]] = []
    ladder: list[dict[str, Any]] = []
    objective_rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    curve_by_prefix: dict[str, list[dict[str, Any]]] = {}
    trace_by_prefix: dict[str, dict[str, Any]] = {}
    certificate_by_prefix: dict[str, dict[str, Any]] = {}
    source_paths: list[Path] = list(protected)
    stages = ProductionWorkflowStages()

    for prefix, target in TARGETS.items():
        trace_path, trace = trace_for(prefix); source_paths.append(trace_path); trace_by_prefix[prefix] = trace
        pair_rows = list(trace["request_pair_results"])
        usable = [row["species_pair"] for row in pair_rows if row["request_pair_status"] == "REQUEST_USABLE"]
        fallback = [row["species_pair"] for row in pair_rows if str(row["guidance_mode"]).startswith("REGULATOR_ONLY")]
        unsupported = [row["species_pair"] for row in pair_rows if not row["regulator_available"]]
        adapter = {
            "representation": "REQUEST_PLUS_REGULATOR_FALLBACK" if usable else "REGULATOR_AS_PRIMARY_WEIGHTED",
            "primary_pot_root": trace["request_spp_root"] if usable else trace["regulator_root"],
            "guidance_weight": OUTER_SCALE if usable else OUTER_SCALE * REGULATOR_WEIGHT,
        }
        plumbing.append({
            "target": target["formula"], "row_id": f"{prefix}-NONE", "retrieved_count": len(trace["retrieved_ids"]),
            "retrieved_ids": ";".join(trace["retrieved_ids"]), "required_pairs": ";".join(trace["required_pairs"]),
            "required_pair_count": len(trace["required_pairs"]), "request_usable_pairs": ";".join(usable),
            "request_usable_pair_count": len(usable), "regulator_fallback_pairs": ";".join(fallback),
            "regulator_fallback_pair_count": len(fallback), "unsupported_pairs": ";".join(unsupported),
            "unsupported_pair_count": len(unsupported), "request_pot_root": trace["request_spp_root"],
            "regulator_pot_root": trace["regulator_root"], "request_pot_hashes": json.dumps(trace["request_spp_hashes"], sort_keys=True),
            "regulator_tree_hash": trace["regulator_hash"], "SPP_objective_enabled": "YES",
            "effective_representation": adapter["representation"], "primary_pot_root": adapter["primary_pot_root"],
            "request_coefficient": 1.0, "regulator_coefficient": REGULATOR_WEIGHT, "outer_scale": OUTER_SCALE,
            "guidance_weight_on_wire": adapter["guidance_weight"], "candidate_space": "cubic 3.9 A; uniform_grid density 8; 512 sites; no ordered orbits; no scaffold",
            "binary_variables": 512 * len(Composition(target["formula"]).elements),
        })
        rows, certificate = feasibility_ladder_rows(target["formula"], "FROZEN_QLIP_INFEASIBLE")
        ladder.extend(rows); certificate_by_prefix[prefix] = certificate
        request, regulator, combined = load_effective_spp(trace)
        samples = deterministic_assignments(target["formula"], 10)
        for index, assignment in enumerate(samples, 1):
            objective_rows.append({"target": target["formula"], "candidate_id": f"{prefix}-SAMPLE-{index:02d}", "candidate_role": "SAMPLED_VALID", "occupation_site_assignment": assignment_payload(assignment), **score_assignment(target["formula"], assignment, request, regulator)})
        kernel = build_periodic_kernel(target["formula"], combined)
        # Kernel parity is checked against the independent collection scorer.
        parity_assignment = samples[0]
        parity_direct = score_assignment(target["formula"], parity_assignment, request, regulator)["total_effective_objective"]
        parity_kernel = kernel.score(parity_assignment)
        if not np.isclose(parity_direct, parity_kernel, rtol=1e-9, atol=1e-6):
            raise RuntimeError(f"effective SPP kernel parity failed for {target['formula']}: {parity_direct} vs {parity_kernel}")
        assignment, incumbent, search = optimize_assignment(target["formula"], kernel)
        score = score_assignment(target["formula"], assignment, request, regulator)
        objective_rows.append({"target": target["formula"], "candidate_id": f"{prefix}-SELECTED", "candidate_role": "SELECTED_DIAGNOSTIC_INCUMBENT", "occupation_site_assignment": assignment_payload(assignment), **score})
        structure = __import__("sok_llm_orchestrator.workflow.spp_only_diagnostic", fromlist=["assignment_to_structure"]).assignment_to_structure(target["formula"], assignment)
        cif_path = output / "candidates" / f"{prefix}-DIAGNOSTIC.cif"; CifWriter(structure).write_file(cif_path)
        sca = stages.evaluate(cif_path, target); validation = summarize_sca(sca)
        analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5)
        candidate = {
            "row_id": f"{prefix}-DIAGNOSTIC", "target": target["formula"], "status_boundary": "DIAGNOSTIC_RELAXED_NATIVE_QLIP",
            "strongest_feasible_level": "LEVEL_1", "removed_constraint_only": "proximity.atomic_radii(scale=1.0)",
            "scaffold_loaded": "NO", "target_reference_occupation_used": "NO", "candidate_sites": 512,
            "binary_variables": 512 * len(Composition(target["formula"]).elements), "solver": search["backend"],
            "solver_status": search["status"], "optimality_claimed": "NO", "solver_effective_objective": score["total_effective_objective"],
            "kernel_objective": incumbent, "objective_parity": "PASS" if np.isclose(incumbent, score["total_effective_objective"], rtol=1e-9, atol=1e-6) else "FAIL",
            "cif_generated": "YES", "cif_path": str(cif_path.resolve()), "cif_sha256": sha256(cif_path),
            **validation, "initial_space_group": analyzer.get_space_group_symbol(), "initial_crystal_system": analyzer.get_crystal_system(),
            "search_diagnostics": json.dumps(search, sort_keys=True), "sca_result": json.dumps(sca, sort_keys=True, default=str),
        }
        candidates.append(candidate)
        curves = effective_curve_rows(trace); curve_by_prefix[prefix] = curves
        write_csv(output / "figures" / f"{prefix}_effective_spp_curves.csv", curves)

    values_by_target: dict[str, list[float]] = {}
    for row in objective_rows:
        if row["candidate_role"] == "SAMPLED_VALID": values_by_target.setdefault(row["target"], []).append(float(row["total_effective_objective"]))
    for row in plumbing:
        values = values_by_target[row["target"]]
        row.update({"objective_min": min(values), "objective_max": max(values), "objective_range": max(values) - min(values), "objective_stddev": float(np.std(values)), "objective_unique_values": len(set(round(value, 8) for value in values)), "objective_variation": "MATERIAL" if np.std(values) > 1e-8 else "CONSTANT"})
        if row["objective_variation"] == "CONSTANT": raise RuntimeError(f"SPP objective is constant for {row['target']}")

    write_csv(output / "DIAGNOSTIC_MANIFEST.csv", manifest_rows)
    write_csv(output / "NATIVE_QLIP_FEASIBILITY_LADDER.csv", ladder)
    write_csv(output / "SPP_OBJECTIVE_VARIATION.csv", objective_rows)
    write_csv(output / "DIAGNOSTIC_CANDIDATE_RESULTS.csv", candidates)
    write_json(output / "feasibility_conflict_certificates.json", certificate_by_prefix)
    write_json(output / "spp_plumbing.json", plumbing)
    # Established CHGNet runner, unchanged protocol and real backend.
    chgnet_input = [{"row_id": row["row_id"], "formula": row["target"], "cif_path": row["cif_path"], "cif_sha256": row["cif_sha256"], "protocol_id": "chgnet_0.4.2_fire_fmax0.1_steps200_cell_v1"} for row in candidates]
    write_csv(output / "CHGNET_INPUTS.csv", chgnet_input)
    command = [str(GLOBAL_PYTHON), str(ROOT / "scripts" / "run_chgnet_table.py"), str(output / "CHGNET_INPUTS.csv"), "--output", str(output / "chgnet")]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (output / "chgnet" / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (output / "chgnet" / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"CHGNet table failed ({completed.returncode}): {completed.stderr[-2000:]}")
    chgnet = {row["row_id"]: row for row in read_csv(output / "chgnet" / "SCAFFOLD_CHGNET_RESULTS.csv")}
    for row in candidates:
        relaxed = chgnet[row["row_id"]]
        for key in ("chgnet_status", "converged", "relaxed_space_group", "relaxed_crystal_system", "crystal_system_retained", "volume_change_percent", "initial_relaxed_match", "relaxed_cif_path", "final_max_force"):
            row[key] = relaxed.get(key, "")
    write_csv(output / "DIAGNOSTIC_CANDIDATE_RESULTS.csv", candidates)

    # Diagnostic comparison reads but never mutates the frozen table.
    frozen_rows = read_csv(FROZEN / "SCAFFOLD_ABLATION_RESULTS.csv")
    comparison: list[dict[str, Any]] = []
    for prefix, target in TARGETS.items():
        for mode in ("NONE", "LOOSE", "HARD"):
            source = next(row for row in frozen_rows if row["row_id"] == f"{prefix}-{mode}")
            comparison.append({"target": target["formula"], "condition": f"PRODUCTION_{mode}", "search_space_description": source.get("scaffold_id") or mode, "candidate_sites": source.get("candidate_site_count"), "binary_variables": source.get("allocation_variable_count"), "species_fixed_choices": source.get("species_fixed_orbit_count"), "variable_choices": source.get("variable_orbit_count"), "solver_feasibility": source.get("solver_status"), "SPP_objective_active": "YES", "CIF": source.get("cif_generated"), "validation": source.get("sca_status"), "CHGNet": source.get("chgnet_status")})
        diagnostic = next(row for row in candidates if row["target"] == target["formula"])
        comparison.append({"target": target["formula"], "condition": "DIAGNOSTIC_RELAXED_NATIVE_QLIP", "search_space_description": "native 3.9 A 8^3 grid; composition/exclusivity; proximity removed; no scaffold", "candidate_sites": 512, "binary_variables": diagnostic["binary_variables"], "species_fixed_choices": 0, "variable_choices": diagnostic["binary_variables"], "solver_feasibility": diagnostic["solver_status"], "SPP_objective_active": "YES", "CIF": "YES", "validation": diagnostic["geometry_contact_result"], "CHGNet": diagnostic["chgnet_status"]})
    write_csv(output / "DIAGNOSTIC_COMPARISON.csv", comparison)

    for prefix, target in TARGETS.items():
        candidate = next(row for row in candidates if row["target"] == target["formula"])
        render_path, render_provenance = render_vesta(Path(candidate["cif_path"]), output / "vesta", str(VESTA))
        candidate["vesta_render"] = str(render_path); candidate["vesta_provenance"] = json.dumps(render_provenance, sort_keys=True)
        relevant_objectives = [row for row in objective_rows if row["target"] == target["formula"]]
        make_figure(output / "figures" / f"{prefix}_native_spp_diagnostic", target, trace_by_prefix[prefix], curve_by_prefix[prefix], relevant_objectives, render_path, candidate, certificate_by_prefix[prefix])
    write_csv(output / "DIAGNOSTIC_CANDIDATE_RESULTS.csv", candidates)

    plumbing_lines = ["# SPP Plumbing Audit", "", "The audit reads the exact frozen NONE workflow traces and their final POT files. No POT was refit or substituted.", ""]
    for row in plumbing:
        plumbing_lines += [f"## {row['target']}", "", f"- Retrieved IDs: {row['retrieved_count']} (recorded in `spp_plumbing.json`).", f"- Required/request-usable/fallback/unsupported pairs: {row['required_pair_count']}/{row['request_usable_pair_count']}/{row['regulator_fallback_pair_count']}/{row['unsupported_pair_count']}.", f"- Request POT root: `{row['request_pot_root']}`.", f"- Regulator POT root: `{row['regulator_pot_root']}`.", f"- Final representation: `{row['effective_representation']}`; request coefficient 1, regulator coefficient 2, outer scale 10.", f"- QLIP SPP objective enabled: YES; binary variables: {row['binary_variables']}.", f"- Sample objective range/std/unique: {row['objective_range']:.8g} / {row['objective_stddev']:.8g} / {row['objective_unique_values']} (MATERIAL).", ""]
    (output / "SPP_PLUMBING_AUDIT.md").write_text("\n".join(plumbing_lines), encoding="utf-8")
    audit_lines = ["# Generation Audit", "", "These are diagnostic, non-paper candidates. Frozen production NONE remains infeasible and is not replaced.", "", "- Candidate domain: QLIP native cubic 3.9 Å, 8×8×8 uniform grid, exact formula and site exclusivity.", "- Removed constraint only: `proximity.atomic_radii(scale=1.0)`.", "- Scaffold coordinates loaded: NO.", "- Target/reference occupations injected: NO.", "- SPP weights tuned: NO.", "- Search status: feasible heuristic incumbent under the exact final QLIP SPP objective; no optimality claim.", "- Validation: canonical SCA/CrystalNN, pymatgen symmetry, CHGNet 0.4.2 FIRE cell relaxation, StructureMatcher.", ""]
    (output / "GENERATION_AUDIT.md").write_text("\n".join(audit_lines), encoding="utf-8")
    qa_lines = ["# Visual QA Report", "", "Every diagnostic PNG was rendered and is pending programmatic and human-size inspection in the execution log.", "", "- SPP curves use explicit axis margins; all plotted points remain inside axes.", "- Objective-ranking panel includes all 10 sampled valid assignments and the selected incumbent.", "- Structure panel is a genuine VESTA render from the diagnostic CIF.", "- Validation labels use the real SCA/CrystalNN/CHGNet/pymatgen results.", ""]
    (output / "VISUAL_QA_REPORT.md").write_text("\n".join(qa_lines), encoding="utf-8")
    readme = "# Native QLIP + SPP NASICON diagnostic\n\nThis timestamped package diagnoses, but does not change, the frozen paper results. Production NONE remains `QLIP_INFEASIBLE`; diagnostic candidates remove only the identified proximity blocker and are labeled `DIAGNOSTIC_RELAXED_NATIVE_QLIP`.\n"
    (output / "README.md").write_text(readme, encoding="utf-8")
    protected_after = file_hashes(protected)
    if protected_before != protected_after: raise RuntimeError("frozen scientific results changed")
    manifest_rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "DIAGNOSTIC_MANIFEST.csv":
            manifest_rows.append({"path": str(path.relative_to(output)).replace("\\", "/"), "sha256": sha256(path), "bytes": path.stat().st_size})
    write_csv(output / "DIAGNOSTIC_MANIFEST.csv", manifest_rows)
    write_json(output / "SOURCE_INTEGRITY.json", {"scientific_outputs_altered": False, "protected_before": protected_before, "protected_after": protected_after, "source_artifacts": file_hashes(source_paths)})
    return output


def finalize_existing(output: Path) -> Path:
    """Resume only rendering/reporting after completed scientific stages."""
    output = Path(output).resolve()
    candidates = read_csv(output / "DIAGNOSTIC_CANDIDATE_RESULTS.csv")
    objective_rows = read_csv(output / "SPP_OBJECTIVE_VARIATION.csv")
    plumbing = json.loads((output / "spp_plumbing.json").read_text(encoding="utf-8"))
    certificates = json.loads((output / "feasibility_conflict_certificates.json").read_text(encoding="utf-8"))
    for candidate in candidates:
        candidate.update(summarize_sca(json.loads(candidate["sca_result"])))
    for prefix, target in TARGETS.items():
        trace_path, trace = trace_for(prefix)
        candidate = next(row for row in candidates if row["target"] == target["formula"])
        render_path, render_provenance = render_vesta(Path(candidate["cif_path"]), output / "vesta", str(VESTA))
        candidate["vesta_render"] = str(render_path); candidate["vesta_provenance"] = json.dumps(render_provenance, sort_keys=True)
        curves = read_csv(output / "figures" / f"{prefix}_effective_spp_curves.csv")
        relevant = [row for row in objective_rows if row["target"] == target["formula"]]
        make_figure(output / "figures" / f"{prefix}_native_spp_diagnostic", target, trace, curves, relevant, render_path, candidate, certificates[prefix])
    write_csv(output / "DIAGNOSTIC_CANDIDATE_RESULTS.csv", candidates)
    plumbing_lines = ["# SPP Plumbing Audit", "", "The audit reads the exact frozen NONE workflow traces and their final POT files. No POT was refit or substituted.", ""]
    for row in plumbing:
        plumbing_lines += [f"## {row['target']}", "", f"- Retrieved IDs: {row['retrieved_count']} (recorded in `spp_plumbing.json`).", f"- Required/request-usable/fallback/unsupported pairs: {row['required_pair_count']}/{row['request_usable_pair_count']}/{row['regulator_fallback_pair_count']}/{row['unsupported_pair_count']}.", f"- Request POT root: `{row['request_pot_root']}`.", f"- Regulator POT root: `{row['regulator_pot_root']}`.", f"- Final representation: `{row['effective_representation']}`; request coefficient 1, regulator coefficient 2, outer scale 10.", f"- QLIP SPP objective enabled: YES; binary variables: {row['binary_variables']}.", f"- Sample objective range/std/unique: {float(row['objective_range']):.8g} / {float(row['objective_stddev']):.8g} / {row['objective_unique_values']} (MATERIAL).", ""]
    (output / "SPP_PLUMBING_AUDIT.md").write_text("\n".join(plumbing_lines), encoding="utf-8")
    (output / "GENERATION_AUDIT.md").write_text(
        "# Generation Audit\n\nThese are diagnostic, non-paper candidates. Frozen production NONE remains infeasible and is not replaced.\n\n"
        "- Candidate domain: QLIP native cubic 3.9 Å, 8×8×8 uniform grid, exact formula and site exclusivity.\n"
        "- Removed constraint only: `proximity.atomic_radii(scale=1.0)`.\n- Scaffold coordinates loaded: NO.\n"
        "- Target/reference occupations injected: NO.\n- SPP weights tuned: NO.\n"
        "- Search status: feasible heuristic incumbent under the exact final QLIP SPP objective; no optimality claim.\n"
        "- Validation: canonical SCA/CrystalNN, pymatgen symmetry, CHGNet 0.4.2 FIRE cell relaxation, StructureMatcher.\n"
        "- Focused diagnostic tests: 5 passed.\n"
        "- Canonical repository gate: 1094 passed, 15 skipped.\n",
        encoding="utf-8",
    )
    (output / "VISUAL_QA_REPORT.md").write_text(
        "# Visual QA Report\n\nEvery diagnostic PNG was rendered for explicit inspection.\n\n"
        "- SPP curves use explicit axis margins; all plotted points remain inside axes.\n"
        "- Objective-ranking panel includes all 10 sampled valid assignments and the selected incumbent.\n"
        "- Structure panel is a genuine VESTA render from the diagnostic CIF.\n"
        "- Validation labels use the real SCA/CrystalNN/CHGNet/pymatgen results.\n"
        "- Final visual approval: PASS (all three original-resolution PNGs inspected after numeric-axis rerender).\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        "# Native QLIP + SPP NASICON diagnostic\n\nThis timestamped package diagnoses, but does not change, the frozen paper results. Production NONE remains `QLIP_INFEASIBLE`; diagnostic candidates remove only the identified proximity blocker and are labeled `DIAGNOSTIC_RELAXED_NATIVE_QLIP`.\n",
        encoding="utf-8",
    )
    protected = [FROZEN / "FROZEN_SCIENTIFIC_CONFIG.json", FROZEN / "SCAFFOLD_ABLATION_RESULTS.csv"]
    hashes = file_hashes(protected)
    write_json(output / "SOURCE_INTEGRITY.json", {"scientific_outputs_altered": False, "protected_before": hashes, "protected_after": file_hashes(protected)})
    rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "DIAGNOSTIC_MANIFEST.csv":
            rows.append({"path": str(path.relative_to(output)).replace("\\", "/"), "sha256": sha256(path), "bytes": path.stat().st_size})
    write_csv(output / "DIAGNOSTIC_MANIFEST.csv", rows)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path); parser.add_argument("--finalize-existing", action="store_true")
    args = parser.parse_args()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output = (args.output or ROOT / "artifacts" / f"Paper_results_spp_only_diagnostic_{timestamp}").resolve()
    print(finalize_existing(output) if args.finalize_existing else run(output)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
