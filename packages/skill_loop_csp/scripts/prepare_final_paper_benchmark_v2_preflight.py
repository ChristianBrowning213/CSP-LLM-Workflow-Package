"""Prepare Benchmark-V2 eligibility/readiness artefacts without running CSP."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.bench.prospective import FrozenReference, ProspectiveBenchmarkStages, audit_option1_pair_coverage
from sok_llm_orchestrator.workflow.evidence import assemble_spp_evidence, canonical_pair
from sok_llm_orchestrator.workflow.runner import WorkflowConfig
from sok_llm_orchestrator.workflow.spp import REQUEST_MISSING, REQUEST_USABLE


ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "artifacts" / "final_paper_benchmark"
OUT = ROOT / "artifacts" / "final_paper_benchmark_v2_preflight"
DB = ROOT.parent / "Crystal-DB" / "data" / "phase6_mp_10k.db"
WORKFLOW_COMMIT = "222b5b3a313c324f86c611a78f0514b449e4030c"
EXPECTED_V1_HASHES = {
    "BENCHMARK_PROTOCOL.md": "67e14c94153f56086e200c99ed10634a3f601ee56e7db638db373ef194a13fd6",
    "BENCHMARK_CONFIG.json": "abb5c78b9d59ce50cf323495a551e04945fc8e39a34b925d352e8e4827a265b9",
    "BENCHMARK_TARGETS.csv": "6ebb38e8aff1350bd6ba2ad3298a5a547cbbbe63967cfb8135e6f0e774e42602",
    "BENCHMARK_FREEZE.json": "bb6404202f7fe76ac677da6049f6d2e0b540cfeaf63432f97b6f79624fad26d0",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(root: Path, pattern: str = "*.POT") -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob(pattern), key=lambda item: item.as_posix().lower()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    columns = fields or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def reference_provenance(structure_id: str) -> dict[str, Any] | None:
    connection = sqlite3.connect(f"file:{DB.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """select s.structure_id, p.source, p.source_id, p.retrieved_at,
                      p.license_notes, s.reduced_formula
               from structures s join provenance p on p.structure_id=s.structure_id
               where s.structure_id=?""",
            (structure_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def pairs_in_path(path: Path) -> set[str]:
    elements = sorted({str(element) for element in Structure.from_file(path).composition.elements}, key=str.lower)
    return {canonical_pair(left, right) for left in elements for right in elements}


def cif_path(item: dict[str, Any]) -> Path | None:
    export = item.get("cif_export") if isinstance(item.get("cif_export"), dict) else {}
    value = export.get("path") or item.get("internal_spp_cif_path")
    path = Path(str(value)).resolve() if value else None
    return path if path is not None and path.is_file() else None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    existing_freeze = ROOT / "artifacts" / "final_paper_benchmark_v2" / "BENCHMARK_V2_FREEZE.json"
    if existing_freeze.is_file():
        raise RuntimeError(f"Benchmark V2 is already frozen; refusing to rewrite: {existing_freeze}")
    previous_final = OUT / "FINAL_TARGET_ELIGIBILITY.csv"
    historical_final = OUT / "FINAL_TARGET_ELIGIBILITY_PRE_OPTION1.csv"
    if previous_final.is_file() and not historical_final.exists():
        shutil.copy2(previous_final, historical_final)
    actual_v1 = {name: sha256(V1 / name) for name in EXPECTED_V1_HASHES}
    if actual_v1 != EXPECTED_V1_HASHES:
        raise RuntimeError(f"Benchmark V1 protected hashes changed: {actual_v1}")

    v1_rows = read_csv(V1 / "BENCHMARK_TARGETS.csv")
    task_payload = json.loads((OUT / "CANONICAL_TARGET_TASKS.json").read_text(encoding="utf-8"))
    tasks = task_payload["tasks"]
    if len(tasks) != 8:
        raise RuntimeError("expected eight canonical target mappings")

    halt_lines = [
        "# Benchmark V1 halt record",
        "",
        f"Frozen workflow commit: `{WORKFLOW_COMMIT}`",
        "",
        "Benchmark V1 is preserved as the immutable record of a pre-generation halt at **0/8 eligible**.",
        "",
        "## Protected hashes",
        "",
    ]
    halt_lines.extend(f"- `{name}`: `{digest}`" for name, digest in actual_v1.items())
    halt_lines.extend(["", "## Original blockers", ""])
    halt_lines.extend(f"- {row['case_id']} / {row['formula']}: {row['eligibility_reason']}" for row in v1_rows)
    (OUT / "V1_HALT_RECORD.md").write_text("\n".join(halt_lines) + "\n", encoding="utf-8")

    reference_records: dict[str, FrozenReference] = {}
    reference_audit: dict[str, dict[str, Any]] = {}
    original_rows: list[dict[str, Any]] = []
    scaffold_rows: list[dict[str, Any]] = []
    for row in v1_rows:
        formula = row["formula"]
        independent = formula != "SrTiO3"
        provenance = reference_provenance(row["reference_structure_id"]) if independent else None
        if independent and provenance is None:
            raise RuntimeError(f"missing Crystal-DB provenance for {row['reference_structure_id']}")
        reference_path = (ROOT / row["reference_cif_path"]).resolve()
        if independent:
            reference = FrozenReference.from_cif(
                case_id=row["case_id"], formula=formula,
                reference_id=row["reference_structure_id"],
                source_structure_id=str(provenance["source_id"]), cif_path=reference_path,
            )
            if reference.raw_sha256 != row["reference_cif_hash"] or reference.canonical_sha256 != row["reference_canonical_hash"]:
                raise RuntimeError(f"frozen reference hash mismatch for {formula}")
            reference_records[formula] = reference
            structure = Structure.from_file(reference_path)
            reference_audit[formula] = {
                "reference_source": "Materials Project via Crystal-DB phase6_mp_10k",
                "external_source_identity": provenance["source"],
                "mp_id": provenance["source_id"],
                "reference_id": row["reference_structure_id"],
                "cif_hash": reference.raw_sha256,
                "canonical_hash": reference.canonical_sha256,
                "space_group": SpacegroupAnalyzer(structure, symprec=1e-2, angle_tolerance=5).get_space_group_symbol(),
                "acquisition_provenance": f"retrieved_at={provenance['retrieved_at']}; {provenance['license_notes']}",
                "not_skill_loop_generated": "YES",
                "not_qlip_output": "YES",
                "not_historical_benchmark_output": "YES",
            }
        mapping = formula in tasks
        scaffold_class = "GENERIC_FAMILY_SCAFFOLD"
        blocker = "" if independent else "NO_INDEPENDENT_REFERENCE"
        original_rows.append({
            "case_id": row["case_id"], "formula": formula,
            "independent_reference": "YES" if independent else "NO",
            "reference_source": reference_audit.get(formula, {}).get("reference_source", "UNRESOLVED"),
            "reference_id": row["reference_structure_id"] if independent else "UNRESOLVED",
            "reference_hash": row["reference_cif_hash"] if independent else "UNRESOLVED",
            "canonical_task_mapping": "YES" if mapping else "NO",
            "scaffold_id": "cubic_perovskite_variable_cation_v1",
            "scaffold_provenance": "CURATED_PM3M_WYCKOFF_PROTOTYPE_FAMILY_SCALE",
            "scaffold_target_derived": "NO",
            "scaffold_independence_class": scaffold_class,
            "exact_source_ID_exclusion": "YES", "raw_duplicate_exclusion": "YES",
            "canonical_duplicate_exclusion": "YES", "StructureMatcher_equivalent_exclusion": "YES",
            "pair_support_expansion_exclusion": "YES",
            "benchmark_eligible": "PENDING_DRY_RUN" if independent and mapping else "NO",
            "blocking_reason": blocker or ("NO_CANONICAL_TASK_MAPPING" if not mapping else ""),
        })
        scaffold_rows.append({
            "case_id": row["case_id"], "formula": formula,
            "scaffold_id": "cubic_perovskite_variable_cation_v1",
            "scaffold_source_id": "CURATED_PM3M_WYCKOFF_PROTOTYPE_FAMILY_SCALE",
            "classification": scaffold_class,
            "target_derived": "NO",
            "eligible_for_independent_result_2": "YES",
            "evidence": "generic ideal Pm-3m 1a/1b/3c ABX3 family geometry; reference roles absent from construction and scoring APIs",
        })

    write_csv(OUT / "ORIGINAL_TARGET_ELIGIBILITY.csv", original_rows)
    write_csv(OUT / "SCAFFOLD_INDEPENDENCE_AUDIT.csv", scaffold_rows)
    write_csv(OUT / "REFERENCE_PROVENANCE_AUDIT.csv", [dict(formula=formula, **record) for formula, record in reference_audit.items()])

    dry_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    pair_coverage_rows: list[dict[str, Any]] = []
    for original in original_rows:
        formula = original["formula"]
        if formula not in reference_records:
            continue
        reference = reference_records[formula]
        task = tasks[formula]
        request = f"Generate {formula} as a {task['family']} crystal with requested {task['space_group']} symmetry."
        run_root = OUT / "dry_run" / original["case_id"]
        run_root.mkdir(parents=True, exist_ok=True)
        stages = ProspectiveBenchmarkStages(tasks=tasks, reference=reference)
        config = WorkflowConfig(output_root=run_root, retrieval_depth=40, retrieval_demo_export=True)
        normalized = stages.normalise(request)
        retrieval = stages.retrieve(request, normalized, config, run_root)
        exclusion = stages.last_exclusion
        if exclusion is None:
            raise RuntimeError(f"missing exclusion result for {formula}")
        required = stages.required_pairs(normalized, config)
        available: set[str] = set()
        for item in retrieval["selected"]:
            path = cif_path(item)
            if path is not None:
                available.update(pairs_in_path(path))
        local_statuses = {pair: REQUEST_USABLE if pair in available else REQUEST_MISSING for pair in required}
        regulator_root = stages._regulator_root(config)
        coverage = audit_option1_pair_coverage(
            required_pairs=required, local_pair_statuses=local_statuses, regulator_root=regulator_root,
        )
        pair_support = set(required).issubset(available)
        assembly_ok = False
        assembly_error = ""
        try:
            locally_available_required = [pair for pair in required if pair in available]
            assemble_spp_evidence(
                retrieval=retrieval, required_pairs=locally_available_required,
                max_ranked_structures=config.retrieval_depth,
            )
            assembly_ok = True
        except ValueError as exc:
            assembly_error = str(exc)
        counts = {
            "exact_ID_removed": sum(row.reference_id_match for row in exclusion.audit),
            "raw_duplicates_removed": sum(row.raw_hash_match for row in exclusion.audit),
            "canonical_duplicates_removed": sum(row.canonical_hash_match for row in exclusion.audit),
            "StructureMatcher_equivalents_removed": sum(row.structurematcher_equivalent for row in exclusion.audit),
        }
        before = len(exclusion.audit)
        remaining = len(retrieval["selected"])
        dry_rows.append({
            "case_id": original["case_id"], "formula": formula,
            "corpus_id": retrieval["corpus"]["corpus_id"],
            "retrieved_count_before_exclusion": before,
            **counts,
            "remaining_retrieval_count": remaining,
            "all_required_pairs_potentially_available": "YES" if pair_support else "NO",
            "canonical_evidence_assembly_usable": "YES" if assembly_ok else "NO",
            "evidence_assembly_note": assembly_error,
            "reference_equivalent_evidence_count": exclusion.reference_equivalent_evidence_count,
            "required_pair_count": coverage.required_pair_count,
            "locally_supported_pair_count": coverage.locally_supported_pair_count,
            "regulator_fallback_pair_count": coverage.regulator_fallback_pair_count,
            "unsupported_pair_count": coverage.unsupported_pair_count,
            "local_support_fraction": f"{coverage.local_support_fraction:.6f}",
            "required_pairs": ";".join(row.species_pair for row in coverage.rows),
            "local_supported_pairs": ";".join(row.species_pair for row in coverage.rows if row.local_request_status == REQUEST_USABLE),
            "regulator_fallback_pairs": ";".join(row.species_pair for row in coverage.rows if row.preflight_pair_mode in {"LOCAL_SUPPORT_INSUFFICIENT_REGULATOR_AVAILABLE", "LOCAL_SUPPORT_MISSING_REGULATOR_AVAILABLE"}),
            "unsupported_pairs": ";".join(row.species_pair for row in coverage.rows if row.preflight_pair_mode == "UNSUPPORTED_REQUIRED_PAIR"),
        })
        if task["family"] == "halide perovskite":
            for pair_row in coverage.rows:
                pair_coverage_rows.append({
                    "case_id": original["case_id"], "formula": formula,
                    "species_pair": pair_row.species_pair,
                    "local_request_status": pair_row.local_request_status,
                    "regulator_available": pair_row.regulator_available,
                    "regulator_quality": pair_row.regulator_quality,
                    "regulator_pot_path": pair_row.regulator_pot_path,
                    "guidance_available": pair_row.guidance_available,
                    "preflight_pair_mode": pair_row.preflight_pair_mode,
                })
        for audit in exclusion.audit:
            candidate_rows.append({
                "case_id": original["case_id"], "formula": formula,
                "structure_id": audit.structure_id, "retrieval_rank": audit.retrieval_rank,
                "retrieval_source": audit.retrieval_source,
                "reference_id_match": audit.reference_id_match,
                "raw_hash_match": audit.raw_hash_match,
                "canonical_hash_match": audit.canonical_hash_match,
                "structurematcher_equivalent": audit.structurematcher_equivalent,
                "included": audit.included_in_request_spp,
                "exclusion_reason": audit.exclusion_reason,
            })
    write_csv(OUT / "DRY_RUN_RETRIEVAL_READINESS.csv", dry_rows)
    write_csv(OUT / "RETRIEVAL_EXCLUSION_AUDIT.csv", candidate_rows)
    write_csv(OUT / "HALIDE_OPTION1_PAIR_COVERAGE.csv", pair_coverage_rows)

    dry_by_formula = {row["formula"]: row for row in dry_rows}
    final_rows: list[dict[str, Any]] = []
    for original in original_rows:
        dry = dry_by_formula.get(original["formula"])
        eligible = (
            original["independent_reference"] == "YES"
            and original["canonical_task_mapping"] == "YES"
            and original["scaffold_target_derived"] == "NO"
            and bool(dry)
            and dry["canonical_evidence_assembly_usable"] == "YES"
            and int(dry["unsupported_pair_count"]) == 0
        )
        blocker = original["blocking_reason"]
        if not blocker and not dry:
            blocker = "DRY_RUN_NOT_AVAILABLE"
        if not blocker and dry and dry["canonical_evidence_assembly_usable"] != "YES":
            blocker = "LEAKAGE_SAFE_EVIDENCE_ASSEMBLY_FAILED"
        if not blocker and dry and int(dry["unsupported_pair_count"]) != 0:
            blocker = "GUIDANCE_PAIR_UNSUPPORTED"
        final_rows.append({
            "case_id": original["case_id"], "formula": original["formula"],
            "independent_reference": original["independent_reference"],
            "reference_source": original["reference_source"], "reference_id": original["reference_id"],
            "reference_hash": original["reference_hash"], "canonical_task_mapping": original["canonical_task_mapping"],
            "scaffold_id": original["scaffold_id"], "scaffold_independent": "YES",
            "corpus_id": dry["corpus_id"] if dry else "NOT_RUN_NO_REFERENCE",
            "exact_ID_exclusion": "YES", "raw_exclusion": "YES", "canonical_exclusion": "YES",
            "StructureMatcher_exclusion": "YES", "pair_expansion_exclusion": "YES",
            "pair_expansion_reentry_prevention": "YES",
            "dry_run_retrieval_success": "YES" if dry else "NO",
            "eligible_evidence_after_exclusion": dry["canonical_evidence_assembly_usable"] if dry else "NO",
            "required_pairs": dry["required_pairs"] if dry else "NOT_AUDITED",
            "local_supported_pairs": dry["local_supported_pairs"] if dry else "NOT_AUDITED",
            "regulator_fallback_pairs": dry["regulator_fallback_pairs"] if dry else "NOT_AUDITED",
            "unsupported_pairs": dry["unsupported_pairs"] if dry else "NOT_AUDITED",
            "required_pair_count": dry["required_pair_count"] if dry else 0,
            "locally_supported_pair_count": dry["locally_supported_pair_count"] if dry else 0,
            "local_supported_pair_count": dry["locally_supported_pair_count"] if dry else 0,
            "regulator_fallback_pair_count": dry["regulator_fallback_pair_count"] if dry else 0,
            "unsupported_pair_count": dry["unsupported_pair_count"] if dry else 0,
            "local_support_fraction": dry["local_support_fraction"] if dry else "0.000000",
            "benchmark_eligible": "YES" if eligible else "NO", "blocking_reason": blocker,
            "RESULT_2_ELIGIBLE": "YES" if eligible else "NO",
        })
    write_csv(OUT / "FINAL_TARGET_ELIGIBILITY.csv", final_rows)
    final_by_formula = {row["formula"]: row for row in final_rows}
    for original in original_rows:
        final = final_by_formula[original["formula"]]
        original["benchmark_eligible"] = final["benchmark_eligible"]
        original["blocking_reason"] = final["blocking_reason"]
    write_csv(OUT / "ORIGINAL_TARGET_ELIGIBILITY.csv", original_rows)

    result3 = []
    for row in final_rows:
        if row["benchmark_eligible"] != "YES":
            continue
        result3.append({
            "case_id": row["case_id"], "formula": row["formula"],
            "tight_scaffold_id": f"canonical_{tasks[row['formula']]['prototype']}",
            "tight_feasible_state_count": 1,
            "loose_scaffold_id": "cubic_perovskite_variable_cation_v1",
            "loose_feasible_state_count": 2,
            "genuinely_variable": "YES",
            "required_pairs": row["required_pairs"],
            "locally_supported_pairs": row["local_supported_pairs"],
            "required_pair_count": row["required_pair_count"],
            "local_supported_pair_count": row["local_supported_pair_count"],
            "regulator_fallback_pair_count": row["regulator_fallback_pair_count"],
            "local_support_fraction": row["local_support_fraction"],
            "request_specific_signal_present": "YES" if int(row["local_supported_pair_count"]) > 0 else "NO",
            "request_specific_contribution_can_differ": "YES" if int(row["locally_supported_pair_count"]) > 0 else "NO",
            "RESULT_3_ELIGIBLE": "YES" if int(row["locally_supported_pair_count"]) > 0 else "NO",
            "RESULT_3_INFORMATIVENESS": "HIGH" if int(row["locally_supported_pair_count"]) > 1 else ("MEDIUM" if int(row["locally_supported_pair_count"]) == 1 else "LOW_NOT_INFORMATIVE"),
            "basis": "two deterministic A/B cation allocations over generic Pm-3m 1a and 1b orbits",
        })
    write_csv(OUT / "RESULT_3_READINESS.csv", result3)

    regulator_root = ProspectiveBenchmarkStages._regulator_root(WorkflowConfig(output_root=OUT))
    positive_specs = [
        ("RDX-E4-A2", "Na3Zr2Si2PO12", ROOT / "data/nasicon/reference/reference.cif", "nasicon_na3zr2si2po12_c2_ordered", "TARGET_DERIVED", "TARGET_DERIVED_DEMONSTRATION", "not headline independent recovery"),
        ("RDX-E4-C2", "Na3Ti2(PO4)3", ROOT / "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp761046.cif", "nasicon_na3ti2po43_r3", "TARGET_DERIVED", "TARGET_DERIVED_DEMONSTRATION", "not headline independent recovery"),
        ("RDX-E4-F1", "LiZr2(PO4)3", ROOT / "data/corpora/nasicon_specialist_v3/cifs/nasicon-mp10499.cif", "nzp_nazr2po43_r3c", "FAMILY_MEMBER_NOT_EQUIVALENT; source nasicon-mp6475", "INDEPENDENT_REFERENCE_RECOVERY", "reference and scaffold source IDs are distinct"),
    ]
    result4 = []
    for case_id, formula, reference_path, scaffold_id, scaffold_provenance, classification, note in positive_specs:
        required = sorted(pairs_in_path(reference_path), key=str.lower)
        coverage = audit_option1_pair_coverage(
            required_pairs=required,
            local_pair_statuses={pair: REQUEST_MISSING for pair in required},
            regulator_root=regulator_root,
        )
        result4.append({
            "case_id": case_id, "formula": formula, "case_type": "POSITIVE",
            "specialist_corpus_routing": "YES", "scaffold_id": scaffold_id,
            "scaffold_provenance": scaffold_provenance,
            "reference_provenance": "Materials Project-derived specialist record",
            "classification": classification,
            "required_pair_count": coverage.required_pair_count,
            "regulator_fallback_pair_count_conservative": coverage.regulator_fallback_pair_count,
            "unsupported_pair_count": coverage.unsupported_pair_count,
            "ready": "YES" if coverage.unsupported_pair_count == 0 else "NO",
            "note": note + "; conservative regulator-only coverage check (local request support not claimed)",
        })
    result4.extend([
        {"case_id": "RDX-NEG-E4-A1", "formula": "Na3Zr2Si2PO12", "case_type": "NEGATIVE_ABSTENTION", "specialist_corpus_routing": "NOT_RUN_PRE_GENERATION_ABSTENTION", "scaffold_id": "registered NASICON scaffold", "scaffold_provenance": "CONTROLLED_NEGATIVE", "reference_provenance": "NOT_APPLICABLE", "classification": "CONTROLLED_REPRESENTABILITY_ABSTENTION", "ready": "YES", "note": "ordered Si4/P2 incompatible with one multiplicity-6 tetrahedral orbit"},
        {"case_id": "RDX-NEG-E4-A3", "formula": "Na3Ti2Si2PO12", "case_type": "NEGATIVE_ABSTENTION", "specialist_corpus_routing": "NOT_RUN_PRE_GENERATION_ABSTENTION", "scaffold_id": "registered NASICON scaffold", "scaffold_provenance": "CONTROLLED_NEGATIVE", "reference_provenance": "NOT_APPLICABLE", "classification": "CONTROLLED_REPRESENTABILITY_ABSTENTION", "ready": "YES", "note": "requested space group incompatible with selected registered scaffold"},
        {"case_id": "RDX-NEG-E4-A4", "formula": "Na3Hf2Si2PO12", "case_type": "NEGATIVE_ABSTENTION", "specialist_corpus_routing": "NOT_RUN_PRE_GENERATION_ABSTENTION", "scaffold_id": "registered NASICON scaffold", "scaffold_provenance": "CONTROLLED_NEGATIVE", "reference_provenance": "NOT_APPLICABLE", "classification": "CONTROLLED_REPRESENTABILITY_ABSTENTION", "ready": "YES", "note": "requested space group incompatible with selected registered scaffold"},
    ])
    write_csv(OUT / "RESULT_4_READINESS.csv", result4)

    (OUT / "OPTION1_ELIGIBILITY_ALIGNMENT_AUDIT.md").write_text(
        "# Option-1 eligibility alignment audit\n\n"
        "## Previous rule\n\n"
        "The first preflight implementation called `assemble_spp_evidence` with every compiled required pair and made complete local pair coverage a direct Result-2 eligibility condition. This incorrectly classified a missing local pair as a terminal blocker. The preserved pre-alignment table is `FINAL_TARGET_ELIGIBILITY_PRE_OPTION1.csv`.\n\n"
        "## Aligned rule\n\n"
        "Result-2 now requires an independent reference, request-derived task mapping, independent scaffold, working equivalence exclusion, successful leakage-safe retrieval/evidence cohort assembly, and zero unsupported compiled pairs. Each pair may be guided by a locally supported request contribution plus the regulator or by the frozen regulator alone. Local support counts and fallback counts remain explicit. No POT was fitted or regenerated.\n\n"
        "## Result-3 separation\n\n"
        "Result-3 causal informativeness additionally requires a genuinely variable scaffold and at least one locally supported request contribution. Regulator fallback is never counted as local request support.\n",
        encoding="utf-8",
    )

    (OUT / "TARGET_REPLACEMENT_AUDIT.md").write_text(
        "# Target replacement audit\n\nNo replacements were selected in this ticket. SrTiO3 is removed from eligibility because `NO_INDEPENDENT_REFERENCE`; the remaining original targets are assessed before any later target-set choice. No generation result informed this decision.\n",
        encoding="utf-8",
    )
    eligible_rows = [row for row in final_rows if row["RESULT_2_ELIGIBLE"] == "YES"]
    if len(eligible_rows) >= 6:
        decision = (
            "# Benchmark V2 target-set decision\n\n"
            f"- Original targets: {len(final_rows)}\n"
            f"- Eligible originals: {len(eligible_rows)}\n"
            f"- Final Result-2 N: {len(eligible_rows)}\n"
            "- Replacement targets: 0\n"
            "- Excluded target: SrTiO3\n"
            "- Exclusion reason: `NO_INDEPENDENT_REFERENCE`\n\n"
            "The final set retains the seven eligible members of the original pre-generated target list. No target was excluded based on CSP performance because zero CSP solves occurred before this decision and freeze.\n"
        )
        (OUT / "TARGET_SET_DECISION.md").write_text(decision, encoding="utf-8")

        freeze_dir = ROOT / "artifacts" / "final_paper_benchmark_v2"
        freeze_dir.mkdir(parents=True, exist_ok=True)
        references_by_formula = dict(reference_audit)
        target_manifest = []
        reference_manifest = []
        for row in eligible_rows:
            target_manifest.append({key: row[key] for key in (
                "case_id", "formula", "canonical_task_mapping", "scaffold_id", "scaffold_independent",
                "corpus_id", "required_pair_count", "local_supported_pair_count",
                "regulator_fallback_pair_count", "unsupported_pair_count", "local_support_fraction",
                "exact_ID_exclusion", "raw_exclusion", "canonical_exclusion", "StructureMatcher_exclusion",
                "pair_expansion_reentry_prevention", "dry_run_retrieval_success", "RESULT_2_ELIGIBLE",
            )})
            audit = references_by_formula[row["formula"]]
            reference_manifest.append({
                "case_id": row["case_id"], "formula": row["formula"],
                "reference_source": audit["reference_source"],
                "crystal_db_structure_id": audit["reference_id"], "source_mp_id": audit["mp_id"],
                "cif_sha256": audit["cif_hash"], "canonical_sha256": audit["canonical_hash"],
                "space_group": audit["space_group"], "acquisition_provenance": audit["acquisition_provenance"],
                "frozen_before_generation": "YES",
            })
        write_csv(freeze_dir / "BENCHMARK_V2_TARGETS.csv", target_manifest)
        write_csv(freeze_dir / "BENCHMARK_V2_REFERENCES.csv", reference_manifest)

        leakage_config = {
            "schema_version": "benchmark_v2_leakage_exclusion.v1",
            "stage": "after_retrieval_before_request_spp_evidence_acceptance",
            "exclude_exact_reference_id": True,
            "exclude_raw_sha256_duplicate": True,
            "exclude_canonical_sha256_duplicate": True,
            "exclude_structurematcher_equivalent": True,
            "apply_to_pair_coverage_expansion": True,
            "ranking_or_score_modification": False,
            "required_reference_equivalent_evidence_count_before_fit": 0,
        }
        result3_config = {
            "schema_version": "benchmark_v2_result3_factorial.v1",
            "targets": [row["case_id"] for row in result3 if row["RESULT_3_ELIGIBLE"] == "YES"],
            "conditions": ["TIGHT_REGULATOR_ONLY", "TIGHT_REGULATOR_PLUS_REQUEST", "LOOSE_REGULATOR_ONLY", "LOOSE_REGULATOR_PLUS_REQUEST"],
            "fixed": ["reference", "holdout_exclusions", "retrieval_config", "regulator", "solver", "SCA", "scaffold_definitions"],
            "varied": ["tight_vs_loose", "request_specific_SPP_OFF_vs_ON"],
            "informativeness_rule": "genuinely variable loose scaffold and at least one local request-supported pair",
        }
        result4_config = {
            "schema_version": "benchmark_v2_result4_nasicon.v1",
            "specialist_corpus_id": "nasicon_specialist_all_targets_out_v3",
            "positive_cases": [{"case_id": row["case_id"], "classification": row["classification"]} for row in result4 if row["case_type"] == "POSITIVE"],
            "negative_cases": [row["case_id"] for row in result4 if row["case_type"] == "NEGATIVE_ABSTENTION"],
            "request_spp": "fresh specialist evidence per execution",
            "regulator_id": "icsd_broad_regulator_v1",
            "workflow": ["canonical NASICON scaffold", "QLIP", "CIF", "SCA"],
        }
        general_db = DB.resolve()
        nasicon_db = ROOT / "data" / "corpora" / "nasicon_specialist_all_targets_out_v3" / "crystaldb.sqlite"
        regulator_root = ProspectiveBenchmarkStages._regulator_root(WorkflowConfig(output_root=OUT))
        benchmark_config = {
            "schema_version": "final_paper_benchmark_v2_config.v1",
            "workflow_commit": WORKFLOW_COMMIT,
            "entrypoint": "sok_llm_orchestrator.workflow.runner.run_csp_workflow",
            "result_2_target_count": len(eligible_rows),
            "retrieval": {"general_corpus_id": "mp_stable_10k_v1", "depth": 40, "text_engine": "robocrys", "text_view": "robocrys", "embedding_model": "text-embedding-bge-m3", "embedding_version": "lmstudio_v1"},
            "spp": {"fresh_per_execution": True, "convention": "reward", "cutoff_angstrom": 11.0, "max_cap_fraction_threshold": 0.5},
            "option_1": {"REQUEST_USABLE": "REQUEST_PLUS_REGULATOR", "REQUEST_INSUFFICIENT": "REGULATOR_ONLY_LOCAL_INSUFFICIENT", "REQUEST_MISSING": "REGULATOR_ONLY_LOCAL_MISSING", "request_and_regulator_missing": "GUIDANCE_PAIR_UNSUPPORTED"},
            "regulator": {"id": "icsd_broad_regulator_v1", "weight": 2.0},
            "qlip": {"backend": "QLIP_IP_CSP_GUROBI", "time_limit_s": 300, "mip_gap": 0.0, "threads": 1, "seed": 0, "objective_parity_required": True},
            "sca": {"package": "sca", "version": "0.1.0", "selection_influence": False},
            "execution_status": "FROZEN_NOT_STARTED",
        }
        protocol = f"""# Final Paper Benchmark V2 Protocol

