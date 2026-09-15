"""Validate manuscript numbers against final aggregate tables."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_final_results_v1"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle: return list(csv.DictReader(handle))


def main() -> int:
    aggregates = {r["metric"]: r for r in rows(OUT / "07_tables" / "FINAL_AGGREGATE_RESULTS.csv")}
    results = (OUT / "08_manuscript" / "PAPER_RESULTS_FINAL.tex").read_text(encoding="utf-8")
    required = {
        "workflow_rows": "34 generated workflow rows",
        "raw_hash_unique": "24 raw-hash-unique",
        "canonical_hash_unique": "24 canonical-hash-unique",
        "structurematcher_unique": "24 StructureMatcher-unique",
        "parse_valid": "24/24 unique initial CIFs parsed",
        "chgnet_relax_completed": "24/24 structures",
        "space_group_retained": "23/24 relaxed structures",
        "topology_retained": "24/24",
        "reference_rediscovery": "4 structures REDISCOVERED_REFERENCE",
        "no_local_reference_match": "20 NO_MATCH_IN_EVALUATED_LOCAL_CORPUS",
        "complete_trace_bundles": "34/34 workflow rows",
    }
    for metric, phrase in required.items():
        assert metric in aggregates and phrase in results, f"missing manuscript support for {metric}: {phrase}"
    main_table = {r["Result"]: r for r in rows(OUT / "07_tables" / "PAPER_MAIN_RESULTS_TABLE.csv")}
    for metric, row in aggregates.items():
        assert metric in main_table
        assert main_table[metric]["Count"] == f"{row['numerator']}/{row['denominator']}"
    claim_matrix = {r["claim"]: r["status"] for r in rows(OUT / "08_manuscript" / "PAPER_CLAIM_MATRIX.csv")}
    assert claim_matrix["DFT stability or energy above hull"] == "NOT_SUPPORTED"
    assert claim_matrix["Global novelty or synthesizability"] == "NOT_SUPPORTED"
    positive_forbidden = ["thermodynamically stable candidate", "globally novel candidate", "demonstrated synthesizability", "DFT-stable"]
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in (OUT / "08_manuscript").glob("*.tex"))
    assert not [phrase for phrase in positive_forbidden if phrase.lower() in corpus.lower()]
    print(json.dumps({"aggregate_metrics":len(aggregates),"manuscript_checks":len(required),"claim_checks":len(claim_matrix),"status":"PASS"},sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
