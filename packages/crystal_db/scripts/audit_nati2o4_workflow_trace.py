"""Create a read-only trace audit of the persisted v4 NaTi2O4 workflow.

This script does not invoke retrieval, SPP fitting, QLIP, SCA, or figure
rendering.  It reads frozen run artifacts and production source, then writes
new audit-only CSV/JSON/Markdown files.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pymatgen.core import Composition, Structure


CRYSTAL_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = CRYSTAL_ROOT.parent / "Skill-Loop-CSP"
QLIP_ROOT = CRYSTAL_ROOT.parent / "qlip"
RESULT_ROOT = (
    CRYSTAL_ROOT
    / "artifacts"
    / "spp_only_oxide_benchmark_v4_taxonomy_fixed"
    / "results"
)
RUN_DIR = RESULT_ROOT / "runs" / "spinel" / "spinel-repaired-046"
OUT_DIR = RESULT_ROOT / "paper_workflow_audit"
CURVE_DIR = OUT_DIR / "NATI2O4_ALL_PAIR_SPP_CURVES"

CELL_SOURCE = SKILL_ROOT / "src" / "sok_llm_orchestrator" / "workflow" / "cell_strategy.py"
RUNNER_SOURCE = SKILL_ROOT / "src" / "sok_llm_orchestrator" / "workflow" / "runner.py"
BENCHMARK_SOURCE = SKILL_ROOT / "src" / "sok_llm_orchestrator" / "workflow" / "spp_only_benchmark.py"
SCAFFOLD_SOURCE = SKILL_ROOT / "src" / "sok_llm_orchestrator" / "workflow" / "scaffold_ablation.py"
POSTPROCESS_SOURCE = CRYSTAL_ROOT / "scripts" / "postprocess_spp_only_oxide_benchmark_v4.py"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(fields or (rows[0].keys() if rows else ()))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def markdown_table(rows: list[dict[str, Any]], fields: Iterable[str]) -> list[str]:
    columns = list(fields)
    output = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = [str(row.get(field, "")).replace("|", "\\|").replace("\n", " ") for field in columns]
        output.append("| " + " | ".join(values) + " |")
    return output


def parse_pot(path: Path) -> tuple[np.ndarray, np.ndarray]:
    distances: list[float] = []
    values: list[float] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        try:
            distances.append(float(parts[0]))
            values.append(float(parts[1]))
        except ValueError:
            continue
    if not distances or len(distances) != len(values):
        raise RuntimeError(f"invalid or empty POT: {path}")
    return np.asarray(distances), np.asarray(values)


def formula_from_cif(path: Path) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Structure.from_file(path).composition.reduced_formula


def resolved_cif_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    # Persisted retrieval paths were serialized relative to Skill-Loop-CSP.
    return (SKILL_ROOT / path).resolve()


def retrieval_audit() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query = read_json(RUN_DIR / "retrieval" / "query.json")
    core = read_json(RUN_DIR / "retrieval" / "retrieval_core.json")
    exclusions = read_json(RUN_DIR / "retrieval" / "exclusions.json")
    coverage_additions = read_json(RUN_DIR / "retrieval" / "retrieval_augmentation.json")
    quality_additions = read_json(RUN_DIR / "retrieval" / "retrieval_quality_augmentation.json")
    evidence = read_json(RUN_DIR / "spp" / "evidence_bundle.json")
    pair_support = read_json(RUN_DIR / "spp" / "pair_support.json")
    target = read_json(RUN_DIR / "target_manifest.json")
    spp_input = read_json(RUN_DIR / "spp" / "fit_round_01" / "spp_input_manifest.json")
    required_pairs = read_json(RUN_DIR / "spp" / "required_pairs.json")["required_pairs"]

    support_by_id = {str(row["structure_id"]): row for row in pair_support}
    decision_by_id = {str(row["structure_id"]): row for row in exclusions}
    core_ids = {str(row["structure_id"]) for row in core["selected"]}
    evidence_ids = {str(row["structure_id"]) for row in evidence["selected"]}
    spp_input_ids = {str(value) for value in spp_input["spp_input_structure_ids"]}
    coverage_ids = {str(row["structure_id"]) for row in coverage_additions}
    quality_ids = {str(row["structure_id"]) for row in quality_additions}

    # The pair inventory contains the 49 non-target members of the original
    # K=50 semantic return, including scores for ranks 2..50.  Rank 1 was the
    # held-out target and its full retrieval payload/score was deliberately not
    # persisted after leakage filtering.
    semantic_rows = sorted(
        (row for row in pair_support if row.get("semantic_rank") is not None),
        key=lambda row: int(row["semantic_rank"]),
    )
    target_row = {
        "structure_id": target["target"]["structure_id"],
        "material_id": target["target"]["material_id"],
        "semantic_rank": 1,
        "semantic_score": None,
        "supported_pairs": [],
        "observation_counts": {},
        "cif_path": str((CRYSTAL_ROOT / target["target"]["target_cif_path"]).resolve()),
    }
    candidates = [target_row, *semantic_rows]
    if len(candidates) != int(query["candidate_k"]):
        raise RuntimeError(f"semantic candidate reconstruction mismatch: {len(candidates)}")

    rows: list[dict[str, Any]] = []
    for item in candidates:
        structure_id = str(item["structure_id"])
        cif_path = Path(str(item["cif_path"]))
        formula = formula_from_cif(cif_path)
        decision = decision_by_id.get(structure_id, {})
        supported = [pair for pair in required_pairs if pair in item.get("supported_pairs", [])]
        obs = item.get("observation_counts", {})
        row: dict[str, Any] = {
            "semantic_rank": int(item["semantic_rank"]),
            "structure_id": structure_id,
            "source_id": str(item.get("material_id") or ""),
            "formula": formula,
            "semantic_score": "" if item.get("semantic_score") is None else float(item["semantic_score"]),
            "score_provenance": (
                "not_persisted_for_excluded_heldout_rank_1"
                if item.get("semantic_score") is None
                else "pair_support.semantic_score"
            ),
            "selection_decision": decision.get("decision", "not_recorded"),
            "selection_reason": decision.get("reason", "not_recorded"),
            "semantic_core": structure_id in core_ids,
            "coverage_augmentation": structure_id in coverage_ids,
            "quality_augmentation": structure_id in quality_ids,
            "final_spp_corpus": structure_id in evidence_ids,
            "entered_spp_maker": structure_id in spp_input_ids,
            "contributed_required_pairs": ";".join(supported),
            "cif_path": str(cif_path),
        }
        for pair in required_pairs:
            key = pair.replace("-", "_")
            row[f"contributed_{key}"] = pair in supported and structure_id in evidence_ids
            row[f"observation_count_{key}"] = int(obs.get(pair, 0)) if structure_id in evidence_ids else 0
        rows.append(row)

    write_csv(OUT_DIR / "NATI2O4_RETRIEVAL_AUDIT.csv", rows)

    contributors: dict[str, list[dict[str, Any]]] = {}
    for pair in required_pairs:
        contributors[pair] = [
            {
                "semantic_rank": row["semantic_rank"],
                "source_id": row["source_id"],
                "structure_id": row["structure_id"],
                "formula": row["formula"],
                "observations": row[f"observation_count_{pair.replace('-', '_')}"] ,
            }
            for row in rows
            if row["entered_spp_maker"] and row[f"contributed_{pair.replace('-', '_')}"]
        ]

    summary = {
        "initial_semantic_k": int(query["candidate_k"]),
        "semantic_core_count": len(core_ids),
        "coverage_pair_augmentation_count": len(coverage_additions),
        "quality_pair_augmentation_count": len(quality_additions),
        "total_pair_augmentation_count": len(coverage_additions) + len(quality_additions),
        "final_spp_corpus_count": len(evidence_ids),
        "spp_maker_input_count": len(spp_input_ids),
        "heldout_rank_1_structure_id": target["target"]["structure_id"],
        "heldout_rank_1_material_id": target["target"]["material_id"],
        "heldout_rank_1_score_persisted": False,
        "effective_non_target_top_rank": 2,
        "effective_non_target_top_score": rows[1]["semantic_score"],
        "contributors": contributors,
    }
    md = [
        "# NaTi2O4 retrieval audit", "",
        "This is a read-only reconstruction from the persisted v4 run. No retrieval or SPP fitting was rerun.", "",
        "## Counts", "",
        f"- Initial semantic request K: **{summary['initial_semantic_k']}**.",
        f"- Leakage-safe semantic core: **{summary['semantic_core_count']}** structures (semantic ranks 2-31).",
        f"- Pair-aware augmentation: **{summary['total_pair_augmentation_count']}** (coverage {summary['coverage_pair_augmentation_count']}; quality {summary['quality_pair_augmentation_count']}).",
        f"- Final SPP evidence corpus: **{summary['final_spp_corpus_count']}**.",
        f"- Hash-checked SPP-Maker inputs: **{summary['spp_maker_input_count']}**.", "",
        "## Rank 1 and the earlier three-neighbour display", "",
        "Semantic rank 1 was the held-out target itself (`materials_project-49cc20fe`, `mp-aaabqvjv`, NaTi2O4). The leakage guard excluded it before evidence assembly. Its score is intentionally absent from the leakage-safe persisted retrieval payload; the first retained non-target is therefore original semantic rank 2.", "",
        "The paper postprocessor did not select neighbours by chemistry or pair support. It sliced the first five retained retrieval rows and set `ILLUSTRATIVE_NEIGHBOUR=true` for retained indices 1-3. Consequently the displayed Na2WO4, NaCr2O4, and NaV2O4 were simply original semantic ranks 2, 3, and 4. This was a deterministic rendering/postprocessing choice, not the SPP corpus.", "",
        "## Required-pair contributors", "",
    ]
    for pair in required_pairs:
        records = contributors[pair]
        rendered = "; ".join(
            f"rank {row['semantic_rank']} {row['formula']} ({row['source_id']}, {row['observations']} observations)"
            for row in records
        ) or "none"
        md.append(f"- **{pair}** ({len(records)} structures): {rendered}")
    md += ["", "## Complete initial semantic cohort", ""]
    md += markdown_table(rows, [
        "semantic_rank", "source_id", "structure_id", "formula", "semantic_score",
        "selection_reason", "semantic_core", "entered_spp_maker", "contributed_required_pairs",
    ])
    md += ["", "## Primary provenance", "", *[f"- `{path}`" for path in (
        RUN_DIR / "retrieval" / "query.json",
        RUN_DIR / "retrieval" / "exclusions.json",
        RUN_DIR / "retrieval" / "retrieval_core.json",
        RUN_DIR / "retrieval" / "retrieval_augmentation.json",
        RUN_DIR / "retrieval" / "retrieval_quality_augmentation.json",
        RUN_DIR / "spp" / "evidence_bundle.json",
        RUN_DIR / "spp" / "pair_support.json",
        RUN_DIR / "spp" / "fit_round_01" / "spp_input_manifest.json",
        POSTPROCESS_SOURCE,
    )], ""]
    (OUT_DIR / "NATI2O4_RETRIEVAL_AUDIT.md").write_text("\n".join(md), encoding="utf-8")
    return rows, summary


def pair_spp_audit() -> list[dict[str, Any]]:
    required = read_json(RUN_DIR / "spp" / "required_pairs.json")["required_pairs"]
    audit = read_json(RUN_DIR / "spp" / "artifact_preflight.json")
    diagnostics = {str(row["pair"]): row for row in audit["pair_diagnostics"]}
    summary = read_json(RUN_DIR / "run_summary.json")
    quality_csv = next(
        csv.DictReader(
            (Path(str(diagnostics["O-O"]["request_pot_path"])).parents[2] / "spp_pot_quality.csv").open(
                encoding="utf-8", newline=""
            )
        )
    )
    del quality_csv  # Existence check; rows are loaded below without retaining an open iterator.
    request_root = Path(str(diagnostics["O-O"]["request_pot_path"])).parents[2]
    with (request_root / "spp_pot_quality.csv").open(encoding="utf-8", newline="") as handle:
        quality_by_pair = {str(row["pair"]): row for row in csv.DictReader(handle)}

    rows: list[dict[str, Any]] = []
    for pair in required:
        item = diagnostics[pair]
        raw_path = request_root / "scaled_all_pairs" / pair / f"{pair}.POT"
        request_path = Path(str(item["request_pot_path"])) if item.get("request_pot_path") else None
        regulator_path = Path(str(item["regulator_pot_path"]))
        raw_quality = quality_by_pair.get(pair, {})
        raw_exists = raw_path.is_file()
        request_exists = bool(request_path and request_path.is_file())
        regulator_exists = regulator_path.is_file()
        request_hash_ok = bool(request_exists and sha256(request_path) == item.get("request_pot_sha256"))
        regulator_hash_ok = bool(regulator_exists and sha256(regulator_path) == item.get("regulator_pot_sha256"))
        local_valid = bool(item.get("local_curve_valid") and request_hash_ok)
        global_valid = bool(item.get("global_curve_valid") and regulator_hash_ok)
        if not global_valid:
            raise RuntimeError(f"global regulator validation failed for {pair}")

        global_x, global_y = parse_pot(regulator_path)
        local_weight = float(item["local_weight"])
        global_weight = float(item["global_weight"])
        if local_valid and request_path is not None:
            distance, request_y = parse_pot(request_path)
            global_interp = np.interp(distance, global_x, global_y)
            curve_rows = [
                {
                    "distance_A": float(x),
                    "request_component": float(local_weight * local),
                    "global_component": float(global_weight * global_value),
                    "final_potential": float(local_weight * local + global_weight * global_value),
                }
                for x, local, global_value in zip(distance, request_y, global_interp, strict=True)
            ]
        else:
            curve_rows = [
                {
                    "distance_A": float(x),
                    "global_component": float(global_weight * global_value),
                    "final_potential": float(global_weight * global_value),
                }
                for x, global_value in zip(global_x, global_y, strict=True)
            ]
        curve_path = CURVE_DIR / f"{pair.replace('-', '_')}_FINAL_SPP.csv"
        write_csv(curve_path, curve_rows)

        final_path = (
            f"weighted-components:{request_path}|{regulator_path}"
            if item["final_source"] == "request_plus_global_regulator"
            else str(regulator_path)
        )
        rows.append({
            "required_pair": pair,
            "local_observation_count": int(item["local_observation_count"]),
            "local_supporting_structure_count": int(item["local_structure_count"]),
            "raw_fitted_local_pot_exists": raw_exists,
            "raw_fitted_local_pot_path": str(raw_path) if raw_exists else "",
            "raw_fitted_local_pot_quality": raw_quality.get("pot_quality", "missing"),
            "raw_fitted_local_pot_quality_reason": raw_quality.get("pot_quality_reason", "missing_pair"),
            "deployed_local_request_pot_exists": request_exists,
            "deployed_local_request_pot_path": str(request_path) if request_path else "",
            "local_pot_valid": local_valid,
            "global_regulator_pot_exists": regulator_exists,
            "global_regulator_pot_valid": global_valid,
            "global_regulator_pot_path": str(regulator_path),
            "local_weight": local_weight,
            "global_weight": global_weight,
            "final_source": item["final_source"],
            "final_pot_path": final_path,
            "final_pot_hash": item["final_curve_hash"],
            "final_pot_hash_kind": item["final_curve_hash_kind"],
            "entered_qlip_objective": bool(audit["SPP_READY"] and summary["qlip_status"] == "OPTIMAL"),
            "objective_entry_basis": "required pair accepted by strict package audit; production adapter covers every required pair; persisted solve OPTIMAL",
            "plotting_csv": str(curve_path.resolve()),
            "plotting_has_request_component": local_valid,
        })
    if [row["required_pair"] for row in rows] != list(required):
        raise RuntimeError("required pair order mismatch")
    write_csv(OUT_DIR / "NATI2O4_ALL_PAIR_SPP_AUDIT.csv", rows)
    return rows


def _top_neighbour_metrics(run_dir: Path, formula: str) -> dict[str, Any]:
    retrieval = read_json(run_dir / "retrieval" / "retrieval_core.json")
    target_cations = {str(element) for element in Composition(formula).elements} - {"O"}
    formulas: list[str] = []
    overlap = 0
    for item in retrieval.get("selected", [])[:5]:
        try:
            path = resolved_cif_path(str(item["cif_export"]["path"]))
            neighbour_formula = formula_from_cif(path)
            formulas.append(neighbour_formula)
            cations = {str(element) for element in Composition(neighbour_formula).elements} - {"O"}
            overlap += bool(cations & target_cations)
        except Exception:
            formulas.append("UNREADABLE")
    return {
        "top5_formula_available_count": sum(value != "UNREADABLE" for value in formulas),
        "top5_target_cation_overlap_count": overlap,
        "top5_neighbour_formulas": ";".join(formulas),
    }


def exemplar_audit() -> list[dict[str, Any]]:
    named = {
        "spinel-repaired-046", "spinel-repaired-040", "spinel-repaired-041",
        "layered-repaired-021", "layered-repaired-020", "layered-repaired-041",
    }
    rows: list[dict[str, Any]] = []
    for run_dir in sorted((RESULT_ROOT / "runs").glob("*/*")):
        summary_path = run_dir / "run_summary.json"
        audit_path = run_dir / "spp" / "artifact_preflight.json"
        sca_path = run_dir / "sca" / "result.json"
        validation_path = run_dir / "generated" / "validation.json"
        retrieval_path = run_dir / "retrieval" / "retrieval_core.json"
        if not all(path.is_file() for path in (summary_path, audit_path, sca_path, validation_path, retrieval_path)):
            continue
        summary = read_json(summary_path)
        audit = read_json(audit_path)
        sca = read_json(sca_path)
        validation = read_json(validation_path)
        diagnostics = audit.get("pair_diagnostics", [])
        informed = sum(
            str(item.get("final_source")) in {"request_only", "request_plus_global_regulator"}
            for item in diagnostics
        )
        global_only = sum(str(item.get("final_source")) == "global_regulator" for item in diagnostics)
        required = len(diagnostics)
        top1 = float(summary.get("retrieval_top1_similarity") or 0.0)
        mean = float(summary.get("retrieval_mean_topk") or 0.0)
        semantic_quality = (top1 + mean) / 2.0
        neighbour = _top_neighbour_metrics(run_dir, str(summary["formula"]))
        clean = bool(
            validation.get("candidate_valid")
            and sca.get("topology_status") == "PASS"
            and int(sca.get("num_bad_contacts") or 0) == 0
        )
        rows.append({
            "paper_trace_rank": 0,
            "family": summary["family"],
            "experiment_id": summary["experiment_id"],
            "formula": summary["formula"],
            "requested_named_candidate": summary["experiment_id"] in named,
            "clean_trace_eligible": clean,
            "required_pair_count": required,
            "request_informed_pair_count": informed,
            "global_only_pair_count": global_only,
            "request_informed_percent": (100.0 * informed / required) if required else 0.0,
            "retrieval_top1_similarity": top1,
            "retrieval_mean_topk": mean,
            "semantic_retrieval_quality_score": semantic_quality,
            "neighbour_interpretability_definition": "count among top 5 with readable formula and at least one target non-O element",
            **neighbour,
            "qlip_status": summary.get("qlip_status"),
            "sca_topology": sca.get("topology_status"),
            "num_bad_contacts": sca.get("num_bad_contacts"),
            "minimum_distance_A": sca.get("min_distance"),
            "generated_cif_valid": validation.get("candidate_valid"),
            "final_classification": summary.get("final_classification"),
            "run_directory": str(run_dir.resolve()),
            "recommended_hero": False,
        })

    rows.sort(key=lambda row: (
        not bool(row["clean_trace_eligible"]),
        str(row["qlip_status"]) != "OPTIMAL",
        -float(row["request_informed_percent"]),
        -int(row["top5_target_cation_overlap_count"]),
        -float(row["semantic_retrieval_quality_score"]),
        str(row["experiment_id"]),
    ))
    for rank, row in enumerate(rows, 1):
        row["paper_trace_rank"] = rank
        row["recommended_hero"] = row["experiment_id"] == "layered-repaired-041"
    write_csv(OUT_DIR / "PAPER_WORKFLOW_EXEMPLAR_AUDIT.csv", rows)
    return rows


def cell_audit() -> dict[str, Any]:
    policy = read_json(RUN_DIR / "target_manifest.json")["policy"]
    run_summary = read_json(RUN_DIR / "run_summary.json")
    comparison = read_json(RUN_DIR / "comparison" / "reference_comparison.json")
    generated = Structure.from_file(RUN_DIR / "qlip" / "generated.cif")

    # Values copied from the production constant and checked below against its
    # literal occurrence in the exact source file as well as the generated CIF.
    global_vpa = 17.986899303180298
    if f"GLOBAL_VPA_A3_PER_ATOM = {global_vpa}" not in CELL_SOURCE.read_text(encoding="utf-8"):
        raise RuntimeError("production GLOBAL_VPA constant changed")
    n_atoms = int(round(Composition(run_summary["formula"]).num_atoms))
    volume = n_atoms * global_vpa
    edge = volume ** (1.0 / 3.0)
    lattice = generated.lattice
    if not all(math.isclose(value, edge, rel_tol=0.0, abs_tol=1e-12) for value in (lattice.a, lattice.b, lattice.c)):
        raise RuntimeError("generated lattice does not match composition_scaled production calculation")
    if not math.isclose(float(lattice.volume), volume, rel_tol=0.0, abs_tol=1e-10):
        raise RuntimeError("generated volume does not match composition_scaled production calculation")
    grid_density = int(policy["native_grid_density"])
    payload = {
        "audit_scope": "persisted v4 NaTi2O4 run; no QLIP/retrieval/SPP/SCA rerun",
        "experiment_id": "spinel-repaired-046",
        "formula_sent_to_native_qlip": run_summary["formula"],
        "physical_search_cell": {
            "a_A": float(lattice.a), "b_A": float(lattice.b), "c_A": float(lattice.c),
            "alpha_deg": float(lattice.alpha), "beta_deg": float(lattice.beta), "gamma_deg": float(lattice.gamma),
            "volume_A3": float(lattice.volume),
        },
        "cell_strategy": {
            "cell_mode": policy["cell_mode"],
            "strategy": "composition_scaled",
            "literal_formula_atom_count": n_atoms,
            "frozen_global_vpa_A3_per_atom": global_vpa,
            "calculation": "V_cell = 7 * 17.986899303180298 A^3; a=b=c=cuberoot(V_cell)",
            "calculated_volume_A3": volume,
            "calculated_edge_A": edge,
            "vpa_source": "frozen broad target-independent Crystal-DB corpus constant",
            "global_vpa_corpus_id": "mp_stable_10k_v1",
            "global_vpa_included_structure_count": 10000,
            "retrieval_used_for_cell_sizing": False,
            "retrieval_derived_branch_executed": False,
            "target_or_family_lattice_statistics_used": False,
            "heldout_target_lattice_used": False,
        },
        "grid_discretisation": {
            "uniform_grid_density_per_axis": grid_density,
            "candidate_position_count": grid_density ** 3,
            "grid_spacing_A": edge / grid_density,
            "meaning": "candidate-position discretisation inside the physical cell; not a lattice dimension",
        },
        "qlip_other_design_inputs": {
            "constraint": "proximity.atomic_radii",
            "constraint_scale": 1.0,
            "constraint_retrieval_derived": False,
            "objective": "spp_energy",
        },
        "heldout_nonleakage_evidence": {
            "manifest_REFERENCE_STRUCTURE_USED_BEFORE_GENERATION": read_json(RUN_DIR / "target_manifest.json")["assertions"]["REFERENCE_STRUCTURE_USED_BEFORE_GENERATION"],
            "run_summary_REFERENCE_STRUCTURE_USED_BEFORE_GENERATION": run_summary["REFERENCE_STRUCTURE_USED_BEFORE_GENERATION"],
            "heldout_structure_id_excluded": "materials_project-49cc20fe",
            "heldout_target_load_order": "_post_generation_reference is called only after solve, candidate copy, validation, and SCA block",
            "post_generation_target_lattice_for_comparison_only": comparison["target_lattice"],
            "post_generation_target_volume_A3": comparison["target_volume"],
        },
        "persisted_generated_cif_check": {
            "path": str((RUN_DIR / "qlip" / "generated.cif").resolve()),
            "sha256": sha256(RUN_DIR / "qlip" / "generated.cif"),
            "matches_calculated_cell": True,
        },
        "production_source_files": {
            str(path.resolve()): sha256(path)
            for path in (CELL_SOURCE, RUNNER_SOURCE, BENCHMARK_SOURCE, SCAFFOLD_SOURCE)
        },
        "primary_persisted_provenance": [
            str((RUN_DIR / "target_manifest.json").resolve()),
            str((RUN_DIR / "qlip" / "generated.cif").resolve()),
            str((RUN_DIR / "comparison" / "reference_comparison.json").resolve()),
            str((RUN_DIR / "run_summary.json").resolve()),
        ],
    }
    write_json(OUT_DIR / "NATI2O4_CELL_STRATEGY_AUDIT.json", payload)
    md = [
        "# NaTi2O4 physical-cell strategy audit", "",
        "No generation or evaluation stage was rerun. The calculation below reconstructs the persisted request from production code/constants and verifies it against the raw QLIP-generated CIF.", "",
        "## Physical search cell supplied to QLIP", "",
        *markdown_table([{
            "a_A": lattice.a, "b_A": lattice.b, "c_A": lattice.c,
            "alpha_deg": lattice.alpha, "beta_deg": lattice.beta, "gamma_deg": lattice.gamma,
            "volume_A3": lattice.volume,
        }], ["a_A", "b_A", "c_A", "alpha_deg", "beta_deg", "gamma_deg", "volume_A3"]), "",
        "## Exact provenance", "",
        "The v4 benchmark policy selected `cell_mode=composition_scaled`. Production computes the literal formula atom count from `NaTi2O4` as 7 and multiplies it by the frozen global VPA constant 17.986899303180298 A^3/atom. Thus V = 125.90829512226209 A^3 and the cubic edge is 5.012081386139977 A. The source constant was frozen from 10,000 structures in the broad target-independent `mp_stable_10k_v1` corpus.", "",
        "This mode does **not** read the request's retrieved 30-structure evidence cohort, a family statistic, a nearest-neighbour cell, or the held-out target lattice. The separate `retrieval_derived` branch exists in production but was not selected for this run.", "",
        "The held-out target CIF is loaded by `_post_generation_reference` only after the solve/candidate validation/SCA block. Its primitive lattice (a=b=c=6.112114 A, alpha=beta=gamma approximately 60 degrees) appears only in the post-generation comparison artifact and is not the QLIP cell.", "",
        "## Grid discretisation is separate", "",
        f"The physical cube above contains a **{grid_density} x {grid_density} x {grid_density} uniform grid = {grid_density ** 3} candidate positions**. The corresponding axis spacing is {edge / grid_density:.15f} A. The number 64 is therefore a candidate-site count, not the physical cell size or atom count.", "",
        "The only native-domain constraint is `proximity.atomic_radii` with scale 1.0; it is not retrieval-derived.", "",
        "## Provenance", "", *[f"- `{path}`" for path in payload["primary_persisted_provenance"]],
        *[f"- `{path}` (SHA256 `{digest}`)" for path, digest in payload["production_source_files"].items()], "",
    ]
    (OUT_DIR / "NATI2O4_CELL_STRATEGY_AUDIT.md").write_text("\n".join(md), encoding="utf-8")
    return payload


def retrieval_to_qlip_trace(retrieval_rows: list[dict[str, Any]], pair_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_by_pair: dict[str, str] = {}
    for pair in (row["required_pair"] for row in pair_rows):
        key = pair.replace("-", "_")
        sources = [
            f"rank {row['semantic_rank']} {row['formula']} ({row['source_id']})"
            for row in retrieval_rows
            if row["entered_spp_maker"] and row[f"contributed_{key}"]
        ]
        source_by_pair[pair] = "; ".join(sources) or "none"

    rows: list[dict[str, Any]] = [{
        "influence": "semantic neighbour selection and leakage filtering",
        "source_retrieved_structures": "30 retained non-target semantic neighbours (original ranks 2-31)",
        "derived_statistic_or_artifact": "fixed, hash-checked 30-CIF SPP evidence corpus",
        "qlip_request_field_or_objective_component": "indirect input to request POT fitting; not itself a QLIP wire field",
        "provenance_file": str((RUN_DIR / "spp" / "fit_round_01" / "spp_input_manifest.json").resolve()),
        "numerical_retrieval_content_entered_objective": "only through any subsequently usable request POT",
    }]
    for pair_row in pair_rows:
        pair = str(pair_row["required_pair"])
        if pair_row["local_pot_valid"]:
            influence = f"{pair} retrieved pair-distance observations -> usable request POT"
            artifact = f"{pair_row['local_observation_count']} observations from {pair_row['local_supporting_structure_count']} structures; request weight {pair_row['local_weight']} plus global weight {pair_row['global_weight']}"
            qlip = f"guidance objective.energy_spp params.supported_pairs includes {pair}; weighted local+global pair term"
            entered = "yes"
        else:
            influence = f"{pair} evidence sufficiency classification -> regulator fallback"
            artifact = f"{pair_row['local_observation_count']} observations from {pair_row['local_supporting_structure_count']} structures; local POT quality {pair_row['raw_fitted_local_pot_quality']}; final source global_regulator"
            qlip = f"guidance objective.energy_spp params.missing_pairs includes {pair}; numerical curve is frozen global regulator only"
            entered = "no retrieved numerical curve; retrieval evidence only determined missing/insufficient status"
        rows.append({
            "influence": influence,
            "source_retrieved_structures": source_by_pair[pair],
            "derived_statistic_or_artifact": artifact,
            "qlip_request_field_or_objective_component": qlip,
            "provenance_file": str((RUN_DIR / "spp" / "artifact_preflight.json").resolve()),
            "numerical_retrieval_content_entered_objective": entered,
        })
    rows.extend([
        {
            "influence": "physical cell sizing (negative boundary)",
            "source_retrieved_structures": "none",
            "derived_statistic_or_artifact": "7 formula atoms x frozen global VPA 17.986899303180298 A^3/atom",
            "qlip_request_field_or_objective_component": "problem.design_space.template.lattice; cubic edge 5.012081386139977 A",
            "provenance_file": str((OUT_DIR / "NATI2O4_CELL_STRATEGY_AUDIT.json").resolve()),
            "numerical_retrieval_content_entered_objective": "no",
        },
        {
            "influence": "uniform-grid discretisation and proximity constraint (negative boundary)",
            "source_retrieved_structures": "none",
            "derived_statistic_or_artifact": "fixed policy density 4; proximity.atomic_radii scale 1.0",
            "qlip_request_field_or_objective_component": "design_space.sites.uniform_grid and constraints",
            "provenance_file": str((RUN_DIR / "target_manifest.json").resolve()),
            "numerical_retrieval_content_entered_objective": "no",
        },
    ])
    write_csv(OUT_DIR / "RETRIEVAL_TO_QLIP_TRACE.csv", rows)
    return rows


def recommendation(exemplars: list[dict[str, Any]], pair_rows: list[dict[str, Any]], retrieval_summary: dict[str, Any]) -> None:
    by_id = {row["experiment_id"]: row for row in exemplars}
    nati = by_id["spinel-repaired-046"]
    hero = by_id["layered-repaired-041"]
    lines = [
        "# Recommended revised Figure 1 content", "",
        "Do not redraw yet. The audit supports switching the workflow hero from NaTi2O4 (`spinel-repaired-046`) to Li2FeO3 (`layered-repaired-041`), subject to an explicit author decision.", "",
        f"NaTi2O4 has {nati['request_informed_pair_count']}/{nati['required_pair_count']} ({nati['request_informed_percent']:.1f}%) request-informed final pairs. Li2FeO3 has {hero['request_informed_pair_count']}/{hero['required_pair_count']} ({hero['request_informed_percent']:.1f}%), while also being QLIP OPTIMAL, SCA topology PASS, zero-bad-contact, minimum distance {hero['minimum_distance_A']:.6f} A, and generated-CIF valid.", "",
        "## Proposed panels", "",
        "1. **Request and leakage guard.** Show the target formula/family, initial semantic K=50, and explicit removal of the held-out target if it appears in retrieval.",
        "2. **Retrieval evidence cohort.** Label the panel `30 retrieved Crystal-DB structures used by SPP-Maker`, not `3 neighbours`. Show six representative non-target structures and an ellipsis/count badge for the remaining 24.",
        "3. **Pair-distance evidence.** Show a compact pair-by-structure support matrix or distance histograms so retrieval-to-SPP evidence is visible rather than implied.",
        "4. **All required SPPs.** Use a 2 x 3 grid of all six final curves, with each subplot visibly tagged `request + global` or `global only`. Add a six-row provenance strip with observation and supporting-structure counts. Never draw a request component for a regulator-only curve.",
        "5. **Physical cell and grid as separate objects.** Show `physical search cell: a=b=c=5.012081 A; 90 degrees; V=125.908295 A^3` for NaTi2O4 (or the audited values for a switched hero), then separately show `4 x 4 x 4 uniform grid = 64 candidate positions`.",
        "6. **QLIP result and SCA.** Retain terminal status, objective type, raw generated CIF, minimum distance, contacts, and family-topology result.", "",
        "## Representative neighbours", "",
        "If NaTi2O4 is retained, show Na2WO4 (highest retained semantic score), NaCr2O4 and NaV2O4 (Na-bearing AB2O4 analogues), Ti2AlO4, LiTi2O4, and MgTi2O4 (Ti-bearing spinel analogues). This deliberately exposes the split Na-support and Ti-support cohorts and the absence of any Na-Ti co-containing local contributor.", "",
        "If Li2FeO3 is adopted, show the first six retained non-target structures by semantic order: LiFeO2; two distinct Li2FeO3 structures; LiFeO2 (second distinct structure); LiFe3O4; and Li4Fe3WO8. All six contribute all six required Li-Fe-O pair types. Label same-formula structures as distinct non-target structures/polymorphs so they are not mistaken for held-out leakage.", "",
        "## NaTi2O4 curve files already prepared for a future redraw", "",
        *[f"- {row['required_pair']}: `{row['plotting_csv']}` ({row['final_source']})" for row in pair_rows], "",
        f"NaTi2O4 retrieval count used in all labels must be **{retrieval_summary['final_spp_corpus_count']}**, with only the displayed representatives identified as illustrative.", "",
    ]
    (OUT_DIR / "FIGURE_1_CONTENT_RECOMMENDATION.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    for path in (RUN_DIR, CELL_SOURCE, RUNNER_SOURCE, BENCHMARK_SOURCE, SCAFFOLD_SOURCE, POSTPROCESS_SOURCE):
        if not path.exists():
            raise FileNotFoundError(path)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CURVE_DIR.mkdir(parents=True, exist_ok=True)

    retrieval_rows, retrieval_summary = retrieval_audit()
    pair_rows = pair_spp_audit()
    exemplars = exemplar_audit()
    cell = cell_audit()
    trace = retrieval_to_qlip_trace(retrieval_rows, pair_rows)
    recommendation(exemplars, pair_rows, retrieval_summary)

    expected = [
        OUT_DIR / "NATI2O4_RETRIEVAL_AUDIT.csv",
        OUT_DIR / "NATI2O4_RETRIEVAL_AUDIT.md",
        OUT_DIR / "NATI2O4_ALL_PAIR_SPP_AUDIT.csv",
        OUT_DIR / "PAPER_WORKFLOW_EXEMPLAR_AUDIT.csv",
        OUT_DIR / "NATI2O4_CELL_STRATEGY_AUDIT.json",
        OUT_DIR / "NATI2O4_CELL_STRATEGY_AUDIT.md",
        OUT_DIR / "RETRIEVAL_TO_QLIP_TRACE.csv",
        OUT_DIR / "FIGURE_1_CONTENT_RECOMMENDATION.md",
        *sorted(CURVE_DIR.glob("*.csv")),
    ]
    manifest = {
        "schema": "nati2o4_workflow_trace_audit.v1",
        "scientific_stages_rerun": [],
        "figure_regenerated": False,
        "retrieval_row_count": len(retrieval_rows),
        "required_pair_count": len(pair_rows),
        "plotting_curve_count": len(list(CURVE_DIR.glob("*.csv"))),
        "exemplar_row_count": len(exemplars),
        "trace_row_count": len(trace),
        "physical_cell": cell["physical_search_cell"],
        "files": [{"path": str(path.resolve()), "sha256": sha256(path)} for path in expected],
    }
    write_json(OUT_DIR / "AUDIT_MANIFEST.json", manifest)
    print(json.dumps({
        "output_directory": str(OUT_DIR.resolve()),
        "retrieval_rows": len(retrieval_rows),
        "required_pairs": len(pair_rows),
        "curves": len(list(CURVE_DIR.glob("*.csv"))),
        "exemplar_rows": len(exemplars),
        "recommended_hero": "layered-repaired-041",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
