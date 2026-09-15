from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
FAILED_ROOT = REPO_ROOT / "test_workdir" / "paper_evidence_pack_v2_robocrys_ollama_validator_live_5_calibrated"
BASELINE_ROOT = REPO_ROOT / "test_workdir" / "paper_evidence_pack_v2_robocrys_ollama_validator_live_5"
REPORT_DIR = REPO_ROOT / "test_workdir" / "paper_evidence_pack_v2" / "reports"


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _case_id_dir(row: Mapping[str, Any]) -> str:
    return Path(str(row.get("case_dir", ""))).name


def _load_manifest(root: Path) -> list[dict[str, Any]]:
    payload = _read_json(root / "manifests" / "paper_evidence_pack_v2_manifest.json")
    return list(payload.get("rows", [])) if isinstance(payload, Mapping) else []


def _query_sidecar(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    return _read_json(root / "raw_runs" / _case_id_dir(row) / "crystal_db_query.json")


def _retrieval_summary(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    return _read_json(root / "raw_runs" / _case_id_dir(row) / "retrieval_summary.json")


def build_report(failed_root: Path = FAILED_ROOT, baseline_root: Path = BASELINE_ROOT) -> dict[str, Any]:
    failed_rows = _load_manifest(failed_root)
    baseline_rows = {row.get("case_id"): row for row in _load_manifest(baseline_root)}
    comparisons: list[dict[str, Any]] = []
    for failed in failed_rows[:5]:
        baseline = baseline_rows.get(failed.get("case_id"), {})
        fq = _query_sidecar(failed_root, failed)
        bq = _query_sidecar(baseline_root, baseline) if baseline else {}
        fr = _retrieval_summary(failed_root, failed)
        br = _retrieval_summary(baseline_root, baseline) if baseline else {}
        raw_error = (((fr.get("step") or {}).get("raw_result_summary") or {}).get("errors") or {})
        comparisons.append(
            {
                "case_id": failed.get("case_id"),
                "short_name": failed.get("short_name"),
                "original_query": failed.get("query"),
                "failed_crystal_db_retrieval_query": fq.get("crystal_db_retrieval_query", failed.get("crystal_db_retrieval_query", "")),
                "baseline_crystal_db_retrieval_query": bq.get("crystal_db_retrieval_query", baseline.get("crystal_db_retrieval_query", "")),
                "failed_compact_retrieval_query": fq.get("compact_retrieval_query", ""),
                "baseline_compact_retrieval_query": bq.get("compact_retrieval_query", ""),
                "failed_pair_evidence_query": fq.get("pair_evidence_query", ""),
                "baseline_pair_evidence_query": bq.get("pair_evidence_query", ""),
                "failed_validator_requirements": fq.get("validator_requirements", []),
                "baseline_validator_requirements": bq.get("validator_requirements", []),
                "failed_terms_added": fq.get("terms_added", []),
                "baseline_terms_added": bq.get("terms_added", []),
                "failed_semantic_neighbour_count": failed.get("semantic_neighbour_count"),
                "baseline_semantic_neighbour_count": baseline.get("semantic_neighbour_count"),
                "failed_exported_cif_count": failed.get("exported_cif_count"),
                "baseline_exported_cif_count": baseline.get("exported_cif_count"),
                "failed_category": failed.get("failure_category"),
                "baseline_category": baseline.get("failure_category"),
                "failed_message": failed.get("failure_message"),
                "baseline_message": baseline.get("failure_message", ""),
                "crystal_db_error_code": raw_error.get("code", ""),
                "crystal_db_error_message": raw_error.get("message", ""),
                "crystal_db_error_diagnostics": raw_error.get("diagnostics", {}),
                "regression_classification": _classify(failed, raw_error),
            }
        )
    return {
        "schema_version": "calibrated_query_regression_audit.v1",
        "failed_root": str(failed_root),
        "baseline_root": str(baseline_root),
        "summary": {
            "failed_cases": len(failed_rows[:5]),
            "baseline_successes": sum(1 for row in baseline_rows.values() if row.get("failure_category") == "success"),
            "failed_failure_categories": dict(Counter(row.get("failure_category") for row in failed_rows[:5])),
            "regression_classifications": dict(Counter(row["regression_classification"] for row in comparisons)),
        },
        "root_cause": (
            "The failed calibrated run did not reach retrieval/export. crystal.csp_pack failed while creating the query "
            "embedding because the LM Studio embeddings endpoint at 127.0.0.1:1234 refused the connection. "
            "The calibrated query was also more validator-oriented than ideal, so query-skill routing should keep "
            "Crystal-DB retrieval terms separate from validator aliases."
        ),
        "comparisons": comparisons,
    }


def _classify(row: Mapping[str, Any], raw_error: Mapping[str, Any]) -> str:
    diagnostics = raw_error.get("diagnostics") if isinstance(raw_error.get("diagnostics"), Mapping) else {}
    if row.get("failure_message") == "query_embedding_failed" or raw_error.get("code") == "query_embedding_failed":
        if "actively refused" in str(diagnostics.get("error", "")):
            return "embedding_backend_unavailable"
        return "query_embedding_failed"
    return "retrieval_or_export_regression"


def write_report(report: Mapping[str, Any], out_dir: Path = REPORT_DIR) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "CALIBRATED_QUERY_REGRESSION_AUDIT.json"
    md_path = out_dir / "CALIBRATED_QUERY_REGRESSION_AUDIT.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Calibrated Query Regression Audit",
        "",
        f"- failed root: {report.get('failed_root')}",
        f"- baseline root: {report.get('baseline_root')}",
        f"- root cause: {report.get('root_cause')}",
        f"- summary: {json.dumps(report.get('summary'), sort_keys=True)}",
        "",
        "## Case Comparisons",
    ]
    for row in report.get("comparisons", []):
        lines.extend(
            [
                "",
                f"### {row.get('case_id')} {row.get('short_name')}",
                f"- classification: {row.get('regression_classification')}",
                f"- failed semantic/exported: {row.get('failed_semantic_neighbour_count')} / {row.get('failed_exported_cif_count')}",
                f"- baseline semantic/exported: {row.get('baseline_semantic_neighbour_count')} / {row.get('baseline_exported_cif_count')}",
                f"- failed message: {row.get('failed_message')}",
                f"- Crystal-DB error: {row.get('crystal_db_error_code')} {row.get('crystal_db_error_diagnostics')}",
                f"- failed query: {row.get('failed_crystal_db_retrieval_query')}",
                f"- baseline query: {row.get('baseline_crystal_db_retrieval_query')}",
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> int:
    print(json.dumps(write_report(build_report()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
