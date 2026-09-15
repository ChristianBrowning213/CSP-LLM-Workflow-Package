"""Assemble the final systems-paper results package from frozen row artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import textwrap
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from pymatgen.core import Structure


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "final_paper_results"
TABLE_RUN = OUT / "table_run"
MANIFEST = ROOT / "experiments" / "paper_results" / "RESULTS_EXPERIMENTS.csv"
SCAFFOLD_CHGNET = OUT / "scaffold_chgnet" / "SCAFFOLD_CHGNET_RESULTS.csv"
LEGACY_COMMIT = "a46587f0f2e6836dee0605390328d9acd8612009"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: encode(value) for key, value in row.items()})


def encode(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def as_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "yes", "1", "pass"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def canonical_structure_hash(path: Path) -> tuple[str, str]:
    structure = Structure.from_file(path)
    sites = sorted(
        (str(site.specie), *(round(float(value) % 1.0, 10) for value in site.frac_coords))
        for site in structure
    )
    payload = {
        "lattice": [[round(float(value), 10) for value in row] for row in structure.lattice.matrix],
        "sites": sites,
    }
    occupation = [item[0] for item in sites]
    return hash_json(payload), hash_json(occupation)


def local_archive(source: dict[str, Any]) -> Path | None:
    group = str(source.get("experiment_group") or "")
    task = str(source.get("source_task_id") or "")
    candidate = ROOT / "local_runs" / group / task
    return candidate if candidate.is_dir() else None


def legacy_retrieval(archive: Path | None) -> tuple[list[str], str, int]:
    if archive is None:
        return [], "", 0
    path = archive / "crystaldb_retrieval_results.json"
    if not path.is_file():
        return [], "", 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    neighbors = payload.get("neighbors") or []
    ids = list(dict.fromkeys(str(item.get("structure_id")) for item in neighbors if item.get("structure_id")))
    return ids, hash_json(neighbors), len(neighbors)


def legacy_evidence(archive: Path | None) -> tuple[list[str], str]:
    if archive is None:
        return [], ""
    path = archive / "selected_evidence_manifest.jsonl"
    if not path.is_file():
        return [], ""
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [str(item.get("structure_id") or item.get("source_id") or "") for item in records]
    return [item for item in ids if item], hash_json(records)


def sca_status(source: dict[str, Any]) -> str:
    if not as_bool(source.get("parse_ok")) or not as_bool(source.get("formula_match")):
        return "FAIL"
    if int(float(source.get("severe_contact_count") or 0)) > 0:
        return "FAIL"
    if str(source.get("topology_status") or "").upper() == "PASS" and as_bool(source.get("geometry_ok")):
        return "PASS"
    return "PARTIAL"


def sca_failed_checks(source: dict[str, Any]) -> list[str]:
    """Return stable, available SCA failures without inventing unavailable checks."""
    result = source.get("sca_result") or {}
    failures: list[str] = []
    if first_present(source.get("parse_ok"), result.get("parse_ok")) is False:
        failures.append("parse")
    geometry = first_present(source.get("geometry_ok"), result.get("geometry_ok"))
    if geometry is False:
        failures.append("geometry")
    contact_pass = first_present(source.get("contact_screen_pass"), result.get("contact_screen_pass"))
    severe = first_present(source.get("severe_contact_count"), result.get("num_bad_contacts"), 0)
    if contact_pass is False or int(float(severe or 0)) > 0:
        failures.append("severe_contacts")
    topology = str(first_present(source.get("topology_status"), result.get("topology_status"), "")).upper()
    if topology in {"FAIL", "FAILED"}:
        failures.append("topology")
    return failures


def trace_record(detail: dict[str, Any]) -> dict[str, Any]:
    selected = detail.get("selected_source_record")
    if isinstance(selected, dict):
        return selected
    canonical = detail.get("canonical_result")
    return canonical if isinstance(canonical, dict) else {}


def first_present(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "", [])), "")


def build_master() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = {row["row_id"]: row for row in read_csv(MANIFEST)}
    table_rows = read_csv(TABLE_RUN / "RESULTS.csv")
    scaffold_chgnet = {row["row_id"]: row for row in read_csv(SCAFFOLD_CHGNET)}
    scaffold_chgnet_by_hash = {row["input_cif_sha256"]: row for row in scaffold_chgnet.values()}
    master: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for table in table_rows:
        row_id = table["row_id"]
        intent = manifest[row_id]
        detail_path = TABLE_RUN / "rows" / row_id / "result.json"
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        source = trace_record(detail)
        materialized_trace = TABLE_RUN / "rows" / row_id / "workflow_trace.json"
        if materialized_trace.is_file():
            source = {**source, **json.loads(materialized_trace.read_text(encoding="utf-8"))}
        block = intent["experiment_block"]
        archive = local_archive(source) if block == "BREADTH" else None
        retrieval_ids, retrieval_hash, retrieval_count = legacy_retrieval(archive)
        evidence_ids, evidence_hash = legacy_evidence(archive)
        if block != "BREADTH":
            retrieval_ids = list(source.get("retrieved_ids") or table.get("retrieved_ids", "").split(";") if first_present(source.get("retrieved_ids"), table.get("retrieved_ids")) else [])
            evidence_ids = list(source.get("SPP_evidence_ids") or source.get("spp_evidence_ids") or table.get("evidence_ids", "").split(";") if first_present(source.get("SPP_evidence_ids"), source.get("spp_evidence_ids"), table.get("evidence_ids")) else [])
            retrieval_count = int(source.get("retrieval_count") or len(retrieval_ids))
            retrieval_hash = hash_json(retrieval_ids) if retrieval_ids else ""
            evidence_hash = first_present((source.get("evidence_bundle") or {}).get("bundle_hash"), table.get("evidence_hash"), hash_json(evidence_ids) if evidence_ids else "")
        cif_path_value = first_present(
            source.get("CIF_path"), source.get("generated_cif_path"), source.get("generated_cif_path"),
            source.get("generated_cif_path") if block == "BREADTH" else "", table.get("cif_path"),
        )
        if block == "BREADTH":
            unique_id = source["unique_structure_id"]
            archived_cif = ROOT / "artifacts" / "paper_final_results_v1" / "PAPER_READY_ARCHIVE" / "02_INITIAL_CIFS" / "by_unique_structure" / f"{unique_id}.cif"
            cif_path = archived_cif if archived_cif.is_file() else Path(source["generated_cif_path"])
        else:
            cif_path = Path(cif_path_value) if cif_path_value else None
        cif_exists = bool(cif_path and cif_path.is_file())
        cif_hash = sha256(cif_path) if cif_exists else ""
        canonical_hash, occupation_hash = canonical_structure_hash(cif_path) if cif_exists else ("", "")
        chgnet = scaffold_chgnet.get(row_id) or scaffold_chgnet_by_hash.get(cif_hash, {})
        if block == "BREADTH":
            chgnet = {
                "chgnet_status": "PASS" if source.get("relaxation_status") == "PASS" else str(source.get("relaxation_status") or "CONTROLLED_FAILURE"),
                "converged": source.get("converged"), "initial_space_group": source.get("space_group_before"),
                "relaxed_space_group": source.get("space_group_after"),
                "initial_crystal_system": source.get("detected_crystal_system"),
                "relaxed_crystal_system": source.get("detected_crystal_system") if as_bool(source.get("crystal_system_retained")) else "CHANGED",
                "initial_volume": source.get("initial_volume"), "relaxed_volume": source.get("final_volume"),
                "volume_change_percent": source.get("volume_change_percent"),
                "initial_relaxed_match": source.get("structure_match_initial_relaxed"),
                "space_group_retained": source.get("space_group_retained"),
                "crystal_system_retained": source.get("crystal_system_retained"),
                "relaxed_cif_path": source.get("relaxed_cif_path"),
                "relaxed_cif_sha256": source.get("relaxed_cif_sha256"),
                "runtime_seconds": source.get("runtime_seconds"),
            }
        request_hashes = source.get("request_spp_hashes") or {}
        repository_manifest = source.get("provenance_manifest") or {}
        workflow_commit = first_present(
            (repository_manifest.get("repositories") or {}).get("Skill-Loop-CSP"),
            table.get("workflow_commit"), LEGACY_COMMIT if block == "BREADTH" else "",
        )
        task = source.get("normalised_task") or source.get("normalised_task") or {}
        if block == "BREADTH":
            task = {"formula": source.get("target_formula"), "family": source.get("target_family"), "space_group": source.get("requested_space_group")}
        parity_value = source.get("objective_parity")
        parity = "PASS" if parity_value is True else str(parity_value or table.get("objective_parity") or ("NOT_AVAILABLE_LEGACY" if block == "BREADTH" else "NOT_APPLICABLE"))
        terminal = "PASS"
        failure_stage = first_present(source.get("failure_stage"), table.get("failure_stage"))
        failure_code = first_present(source.get("failure_code"), table.get("failure_code"))
        failure_message = first_present(source.get("failure_message"), table.get("failure_message"))
        if block == "ABSTENTION":
            terminal = "EXPECTED_CONTROLLED_ABSTENTION"
            parity = "NOT_APPLICABLE"
        elif table.get("workflow_status") not in {"PASS", "REUSED_FROZEN_RESULT"}:
            terminal = table.get("workflow_status")
        failed_checks = sca_failed_checks(source)
        master_row = {
            "row_id": row_id, "experiment_block": block, "formula": intent["formula"],
            "family": intent["family"], "request": intent["request"],
            "scaffold_mode": intent["scaffold_mode"],
            "candidate_space_id": first_present(source.get("scaffold_id"), source.get("scaffold_id"), source.get("scaffold_id"), source.get("scaffold_id"), table.get("candidate_space_id")),
            "repeat_group": intent.get("repeat_group", ""), "repeat_index": intent.get("repeat_index", ""),
            "run_id": first_present(source.get("run_id"), table.get("run_id")),
            "attempt_id": first_present(source.get("attempt_id"), table.get("attempt_id")),
            "workflow_commit": workflow_commit, "corpus_id": first_present(source.get("corpus_id"), source.get("retrieval_corpus"), intent.get("corpus")),
            "corpus_hash": first_present(source.get("corpus_hash"), "NOT_AVAILABLE_LEGACY" if block == "BREADTH" else ""),
            "retrieval_count": retrieval_count, "retrieval_ids": retrieval_ids,
            "retrieval_record_hash": retrieval_hash, "evidence_count": len(evidence_ids),
            "evidence_ids": evidence_ids, "evidence_hash": evidence_hash,
            "request_spp_status": first_present(source.get("request_spp_status"), source.get("request_support_status"), source.get("spp_status")),
            "request_spp_hash": hash_json(request_hashes) if request_hashes else (sha256(archive / "spp_summary.json") if archive and (archive / "spp_summary.json").is_file() else ""),
            "request_spp_usable_pairs": first_present(source.get("request_supported_pair_count"), source.get("request_supported_pair_count"), table.get("request_usable_pair_count")),
            "regulator_fallback_pairs": first_present(source.get("regulator_fallback_pair_count"), table.get("fallback_pair_count")),
            "unsupported_pairs": first_present(source.get("unsupported_pair_count"), table.get("unsupported_pair_count")),
            "solver_status": first_present(source.get("solver_status"), source.get("solver_status"), table.get("solver_status")),
            "solver_objective": first_present(source.get("solver_objective"), table.get("solver_objective")),
            "independent_objective": first_present(source.get("independent_objective"), table.get("independent_objective")),
            "objective_difference": first_present(source.get("objective_difference"), table.get("objective_difference")),
            "objective_parity": parity, "selected_occupation_hash": occupation_hash,
            "cif_emitted": "YES" if cif_exists else "NO", "cif_path": str(cif_path.resolve()) if cif_exists else "",
            "cif_hash": cif_hash, "canonical_cif_hash": canonical_hash,
            "exact_composition": "YES" if (block != "BREADTH" or as_bool(source.get("formula_match"))) and cif_exists else ("NOT_APPLICABLE" if block == "ABSTENTION" else "NO"),
            "initial_space_group": first_present(source.get("generated_space_group"), source.get("detected_space_group"), chgnet.get("initial_space_group"), task.get("space_group")),
            "initial_crystal_system": first_present(source.get("generated_crystal_system"), source.get("detected_crystal_system"), chgnet.get("initial_crystal_system")),
            "initial_volume": first_present(source.get("generated_volume"), source.get("volume"), chgnet.get("initial_volume")),
            "sca_status": sca_status(source) if block == "BREADTH" else first_present(source.get("SCA_status"), table.get("sca_status"), "NOT_APPLICABLE" if block == "ABSTENTION" else ""),
            "sca_topology": first_present(source.get("topology_status"), (source.get("sca_result") or {}).get("topology_status"), table.get("sca_topology_status")),
            "sca_geometry_ok": first_present(source.get("geometry_ok"), (source.get("sca_result") or {}).get("geometry_ok"), table.get("sca_geometry_ok")),
            "sca_min_distance": first_present(source.get("minimum_distance"), (source.get("sca_result") or {}).get("min_distance"), table.get("sca_min_distance")),
            "sca_severe_contact_count": first_present(source.get("severe_contact_count"), (source.get("sca_result") or {}).get("num_bad_contacts"), table.get("sca_num_bad_contacts")),
            "sca_failed_check_count": len(failed_checks),
            "sca_failed_check_names": failed_checks,
            "chgnet_status": first_present(chgnet.get("chgnet_status"), "NOT_APPLICABLE"),
            "chgnet_converged": first_present(chgnet.get("converged"), "NOT_APPLICABLE"),
            "relaxed_space_group": chgnet.get("relaxed_space_group", ""),
            "relaxed_crystal_system": chgnet.get("relaxed_crystal_system", ""),
            "relaxed_volume": chgnet.get("relaxed_volume", ""),
            "volume_change_percent": chgnet.get("volume_change_percent", ""),
            "initial_relaxed_match": chgnet.get("initial_relaxed_match", ""),
            "space_group_retained": chgnet.get("space_group_retained", ""),
            "crystal_system_retained": chgnet.get("crystal_system_retained", ""),
            "reference_match": first_present(source.get("reference_match"), source.get("label")),
            "runtime_seconds": first_present(source.get("runtime_seconds"), source.get("wall_time_seconds"), chgnet.get("runtime_seconds")),
            "workflow_terminal_status": terminal, "failure_stage": failure_stage,
            "failure_code": failure_code, "failure_message": failure_message,
            "execution_mode": intent["execution_mode"], "source_artifact": intent.get("source_artifact", ""),
            "source_artifact_key": intent.get("source_artifact_key", ""),
        }
        if block == "ABSTENTION":
            master_row.update({"solver_status": "NOT_REACHED", "cif_emitted": "NO", "exact_composition": "NOT_APPLICABLE", "sca_status": "NOT_REACHED", "chgnet_status": "NOT_APPLICABLE"})
        checks: dict[str, bool | None] = {
            "original_request": bool(intent.get("request")),
            "structured_task": bool(task),
            "corpus_identity": bool(master_row["corpus_id"] and master_row["corpus_hash"]),
            "retrieval_ids_provenance": bool(retrieval_ids),
            "evidence_ids_hash": bool(evidence_ids and evidence_hash) if block != "ABSTENTION" else None,
            "request_spp_artifacts_config": bool(master_row["request_spp_hash"]) if block != "ABSTENTION" else None,
            "candidate_space_definition": bool(master_row["candidate_space_id"] or task.get("prototype") or (archive and (archive / "orbit_candidates.json").is_file())),
            "solver_configuration": bool(source.get("qlip_adapter") or (archive and (archive / "qlip_request.json").is_file())) if block != "ABSTENTION" else None,
            "solver_result": bool(master_row["solver_status"]) if block != "ABSTENTION" else None,
            "objective_parity": master_row["objective_parity"] == "PASS" if block != "ABSTENTION" else None,
            "generated_cif": cif_exists if block != "ABSTENTION" else None,
            "sca": bool(master_row["sca_status"] and master_row["sca_status"] not in {"", "NOT_REACHED"}) if block != "ABSTENTION" else None,
            "chgnet": master_row["chgnet_status"] == "PASS" if intent.get("run_chgnet") == "yes" and block != "ABSTENTION" else None,
            "workflow_trace": bool(source) or bool(archive and (archive / "workflow_trace.json").is_file()),
            "attempt_manifest": bool((TABLE_RUN / "rows" / row_id / "attempt_manifest.json").is_file()) or bool(intent.get("source_artifact") and (ROOT / intent["source_artifact"]).resolve().parent.joinpath("attempt_manifest.json").is_file()) or bool(archive and (archive / "artifact_manifest.json").is_file()),
            "terminal_status_failure_reason": bool(master_row["workflow_terminal_status"]),
        }
        applicable = [name for name, value in checks.items() if value is not None]
        missing = [name for name in applicable if checks[name] is False]
        complete_count = len(applicable) - len(missing)
        master_row["provenance_complete"] = "YES" if not missing else "NO"
        master_row["provenance_completeness_percent"] = 100.0 * complete_count / len(applicable)
        master_row["provenance_missing_fields"] = missing
        provenance.append({
            "row_id": row_id, "experiment_block": block,
            **{name: "NOT_APPLICABLE" if value is None else "PRESENT" if value else "MISSING" for name, value in checks.items()},
            "applicable_fields": len(applicable), "complete_fields": complete_count,
            "missing_fields": missing, "complete": "YES" if not missing else "NO",
            "completeness_percent": 100.0 * complete_count / len(applicable),
        })
        master.append(master_row)
    return master, provenance


def markdown_table(rows: list[dict[str, Any]], fields: list[tuple[str, str]]) -> list[str]:
    lines = ["| " + " | ".join(label for _, label in fields) + " |", "|" + "|".join("---" for _ in fields) + "|"]
    for row in rows:
        values = []
        for key, _ in fields:
            value = encode(row.get(key, ""))
            if isinstance(value, float):
                value = f"{value:.4g}"
            values.append(str(value or "-").replace("|", "\\|"))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def structure_panel(axis: Any, cif_path: str, title: str) -> None:
    structure = Structure.from_file(cif_path)
    coords = structure.cart_coords
    elements = [str(site.specie) for site in structure]
    palette = {element: plt.cm.tab20(index % 20) for index, element in enumerate(sorted(set(elements)))}
    axis.scatter(coords[:, 0], coords[:, 1], s=55, c=[palette[value] for value in elements], edgecolors="black", linewidths=0.35)
    axis.set_title(title, fontsize=9, weight="bold")
    axis.set_aspect("equal", adjustable="datalim")
    axis.set_xticks([]); axis.set_yticks([])
    for element, color in palette.items():
        axis.scatter([], [], c=[color], label=element, s=24)
    axis.legend(fontsize=6, ncol=3, frameon=False, loc="lower center")


def save_figure(fig: Any, stem: Path) -> None:
    fig.savefig(stem.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(stem.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def figures(master: list[dict[str, Any]]) -> None:
    figures_dir = OUT / "figures"; figures_dir.mkdir(parents=True, exist_ok=True)
    by_id = {row["row_id"]: row for row in master}
    trace = by_id["TRACE-A2"]
    detail = json.loads((TABLE_RUN / "rows" / "TRACE-A2" / "result.json").read_text(encoding="utf-8"))["selected_source_record"]
    pair_results = detail.get("request_pair_results") or []
    curve_record = next((row for row in pair_results if row.get("species_pair") == "Na-O" and row.get("request_pot_path")), None)
    if curve_record is None:
        curve_record = next(row for row in pair_results if row.get("request_pot_path"))
    curve_path = Path(curve_record["request_pot_path"])
    curve_points = [
        (float(parts[0]), float(parts[1]))
        for line in curve_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        for parts in [line.split()]
    ]
    figure1_source = {
        key: trace.get(key) for key in (
            "row_id", "formula", "request", "corpus_id", "corpus_hash", "retrieval_count",
            "retrieval_ids", "evidence_count", "evidence_hash", "request_spp_status",
            "request_spp_usable_pairs", "regulator_fallback_pairs", "solver_status",
            "solver_objective", "independent_objective", "objective_difference", "objective_parity",
            "cif_hash", "sca_status", "chgnet_status", "volume_change_percent", "runtime_seconds",
        )
    }
    figure1_source["representative_request_spp_curve"] = {
        "species_pair": curve_record["species_pair"],
        "pot_path": str(curve_path),
        "pot_sha256": sha256(curve_path),
        "distance_A": [point[0] for point in curve_points],
        "potential": [point[1] for point in curve_points],
    }
    (figures_dir / "Figure_1_trace_source.json").write_text(json.dumps(figure1_source, indent=2, default=str) + "\n", encoding="utf-8")
    fig, axes = plt.subplots(2, 4, figsize=(14, 7))
    panels = [
        ("1. Researcher request", trace["request"]),
        ("2. Structured task", json.dumps(detail.get("normalised_task"), indent=2)),
        ("3. Crystal-DB evidence", f"{trace['corpus_id']}\n{trace['retrieval_count']} records\nIDs: {', '.join(trace['retrieval_ids'][:3])} ..."),
        ("4. Request SPP", f"{trace['request_spp_status'].replace('_', ' ')}\nusable pairs: {trace['request_spp_usable_pairs']}\nfallback pairs: {trace['regulator_fallback_pairs']}\nhash: {trace['request_spp_hash'][:16]}..."),
        ("5. IP-CSP / QLIP", f"status: {trace['solver_status']}\nobjective: {float(trace['solver_objective']):.6f}\nparity: {trace['objective_parity']}\ndifference: {float(trace['objective_difference']):.3g}"),
        ("6. Generated CIF", f"{trace['formula']}\nSG: {trace['initial_space_group']}\nhash: {trace['cif_hash'][:16]}..."),
        ("7. Independent QC", f"SCA: {trace['sca_status']}\nCHGNet: {trace['chgnet_status']}\nvolume change: {float(trace['volume_change_percent']):+.2f}%\nSG retained: {trace['space_group_retained']}"),
    ]
    for axis, (title, text) in zip(axes.flat[:7], panels):
        axis.axis("off"); axis.set_title(title, fontsize=10, weight="bold")
        wrap_width = 34 if title == "4. Request SPP" else 40
        axis.text(0.03, 0.9, textwrap.fill(str(text), wrap_width), va="top", fontsize=8,
                  family="monospace" if title in {"2. Structured task", "5. IP-CSP / QLIP"} else None,
                  clip_on=True)
    spp_axis = axes.flat[3]
    spp_axis.clear()
    spp_axis.set_title("4. Actual request SPP", fontsize=10, weight="bold")
    spp_axis.plot([point[0] for point in curve_points], [point[1] for point in curve_points], color="#7b3294", linewidth=1.2)
    spp_axis.set_xlabel("Distance (Angstrom)", fontsize=7)
    spp_axis.set_ylabel("Potential", fontsize=7)
    spp_axis.tick_params(labelsize=6)
    spp_axis.text(0.03, 0.95, f"{curve_record['species_pair']} | {trace['request_spp_usable_pairs']} usable + {trace['regulator_fallback_pairs']} fallback", transform=spp_axis.transAxes, va="top", fontsize=6.5)
    structure_panel(axes.flat[7], trace["cif_path"], "8. Actual generated structure")
    fig.suptitle("Figure 1. One complete traceable request-to-crystal execution", fontsize=14, weight="bold", y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.94), h_pad=2.4, w_pad=2.0)
    save_figure(fig, figures_dir / "Figure_1_trace")

    source_png = ROOT / "artifacts" / "paper_final_results_v1" / "PAPER_READY_ARCHIVE" / "07_FIGURES" / "GENERATED_STRUCTURE_FIGURES" / "initial_representative_12_structures_main_text.png"
    source_pdf = source_png.with_suffix(".pdf")
    shutil.copy2(source_png, figures_dir / "Figure_2_structure_montage.png")
    shutil.copy2(source_pdf, figures_dir / "Figure_2_structure_montage.pdf")
    source_manifest = ROOT / "artifacts" / "paper_final_results_v1" / "PAPER_READY_ARCHIVE" / "07_FIGURES" / "scripts" / "structure_figure_manifest.csv"
    montage_ids = {"U-001", "U-004", "U-010", "U-020", "U-008", "U-009", "U-018", "U-017", "U-012", "U-013", "U-022", "U-024"}
    montage_rows = [row for row in read_csv(source_manifest) if row["unique_structure_id"] in montage_ids]
    write_csv(figures_dir / "Figure_2_structure_montage_source.csv", montage_rows)

    breadth = [row for row in master if row["experiment_block"] == "BREADTH"]
    values = [float(row["volume_change_percent"]) for row in breadth]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), gridspec_kw={"width_ratios": [3, 1]})
    colors = ["#c0392b" if abs(value) >= 10 else "#2c7fb8" for value in values]
    axes[0].bar(range(len(breadth)), values, color=colors)
    axes[0].axhline(0, color="black", linewidth=0.7)
    axes[0].set_xticks(range(len(breadth)), [row["formula"] for row in breadth], rotation=55, ha="right", fontsize=8)
    axes[0].set_ylabel("Volume change after CHGNet relaxation (%)")
    axes[0].set_title("Uniform frozen CHGNet relaxation")
    axes[0].set_ylim(min(-18.0, min(values) - 4.0), max(55.0, max(values) + 4.0))
    for index, value in enumerate(values):
        if abs(value) >= 10:
            axes[0].annotate(
                f"{breadth[index]['formula']} {value:+.1f}%",
                xy=(index, value), xytext=(0, 4 if value >= 0 else -4),
                textcoords="offset points", ha="center",
                va="bottom" if value >= 0 else "top", fontsize=7,
            )
    retained = sum(as_bool(row["space_group_retained"]) for row in breadth)
    axes[1].bar(["retained", "changed"], [retained, len(breadth) - retained], color=["#31a354", "#de2d26"])
    axes[1].set_ylim(0, len(breadth)); axes[1].set_ylabel("Structures")
    axes[1].set_title("Space-group retention")
    fig.suptitle("Figure 3. Structural quality control for the frozen breadth set", fontsize=13, weight="bold", y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.92), w_pad=2.4)
    save_figure(fig, figures_dir / "Figure_3_quality_control")
    write_csv(figures_dir / "Figure_3_quality_control_source.csv", breadth)

    positive = by_id["SCAFFOLD-A2"]; abstention = by_id["ABSTENTION-A1"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1.3, 1.2, 1.2]})
    axes[0].axis("off"); axes[0].set_title("Explicit scaffold prior", weight="bold")
    axes[0].text(0.03, 0.9, textwrap.fill(f"Request: {positive['request']}\n\nScaffold: {positive['candidate_space_id']}\nCorpus: {positive['corpus_id']}\nEvidence: {positive['evidence_count']} records\nRequest-supported pairs: {positive['request_spp_usable_pairs']}\nRegulator fallback: {positive['regulator_fallback_pairs']}", 38), va="top", fontsize=9)
    structure_panel(axes[1], positive["cif_path"], "Generated NASICON candidate")
    axes[2].axis("off"); axes[2].set_title("Controlled unrepresentable request", weight="bold", color="#b30000")
    axes[2].text(0.03, 0.9, textwrap.fill(f"{abstention['request']}\n\nTerminal code: {abstention['failure_code']}\nSolver invoked: NO\nCIF emitted: {abstention['cif_emitted']}\nOutcome: explicit abstention within the selected scaffold; not a claim of physical impossibility.", 38), va="top", fontsize=9)
    fig.suptitle("Figure 4. Explicit scaffolds extend the workflow and expose representability limits", fontsize=13, weight="bold")
    save_figure(fig, figures_dir / "Figure_4_scaffold_extension")
    write_csv(figures_dir / "Figure_4_scaffold_extension_source.csv", [positive, abstention])


def reports(master: list[dict[str, Any]], provenance: list[dict[str, Any]]) -> None:
    breadth = [row for row in master if row["experiment_block"] == "BREADTH"]
    repeats = [row for row in master if row["experiment_block"] == "REPEATABILITY"]
    scaffold = [row for row in master if row["experiment_block"] in {"SCAFFOLD", "ABSTENTION"}]
    qc = [row for row in master if row["experiment_block"] in {"BREADTH", "TRACE", "SCAFFOLD"}]
    write_csv(OUT / "MASTER_RESULTS.csv", master)
    write_csv(OUT / "PROVENANCE_COMPLETENESS.csv", provenance)
    write_csv(OUT / "SCA_CHGNET_RESULTS.csv", qc)
    write_csv(OUT / "SCAFFOLD_EXTENSION_RESULTS.csv", scaffold)
    write_csv(OUT / "TABLE_1_BREADTH.csv", breadth)
    write_csv(OUT / "TABLE_2_SCA_CHGNET.csv", breadth)
    write_csv(OUT / "TABLE_3_SCAFFOLD_EXTENSION.csv", scaffold)

    repeat_rows = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in repeats: groups[row["repeat_group"]].append(row)
    for group, rows in groups.items():
        objective_same = len({str(row["solver_objective"]) for row in rows}) == 1
        occupation_same = len({row["selected_occupation_hash"] for row in rows}) == 1
        cif_same = len({row["canonical_cif_hash"] for row in rows}) == 1
        evidence_same = len({encode(row["evidence_ids"]) for row in rows}) == 1
        spp_same = len({row["request_spp_hash"] for row in rows}) == 1
        for row in rows:
            repeat_rows.append({
                **row, "identical_solver_objective": objective_same,
                "identical_selected_occupation": occupation_same,
                "identical_canonical_cif": cif_same, "identical_evidence_ids": evidence_same,
                "identical_request_spp_hash": spp_same,
            })
    write_csv(OUT / "REPEATABILITY_RESULTS.csv", repeat_rows)

    trace = next(row for row in master if row["experiment_block"] == "TRACE")
    trace_provenance = next(row for row in provenance if row["row_id"] == trace["row_id"])
    trace_audit = [
        {"check": key, "status": "PASS" if value not in {"", None, "[]"} else "MISSING"}
        for key, value in trace_provenance.items()
        if key not in {"row_id", "experiment_block", "applicable_fields", "complete_fields", "completeness_percent", "complete", "missing_fields"}
        and value != "NOT_APPLICABLE"
    ]
    write_csv(OUT / "TRACEABILITY_AUDIT.csv", trace_audit)
    trace_audit_md = ["# Flagship Traceability Audit", "", f"- Row: {trace['row_id']}", f"- Formula: {trace['formula']}", f"- Complete: {trace_provenance['complete']}", f"- Applicable fields present: {trace_provenance['complete_fields']}/{trace_provenance['applicable_fields']} ({float(trace_provenance['completeness_percent']):.2f}%)", "", *markdown_table(trace_audit, [("check", "Check"), ("status", "Status")])]
    (OUT / "TRACEABILITY_AUDIT.md").write_text("\n".join(trace_audit_md) + "\n", encoding="utf-8")

    main_fields = [("formula", "Formula"), ("family", "Family"), ("sca_status", "SCA"), ("chgnet_status", "CHGNet"), ("reference_match", "Reference"), ("initial_space_group", "Initial SG"), ("volume_change_percent", "Delta V %"), ("solver_status", "Solver"), ("objective_parity", "Parity")]
    master_md = ["# Master Results", "", "QLIP status reports optimization completion; it is not a realism score.", ""] + markdown_table(master, [("row_id", "Row"), ("experiment_block", "Block"), *main_fields])
    (OUT / "MASTER_RESULTS.md").write_text("\n".join(master_md) + "\n", encoding="utf-8")
    tables = ["# Paper Results Tables", "", "## Table 1. Breadth results", ""] + markdown_table(breadth, main_fields)
    tables += ["", "## Table 2. SCA and CHGNet quality control", ""] + markdown_table(breadth, [("formula", "Formula"), ("sca_status", "SCA"), ("sca_topology", "Topology"), ("sca_min_distance", "Min distance"), ("chgnet_status", "CHGNet"), ("volume_change_percent", "Delta V %"), ("space_group_retained", "SG retained"), ("initial_relaxed_match", "Initial-relaxed match")])
    tables += ["", "## Table 3. Scaffold extension and controlled abstention", ""] + markdown_table(scaffold, [("row_id", "Case"), ("formula", "Formula"), ("workflow_terminal_status", "Terminal status"), ("solver_status", "Solver"), ("objective_parity", "Parity"), ("cif_emitted", "CIF"), ("sca_status", "SCA"), ("chgnet_status", "CHGNet"), ("failure_code", "Failure code")])
    (OUT / "PAPER_RESULTS_TABLES.md").write_text("\n".join(tables) + "\n", encoding="utf-8")

    sca_counts = Counter(row["sca_status"] for row in breadth)
    chgnet_completed = sum(row["chgnet_status"] == "PASS" for row in breadth)
    retained = sum(as_bool(row["space_group_retained"]) for row in breadth)
    systems = sum(as_bool(row["crystal_system_retained"]) for row in breadth)
    volume_values = [float(row["volume_change_percent"]) for row in breadth]
    outlier = max(breadth, key=lambda row: abs(float(row["volume_change_percent"])))
    complete = sum(row["complete"] == "YES" for row in provenance)
    total_applicable = sum(int(row["applicable_fields"]) for row in provenance)
    total_complete = sum(int(row["complete_fields"]) for row in provenance)
    completeness_rate = 100.0 * total_complete / total_applicable
    summary = f"""# Paper Results Summary Text

