"""Repair v4 reference comparisons and extract deterministic paper artifacts.

This script is deliberately post-generation only.  It reads the frozen target
manifest and persisted candidate/SCA/SPP/retrieval artifacts; it never invokes
retrieval, SPP fitting, QLIP, candidate generation, or SCA evaluation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Structure

from sok_llm_orchestrator.workflow.spp_only_benchmark import (
    RESULT_COLUMNS,
    SPPOnlyBenchmarkPolicy,
    _aggregate,
    _post_generation_reference,
)


CRYSTAL_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
WRAPPER_ROOT = CRYSTAL_ROOT / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed"
RESULT_ROOT = WRAPPER_ROOT / "results"
FROZEN_PATH = WRAPPER_ROOT / "frozen_benchmark.json"
MATCHER_CONFIG = {
    "primitive_cell": True,
    "scale": True,
    "attempt_supercell": True,
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    names = list(fields)
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in names})
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_structure_hash(structure: Structure) -> str:
    """Exact deterministic lattice/site payload hash used by paper SCA audits."""
    payload = {
        "lattice": [
            [round(float(value), 10) for value in row]
            for row in structure.lattice.matrix
        ],
        "sites": sorted(
            (
                site.species_string,
                *(round(float(value % 1), 10) for value in site.frac_coords),
            )
            for site in structure
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def safe_float(value: Any, default: float = math.inf) -> float:
    return float(value) if finite(value) else default


def sanitize(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in value)


def markdown_table(rows: list[dict[str, Any]], fields: list[str]) -> list[str]:
    def cell(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    return [
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
        *("| " + " | ".join(cell(row.get(field, "")) for field in fields) + " |" for row in rows),
    ]


def candidate_sources(frozen: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    targets = list(frozen["targets"])
    if len(targets) != 100 or Counter(str(row["family"]) for row in targets) != Counter(
        {"layered": 50, "spinel": 50}
    ):
        raise RuntimeError("V4_FROZEN_TARGET_DENOMINATOR_MISMATCH")
    paths: dict[str, Path] = {}
    for target in targets:
        run_dir = RESULT_ROOT / "runs" / str(target["family"]) / str(target["benchmark_id"])
        if not (run_dir / "run_summary.json").is_file():
            raise RuntimeError(f"MISSING_RUN_SUMMARY: {target['benchmark_id']}")
        candidate = run_dir / "generated" / "candidate.cif"
        if candidate.is_file():
            paths[str(target["benchmark_id"])] = candidate
    if len(paths) != 95:
        raise RuntimeError(f"GENERATED_CIF_COUNT_MISMATCH: {len(paths)}")
    return targets, paths


def repair_reference_comparisons(
    frozen: dict[str, Any], targets: list[dict[str, Any]], candidate_paths: dict[str, Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audit_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for target in targets:
        experiment_id = str(target["benchmark_id"])
        run_dir = RESULT_ROOT / "runs" / str(target["family"]) / experiment_id
        candidate_path = candidate_paths.get(experiment_id)
        generated = Structure.from_file(candidate_path) if candidate_path else None
        comparison = _post_generation_reference(
            crystal_root=CRYSTAL_ROOT,
            target=target,
            generated=generated,
            run_dir=run_dir,
        )
        write_json(run_dir / "comparison" / "reference_comparison.json", comparison)
        summary = read_json(run_dir / "run_summary.json")
        summary["target_spacegroup"] = comparison.get("target_spacegroup", "")
        summary["target_atom_count"] = comparison.get("target_atom_count", "")
        summary["structure_match"] = bool(comparison.get("structure_match", False))
        summary["structure_match_rms"] = comparison.get("structure_match_rms") or ""
        if bool(summary.get("candidate_valid")):
            summary["final_classification"] = (
                "SUCCESS_REFERENCE_MATCH"
                if summary["structure_match"]
                else "SUCCESS_PLAUSIBLE_NONMATCH"
            )
        write_json(run_dir / "run_summary.json", summary)
        attempt_summary = run_dir / "development_attempts" / "attempt_001" / "run_summary.json"
        if attempt_summary.is_file():
            write_json(attempt_summary, summary)
        summaries.append(summary)
        audit_rows.append({
            "experiment_id": experiment_id,
            "family": target["family"],
            "formula": target["formula"],
            "candidate_present": candidate_path is not None,
            "target_cif_path": str((CRYSTAL_ROOT / str(target["target_cif_path"])).resolve()),
            "expected_normalized_sha256": target["target_cif_sha256"],
            "target_cif_sha256_verified": comparison.get("target_cif_sha256_verified", False),
            "structure_match": comparison.get("structure_match", False),
            "spacegroup_match": comparison.get("spacegroup_match", ""),
            "crystal_system_match": comparison.get("crystal_system_match", ""),
            "volume_per_atom_percent_difference": comparison.get(
                "volume_per_atom_percent_difference", ""
            ),
            "comparison_path": str((run_dir / "comparison" / "reference_comparison.json").resolve()),
        })
    if sum(bool(row["target_cif_sha256_verified"]) for row in audit_rows) != 100:
        raise RuntimeError("NORMALIZED_TARGET_HASH_VERIFICATION_FAILED")
    policy = SPPOnlyBenchmarkPolicy(**read_json(RESULT_ROOT / "RUN_MANIFEST_INDEX.json")["policy"])
    _aggregate(RESULT_ROOT, summaries, frozen, policy)
    return summaries, audit_rows


def duplicate_audit(
    summaries: list[dict[str, Any]], candidate_paths: dict[str, Path],
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, int]]:
    structures = {experiment_id: Structure.from_file(path) for experiment_id, path in candidate_paths.items()}
    raw_hashes = {experiment_id: sha256(path) for experiment_id, path in candidate_paths.items()}
    canonical_hashes = {
        experiment_id: canonical_structure_hash(structure)
        for experiment_id, structure in structures.items()
    }
    raw_members: dict[str, list[str]] = defaultdict(list)
    canonical_members: dict[str, list[str]] = defaultdict(list)
    formula_members: dict[str, list[str]] = defaultdict(list)
    for experiment_id, structure in structures.items():
        raw_members[raw_hashes[experiment_id]].append(experiment_id)
        canonical_members[canonical_hashes[experiment_id]].append(experiment_id)
        formula_members[structure.composition.reduced_formula].append(experiment_id)
    raw_group = {
        experiment_id: f"RAW-{index:03d}"
        for index, digest in enumerate(sorted(raw_members), 1)
        for experiment_id in raw_members[digest]
    }
    canonical_group = {
        experiment_id: f"CAN-{index:03d}"
        for index, digest in enumerate(sorted(canonical_members), 1)
        for experiment_id in canonical_members[digest]
    }
    matcher = StructureMatcher(**MATCHER_CONFIG)
    groups: list[list[str]] = []
    for formula in sorted(formula_members):
        remaining = sorted(formula_members[formula])
        while remaining:
            seed = remaining.pop(0)
            group = [seed]
            for other in list(remaining):
                if matcher.fit(structures[seed], structures[other]):
                    group.append(other)
                    remaining.remove(other)
            groups.append(group)
    groups.sort(key=lambda members: members[0])
    structural_group = {
        experiment_id: f"SM-{index:03d}"
        for index, members in enumerate(groups, 1)
        for experiment_id in members
    }
    structural_sizes = {experiment_id: len(members) for members in groups for experiment_id in members}
    summary_by_id = {str(row["experiment_id"]): row for row in summaries}
    rows = []
    for experiment_id in sorted(candidate_paths):
        summary = summary_by_id[experiment_id]
        rows.append({
            "experiment_id": experiment_id,
            "family": summary["family"],
            "formula": summary["formula"],
            "candidate_path": str(candidate_paths[experiment_id].resolve()),
            "raw_cif_sha256": raw_hashes[experiment_id],
            "raw_hash_group": raw_group[experiment_id],
            "raw_hash_group_size": len(raw_members[raw_hashes[experiment_id]]),
            "canonical_structure_sha256": canonical_hashes[experiment_id],
            "canonical_hash_group": canonical_group[experiment_id],
            "canonical_hash_group_size": len(canonical_members[canonical_hashes[experiment_id]]),
            "structurematcher_group": structural_group[experiment_id],
            "structurematcher_group_size": structural_sizes[experiment_id],
            "structurematcher_config": json.dumps(MATCHER_CONFIG, sort_keys=True),
        })
    fields = list(rows[0])
    write_csv(RESULT_ROOT / "GENERATED_CIF_DUPLICATE_AUDIT.csv", rows, fields)
    stats = {
        "generated_count": len(rows),
        "raw_hash_unique_count": len(raw_members),
        "canonical_hash_unique_count": len(canonical_members),
        "structurally_distinct_count": len(groups),
        "raw_duplicate_group_count": sum(len(value) > 1 for value in raw_members.values()),
        "canonical_duplicate_group_count": sum(len(value) > 1 for value in canonical_members.values()),
        "structurematcher_duplicate_group_count": sum(len(value) > 1 for value in groups),
    }
    return rows, structural_group, stats


def build_candidate_rows(
    summaries: list[dict[str, Any]],
    candidate_paths: dict[str, Path],
    duplicate_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    duplicate_by_id = {str(row["experiment_id"]): row for row in duplicate_rows}
    rows = []
    for summary in summaries:
        experiment_id = str(summary["experiment_id"])
        candidate_path = candidate_paths.get(experiment_id)
        if candidate_path is None:
            continue
        run_dir = candidate_path.parents[1]
        validation = read_json(run_dir / "generated" / "validation.json")
        sca = read_json(run_dir / "sca" / "result.json")
        comparison = read_json(run_dir / "comparison" / "reference_comparison.json")
        structure = Structure.from_file(candidate_path)
        objective = safe_float(summary.get("qlip_objective"))
        objective_per_atom = objective / len(structure)
        density = safe_float(sca.get("density"))
        minimum_distance = safe_float(
            sca.get("min_distance")
            if finite(sca.get("min_distance"))
            else validation.get("minimum_distance"),
            -math.inf,
        )
        topology = str(sca.get("topology_status", "NOT_AVAILABLE"))
        energy = sca.get("formation_energy_per_atom")
        eligible_checks = {
            "candidate_generated": bool(summary.get("candidate_generated")),
            "candidate_valid": bool(summary.get("candidate_valid")),
            "sca_completed": str(summary.get("sca_status")) == "COMPLETED",
            "composition_correct": bool(validation.get("exact_requested_composition")),
            "geometry_valid": bool(sca.get("geometry_ok")),
            "no_severe_contacts": int(sca.get("num_bad_contacts") or 0) == 0 and minimum_distance >= 1.0,
            "density_plausible": finite(density) and 0.5 <= density <= 15.0,
            "finite_qlip_spp_objective": finite(objective),
            "spp_package_valid": bool(summary.get("SPP_ARTIFACT_VALID")),
            "no_scaffold": not bool(summary.get("SCAFFOLD_USED")),
            "no_leakage": bool(summary.get("NO_TARGET_LEAKAGE")),
            "no_pre_generation_reference": not bool(
                summary.get("REFERENCE_STRUCTURE_USED_BEFORE_GENERATION")
            ),
            "topology_not_failed": topology != "FAIL",
        }
        eligible = all(eligible_checks.values())
        row = {
            "family": summary["family"],
            "experiment_id": experiment_id,
            "target_id": summary["target_mpid"],
            "formula": summary["formula"],
            "reduced_formula": structure.composition.reduced_formula,
            "qlip_status": summary["qlip_status"],
            "qlip_objective": objective,
            "qlip_objective_per_atom": objective_per_atom,
            "qlip_runtime": summary["qlip_runtime"],
            "candidate_original_path": str(candidate_path.resolve()),
            "candidate_sha256": duplicate_by_id[experiment_id]["raw_cif_sha256"],
            "canonical_structure_sha256": duplicate_by_id[experiment_id][
                "canonical_structure_sha256"
            ],
            "composition_valid": validation.get("exact_requested_composition"),
            "minimum_distance": minimum_distance,
            "density": density,
            "sca_status": summary["sca_status"],
            "sca_geometry_valid": sca.get("geometry_ok"),
            "severe_contact_count": sca.get("num_bad_contacts"),
            "family_topology_valid": topology == "PASS",
            "family_topology_status": topology,
            "detected_space_group": sca.get("detected_space_group"),
            "formation_energy_per_atom": energy if finite(energy) else "NOT_EVALUATED",
            "spp_score": summary.get("spp_score", "") or "NOT_PERSISTED",
            "structure_match": comparison.get("structure_match"),
            "structure_match_rms": comparison.get("structure_match_rms"),
            "volume_per_atom_percent_difference": comparison.get(
                "volume_per_atom_percent_difference"
            ),
            "spacegroup_match": comparison.get("spacegroup_match"),
            "crystal_system_match": comparison.get("crystal_system_match"),
            "duplicate_group": duplicate_by_id[experiment_id]["structurematcher_group"],
            "duplicate_group_size": duplicate_by_id[experiment_id]["structurematcher_group_size"],
            "eligible": eligible,
            "eligibility_failures": ";".join(key for key, value in eligible_checks.items() if not value),
        }
        rows.append(row)
    topology_rank = {"PASS": 0, "PARTIAL": 1}
    rows.sort(key=lambda row: (
        not bool(row["eligible"]),
        topology_rank.get(str(row["family_topology_status"]), 2),
        int(row["severe_contact_count"] or 0),
        0 if finite(row["formation_energy_per_atom"]) else 1,
        safe_float(row["formation_energy_per_atom"]),
        safe_float(row["qlip_objective_per_atom"]),
        0 if str(row["qlip_status"]) == "OPTIMAL" else 1,
        abs(safe_float(row["volume_per_atom_percent_difference"])),
        -safe_float(row["minimum_distance"], -math.inf),
        str(row["experiment_id"]),
    ))
    family_ranks: dict[str, int] = defaultdict(int)
    for row in rows:
        family_ranks[str(row["family"])] += 1
        row["quality_rank_within_family"] = family_ranks[str(row["family"])]
    return rows


def diverse_top(rows: list[dict[str, Any]], family: str, count: int = 10) -> list[dict[str, Any]]:
    ordered = [row for row in rows if row["family"] == family and row["eligible"]]
    selected: list[dict[str, Any]] = []
    groups: set[str] = set()
    formulas: set[str] = set()
    for require_new_formula in (True, False):
        for row in ordered:
            if row in selected or row["duplicate_group"] in groups:
                continue
            if require_new_formula and row["reduced_formula"] in formulas:
                continue
            selected.append(row)
            groups.add(str(row["duplicate_group"]))
            formulas.add(str(row["reduced_formula"]))
            if len(selected) == count:
                return selected
    raise RuntimeError(f"INSUFFICIENT_STRUCTURALLY_DISTINCT_{family.upper()}_CANDIDATES")


def write_rankings_and_cifs(
    candidate_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    layered = diverse_top(candidate_rows, "layered")
    spinel = diverse_top(candidate_rows, "spinel")
    output_fields = [
        "paper_rank", "quality_rank_within_family", "family", "experiment_id", "target_id",
        "formula", "qlip_status", "qlip_objective", "qlip_objective_per_atom", "qlip_runtime",
        "candidate_original_path", "candidate_sha256", "composition_valid", "minimum_distance",
        "density", "sca_status", "sca_geometry_valid", "severe_contact_count",
        "family_topology_valid", "family_topology_status", "detected_space_group",
        "formation_energy_per_atom", "spp_score", "structure_match", "structure_match_rms",
        "volume_per_atom_percent_difference", "spacegroup_match", "crystal_system_match",
        "duplicate_group", "duplicate_group_size", "selection_reason",
    ]
    for selected in (layered, spinel):
        for index, row in enumerate(selected, 1):
            row["paper_rank"] = index
            row["selection_reason"] = (
                f"eligible; topology={row['family_topology_status']}; zero severe contacts; "
                f"deterministic quality rank={row['quality_rank_within_family']}; "
                "new StructureMatcher group and chemistry-preferred greedy diversity"
            )
    write_csv(RESULT_ROOT / "TOP_10_LAYERED_GENERATED_CIFS.csv", layered, output_fields)
    write_csv(RESULT_ROOT / "TOP_10_SPINEL_GENERATED_CIFS.csv", spinel, output_fields)
    paper_dir = RESULT_ROOT / "paper_cifs"
    paper_dir.mkdir(parents=True, exist_ok=True)
    selected_all = layered + spinel
    expected_names = {
        f"{row['family']}_{int(row['paper_rank']):02d}_"
        f"{sanitize(str(row['formula']))}_{sanitize(str(row['experiment_id']))}.cif"
        for row in selected_all
    }
    for existing in paper_dir.glob("*.cif"):
        if existing.name not in expected_names:
            existing.unlink()
    for row in selected_all:
        filename = (
            f"{row['family']}_{int(row['paper_rank']):02d}_"
            f"{sanitize(str(row['formula']))}_{sanitize(str(row['experiment_id']))}.cif"
        )
        destination = paper_dir / filename
        source = Path(str(row["candidate_original_path"]))
        if destination.exists() and sha256(destination) != sha256(source):
            raise RuntimeError(f"PAPER_CIF_DESTINATION_CONFLICT: {destination}")
        shutil.copy2(source, destination)
        if sha256(destination) != row["candidate_sha256"]:
            raise RuntimeError(f"PAPER_CIF_COPY_HASH_MISMATCH: {destination}")
        row["paper_copy_path"] = str(destination.resolve())
        row["PRIMARY_PAPER_EXAMPLE"] = int(row["paper_rank"]) <= 5
    manifest_fields = [
        "paper_rank", "family", "experiment_id", "target_id", "formula", "qlip_status",
        "qlip_objective", "qlip_runtime", "candidate_original_path", "paper_copy_path",
        "candidate_sha256", "composition_valid", "minimum_distance", "density", "sca_status",
        "family_topology_valid", "family_topology_status", "formation_energy_per_atom",
        "spp_score", "structure_match", "volume_per_atom_percent_difference", "duplicate_group",
        "duplicate_group_size", "PRIMARY_PAPER_EXAMPLE", "selection_reason",
    ]
    write_csv(RESULT_ROOT / "PAPER_GENERATED_CIF_MANIFEST.csv", selected_all, manifest_fields)
    manifest_md = [
        "# Paper Generated CIF Manifest", "",
        "All files are byte-identical copies of raw `generated/candidate.cif` outputs. Held-out and relaxed CIFs are excluded.", "",
        "`PRIMARY_PAPER_EXAMPLE=true` marks the top five per family. MLIP energy is `NOT_EVALUATED` because v4 did not run an MLIP backend.", "",
        *markdown_table(selected_all, [
            "paper_rank", "family", "experiment_id", "formula", "qlip_status",
            "minimum_distance", "density", "family_topology_status", "duplicate_group",
            "PRIMARY_PAPER_EXAMPLE", "paper_copy_path",
        ]), "",
    ]
    (RESULT_ROOT / "PAPER_GENERATED_CIF_MANIFEST.md").write_text(
        "\n".join(manifest_md), encoding="utf-8"
    )
    best_fields = [
        "paper_rank", "family", "experiment_id", "formula", "qlip_status",
        "qlip_objective_per_atom", "minimum_distance", "density", "family_topology_status",
        "detected_space_group", "formation_energy_per_atom", "structure_match",
        "volume_per_atom_percent_difference", "duplicate_group", "paper_copy_path",
    ]
    write_csv(RESULT_ROOT / "PAPER_BEST_GENERATED_STRUCTURES.csv", selected_all, best_fields)
    best_md = [
        "# Best Generated Structures", "",
        "Deterministic ranking order: eligibility; SCA topology; severe contacts; available MLIP energy; QLIP SPP objective per atom; solver status; held-out volume relation; minimum distance; experiment ID. Selection greedily prefers new reduced formulas and StructureMatcher groups.", "",
        "CHGNet/MLIP formation energies were not evaluated in v4 and are not inferred.", "",
        *markdown_table(selected_all, best_fields[:-1]), "",
    ]
    (RESULT_ROOT / "PAPER_BEST_GENERATED_STRUCTURES.md").write_text(
        "\n".join(best_md), encoding="utf-8"
    )
    return layered, spinel


def workflow_candidates(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for row in candidate_rows:
        if not row["eligible"]:
            continue
        run_dir = Path(str(row["candidate_original_path"])).parents[1]
        summary = read_json(run_dir / "run_summary.json")
        diagnostics = read_json(run_dir / "spp" / "artifact_preflight.json")["pair_diagnostics"]
        modes = Counter(str(item["final_source"]) for item in diagnostics)
        row = dict(row)
        row.update({
            "retrieval_top1_similarity": summary["retrieval_top1_similarity"],
            "retrieval_mean_topk": summary["retrieval_mean_topk"],
            "required_pair_count": len(diagnostics),
            "request_plus_global_pair_count": modes["request_plus_global_regulator"],
            "regulator_only_pair_count": modes["global_regulator"],
            "mixed_local_global_evidence": (
                modes["request_plus_global_regulator"] > 0 and modes["global_regulator"] > 0
            ),
        })
        ranked.append(row)
    ranked.sort(key=lambda row: (
        0 if row["family_topology_status"] == "PASS" else 1,
        0 if row["qlip_status"] == "OPTIMAL" else 1,
        not bool(row["mixed_local_global_evidence"]),
        abs(int(row["required_pair_count"]) - 6),
        -safe_float(row["retrieval_top1_similarity"], -math.inf),
        abs(safe_float(row["volume_per_atom_percent_difference"])),
        safe_float(row["qlip_objective_per_atom"]),
        str(row["experiment_id"]),
    ))
    for index, row in enumerate(ranked, 1):
        row["workflow_rank"] = index
    fields = [
        "workflow_rank", "family", "experiment_id", "formula", "qlip_status",
        "family_topology_status", "minimum_distance", "density", "retrieval_top1_similarity",
        "retrieval_mean_topk", "required_pair_count", "request_plus_global_pair_count",
        "regulator_only_pair_count", "mixed_local_global_evidence",
        "volume_per_atom_percent_difference", "duplicate_group",
    ]
    write_csv(RESULT_ROOT / "WORKFLOW_EXAMPLE_CANDIDATES.csv", ranked[:3], fields)
    return ranked[:3]


def parse_pot(path: Path) -> tuple[np.ndarray, np.ndarray]:
    distances: list[float] = []
    values: list[float] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) != 2:
            continue
        try:
            distance, value = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        distances.append(distance)
        values.append(value)
    if not distances:
        raise RuntimeError(f"EMPTY_POT_CURVE: {path}")
    return np.asarray(distances), np.asarray(values)


def pair_manifest_row(item: dict[str, Any]) -> dict[str, Any]:
    combined = item["final_source"] == "request_plus_global_regulator"
    final_path = (
        f"weighted-components:{item.get('request_pot_path')}|{item.get('regulator_pot_path')}"
        if combined
        else item.get("regulator_pot_path")
    )
    return {
        "pair": item["pair"],
        "local_observation_count": item.get("local_observation_count"),
        "supporting_structure_count": item.get("local_structure_count"),
        "request_curve_exists": item.get("local_curve_exists"),
        "global_regulator_used": item.get("global_curve_exists"),
        "local_weight": item.get("local_weight"),
        "global_weight": item.get("global_weight"),
        "final_source": item.get("final_source"),
        "final_pot_path": final_path,
        "final_pot_hash": item.get("final_curve_hash"),
        "final_pot_hash_kind": item.get("final_curve_hash_kind"),
        "request_pot_path": item.get("request_pot_path"),
        "request_pot_sha256": item.get("request_pot_sha256"),
        "regulator_pot_path": item.get("regulator_pot_path"),
        "regulator_pot_sha256": item.get("regulator_pot_sha256"),
    }


def write_plot_curve(bundle_dir: Path, item: dict[str, Any]) -> Path:
    request_path = Path(str(item["request_pot_path"])) if item.get("request_pot_path") else None
    regulator_path = Path(str(item["regulator_pot_path"]))
    if sha256(regulator_path) != str(item["regulator_pot_sha256"]):
        raise RuntimeError(f"REGULATOR_POT_HASH_MISMATCH: {regulator_path}")
    global_x, global_y = parse_pot(regulator_path)
    if request_path:
        if sha256(request_path) != str(item["request_pot_sha256"]):
            raise RuntimeError(f"REQUEST_POT_HASH_MISMATCH: {request_path}")
        distance, request_y = parse_pot(request_path)
        global_interp = np.interp(distance, global_x, global_y)
    else:
        mask = (global_x >= 0.5) & (global_x <= 11.0)
        distance = global_x[mask]
        request_y = np.zeros_like(distance)
        global_interp = global_y[mask]
    request_component = request_y * float(item.get("local_weight") or 0.0)
    global_component = global_interp * float(item.get("global_weight") or 0.0)
    rows = [
        {
            "distance_A": float(x),
            "request_component": float(local),
            "global_component": float(global_value),
            "final_potential": float(local + global_value),
        }
        for x, local, global_value in zip(
            distance, request_component, global_component, strict=True
        )
    ]
    output = bundle_dir / "spp_curves" / f"{sanitize(str(item['pair']))}.csv"
    write_csv(
        output, rows,
        ("distance_A", "request_component", "global_component", "final_potential"),
    )
    return output


def build_workflow_bundle(
    top_three: list[dict[str, Any]], frozen: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    winner = top_three[0]
    experiment_id = str(winner["experiment_id"])
    target = next(row for row in frozen["targets"] if row["benchmark_id"] == experiment_id)
    run_dir = Path(str(winner["candidate_original_path"])).parents[1]
    bundle = RESULT_ROOT / "paper_workflow_example"
    bundle.mkdir(parents=True, exist_ok=True)
    comparison = read_json(run_dir / "comparison" / "reference_comparison.json")
    summary = read_json(run_dir / "run_summary.json")
    sca = read_json(run_dir / "sca" / "result.json")
    query = read_json(run_dir / "retrieval" / "query.json")
    target_summary = {
        "target": target,
        "target_hash_verified": comparison["target_cif_sha256_verified"],
        "target_spacegroup": comparison["target_spacegroup"],
        "target_crystal_system": comparison["target_crystal_system"],
        "target_volume_per_atom": comparison["target_volume_per_atom"],
    }
    write_json(bundle / "TARGET_SUMMARY.json", target_summary)
    write_json(bundle / "REQUEST.json", {
        "text_request": query["query_text"],
        "structured_request": {
            "formula": target["formula"],
            "family": target["family"],
            "objective": "spp_energy",
            "cell_mode": read_json(run_dir / "target_manifest.json")["policy"]["cell_mode"],
        },
        "source": str((run_dir / "retrieval" / "query.json").resolve()),
    })
    retrieval = read_json(run_dir / "retrieval" / "results.json")["selected"]
    pair_support = read_json(run_dir / "spp" / "pair_support.json")
    support_by_id = {str(row["structure_id"]): row for row in pair_support}
    neighbour_rows = []
    for retained_index, item in enumerate(retrieval[:5], 1):
        structure_id = str(item["structure_id"])
        cif_path = run_dir / "retrieval" / "retrieved_cifs" / f"{structure_id}.cif"
        formula = Structure.from_file(cif_path).composition.reduced_formula if cif_path.is_file() else "NOT_AVAILABLE"
        support = support_by_id.get(structure_id, {})
        pairs = list(support.get("supported_pairs", []))
        neighbour_rows.append({
            "rank": item.get("rank"),
            "source": (item.get("provenance") or {}).get("source"),
            "source_id": (item.get("provenance") or {}).get("source_id"),
            "structure_id": structure_id,
            "formula": formula,
            "similarity_score": item.get("score", item.get("retrieval_score")),
            "family": target["family"],
            "why_it_contributed": (
                "semantic neighbour; supplied pair-distance observations for " + ", ".join(pairs)
                if pairs else "semantic neighbour; retained in the fixed SPP evidence cohort"
            ),
            "target_pairs_supported": ";".join(pairs),
            "source_cif_path": str(cif_path.resolve()),
            "ILLUSTRATIVE_NEIGHBOUR": retained_index <= 3,
        })
    neighbour_fields = list(neighbour_rows[0])
    write_csv(bundle / "RETRIEVAL_NEIGHBOURS.csv", neighbour_rows, neighbour_fields)
    neighbour_md = [
        "# Retrieved Neighbours", "",
        "The first three rows are the recommended workflow-figure neighbours.", "",
        *markdown_table(neighbour_rows, [
            "rank", "source_id", "formula", "similarity_score", "target_pairs_supported",
            "ILLUSTRATIVE_NEIGHBOUR",
        ]), "",
    ]
    (bundle / "RETRIEVAL_NEIGHBOURS.md").write_text("\n".join(neighbour_md), encoding="utf-8")
    diagnostics = read_json(run_dir / "spp" / "artifact_preflight.json")["pair_diagnostics"]
    pair_rows = [pair_manifest_row(item) for item in diagnostics]
    write_csv(bundle / "SPP_PAIR_PROVENANCE.csv", pair_rows, list(pair_rows[0]))
    combined = sorted(
        (item for item in diagnostics if item["final_source"] == "request_plus_global_regulator"),
        key=lambda item: (-int(item.get("local_observation_count") or 0), str(item["pair"])),
    )
    regulator_only = sorted(
        (item for item in diagnostics if item["final_source"] == "global_regulator"),
        key=lambda item: (-int(item.get("local_observation_count") or 0), str(item["pair"])),
    )
    selected_pairs = combined[:3]
    if regulator_only:
        selected_pairs = combined[:2] + regulator_only[:1]
    curve_rows = []
    for item in selected_pairs:
        path = write_plot_curve(bundle, item)
        curve_rows.append({
            "pair": item["pair"],
            "final_source": item["final_source"],
            "local_weight": item["local_weight"],
            "global_weight": item["global_weight"],
            "plotting_csv": str(path.resolve()),
            "selection_reason": (
                "locally informed plus frozen global regularization"
                if item["final_source"] == "request_plus_global_regulator"
                else "sparse/insufficient local evidence supported by frozen global regulator"
            ),
        })
    write_csv(bundle / "SPP_CURVE_MANIFEST.csv", curve_rows, list(curve_rows[0]))
    policy = read_json(run_dir / "target_manifest.json")["policy"]
    qlip_summary = {
        "experiment_id": experiment_id,
        "formula": summary["formula"],
        "objective_type": "spp_energy",
        "terminal_status": summary["qlip_status"],
        "solver_objective": summary["qlip_objective"],
        "runtime_seconds": summary["qlip_runtime"],
        "native_grid_density": policy["native_grid_density"],
        "native_grid_site_count": int(policy["native_grid_density"]) ** 3,
        "cell_mode": policy["cell_mode"],
        "scaffold_used": summary["SCAFFOLD_USED"],
        "generated_cif_source": str((run_dir / "qlip" / "generated.cif").resolve()),
        "generated_cif_sha256": sha256(run_dir / "qlip" / "generated.cif"),
        "note": "Extracted from persisted v4 run summary/policy; QLIP was not rerun.",
    }
    write_json(bundle / "QLIP_SOLVER_SUMMARY.json", qlip_summary)
    generated_copy = bundle / "GENERATED_RAW.cif"
    shutil.copy2(Path(str(winner["candidate_original_path"])), generated_copy)
    if sha256(generated_copy) != winner["candidate_sha256"]:
        raise RuntimeError("WORKFLOW_GENERATED_CIF_COPY_HASH_MISMATCH")
    shutil.copy2(run_dir / "sca" / "result.json", bundle / "SCA_SUMMARY.json")
    shutil.copy2(
        run_dir / "comparison" / "reference_comparison.json",
        bundle / "REFERENCE_COMPARISON.json",
    )
    retrieval_corpus = read_json(run_dir / "retrieval" / "retrieval_core.json")["corpus"]
    reason = (
        "It is a solver-optimal, topology-PASS, zero-bad-contact candidate with complete pair-aware "
        "evidence, both locally informed/global-regularized and regulator-only pairs, strong semantic "
        "retrieval, and a byte-preserved raw generated CIF."
    )
    workflow_lines = [
        "# Paper Workflow Example", "",
        f"- Target formula: **{summary['formula']}**",
        f"- Material family: **{summary['family']}**",
        f"- Request: `{query['query_text']}`",
        f"- Searched database: `{retrieval_corpus['corpus_id']}` (`{retrieval_corpus['database']}`)",
        f"- Retrieved neighbours used: **{summary['retrieval_k']}**; illustrative neighbours: **3**",
        f"- Required species pairs: **{len(diagnostics)}** ({', '.join(item['pair'] for item in diagnostics)})",
        f"- Local/global combination: **{sum(item['final_source'] == 'request_plus_global_regulator' for item in diagnostics)}** request+global; **{sum(item['final_source'] == 'global_regulator' for item in diagnostics)}** regulator-only",
        f"- QLIP grid/objective: **{policy['native_grid_density']}^3 = {int(policy['native_grid_density']) ** 3} sites**, `spp_energy`, `{policy['cell_mode']}` cell",
        f"- QLIP terminal status: **{summary['qlip_status']}**",
        f"- QLIP objective: **{summary['qlip_objective']}**",
        f"- QLIP runtime: **{summary['qlip_runtime']:.3f} s**",
        f"- Resulting raw CIF: `{generated_copy.resolve()}`",
        f"- SCA geometry: **{sca['geometry_ok']}**, minimum distance **{sca['min_distance']:.4f} angstrom**, bad contacts **{sca['num_bad_contacts']}**",
        f"- Family topology: **{sca['topology_status']}** (`{sca['topology_policy']}`)",
        f"- Density: **{sca['density']:.4f} g cm^-3**",
        "- MLIP/CHGNet energy: **NOT EVALUATED in v4**",
        f"- Held-out target StructureMatcher match: **{comparison['structure_match']}**",
        f"- Held-out volume/atom difference: **{comparison['volume_per_atom_percent_difference']:.3f}%**",
        f"- Why selected: {reason}", "",
        "## Metric provenance", "",
        "Candidate-only SCA metrics (geometry, contacts, density, topology) were already valid before the hash repair and were copied unchanged. Held-out hash verification, StructureMatcher, lattice/volume, and space-group comparisons were recomputed after the normalized-text repair.", "",
        "## Top three deterministic workflow candidates", "",
        *markdown_table(top_three, [
            "workflow_rank", "family", "experiment_id", "formula", "qlip_status",
            "family_topology_status", "retrieval_top1_similarity", "required_pair_count",
            "request_plus_global_pair_count", "regulator_only_pair_count",
        ]), "",
    ]
    text = "\n".join(workflow_lines)
    (bundle / "WORKFLOW_SUMMARY.md").write_text(text, encoding="utf-8")
    (RESULT_ROOT / "PAPER_WORKFLOW_EXAMPLE.md").write_text(text, encoding="utf-8")
    return winner, curve_rows


def main() -> None:
    frozen = read_json(FROZEN_PATH)
    targets, candidate_paths = candidate_sources(frozen)
    before = {experiment_id: sha256(path) for experiment_id, path in candidate_paths.items()}
    summaries, reference_rows = repair_reference_comparisons(
        frozen, targets, candidate_paths
    )
    after_reference = {experiment_id: sha256(path) for experiment_id, path in candidate_paths.items()}
    if before != after_reference:
        raise RuntimeError("GENERATED_CIF_MUTATION_DURING_REFERENCE_REPAIR")
    write_csv(
        RESULT_ROOT / "REFERENCE_HASH_REPAIR_AUDIT.csv", reference_rows,
        list(reference_rows[0]),
    )
    duplicate_rows, _, duplicate_stats = duplicate_audit(summaries, candidate_paths)
    candidate_rows = build_candidate_rows(summaries, candidate_paths, duplicate_rows)
    layered, spinel = write_rankings_and_cifs(candidate_rows)
    top_three = workflow_candidates(candidate_rows)
    winner, curve_rows = build_workflow_bundle(top_three, frozen)
    after_all = {experiment_id: sha256(path) for experiment_id, path in candidate_paths.items()}
    mutation_rows = [
        {
            "experiment_id": experiment_id,
            "candidate_path": str(candidate_paths[experiment_id].resolve()),
            "before_sha256": before[experiment_id],
            "after_sha256": after_all[experiment_id],
            "mutated": before[experiment_id] != after_all[experiment_id],
        }
        for experiment_id in sorted(candidate_paths)
    ]
    write_csv(
        RESULT_ROOT / "GENERATED_CIF_MUTATION_AUDIT.csv", mutation_rows,
        list(mutation_rows[0]),
    )
    if any(row["mutated"] for row in mutation_rows):
        raise RuntimeError("GENERATED_CIF_MUTATION_DETECTED")
    counts = {
        "overall": Counter(str(row["qlip_status"]) for row in summaries),
        "by_family": {
            family: Counter(str(row["qlip_status"]) for row in summaries if row["family"] == family)
            for family in ("layered", "spinel")
        },
        "generated": sum(bool(row["candidate_generated"]) for row in summaries),
        "sca_completed": sum(str(row["sca_status"]) == "COMPLETED" for row in summaries),
        "reference_matches": sum(bool(row["structure_match"]) for row in summaries),
        "plausible_nonmatches": sum(
            row["final_classification"] == "SUCCESS_PLAUSIBLE_NONMATCH" for row in summaries
        ),
    }
    report = {
        "schema_version": "spp_only_v4_post_generation_extraction.v1",
        "frozen_target_count": len(targets),
        "normalized_target_hashes_verified": sum(
            bool(row["target_cif_sha256_verified"]) for row in reference_rows
        ),
        "generated_cif_count": len(candidate_paths),
        "generated_cif_mutation_count": sum(bool(row["mutated"]) for row in mutation_rows),
        "eligible_candidate_count": sum(bool(row["eligible"]) for row in candidate_rows),
        "paper_cif_count": len(layered) + len(spinel),
        "primary_paper_cif_count": 10,
        "counts": counts,
        "duplicate_stats": duplicate_stats,
        "workflow_winner": {
            "experiment_id": winner["experiment_id"],
            "formula": winner["formula"],
            "family": winner["family"],
        },
        "plotting_curve_count": len(curve_rows),
        "candidate_only_metrics_reused": [
            "SCA geometry", "minimum distance/bad contacts", "density", "family topology",
        ],
        "reference_dependent_metrics_recomputed": [
            "normalized target CIF hash", "StructureMatcher fit/RMS", "lattice", "volume per atom",
            "space group", "crystal system",
        ],
        "qlip_rerun": False,
        "sca_rerun": False,
    }
    write_json(RESULT_ROOT / "POST_GENERATION_REPAIR_SUMMARY.json", report)
    print(json.dumps(report, indent=2, sort_keys=True, default=dict))


if __name__ == "__main__":
    main()