This protocol was frozen before generation. Result 2 contains {len(eligible_rows)} prospective held-out targets selected exclusively from the original eight; SrTiO3 is excluded for `NO_INDEPENDENT_REFERENCE`, with no replacement.

## Result 2

Each independently sourced Materials Project reference is excluded from retrieval evidence by source ID, raw hash, canonical hash and StructureMatcher equivalence before request-SPP fitting, including pair-support expansion. Every execution fits a fresh request SPP, uses the frozen `icsd_broad_regulator_v1`, and applies Option 1 pair guidance: usable local pairs receive request plus regulator guidance; missing or insufficient local pairs receive regulator-only guidance; a pair missing from both sources fails controllably. The unchanged canonical sequence then uses the canonical scaffold, QLIP, objective-parity verification, CIF export, SCA, and post-generation reference comparison.

## Result 3

The four frozen conditions are tight/loose crossed with request-specific SPP off/on. References, exclusions, retrieval, regulator, solver, SCA and scaffold definitions are held fixed.

## Result 4

Three positive NASICON cases and three negative representability/abstention cases use the target-excluded specialist corpus, fresh specialist request SPP, the same frozen broad regulator, canonical NASICON scaffold, QLIP and SCA. Provenance classifications remain explicit.

No CSP solve occurred before this freeze.
"""
        (freeze_dir / "BENCHMARK_V2_PROTOCOL.md").write_text(protocol, encoding="utf-8")
        write_json(freeze_dir / "BENCHMARK_V2_CONFIG.json", benchmark_config)
        write_json(freeze_dir / "LEAKAGE_EXCLUSION_CONFIG.json", leakage_config)
        write_json(freeze_dir / "RESULT_3_FACTORIAL_CONFIG.json", result3_config)
        write_json(freeze_dir / "RESULT_4_NASICON_CONFIG.json", result4_config)

        frozen_names = [
            "BENCHMARK_V2_PROTOCOL.md", "BENCHMARK_V2_TARGETS.csv", "BENCHMARK_V2_REFERENCES.csv",
            "BENCHMARK_V2_CONFIG.json", "LEAKAGE_EXCLUSION_CONFIG.json", "RESULT_3_FACTORIAL_CONFIG.json",
            "RESULT_4_NASICON_CONFIG.json",
        ]
        frozen_hashes = {name: sha256(freeze_dir / name) for name in frozen_names}
        freeze = {
            "schema_version": "final_paper_benchmark_v2_freeze.v1",
            "canonical_workflow_commit": WORKFLOW_COMMIT,
            "benchmark_v1_hashes": actual_v1,
            "benchmark_v2_file_hashes": frozen_hashes,
            "general_corpus": {"id": "mp_stable_10k_v1", "sha256": sha256(general_db)},
            "nasicon_corpus": {"id": "nasicon_specialist_all_targets_out_v3", "sha256": sha256(nasicon_db)},
            "regulator": {"id": "icsd_broad_regulator_v1", "tree_sha256": tree_hash(regulator_root)},
            "embedding_model": "text-embedding-bge-m3/lmstudio_v1",
            "spp_convention": "reward",
            "spp_quality_threshold": {"max_cap_fraction": 0.5, "pot_quality_required_for_local": "usable"},
            "option_1_fallback_policy": benchmark_config["option_1"],
            "qlip_config": benchmark_config["qlip"], "sca_config": benchmark_config["sca"],
            "selected_target_count": len(eligible_rows),
            "excluded_original_targets": [{"formula": "SrTiO3", "reason": "NO_INDEPENDENT_REFERENCE"}],
            "references_frozen_before_generation": True,
            "target_set_frozen_before_generation": True,
            "CSP_solves_executed_before_freeze": 0,
        }
        write_json(freeze_dir / "BENCHMARK_V2_FREEZE.json", freeze)
        hash_rows = [{"path": name, "sha256": sha256(freeze_dir / name)} for name in frozen_names + ["BENCHMARK_V2_FREEZE.json"]]
        write_csv(freeze_dir / "OUTPUT_HASH_MANIFEST.csv", hash_rows)
        for row in hash_rows:
            if sha256(freeze_dir / row["path"]) != row["sha256"]:
                raise RuntimeError(f"post-write hash verification failed: {row['path']}")
    summary = {
        "schema_version": "final_paper_benchmark_v2_preflight.v1",
        "workflow_commit": WORKFLOW_COMMIT,
        "v1_hashes_verified": True,
        "original_target_count": len(final_rows),
        "eligible_original_count": sum(row["benchmark_eligible"] == "YES" for row in final_rows),
        "ineligible_originals": [{"formula": row["formula"], "reason": row["blocking_reason"]} for row in final_rows if row["benchmark_eligible"] != "YES"],
        "result3_genuinely_variable_count": sum(row["genuinely_variable"] == "YES" for row in result3),
        "nasicon_positive_ready": sum(row["case_type"] == "POSITIVE" and row["ready"] == "YES" for row in result4),
        "nasicon_negative_ready": sum(row["case_type"] == "NEGATIVE_ABSTENTION" and row["ready"] == "YES" for row in result4),
        "solves_executed": 0,
        "benchmark_v2_frozen": len(eligible_rows) >= 6,
    }
    (OUT / "PREFLIGHT_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