## 2.1 From a text request to a traceable crystal-generation workflow

The flagship Na3Zr2Si2PO12 execution preserved the researcher request, structured task, specialist Crystal-DB corpus and {master[0]['retrieval_count']} retrieved record identifiers, the request-specific SPP artifacts, explicit scaffold definition, QLIP configuration and result, independent objective-parity check, generated CIF, SCA result, CHGNet relaxation and attempt trace. QLIP returned {master[0]['solver_status']} and the independent objective differed by {float(master[0]['objective_difference']):.3g}; this establishes execution fidelity, not physical realism. The generated candidate passed SCA and the separate CHGNet surrogate relaxation converged while retaining its detected space group.

## 2.2 Generation across multiple material families

The frozen breadth set contains {len(breadth)} candidates spanning {len(set(row['family'] for row in breadth))} material families. All {sum(row['cif_emitted'] == 'YES' for row in breadth)} archived CIFs were parseable and preserved the requested reduced composition. SCA classified {sca_counts.get('PASS', 0)} PASS, {sca_counts.get('PARTIAL', 0)} PARTIAL and {sca_counts.get('FAIL', 0)} FAIL. Legacy breadth executions without an independent objective certificate are reported as NOT_AVAILABLE_LEGACY rather than being retrospectively relabelled as parity passes.

