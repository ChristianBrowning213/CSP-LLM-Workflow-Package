"""Run the frozen target-excluded retrieval and production SPP quality audit.

This is deliberately evidence-only.  It never supplements a semantic
neighbourhood, invents a missing pair, scores a candidate, or launches CSP.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CRYSTAL_DB = ROOT.parent / "Crystal-DB"
SPP = ROOT.parent / "SPP-Maker-QLIP"
sys.path[:0] = [str(CRYSTAL_DB), str(SPP / "src")]

OUT = ROOT / "artifacts" / "paper_results_final_redesign"
DESIGN = OUT / "00_design"
ABX3_DB = CRYSTAL_DB / "data" / "phase6_mp_10k.db"
NASICON_DB = ROOT / "data" / "corpora" / "nasicon_specialist_v3" / "crystaldb.sqlite"
CUTOFF = 11.0
PRIMARY_RETRIEVAL_CAP = 10


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_hash(structure: Any) -> str:
    payload = {
        "lattice": [round(float(v), 10) for row in structure.lattice.matrix for v in row],
        "sites": sorted(
            (str(site.specie), *[round(float(v) % 1.0, 10) for v in site.frac_coords])
            for site in structure
        ),
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def manifest_rows() -> list[dict[str, str]]:
    manifest = DESIGN / "BENCHMARK_MANIFEST.csv"
    frozen = json.loads((DESIGN / "FREEZE_METADATA.json").read_text(encoding="utf-8"))
    actual = sha256(manifest)
    if actual != frozen["manifest_sha256"]:
        raise RuntimeError(f"frozen benchmark manifest changed: expected {frozen['manifest_sha256']}, got {actual}")
    with manifest.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def query_for(row: dict[str, str]) -> str:
    formula = row["target_formula"]
    if row["benchmark_role"] == "SCAFFOLD_SPP_FACTORIAL":
        kind = "oxide" if "oxide" in row["target_family"] else "halide"
        return f"{kind} perovskite {formula} ABX3 corner-sharing octahedra"
    return f"NASICON NZP {formula} phosphate framework mobile ion conductor tetrahedral phosphate units"


def inspect_record(
    *, record: sqlite3.Row, row: dict[str, str], reference: Any, matcher: Any, target_reduced: Any
) -> dict[str, Any]:
    from pymatgen.core import Composition, Structure

    cif_text = str(record["cif_text"] or "")
    reduced = Composition(str(record["reduced_formula"])).reduced_composition
    exact_id = str(record["structure_id"]) == row["target_reference_id"] or str(record["source_id"]) == row["target_reference_id"]
    same_formula = reduced == target_reduced
    raw_duplicate = sha256_bytes(cif_text.encode("utf-8")) == row["reference_raw_hash"]
    canonical_duplicate = False
    matcher_equivalent = False
    parse_error = ""
    if same_formula or raw_duplicate:
        try:
            candidate = Structure.from_str(cif_text, fmt="cif")
            canonical_duplicate = canonical_hash(candidate) == row["reference_canonical_hash"]
            matcher_equivalent = bool(matcher.fit(candidate, reference))
        except Exception as exc:  # retained in the audit; never accepted as evidence
            parse_error = f"{exc.__class__.__name__}: {exc}"
    excluded = exact_id or same_formula or raw_duplicate or canonical_duplicate or matcher_equivalent
    return {
        "exact_id": exact_id,
        "same_formula": same_formula,
        "raw_duplicate": raw_duplicate,
        "canonical_duplicate": canonical_duplicate,
        "structurematcher_equivalent": matcher_equivalent,
        "excluded": excluded,
        "parse_error": parse_error,
    }


def run_case(row: dict[str, str], db_path: Path, section: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    from crystal_db.retrieval import text_search
    from pymatgen.analysis.structure_matcher import StructureMatcher
    from pymatgen.core import Composition, Structure
    from spp_maker_qlip.required_pair_extraction import export_required_pair_spp_root

    case_id = row["case_id"]
    case_slug = case_id.lower().replace("rdx-", "").replace("-", "_")
    raw_root = section / "raw" / case_slug
    evidence = raw_root / "retrieved_target_excluded_cifs"
    if raw_root.exists():
        resolved = raw_root.resolve()
        if OUT.resolve() not in resolved.parents:
            raise RuntimeError(f"refusing to clear path outside output root: {resolved}")
        shutil.rmtree(raw_root)
    evidence.mkdir(parents=True)

    reference = Structure.from_file(row["target_reference_cif"])
    target_reduced = Composition(row["target_formula"]).reduced_composition
    matcher = StructureMatcher(ltol=0.2, stol=0.3, angle_tol=5, primitive_cell=True, scale=True, attempt_supercell=False)
    query = query_for(row)
    result = text_search(
        query_text=query, db_path=str(db_path), k=200,
        embed_engine="lmstudio", model_name="text-embedding-bge-m3", model_version="lmstudio_v1",
        text_engine="robocrys", text_view="robocrys", hybrid=False,
        show_text_top=0, export_dir=None, export_top=0, redacted=False,
    )
    write_json(raw_root / "retrieval_response.json", result)
    if result.get("status") != "ok":
        raise RuntimeError(f"production retrieval failed for {case_id}: {result.get('errors')}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    corpus_size = int(conn.execute("SELECT count(*) FROM structures").fetchone()[0])
    db_rows = conn.execute(
        "SELECT s.structure_id,s.cif_text,s.reduced_formula,p.source,p.source_id,p.allow_derivatives "
        "FROM structures s JOIN provenance p USING(structure_id) ORDER BY s.structure_id"
    ).fetchall()
    target_elements = {str(e) for e in target_reduced.elements}
    eligible_count = 0
    exclusion_counts = {key: 0 for key in ("exact_id", "same_formula", "raw_duplicate", "canonical_duplicate", "structurematcher_equivalent")}
    record_audit: dict[str, dict[str, Any]] = {}
    for record in db_rows:
        audit = inspect_record(record=record, row=row, reference=reference, matcher=matcher, target_reduced=target_reduced)
        record_audit[str(record["structure_id"])] = audit
        for key in exclusion_counts:
            exclusion_counts[key] += int(bool(audit[key]))
        try:
            elements = {str(e) for e in Composition(str(record["reduced_formula"])).elements}
        except Exception:
            continue
        if record["cif_text"] and record["allow_derivatives"] and not audit["excluded"] and len(elements & target_elements) >= 2:
            eligible_count += 1

    retrieval_rows: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for neighbor in result["neighbors"]:
        structure_id = str(neighbor["structure_id"])
        record = conn.execute(
            "SELECT s.structure_id,s.cif_text,s.reduced_formula,p.source,p.source_id,p.allow_derivatives "
            "FROM structures s JOIN provenance p USING(structure_id) WHERE s.structure_id=?", (structure_id,),
        ).fetchone()
        if record is None:
            continue
        audit = record_audit[structure_id]
        try:
            elements = {str(e) for e in Composition(str(record["reduced_formula"])).elements}
        except Exception:
            elements = set()
        relevant = len(elements & target_elements) >= 2
        policy_ok = bool(record["cif_text"] and record["allow_derivatives"])
        used = bool(policy_ok and relevant and not audit["excluded"] and len(selected) < PRIMARY_RETRIEVAL_CAP)
        reason = "USED" if used else (
            "TARGET_OR_EQUIVALENT_EXCLUDED" if audit["excluded"] else
            "INSUFFICIENT_TARGET_ELEMENT_OVERLAP" if not relevant else
            "POLICY_OR_CIF_INELIGIBLE" if not policy_ok else "PRIMARY_RETRIEVAL_CAP"
        )
        if used:
            cif_path = evidence / f"{structure_id}.cif"
            cif_path.write_text(str(record["cif_text"]), encoding="utf-8")
            selected.append({"structure_id": structure_id, "cif": str(cif_path), "formula": record["reduced_formula"]})
        retrieval_rows.append({
            "case_id": case_id, "query": query, "corpus_id": row["retrieval_corpus_id"],
            "corpus_size": corpus_size, "eligible_count": eligible_count, "retrieved_count": len(result["neighbors"]),
            "retrieval_rank": neighbor.get("rank"), "retrieval_score": neighbor.get("score"),
            "retrieved_id": structure_id, "retrieved_formula": record["reduced_formula"],
            "same_family_status": "TARGET_ELEMENT_OVERLAP_GE_2" if relevant else "NO",
            "same_formula_status": audit["same_formula"], "target_equivalent_status": audit["structurematcher_equivalent"],
            "raw_duplicate_status": audit["raw_duplicate"], "canonical_duplicate_status": audit["canonical_duplicate"],
            "used_for_SPP": used, "exclusion_or_selection_reason": reason,
            "primary_retrieval_cap": PRIMARY_RETRIEVAL_CAP,
        })
    conn.close()
    if not selected:
        raise RuntimeError(f"no eligible primary semantic evidence for {case_id}")

    spp_root = raw_root / "spp_root"
    generation = export_required_pair_spp_root(
        cif_dir=evidence, formula=row["target_formula"], out_root=spp_root,
        name=f"paper_results_redesign_{case_slug}_strict_target_excluded", cutoff=CUTOFF,
        supercell=None, alpha=1e-3, d_min=0.5, bin_width=0.05,
    )
    write_json(raw_root / "spp_generation.json", generation)
    quality = generation.get("spp_pot_quality") or {}
    required = list(generation.get("required_pairs") or [])
    available = set(generation.get("available_pairs") or [])
    complete = bool(required and set(required) <= available)
    valid = complete and quality.get("spp_pot_quality_status") == "usable"
    pair_summary = {
        item["required_pair"]: item for item in generation.get("corpus_quality", {}).get("pair_evidence_summary", [])
    }
    coverage_rows = []
    for pair in required:
        detail = pair_summary.get(pair, {})
        support = detail.get("direct_support_candidate_ids") or []
        coverage_rows.append({
            "case_id": case_id, "species_pair": pair, "required": True, "curve_available": pair in available,
            "distance_observations": detail.get("direct_observation_count", 0),
            "structures_contributing": len(support), "fallback_used": False, "fallback_source": "NA",
            "coverage_class": "STRICT_COMPLETE" if complete else "INSUFFICIENT",
            "notes": "Primary production semantic retrieval only; no supplementation or zeroed interactions.",
        })
    summary = {
        "case_id": case_id, "formula": row["target_formula"], "corpus_size": corpus_size,
        "eligible_count": eligible_count, "retrieved_count": len(result["neighbors"]), "used_for_spp_count": len(selected),
        "required_pair_count": len(required), "available_pair_count": len(available),
        "coverage_class": "STRICT_COMPLETE" if complete else "INSUFFICIENT",
        "fitter_status": "COMPLETED" if generation.get("attempted") else "NOT_ATTEMPTED",
        "numerical_export_status": "COMPLETE" if complete else "INCOMPLETE",
        "spp_pot_quality_status": quality.get("spp_pot_quality_status", "missing"),
        "diagnostic_only": quality.get("diagnostic_only", True), "valid_for_ranking": valid,
        "quality_failures": ";".join(str(item.get("code", item)) for item in generation.get("errors", [])) or "NONE",
        "exact_id_excluded_count": exclusion_counts["exact_id"], "exact_formula_excluded_count": exclusion_counts["same_formula"],
        "raw_duplicate_excluded_count": exclusion_counts["raw_duplicate"],
        "canonical_duplicate_excluded_count": exclusion_counts["canonical_duplicate"],
        "structurematcher_equivalent_excluded_count": exclusion_counts["structurematcher_equivalent"],
        "spp_artifact": str(spp_root.relative_to(ROOT)).replace("\\", "/"),
        "notes": "Valid for ranking only when strict pair coverage is complete and production POT status is usable.",
    }
    write_json(raw_root / "case_audit.json", {"summary": summary, "exclusion_counts": exclusion_counts})
    return retrieval_rows, coverage_rows, summary


def reference_provenance(rows: list[dict[str, str]]) -> None:
    from pymatgen.core import Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    output = []
    for row in rows:
        if row["benchmark_role"] not in {"SCAFFOLD_SPP_FACTORIAL", "NASICON_EXTENSION"}:
            continue
        strict = row["scaffold_provenance_class"] == "CURATED_CONFIGURATION_NOT_TARGET_DERIVED" and row["target_reference_id"] != "historical-srtio3-pm3m"
        relationship = {
            "CURATED_CONFIGURATION_NOT_TARGET_DERIVED": "generic family prototype; not target-derived",
            "TARGET_DERIVED": "exact target supplies scaffold",
            "FAMILY_MEMBER_NOT_EQUIVALENT": "another family member supplies scaffold topology",
        }.get(row["scaffold_provenance_class"], row["scaffold_provenance_class"])
        independence = "STRICT_INDEPENDENT" if strict else (
            "SCAFFOLD_RELATED_BUT_NOT_EQUIVALENT" if row["scaffold_provenance_class"] == "FAMILY_MEMBER_NOT_EQUIVALENT" else
            "TARGET_DERIVED_SCAFFOLD" if row["scaffold_provenance_class"] == "TARGET_DERIVED" else "UNCLEAR"
        )
        structure = Structure.from_file(row["target_reference_cif"])
        output.append({
            "case_id": row["case_id"], "formula": row["target_formula"], "reference_source": row["reference_source"],
            "reference_id": row["target_reference_id"], "reference_cif": row["target_reference_cif"],
            "reference_raw_hash": row["reference_raw_hash"], "reference_canonical_hash": row["reference_canonical_hash"],
            "reference_space_group": SpacegroupAnalyzer(structure, symprec=0.001, angle_tolerance=5).get_space_group_symbol(),
            "retrieval_target_excluded": True, "raw_duplicate_excluded": True, "canonical_duplicate_excluded": True,
            "structurematcher_equivalent_excluded": True, "scaffold_id": row["candidate_scaffold_id"],
            "scaffold_source_id": row["scaffold_source_id"], "scaffold_source_formula": "GENERIC_ABX3" if strict else "SEE_SCAFFOLD_REGISTRY",
            "scaffold_target_relationship": relationship, "reference_independence_class": independence,
            "notes": "Exclusion tests are recorded by category; exact-formula exclusion is stronger than duplicate-only exclusion.",
        })
    fields = list(output[0])
    write_csv(OUT / "02_rediscovery" / "REFERENCE_PROVENANCE.csv", [r for r in output if r["case_id"].startswith("RDX-") and "E4" not in r["case_id"]], fields)
    write_csv(OUT / "08_nasicon" / "NASICON_PROVENANCE.csv", [r for r in output if "E4" in r["case_id"]], fields)


def write_quality_report(path: Path, title: str, summaries: list[dict[str, Any]]) -> None:
    lines = [f"# {title}", "", "Primary ranking requires both complete required-pair export and production `spp_pot_quality_status=usable`.", "Diagnostic-only or unusable POTs are archived but never scored.", ""]
    for item in summaries:
        lines += [
            f"## {item['case_id']} — {item['formula']}", "",
            f"- Fitter: {item['fitter_status']}",
            f"- Numerical export: {item['numerical_export_status']} ({item['available_pair_count']}/{item['required_pair_count']} pairs)",
            f"- Coverage: {item['coverage_class']}",
            f"- Production POT quality: {item['spp_pot_quality_status']}",
            f"- Diagnostic only: {item['diagnostic_only']}",
            f"- Valid for ranking: {item['valid_for_ranking']}",
            f"- Quality failures: {item['quality_failures']}", "",
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows = manifest_rows()
    reference_provenance(rows)
    all_retrieval: list[dict[str, Any]] = []
    abx_coverage: list[dict[str, Any]] = []
    nasicon_coverage: list[dict[str, Any]] = []
    abx_summary: list[dict[str, Any]] = []
    nasicon_summary: list[dict[str, Any]] = []
    for row in rows:
        role = row["benchmark_role"]
        if role not in {"SCAFFOLD_SPP_FACTORIAL", "NASICON_EXTENSION"}:
            continue
        section = OUT / ("02_rediscovery" if role == "SCAFFOLD_SPP_FACTORIAL" else "08_nasicon")
        db = ABX3_DB if role == "SCAFFOLD_SPP_FACTORIAL" else NASICON_DB
        retrieval, coverage, summary = run_case(row, db, section)
        print(f"{row['case_id']}: {summary['used_for_spp_count']} evidence, {summary['available_pair_count']}/{summary['required_pair_count']} pairs, quality={summary['spp_pot_quality_status']}", flush=True)
        all_retrieval.extend(retrieval)
        if role == "SCAFFOLD_SPP_FACTORIAL":
            abx_coverage.extend(coverage); abx_summary.append(summary)
        else:
            nasicon_coverage.extend(coverage); nasicon_summary.append(summary)
    retrieval_fields = [
        "case_id", "query", "corpus_id", "corpus_size", "eligible_count", "retrieved_count", "retrieval_rank",
        "retrieval_score", "retrieved_id", "retrieved_formula", "same_family_status", "same_formula_status",
        "target_equivalent_status", "raw_duplicate_status", "canonical_duplicate_status", "used_for_SPP",
        "exclusion_or_selection_reason", "primary_retrieval_cap",
    ]
    write_csv(OUT / "02_rediscovery" / "RETRIEVAL_RESULTS.csv", [r for r in all_retrieval if "E4" not in r["case_id"]], retrieval_fields)
    write_csv(OUT / "08_nasicon" / "NASICON_RETRIEVAL.csv", [r for r in all_retrieval if "E4" in r["case_id"]], retrieval_fields)
    coverage_fields = ["case_id", "species_pair", "required", "curve_available", "distance_observations", "structures_contributing", "fallback_used", "fallback_source", "coverage_class", "notes"]
    write_csv(OUT / "02_rediscovery" / "SPP_PAIR_COVERAGE.csv", abx_coverage, coverage_fields)
    write_csv(OUT / "08_nasicon" / "NASICON_SPP_COVERAGE.csv", nasicon_coverage, coverage_fields)
    summary_fields = list(abx_summary[0])
    write_csv(OUT / "02_rediscovery" / "SPP_CASE_AUDIT.csv", abx_summary, summary_fields)
    write_csv(OUT / "08_nasicon" / "NASICON_SPP_CASE_AUDIT.csv", nasicon_summary, summary_fields)
    write_quality_report(OUT / "02_rediscovery" / "SPP_QUALITY_AUDIT.md", "Production SPP quality audit", abx_summary)
    write_quality_report(OUT / "08_nasicon" / "NASICON_SPP_QUALITY.md", "NASICON production SPP quality audit", nasicon_summary)
    (OUT / "02_rediscovery" / "TARGET_EXCLUSION_PROTOCOL.md").write_text(
        "# Target exclusion protocol\n\n"
        "Each frozen reference is tested against the full corpus for exact structure/source ID, exact reduced formula, raw UTF-8 CIF SHA-256, canonical lattice/site hash, and fixed-configuration StructureMatcher equivalence. "
        "Every exact-formula record is excluded regardless of the duplicate tests; therefore same-composition equivalents cannot enter fitting. Retrieval output records each tested category. "
        "Only the top 10 normal production BGE-M3/Robocrys semantic neighbours with derivative permission, a stored CIF, and at least two target elements are used for fitting; all 200 returned neighbours remain in the retrieval audit. No secondary query, metadata supplement, fallback caption, held-out reference, invented interaction, or zero curve is permitted.\n",
        encoding="utf-8",
    )
    print(f"PASS evidence audit: ABX3={len(abx_summary)}, NASICON={len(nasicon_summary)}")


if __name__ == "__main__":
    main()
