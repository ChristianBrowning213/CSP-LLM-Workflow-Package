"""Run the frozen final SCA protocol on hash-unique workflow CIFs."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT.parent
SCA_ROOT = GITHUB / "Structured_Crystal_Analyser"
sys.path.insert(0, str(SCA_ROOT))

from sca.evaluators.bonds import evaluate_bonds  # noqa: E402
from sca.evaluators.geometry import evaluate_geometry  # noqa: E402
from sca.evaluators.mlip import M3GNetStaticBenchmarkEvaluator  # noqa: E402
from sca.evaluators.topology import family_topology_metrics  # noqa: E402


OUT = ROOT / "artifacts" / "paper_final_results_v1"
MANIFESTS = OUT / "01_manifests"
PROTOCOL = OUT / "02_protocol"
SCA_OUT = OUT / "03_sca"
ACCEPT = OUT / "04_acceptance"
ANALYSIS = OUT / "05_analysis"
RUNS = ROOT / "runs" / "paper_final_results_v1"
SOURCE_SCA = SCA_ROOT / "artifacts" / "paper_full_sca_v1"
MATCHER_SETTINGS = {"ltol": 0.2, "stol": 0.3, "angle_tol": 5.0, "primitive_cell": True, "scale": True, "attempt_supercell": False}
RELAX_SETTINGS = {"optimizer": "FIRE", "fmax": 0.1, "steps": 200, "relax_cell": True}
POLICY_MAP = {
    "rocksalt": "ROCKSALT", "nitride": "ROCKSALT", "fluorite": "FLUORITE",
    "perovskite": "PEROVSKITE_3D", "spinel": "SPINEL",
    "olivine phosphate": "OLIVINE", "layered oxide": "LAYERED_OXIDE",
    "argyrodite": "ARGYRODITE_ORDERED", "halide perovskite": "HALIDE_PEROVSKITE_3D",
    "nasicon": "NASICON_ORDERED",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    columns = fields or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True, default=str) + "\n" for row in rows), encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(structure: Structure) -> str:
    payload = {
        "lattice": [[round(float(value), 10) for value in row] for row in structure.lattice.matrix],
        "sites": sorted((site.species_string, *(round(float(x % 1), 10) for x in site.frac_coords)) for site in structure),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "pass", "optimal"}


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def git_state(path: Path) -> dict[str, Any]:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True, check=True).stdout.splitlines()
    return {"path": str(path), "commit": sha, "dirty": bool(status), "status_line_count": len(status)}


def ensure_gate() -> None:
    checks = read_csv(MANIFESTS / "FINAL_PRE_RUN_HASH_CHECK.csv")
    if not checks or any(row["status"] != "PASS" for row in checks):
        raise RuntimeError("PROTECTED_INPUT_HASH_MISMATCH: final pre-run gate is not green")


def freeze_protocol() -> dict[str, Any]:
    import torch
    protocol = {
        "protocol_id": "paper_final_sca_v1",
        "initial": {
            "parse": True, "strict_reduced_formula": True, "site_count": True,
            "severe_contacts": True, "bond_reasonableness": True, "minimum_distance": True,
            "density_volume": True, "symmetry_symprec": [0.001, 0.01, 0.1],
            "angle_tolerance_degrees": 5.0, "family_topology": True,
            "reference_matching": True, "trace_completeness": True,
        },
        "structure_matcher": MATCHER_SETTINGS,
        "static_mlip": {
            "operational": ["CHGNet", "M3GNet/MatGL"],
            "unavailable_unless_preconfigured": ["ALIGNN", "MACE", "SevenNet"],
            "energy_comparison": "within-model percentile ranks only",
        },
        "relaxation": {"model": "CHGNet pretrained 0.3.0", **RELAX_SETTINGS, "cell_policy": "CHGNet StructOptimizer default"},
        "collapse": {"formula_or_site_count_changed": True, "minimum_distance_below_angstrom": 1.0, "absolute_volume_change_percent_above": 30.0, "topology_fail": True},
        "predicted_hull": {"status": "NOT_COMPUTABLE", "reason": "INCOMPLETE_SAME_MODEL_COMPETING_PHASE_SET"},
        "versions": {
            "repositories": [git_state(path) for path in (ROOT, GITHUB / "qlip", GITHUB / "Crystal-DB", SCA_ROOT)],
            "python": sys.version, "operating_system": platform.platform(),
            "pymatgen": package_version("pymatgen"), "spglib": package_version("spglib"),
            "chgnet": package_version("chgnet"), "matgl": package_version("matgl"),
            "torch": package_version("torch"), "cuda": torch.version.cuda or "NOT_AVAILABLE",
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU_ONLY",
            "gurobi_qlip_environment": "recorded row-wise from archived solver certificates",
        },
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    PROTOCOL.mkdir(parents=True, exist_ok=True)
    write_json(PROTOCOL / "FINAL_SCA_PROTOCOL.json", protocol)
    (PROTOCOL / "FINAL_SCA_PROTOCOL.md").write_text(
        "# Frozen final SCA protocol\n\nInitial CIFs are checked for parse, exact reduced formula, sites, contacts, geometry, a three-tolerance symmetry sweep, family topology, local reference matching and trace completeness. Static CHGNet and M3GNet values remain model-specific. Fresh CHGNet relaxation uses FIRE, 0.1 eV/Å, 200 steps and cell relaxation. Collapse requires formula/site loss, a sub-1 Å contact, absolute volume change above 30%, or failed required topology.\n",
        encoding="utf-8",
    )
    (PROTOCOL / "SOFTWARE_AND_MODEL_VERSIONS.txt").write_text(
        json.dumps(protocol["versions"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return protocol


def deduplicate(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    structures: dict[str, Structure] = {}
    enriched = []
    for row in rows:
        path = Path(row["generated_cif_path"])
        actual = sha256(path)
        if actual != row["expected_cif_sha256"]:
            raise RuntimeError(f"PROTECTED_INPUT_HASH_MISMATCH: {row['final_row_id']}")
        structure = Structure.from_file(path)
        structures[row["final_row_id"]] = structure
        enriched.append({**row, "raw_cif_sha256": actual, "canonical_structure_sha256": canonical_hash(structure), "parsed_formula": structure.composition.reduced_formula, "site_count": len(structure)})
    raw_groups: dict[str, list[str]] = defaultdict(list)
    canonical_groups: dict[str, list[str]] = defaultdict(list)
    for row in enriched:
        raw_groups[row["raw_cif_sha256"]].append(row["final_row_id"])
        canonical_groups[row["canonical_structure_sha256"]].append(row["final_row_id"])
    matcher = StructureMatcher(**MATCHER_SETTINGS)
    formula_groups: dict[str, list[str]] = defaultdict(list)
    for row in enriched:
        formula_groups[Composition(row["target_formula"]).reduced_formula].append(row["final_row_id"])
    sm_groups: list[list[str]] = []
    for ids in formula_groups.values():
        remaining = list(ids)
        while remaining:
            seed = remaining.pop(0); group = [seed]
            for other in list(remaining):
                if matcher.fit(structures[seed], structures[other]):
                    group.append(other); remaining.remove(other)
            sm_groups.append(group)
    raw_id = {hash_: f"RAW-{i:03d}" for i, hash_ in enumerate(sorted(raw_groups), 1)}
    canonical_id = {hash_: f"CAN-{i:03d}" for i, hash_ in enumerate(sorted(canonical_groups), 1)}
    sm_id = {row_id: f"SM-{i:03d}" for i, group in enumerate(sorted(sm_groups, key=lambda g: g[0]), 1) for row_id in group}
    unique_rows = []
    mapping = []
    for row in enriched:
        uid = f"U-{len(unique_rows)+1:03d}" if row["raw_cif_sha256"] not in {u["raw_cif_sha256"] for u in unique_rows} else next(u["unique_structure_id"] for u in unique_rows if u["raw_cif_sha256"] == row["raw_cif_sha256"])
        if not any(u["unique_structure_id"] == uid for u in unique_rows):
            unique_rows.append({"unique_structure_id": uid, **row})
        mapping.append({"final_row_id": row["final_row_id"], "unique_structure_id": uid, "raw_hash_group": raw_id[row["raw_cif_sha256"]], "canonical_hash_group": canonical_id[row["canonical_structure_sha256"]], "structurematcher_group": sm_id[row["final_row_id"]]})
    write_csv(MANIFESTS / "FINAL_UNIQUE_STRUCTURE_MANIFEST.csv", unique_rows)
    write_csv(MANIFESTS / "FINAL_ROW_TO_UNIQUE_STRUCTURE_MAP.csv", mapping)
    duplicate_tables = (
        ("FINAL_RAW_HASH_DUPLICATE_GROUPS.csv", raw_groups, raw_id),
        ("FINAL_CANONICAL_HASH_DUPLICATE_GROUPS.csv", canonical_groups, canonical_id),
    )
    for name, groups, ids in duplicate_tables:
        write_csv(MANIFESTS / name, [{"group_id": ids[key], "hash": key, "row_count": len(value), "final_row_ids": ";".join(value)} for key, value in groups.items() if len(value) > 1], ["group_id", "hash", "row_count", "final_row_ids"])
    write_csv(MANIFESTS / "FINAL_STRUCTUREMATCHER_GROUPS.csv", [{"group_id": f"SM-{i:03d}", "row_count": len(group), "final_row_ids": ";".join(group), "formula": structures[group[0]].composition.reduced_formula} for i, group in enumerate(sorted(sm_groups, key=lambda g: g[0]), 1)])
    causes = []
    by_row = {row["final_row_id"]: row for row in enriched}
    for i, group in enumerate(sm_groups, 1):
        if len(group) < 2: continue
        members = [by_row[item] for item in group]
        same_raw = len({m["raw_cif_sha256"] for m in members}) == 1
        same_scaffold = len({m["scaffold_id"] for m in members}) == 1
        same_request = len({m["natural_language_request"] for m in members}) == 1
        cause = "REPEATED_EXPERIMENTAL_CONDITION" if same_request else "SAME_FORMULA_SAME_SCAFFOLD" if same_scaffold else "SAME_STRUCTURE_DIFFERENT_TRACE" if same_raw else "HASH_DIFFERENT_STRUCTURE_EQUIVALENT"
        causes.append({"group_id": f"SM-{i:03d}", "classification": cause, "final_row_ids": ";".join(group), "same_raw_hash": same_raw, "same_scaffold": same_scaffold, "same_request": same_request})
    write_csv(MANIFESTS / "FINAL_DUPLICATE_CAUSE_AUDIT.csv", causes, ["group_id", "classification", "final_row_ids", "same_raw_hash", "same_scaffold", "same_request"])
    return unique_rows, mapping


def symmetry(structure: Structure) -> dict[str, Any]:
    values = {}
    for tol in (0.001, 0.01, 0.1):
        analyzer = SpacegroupAnalyzer(structure, symprec=tol, angle_tolerance=5.0)
        values[str(tol)] = {"symbol": analyzer.get_space_group_symbol(), "number": analyzer.get_space_group_number(), "crystal_system": analyzer.get_crystal_system()}
    return values


def initial_evaluate(row: dict[str, Any], run: Path, references: list[tuple[str, Structure]]) -> dict[str, Any]:
    base = {"unique_structure_id": row["unique_structure_id"], "target_formula": row["target_formula"], "target_family": row["target_family"], "status": "ERROR"}
    try:
        structure = Structure.from_file(row["generated_cif_path"])
        geom = evaluate_geometry(structure); bonds = evaluate_bonds(structure); sweep = symmetry(structure)
        formula_match = structure.composition.reduced_formula == Composition(row["target_formula"]).reduced_formula
        policy = POLICY_MAP.get(row["target_family"].lower(), "GENERIC_SCAFFOLD_ONLY")
        topology, topology_details = family_topology_metrics(structure, policy)
        matcher = StructureMatcher(**MATCHER_SETTINGS)
        exact, near = [], []
        for ref_id, ref in references:
            if ref.composition.reduced_formula != structure.composition.reduced_formula: continue
            if matcher.fit(structure, ref): exact.append(ref_id)
            elif matcher.fit_anonymous(structure, ref): near.append(ref_id)
        reference_label = "REDISCOVERED_REFERENCE" if exact else "NEAR_REFERENCE" if near else "NO_MATCH_IN_EVALUATED_LOCAL_CORPUS"
        item = {**base, "status": "PASS", "parse_ok": True, "detected_formula": structure.composition.reduced_formula,
            "formula_match": formula_match, "site_count": len(structure), "severe_contact_count": bonds.num_bad_contacts,
            "contact_screen_pass": bonds.num_bad_contacts == 0 and bonds.bond_lengths_reasonable is True,
            "bond_lengths_reasonable": bonds.bond_lengths_reasonable, "minimum_distance": bonds.min_distance,
            "minimum_distance_pair": bonds.min_distance_pair, "density": geom.density, "volume": geom.volume,
            "volume_per_atom": geom.volume_per_atom, "geometry_ok": geom.geometry_ok, "symmetry_sweep": sweep,
            "detected_space_group": sweep["0.01"]["symbol"], "detected_crystal_system": sweep["0.01"]["crystal_system"],
            "topology_policy": policy, "topology_status": topology["topology_status"], "topology_details": topology_details,
            "reference_label": reference_label, "reference_matches": exact or near,
            "raw_cif_sha256": row["raw_cif_sha256"], "canonical_structure_sha256": row["canonical_structure_sha256"], "error": ""}
    except Exception as exc:
        item = {**base, "parse_ok": False, "formula_match": False, "error": f"{type(exc).__name__}: {exc}"}
    write_json(run / "initial_sca" / "result.json", item)
    return item


def static_evaluate(row: dict[str, Any], run: Path, chgnet_model: Any) -> dict[str, Any]:
    result = {"unique_structure_id": row["unique_structure_id"], "chgnet_status": "ERROR", "m3gnet_status": "ERROR", "alignn_status": "NOT_CONFIGURED", "mace_status": "NOT_CONFIGURED", "sevennet_status": "NOT_CONFIGURED"}
    path = row["generated_cif_path"]
    try:
        structure = Structure.from_file(path); pred = chgnet_model.predict_structure(structure)
        forces = np.asarray(pred.get("f") if pred.get("f") is not None else pred.get("forces"), dtype=float)
        result.update({"chgnet_status": "PASS", "chgnet_model": getattr(chgnet_model, "model_name", "CHGNet pretrained 0.3.0"), "chgnet_energy_per_atom": float(np.asarray(pred.get("e") if pred.get("e") is not None else pred.get("energy_per_atom")).reshape(-1)[0]), "chgnet_max_force": float(np.linalg.norm(forces, axis=1).max()), "chgnet_error": ""})
    except Exception as exc:
        result["chgnet_error"] = f"{type(exc).__name__}: {exc}"
    try:
        m3 = M3GNetStaticBenchmarkEvaluator().evaluate_path(path)
        result.update({"m3gnet_status": "PASS" if m3.ok else "NOT_CONFIGURED" if m3.skipped else "ERROR", "m3gnet_model": m3.model, "m3gnet_energy_per_atom": m3.metrics.get("m3gnet_energy_per_atom"), "m3gnet_max_force": m3.metrics.get("m3gnet_forces_max"), "m3gnet_error": m3.error_message or ""})
    except Exception as exc:
        result["m3gnet_error"] = f"{type(exc).__name__}: {exc}"
    write_json(run / "static_mlip" / "result.json", result)
    return result


def force_metrics(forces: Any) -> tuple[float | None, float | None]:
    arr = np.asarray(forces, dtype=float)
    if not arr.size or not np.isfinite(arr).all(): return None, None
    norms = np.linalg.norm(arr, axis=1)
    return float(norms.max()), float(np.sqrt(np.mean(norms ** 2)))


def relax_evaluate(row: dict[str, Any], run: Path, model: Any, relaxer: Any) -> dict[str, Any]:
    started = time.perf_counter(); base = {"unique_structure_id": row["unique_structure_id"], "relaxation_status": "ERROR", **RELAX_SETTINGS}
    try:
        before = Structure.from_file(row["generated_cif_path"]); initial_pred = model.predict_structure(before)
        result = relaxer.relax(before, fmax=0.1, steps=200, relax_cell=True, verbose=False)
        after = result.get("final_structure") or result.get("structure")
        if after is None: raise RuntimeError("CHGNet returned no final structure")
        trajectory = result.get("trajectory"); energies = list(getattr(trajectory, "energies", []) or []); forces = list(getattr(trajectory, "forces", []) or [])
        initial_force = initial_pred.get("f") if initial_pred.get("f") is not None else initial_pred.get("forces")
        final_force = forces[-1] if forces else np.full((len(after), 3), np.nan)
        initial_max, initial_rms = force_metrics(initial_force); final_max, final_rms = force_metrics(final_force)
        relaxed_path = run / "relaxation" / "relaxed.cif"; CifWriter(after).write_file(relaxed_path)
        initial_energy = float(np.asarray(initial_pred.get("e") if initial_pred.get("e") is not None else initial_pred.get("energy_per_atom")).reshape(-1)[0])
        final_energy = float(energies[-1]) / len(after) if energies else None
        item = {**base, "relaxation_status": "PASS", "converged": final_max is not None and final_max <= 0.1,
            "termination_reason": "force_threshold" if final_max is not None and final_max <= 0.1 else "maximum_steps_or_optimizer_termination",
            "initial_energy_per_atom": initial_energy, "final_energy_per_atom": final_energy,
            "energy_change_per_atom": final_energy - initial_energy if final_energy is not None else None,
            "initial_max_force": initial_max, "final_max_force": final_max, "initial_rms_force": initial_rms, "final_rms_force": final_rms,
            "relaxation_steps": len(energies), "initial_volume": before.volume, "final_volume": after.volume,
            "volume_change_percent": 100 * (after.volume - before.volume) / before.volume,
            "relaxed_cif_path": str(relaxed_path), "relaxed_cif_sha256": sha256(relaxed_path), "runtime_seconds": time.perf_counter() - started, "error": ""}
    except Exception as exc:
        item = {**base, "converged": False, "runtime_seconds": time.perf_counter() - started, "error": f"{type(exc).__name__}: {exc}"}
    write_json(run / "relaxation" / "result.json", item)
    return item


def post_evaluate(row: dict[str, Any], initial: dict[str, Any], relax: dict[str, Any], run: Path) -> dict[str, Any]:
    base = {"unique_structure_id": row["unique_structure_id"], "post_relax_status": "NOT_COMPUTABLE"}
    if relax["relaxation_status"] != "PASS":
        item = {**base, "error": relax.get("error", "relaxation unavailable")}; write_json(run / "relaxed_sca" / "result.json", item); return item
    try:
        before = Structure.from_file(row["generated_cif_path"]); after = Structure.from_file(relax["relaxed_cif_path"])
        bonds = evaluate_bonds(after); geom = evaluate_geometry(after); sweep = symmetry(after)
        policy = POLICY_MAP.get(row["target_family"].lower(), "GENERIC_SCAFFOLD_ONLY")
        topology, details = family_topology_metrics(after, policy)
        matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5.0, primitive_cell=False, scale=False, attempt_supercell=False)
        fit = matcher.fit(before, after); rms = matcher.get_rms_dist(before, after) if fit else None
        formula = before.composition.reduced_composition.almost_equals(after.composition.reduced_composition)
        volume_change = 100 * (after.volume - before.volume) / before.volume
        topology_retained = topology["topology_status"] == "PASS" or topology["topology_status"] == initial.get("topology_status")
        collapse = (not formula or len(before) != len(after) or (bonds.min_distance is not None and bonds.min_distance < 1.0) or abs(volume_change) > 30 or topology["topology_status"] == "FAIL")
        item = {**base, "post_relax_status": "PASS", "parse_ok": True, "formula_preserved": formula,
            "site_count_preserved": len(before) == len(after), "structure_match_initial_relaxed": fit,
            "rms_dist_initial_relaxed": rms[0] if rms else None, "max_dist_initial_relaxed": rms[1] if rms else None,
            "space_group_before": initial["detected_space_group"], "space_group_after": sweep["0.01"]["symbol"],
            "space_group_retained": initial["detected_space_group"] == sweep["0.01"]["symbol"],
            "crystal_system_retained": initial["detected_crystal_system"] == sweep["0.01"]["crystal_system"],
            "topology_before": initial["topology_status"], "topology_after": topology["topology_status"],
            "topology_retained": topology_retained, "topology_improved": initial["topology_status"] != "PASS" and topology["topology_status"] == "PASS",
            "topology_details": details, "minimum_distance_before": initial.get("minimum_distance"), "minimum_distance_after": bonds.min_distance,
            "severe_contact_count_after": bonds.num_bad_contacts, "new_severe_contacts": bonds.num_bad_contacts > int(initial.get("severe_contact_count") or 0),
            "density_after": geom.density, "volume_after": geom.volume, "volume_change_percent": volume_change,
            "collapse_flag": collapse, "error": ""}
    except Exception as exc:
        item = {**base, "post_relax_status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    write_json(run / "relaxed_sca" / "result.json", item)
    return item


def verdict(initial: dict[str, Any], relax: dict[str, Any], post: dict[str, Any]) -> tuple[str, str]:
    if not initial.get("parse_ok"): return "REJECT_INVALID_CIF", "initial CIF parse failed"
    if not initial.get("formula_match"): return "REJECT_FORMULA", "exact reduced formula mismatch"
    if not initial.get("contact_screen_pass") or not initial.get("geometry_ok"): return "REJECT_GEOMETRY", "initial geometry/contact screen failed"
    if initial.get("topology_status") == "FAIL": return "REJECT_TOPOLOGY", "initial family topology failed"
    if relax.get("relaxation_status") != "PASS" or post.get("post_relax_status") != "PASS": return "INSUFFICIENT_EVIDENCE", "relaxation or post-relaxation validation unavailable"
    if post.get("collapse_flag"): return "REJECT_SURROGATE_COLLAPSE", "surrogate relaxation collapse policy triggered"
    warnings = []
    if not relax.get("converged"): warnings.append("force threshold not reached")
    if not post.get("structure_match_initial_relaxed"): warnings.append("initial/relaxed StructureMatcher mismatch")
    if not post.get("space_group_retained"): warnings.append("space group changed")
    if not post.get("topology_retained"): return "REJECT_TOPOLOGY", "topology not retained"
    if initial.get("topology_status") != "PASS" or warnings: return "ACCEPT_WITH_WARNING", "; ".join(warnings) or "initial topology partial"
    return "ACCEPT", "frozen acceptance policy passed"


def main() -> int:
    ensure_gate()
    for directory in (SCA_OUT, ACCEPT, ANALYSIS): directory.mkdir(parents=True, exist_ok=True)
    protocol = freeze_protocol()
    rows = read_csv(MANIFESTS / "FINAL_WORKFLOW_ROW_MANIFEST.csv")
    unique_rows, mapping = deduplicate(rows)
    reference_rows = read_csv(SOURCE_SCA / "reference" / "REFERENCE_CORPUS_MANIFEST.csv")
    references = []
    reference_hashes = []
    for ref in reference_rows:
        path = Path(ref["reference_cif_path"]); actual = sha256(path)
        if actual != ref["sha256"]: raise RuntimeError(f"PROTECTED_INPUT_HASH_MISMATCH: reference {ref['reference_id']}")
        references.append((ref["reference_id"], Structure.from_file(path))); reference_hashes.append(actual)
    reference_corpus_hash = hashlib.sha256("".join(sorted(reference_hashes)).encode()).hexdigest()
    try:
        from chgnet.model.dynamics import StructOptimizer
        from chgnet.model.model import CHGNet
        import torch
        chgnet = CHGNet.load(); relaxer = StructOptimizer(model=chgnet, optimizer_class="FIRE", use_device="cuda" if torch.cuda.is_available() else "cpu")
        chgnet_available = True
    except Exception as exc:
        chgnet = relaxer = None; chgnet_available = False; chgnet_load_error = f"{type(exc).__name__}: {exc}"
    initial_rows, static_rows, relax_rows, post_rows, failure_rows, verdict_rows, reference_results = [], [], [], [], [], [], []
    for index, row in enumerate(unique_rows, start=1):
        uid = row["unique_structure_id"]; print(f"evaluate {index}/{len(unique_rows)} {uid} {row['source_task_id']}", flush=True)
        run = RUNS / uid
        for name in ("input", "initial_sca", "static_mlip", "relaxation", "relaxed_sca", "topology", "reference_matching", "logs", "provenance"):
            (run / name).mkdir(parents=True, exist_ok=True)
        source = Path(row["generated_cif_path"]); copied = run / "input" / "initial.cif"; shutil.copy2(source, copied)
        write_json(run / "provenance" / "source.json", row)
        initial = initial_evaluate(row, run, references); initial_rows.append(initial)
        reference_results.append({"unique_structure_id": uid, "reference_corpus_id": "paper_full_sca_v1_local_reference_corpus", "reference_corpus_hash": reference_corpus_hash, "label": initial.get("reference_label", "REFERENCE_MATCH_NOT_COMPUTABLE"), "matched_reference_ids": ";".join(initial.get("reference_matches", [])), **MATCHER_SETTINGS})
        if chgnet_available:
            static = static_evaluate(row, run, chgnet); relax = relax_evaluate(row, run, chgnet, relaxer)
        else:
            static = {"unique_structure_id": uid, "chgnet_status": "NOT_CONFIGURED", "chgnet_error": chgnet_load_error, "m3gnet_status": "NOT_COMPUTABLE", "alignn_status": "NOT_CONFIGURED", "mace_status": "NOT_CONFIGURED", "sevennet_status": "NOT_CONFIGURED"}
            relax = {"unique_structure_id": uid, "relaxation_status": "NOT_COMPUTABLE", "converged": False, "error": chgnet_load_error}
            write_json(run / "static_mlip" / "result.json", static); write_json(run / "relaxation" / "result.json", relax)
        static_rows.append(static); relax_rows.append(relax)
        post = post_evaluate(row, initial, relax, run); post_rows.append(post)
        final_verdict, reason = verdict(initial, relax, post)
        verdict_rows.append({"unique_structure_id": uid, "verdict": final_verdict, "reason": reason})
        for evaluator, record in (("initial_sca", initial), ("chgnet_static", static), ("chgnet_relaxation", relax), ("post_relax_sca", post)):
            status = record.get("status") or record.get("chgnet_status") or record.get("relaxation_status") or record.get("post_relax_status")
            error = record.get("error") or record.get("chgnet_error") or ""
            if status in {"ERROR", "FAIL", "NOT_COMPUTABLE"} or error: failure_rows.append({"unique_structure_id": uid, "evaluator": evaluator, "status": status, "error": error})
    write_csv(SCA_OUT / "FINAL_SCA_INITIAL_RESULTS.csv", initial_rows); write_jsonl(SCA_OUT / "FINAL_SCA_INITIAL_RESULTS.jsonl", initial_rows)
    write_csv(SCA_OUT / "FINAL_STATIC_MLIP_RESULTS.csv", static_rows)
    write_csv(SCA_OUT / "FINAL_RELAXATION_RESULTS.csv", relax_rows); write_jsonl(SCA_OUT / "FINAL_RELAXATION_RESULTS.jsonl", relax_rows)
    write_csv(SCA_OUT / "FINAL_SCA_POST_RELAX_RESULTS.csv", post_rows); write_jsonl(SCA_OUT / "FINAL_SCA_POST_RELAX_RESULTS.jsonl", post_rows)
    availability = []
    for model in ("CHGNet", "M3GNet", "ALIGNN", "MACE", "SevenNet"):
        key = model.lower() + "_status" if model != "M3GNet" else "m3gnet_status"
        statuses = defaultdict(int)
        for row in static_rows: statuses[str(row.get(key, "NOT_CONFIGURED"))] += 1
        availability.append({"evaluator": model, "status_counts": json.dumps(statuses, sort_keys=True), "configured": model in {"CHGNet", "M3GNet"}})
    write_csv(SCA_OUT / "FINAL_SCA_EVALUATOR_AVAILABILITY.csv", availability)
    write_csv(SCA_OUT / "FINAL_SCA_FAILURE_LOG.csv", failure_rows, ["unique_structure_id", "evaluator", "status", "error"])
    write_csv(ACCEPT / "FINAL_UNIQUE_STRUCTURE_VERDICTS.csv", verdict_rows)
    verdict_by_unique = {row["unique_structure_id"]: row for row in verdict_rows}
    write_csv(ACCEPT / "FINAL_WORKFLOW_ROW_VERDICTS.csv", [{**row, **verdict_by_unique[row["unique_structure_id"]]} for row in mapping])
    (ACCEPT / "FINAL_ACCEPTANCE_POLICY.md").write_text("# Final acceptance policy\n\nVerdicts are derived in order from parse, exact formula, initial geometry/contact, initial topology, relaxation and post-relaxation availability, collapse, force convergence, initial/relaxed StructureMatcher fit, symmetry and topology retention. Force convergence alone is never sufficient.\n", encoding="utf-8")
    warnings = [row for row in verdict_rows if row["verdict"] != "ACCEPT"]
    (ACCEPT / "FINAL_FAILURE_AND_WARNING_CASES.md").write_text("# Failure and warning cases\n\n" + "\n".join(f"- `{row['unique_structure_id']}`: `{row['verdict']}` — {row['reason']}" for row in warnings) + "\n", encoding="utf-8")
    write_csv(ANALYSIS / "FINAL_REFERENCE_MATCHING.csv", reference_results)
    counts = defaultdict(int)
    for row in reference_results: counts[row["label"]] += 1
    (ANALYSIS / "FINAL_REFERENCE_MATCHING_REPORT.md").write_text("# Frozen local reference matching\n\n" + "\n".join(f"- `{key}`: {value}" for key, value in sorted(counts.items())) + f"\n\nCorpus hash: `{reference_corpus_hash}`. Formula-restricted StructureMatcher settings are recorded row-wise.\n", encoding="utf-8")
    # Two-model percentile ranks only where both predictions succeeded.
    comparable = [row for row in static_rows if row.get("chgnet_status") == "PASS" and row.get("m3gnet_status") == "PASS"]
    if comparable:
        chg = pd.Series({row["unique_structure_id"]: float(row["chgnet_energy_per_atom"]) for row in comparable}).rank(method="average", pct=True)
        m3 = pd.Series({row["unique_structure_id"]: float(row["m3gnet_energy_per_atom"]) for row in comparable}).rank(method="average", pct=True)
    disagreement_rows = []
    for row in comparable:
        uid = row["unique_structure_id"]; score = abs(float(chg[uid]) - float(m3[uid])); disagree = score > 0.25
        disagreement_rows.append({"unique_structure_id": uid, "chgnet_percentile_rank": float(chg[uid]), "m3gnet_percentile_rank": float(m3[uid]), "rank_difference": score, "disagreement": disagree})
    write_csv(ANALYSIS / "FINAL_MLIP_DISAGREEMENT.csv", disagreement_rows, ["unique_structure_id", "chgnet_percentile_rank", "m3gnet_percentile_rank", "rank_difference", "disagreement"])
    disagreements = sum(bool_value(row["disagreement"]) for row in disagreement_rows)
    (ANALYSIS / "FINAL_MLIP_DISAGREEMENT_REPORT.md").write_text(f"# Two-model MLIP comparison\n\nCompared structures: {len(comparable)}. Agreement: {len(comparable)-disagreements}. Disagreement: {disagreements}. Disagreement fraction: {disagreements/len(comparable) if comparable else 'NOT_COMPUTABLE'}. Raw energies were not averaged; comparison uses within-model percentile ranks.\n", encoding="utf-8")
    thermo = [{"unique_structure_id": row["unique_structure_id"], "predicted_hull_status": "NOT_COMPUTABLE", "reason": "INCOMPLETE_SAME_MODEL_COMPETING_PHASE_SET", "dft_status": "NOT_EVALUATED"} for row in unique_rows]
    write_csv(ANALYSIS / "FINAL_THERMODYNAMIC_EVIDENCE_STATUS.csv", thermo)
    (ANALYSIS / "FINAL_THERMODYNAMIC_LIMITATIONS.md").write_text("# Thermodynamic limitations\n\nNo candidate has a compositionally complete same-model competing-phase set. Predicted hull is `NOT_COMPUTABLE` for every unique structure. No DFT was run, and no MLIP energy is mixed with Materials Project DFT energy.\n", encoding="utf-8")
    print(json.dumps({"workflow_rows": len(rows), "raw_hash_unique": len(unique_rows), "canonical_hash_unique": len({r['canonical_structure_sha256'] for r in unique_rows}), "structurematcher_unique": len({m['structurematcher_group'] for m in mapping}), "initial_rows": len(initial_rows), "relaxation_rows": len(relax_rows), "candidate_failures_recorded": len(failure_rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