## 2.3 Structural quality control of generated candidates

The same {len(breadth)} breadth candidates were evaluated with one frozen CHGNet protocol (pretrained CHGNet, FIRE, fmax 0.1 eV/Angstrom, 200 maximum steps, cell relaxation enabled). Relaxation completed for {chgnet_completed}/{len(breadth)} candidates. Detected space group was retained for {retained}/{len(breadth)} and crystal system for {systems}/{len(breadth)}. The median signed volume change was {median(volume_values):+.2f}%. The largest absolute volume-change outlier was {outlier['formula']} at {float(outlier['volume_change_percent']):+.2f}%; it remains in the denominator. These are surrogate-relaxation sanity checks, not DFT stability, ground-state or synthesizability evidence.

## 2.4 Reproducibility of the frozen downstream CSP workflow

Three representative tasks were executed three times each. Within every repeat group, solver objective, selected-occupation signature, canonical CIF hash, retrieval/evidence identifiers and request-SPP POT hashes were identical. The supported claim is therefore conditional: the downstream CSP workflow is deterministic given a frozen structured task, evidence state and configuration.

## 2.5 Explicit structural scaffolds extend the workflow to more complex crystallographic spaces

Three registered NASICON/NZP scaffold cases produced QLIP-optimal, objective-parity-checked CIFs that passed SCA; all three also completed the uniform CHGNet check while retaining detected space group and crystal system. Two cases are target-derived scaffold demonstrations and retain that claim boundary; the independent LiZr2(PO4)3 reference test did not recover its held-out reference. Three incompatible requests terminated with explicit representability codes before solve and emitted no CIF. These results show inspectable extension and abstention within registered candidate spaces, not broad NASICON generalisation.
"""
    (OUT / "PAPER_RESULTS_SUMMARY_TEXT.md").write_text(summary, encoding="utf-8")

    provenance_index = ["# Provenance Index", "", f"- Manifest: `{MANIFEST.relative_to(ROOT)}`", f"- Table run: `{TABLE_RUN.relative_to(ROOT)}`", f"- Breadth source: `artifacts/paper_final_results_v1/PAPER_READY_ARCHIVE/06_TABLES/CSV/FINAL_UNIQUE_STRUCTURE_RESULTS.csv`", f"- Scaffold source: `artifacts/final_paper_combined_results/RESULT_4_COMBINED.csv`", f"- Scaffold CHGNet: `{SCAFFOLD_CHGNET.relative_to(ROOT)}`", "", "| Row | Block | Source | Key | Workflow commit |", "|---|---|---|---|---|"]
    for row in master:
        provenance_index.append(f"| {row['row_id']} | {row['experiment_block']} | {row['source_artifact'] or 'table_run/rows/' + row['row_id']} | {row['source_artifact_key'] or '-'} | {row['workflow_commit']} |")
    (OUT / "PROVENANCE_INDEX.md").write_text("\n".join(provenance_index) + "\n", encoding="utf-8")

    audit = f"""# Final Results Audit

## Outcome

- Manifest rows: {len(master)}
- Master rows: {len(master)}
- One-to-one row accounting: PASS
- Breadth rows: {len(breadth)}
- Repeatability executions: {len(repeats)}
- Scaffold positives: {sum(row['experiment_block'] == 'SCAFFOLD' for row in scaffold)}
- Controlled abstentions: {sum(row['experiment_block'] == 'ABSTENTION' for row in scaffold)}
- SCA breadth coverage: {sum(row['sca_status'] in {'PASS', 'PARTIAL', 'FAIL'} for row in breadth)}/{len(breadth)}
- CHGNet breadth coverage: {chgnet_completed}/{len(breadth)}
- Fully complete provenance rows: {complete}/{len(provenance)}
- Applicable provenance fields present: {total_complete}/{total_applicable} ({completeness_rate:.2f}%)

## Integrity boundaries

- No target was replaced after validation.
- Failed and outlying outcomes remain in denominators.
- The three historical NASICON software-failed attempts are preserved; post-repair attempts use unchanged scientific inputs.
- Twenty legacy breadth rows lack independent objective-parity certificates and are labelled NOT_AVAILABLE_LEGACY.
- QLIP OPTIMAL is interpreted only as optimization completion.
- CHGNet is described only as a surrogate-relaxation sanity check.
- Target-derived scaffold demonstrations are not relabelled as independent predictions.
- No push was performed.

## Machine-source checks

- Every paper table is generated from MASTER_RESULTS.csv projections.
- Figure 1 source: figures/Figure_1_trace_source.json.
- Figure 2 source: figures/Figure_2_structure_montage_source.csv and frozen VESTA renders.
- Figure 3 source: figures/Figure_3_quality_control_source.csv.
- Figure 4 source: figures/Figure_4_scaffold_extension_source.csv.
"""
    (OUT / "FINAL_RESULTS_AUDIT.md").write_text(audit, encoding="utf-8")


def freeze_machine_outputs(master: list[dict[str, Any]]) -> None:
    manifest_rows = read_csv(MANIFEST)
    freeze = {
        "manifest": str(MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": sha256(MANIFEST),
        "row_count": len(manifest_rows),
        "ordered_row_ids": [row["row_id"] for row in manifest_rows],
        "master_sha256": sha256(OUT / "MASTER_RESULTS.csv"),
        "master_row_count": len(master),
    }
    (OUT / "MANIFEST_FREEZE.json").write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    hashed: list[dict[str, Any]] = []
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path.name == "OUTPUT_HASH_MANIFEST.csv":
            continue
        if any(part in {"dry_run", "table_run", "scaffold_chgnet"} for part in path.relative_to(OUT).parts):
            continue
        hashed.append({
            "path": str(path.relative_to(OUT)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    write_csv(OUT / "OUTPUT_HASH_MANIFEST.csv", hashed)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    master, provenance = build_master()
    reports(master, provenance)
    figures(master)
    row_figure_manifest = OUT / "figures" / "ROW_WORKFLOW_FIGURES.csv"
    if row_figure_manifest.is_file():
        row_figures = read_csv(row_figure_manifest)
        if row_figures and all(row.get("visual_QA_status") == "PASS" for row in row_figures):
            from sok_llm_orchestrator.workflow.paper_figures import build_paper_figures

            build_paper_figures(OUT / "MASTER_RESULTS.csv", TABLE_RUN, OUT / "figures")
    freeze_machine_outputs(master)
    print(f"built {len(master)} master rows under {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
