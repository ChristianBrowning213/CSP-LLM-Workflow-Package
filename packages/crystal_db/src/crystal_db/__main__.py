import argparse
import json
import os
import subprocess
import sys
from typing import List, Optional

from .db import connect, init_db
from .describe import describe_structure
from .fingerprint import fingerprint_structure
from .ingest import ingest_sample
from .ingest_folder import ingest_folder
from .query import get_structure, query_structures
from .similarity import similar_structures
from .agent import run_agent
from .phase2 import run_phase2_agent
from .audit_log import fetch_audit_bundle
from .novelty import run_novelty
from .novelty_check import run_novelty_check
from .bench import run_bench
from .export_run import export_run
from .snapshot import snapshot_db
from .propose import propose_candidates
from .report import generate_report
from .calibrate import calibrate_novelty, run_retrieval_calibration
from .crystalcard import build_crystalcard
from .retrieval import similar_text, similar_seq, similar_struct, similar_hybrid, text_search
from .reporting import report_run
from .sequence_index import encode_sequences, embed_sequences
from .text_index import embed_text_docs, embed_texts, generate_text_docs
from .csp_pack import run_csp_pack
from .bench_retrieval import run_bench_retrieval
from .cases_tools import normalize_cases, sample_cases
from .gate import run_gate_retrieval
from .retrieval_config import DEFAULT_RETRIEVAL_DEFAULTS, load_retrieval_defaults, resolve_retrieval_value


def _load_filter(args: argparse.Namespace):
    if args.filter_file:
        with open(args.filter_file, "r", encoding="utf-8") as f:
            return json.load(f)
    if args.filter:
        return json.loads(args.filter)
    return {}


def _load_cif(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _all_structure_ids(db_path: Optional[str]) -> List[str]:
    conn = connect(db_path)
    init_db(conn)
    rows = conn.execute("SELECT structure_id FROM structures ORDER BY structure_id").fetchall()
    conn.close()
    return [row["structure_id"] for row in rows]


def _parse_bool_arg(value: str) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in ("true", "1", "yes", "y"):
        return True
    if normalized in ("false", "0", "no", "n"):
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _truncate_for_pretty(text: str, limit: int = 220) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."


def _render_text_search_pretty(result: dict) -> str:
    query = result.get("query", {})
    lines = [
        f'Query: "{query.get("text", "")}"',
        (
            "Embedding space: "
            f'{query.get("embed_engine", "?")}/{query.get("model_name", "?")}/{query.get("model_version", "?")}'
        ),
    ]
    neighbors = result.get("neighbors", [])
    if not neighbors:
        lines.append("No neighbors found.")
        return "\n".join(lines)

    for item in neighbors:
        rank = item.get("rank", "?")
        sid = item.get("structure_id", "?")
        score = float(item.get("score", 0.0))
        provenance = item.get("provenance") or {}
        source = provenance.get("source") or "?"
        source_id = provenance.get("source_id") or "?"
        allow_export = provenance.get("allow_export")
        if "final_score" in item:
            lines.append(
                f'{rank}. {sid} (final={float(item.get("final_score", score)):.4f}, '
                f'text={float(item.get("text_score", 0.0)):.4f}, fp={float(item.get("fp_score", 0.0)):.4f})'
            )
        else:
            lines.append(f"{rank}. {sid} (score={score:.4f})")
        lines.append(f"   provenance: {source} {source_id} allow_export={allow_export}")

        text_doc = item.get("text_doc")
        if isinstance(text_doc, dict):
            preview = text_doc.get("text")
            if preview:
                lines.append(f'   text: {_truncate_for_pretty(preview)}')
            else:
                lines.append(
                    f'   text: [unavailable] status={text_doc.get("status")} error={text_doc.get("error")}'
                )

        cif_export = item.get("cif_export")
        if isinstance(cif_export, dict):
            status = cif_export.get("status")
            if status == "exported":
                lines.append(f'   cif: exported {cif_export.get("path")}')
            elif status == "blocked":
                lines.append(f'   cif: blocked ({cif_export.get("error")})')
            elif status == "error":
                lines.append(f'   cif: error ({cif_export.get("error")})')
            elif status == "skipped":
                lines.append("   cif: skipped")
    return "\n".join(lines)


def _open_cif_paths(*, paths: List[str], vesta_path: Optional[str]) -> None:
    for path in paths:
        if vesta_path:
            subprocess.run([vesta_path, path], check=False)
            continue
        if sys.platform.startswith("win") and hasattr(os, "startfile"):
            os.startfile(path)  # type: ignore[attr-defined]
            continue
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
            continue
        subprocess.run(["xdg-open", path], check=False)


def _render_agent_pretty(result: dict) -> str:
    lines = [f'run_id: {result.get("run_id")}']
    answer = result.get("answer") or ""
    if answer:
        lines.append(answer)
    cited = result.get("cited_structure_ids") or []
    if cited:
        lines.append("Citations: " + ", ".join(cited))
    return "\n".join(lines)


def _resolve_retrieval_settings(args: argparse.Namespace, fallback: dict) -> dict:
    config = load_retrieval_defaults(getattr(args, "config_path", None))
    config_key_alias = {"model_name": "model"}
    resolved = {}
    for field, default_value in fallback.items():
        config_value = None
        if field in config:
            config_value = config[field]
        elif field in config_key_alias and config_key_alias[field] in config:
            config_value = config[config_key_alias[field]]
        resolved[field] = resolve_retrieval_value(
            field=field,
            explicit_value=getattr(args, field, None),
            config={field: config_value} if config_value is not None or field in config else {},
            fallback_defaults=fallback,
        )
        if resolved[field] is None:
            resolved[field] = default_value
    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="crystal_db")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest synthetic sample data")
    ingest_parser.add_argument("--db", dest="db_path", default=None)
    ingest_parser.add_argument("--count", type=int, default=100)

    ingest_folder_parser = subparsers.add_parser("ingest-folder", help="Ingest CIFs from a folder")
    ingest_folder_parser.add_argument("--db", dest="db_path", default=None)
    ingest_folder_parser.add_argument("--path", dest="folder_path", required=True)
    ingest_folder_parser.add_argument("--source", dest="source", required=True)
    ingest_folder_parser.add_argument("--policy", dest="policy", required=True)
    ingest_folder_parser.add_argument("--cache-dir", dest="cache_dir", default=None)

    query_parser = subparsers.add_parser("query", help="Query structures")
    query_parser.add_argument("--db", dest="db_path", default=None)
    query_parser.add_argument("--filter", dest="filter", default=None)
    query_parser.add_argument("--filter-file", dest="filter_file", default=None)

    get_parser = subparsers.add_parser("get", help="Get a structure by structure_id")
    get_parser.add_argument("--db", dest="db_path", default=None)
    get_parser.add_argument("--id", dest="structure_id", required=True)

    describe_parser = subparsers.add_parser("describe", help="Generate or fetch a descriptor")
    describe_parser.add_argument("--db", dest="db_path", default=None)
    describe_parser.add_argument("--id", dest="structure_id", default=None)
    describe_parser.add_argument("--all", action="store_true")
    describe_parser.add_argument("--cif", dest="cif_path", default=None)

    fingerprint_parser = subparsers.add_parser("fingerprint", help="Generate or fetch a fingerprint")
    fingerprint_parser.add_argument("--db", dest="db_path", default=None)
    fingerprint_parser.add_argument("--id", dest="structure_id", default=None)
    fingerprint_parser.add_argument("--all", action="store_true")
    fingerprint_parser.add_argument("--cif", dest="cif_path", default=None)

    similar_parser = subparsers.add_parser("similar", help="Find similar structures")
    similar_parser.add_argument("--db", dest="db_path", default=None)
    similar_parser.add_argument("--id", dest="structure_id", default=None)
    similar_parser.add_argument("--cif", dest="cif_path", default=None)
    similar_parser.add_argument("--mode", dest="mode", default="fingerprint")
    similar_parser.add_argument("--k", dest="k", type=int, default=10)

    agent_parser = subparsers.add_parser("agent", help="Run the Phase 2 agent")
    agent_parser.add_argument("--db", dest="db_path", default=None)
    agent_parser.add_argument("--query", dest="query", default=None)
    agent_parser.add_argument("--question", dest="question", default=None)
    agent_parser.add_argument("--k", dest="k", type=int, default=10)
    agent_parser.add_argument("--engine", dest="engine", default="auto")
    agent_parser.add_argument("--model", dest="model_name", default=None)
    agent_parser.add_argument("--model-version", dest="model_version", default=None)
    agent_parser.add_argument("--text-engine", dest="text_engine", default="robocrys")
    agent_parser.add_argument("--text-view", dest="text_view", choices=("robocrys", "caption"), default="robocrys")
    agent_parser.add_argument("--hybrid", dest="hybrid", type=_parse_bool_arg, default=False)
    agent_parser.add_argument("--w-text", dest="w_text", type=float, default=1.0)
    agent_parser.add_argument("--w-fp", dest="w_fp", type=float, default=0.0)
    agent_parser.add_argument("--format", dest="format", choices=("json", "pretty"), default="json")
    agent_parser.add_argument("--llm", dest="llm", default="off")
    agent_parser.add_argument("--run-name", dest="run_name", default=None)
    agent_parser.add_argument("--output", dest="output", default="json")

    audit_parser = subparsers.add_parser("audit", help="Fetch audit logs for a run")
    audit_parser.add_argument("--db", dest="db_path", default=None)
    audit_parser.add_argument("--run-id", dest="run_id", required=True)

    novelty_parser = subparsers.add_parser("novelty", help="Run novelty check for a CIF")
    novelty_parser.add_argument("--db", dest="db_path", default=None)
    novelty_parser.add_argument("--cif", dest="cif_path", required=True)
    novelty_parser.add_argument("--threshold", dest="threshold", type=float, default=25.0)
    novelty_parser.add_argument("--k", dest="k", type=int, default=5)
    novelty_parser.add_argument("--run-name", dest="run_name", default=None)

    novelty_check_parser = subparsers.add_parser("novelty-check", help="Run Phase 2 novelty check")
    novelty_check_parser.add_argument("--db", dest="db_path", default=None)
    novelty_check_parser.add_argument("--id", dest="structure_id", default=None)
    novelty_check_parser.add_argument("--cif", dest="cif_path", default=None)
    novelty_check_parser.add_argument("--k", dest="k", type=int, default=5)
    novelty_check_parser.add_argument("--engine", dest="engine", default="auto")
    novelty_check_parser.add_argument("--model", dest="model_name", default=None)
    novelty_check_parser.add_argument("--model-version", dest="model_version", default=None)
    novelty_check_parser.add_argument("--text-engine", dest="text_engine", default="robocrys")
    novelty_check_parser.add_argument("--text-sim-threshold", dest="text_sim_threshold", type=float, default=0.80)
    novelty_check_parser.add_argument("--fp-sim-threshold", dest="fp_sim_threshold", type=float, default=0.95)
    novelty_check_parser.add_argument("--force", dest="force", action="store_true")
    novelty_check_parser.add_argument("--run-name", dest="run_name", default=None)

    bench_parser = subparsers.add_parser("bench", help="Run benchmark suite")
    bench_parser.add_argument("--db", dest="db_path", default=None)
    bench_parser.add_argument("--n-queries", dest="n_queries", type=int, default=None)
    bench_parser.add_argument("--iters", dest="iters", type=int, default=20)
    bench_parser.add_argument("--k", dest="k", type=int, default=5)
    bench_parser.add_argument("--include-novelty", dest="include_novelty", action="store_true")
    bench_parser.add_argument("--skip-novelty", dest="include_novelty", action="store_false")
    bench_parser.set_defaults(include_novelty=False)
    bench_parser.add_argument("--novelty-iters", dest="novelty_iters", type=int, default=3)
    bench_parser.add_argument("--warm", dest="warm_cache", action="store_true")
    bench_parser.add_argument("--cold", dest="warm_cache", action="store_false")
    bench_parser.set_defaults(warm_cache=True)
    bench_parser.add_argument("--timeout-budget-ms", dest="timeout_budget_ms", type=int, default=None)
    bench_parser.add_argument("--profile", dest="profile", action="store_true")
    bench_parser.add_argument("--out", dest="out_path", default=None)

    export_parser = subparsers.add_parser("export-run", help="Export a run bundle")
    export_parser.add_argument("--db", dest="db_path", default=None)
    export_parser.add_argument("--run-id", dest="run_id", required=True)
    export_parser.add_argument("--out", dest="out_path", required=True)

    report_run_parser = subparsers.add_parser("report-run", help="Report Phase 2 run details")
    report_run_parser.add_argument("--db", dest="db_path", default=None)
    report_run_parser.add_argument("--run-id", dest="run_id", required=True)

    snapshot_parser = subparsers.add_parser("snapshot", help="Snapshot the database")
    snapshot_parser.add_argument("--db", dest="db_path", required=True)
    snapshot_parser.add_argument("--out", dest="out_dir", required=True)

    propose_parser = subparsers.add_parser("propose", help="Register CSP candidates")
    propose_parser.add_argument("--db", dest="db_path", default=None)
    propose_parser.add_argument("--run-name", dest="run_name", default=None)
    propose_parser.add_argument("--candidates", dest="candidates_path", required=True)
    propose_parser.add_argument("--source", dest="source", default="csp")

    report_parser = subparsers.add_parser("report", help="Generate Phase 4 report bundle")
    report_parser.add_argument("--db", dest="db_path", default=None)
    report_parser.add_argument("--run-id", dest="run_id", required=True)
    report_parser.add_argument("--out", dest="out_dir", required=True)
    report_parser.add_argument("--k", dest="k", type=int, default=5)
    report_parser.add_argument("--threshold", dest="threshold", type=float, default=25.0)

    calibrate_parser = subparsers.add_parser("calibrate-novelty", help="Calibrate novelty thresholds")
    calibrate_parser.add_argument("--db", dest="db_path", default=None)
    calibrate_parser.add_argument("--k", dest="k", type=int, default=10)
    calibrate_parser.add_argument("--out", dest="out_dir", default=None)

    cases_normalize_parser = subparsers.add_parser("cases-normalize", help="Normalize benchmark JSONL cases deterministically")
    cases_normalize_parser.add_argument("--in", dest="in_path", required=True)
    cases_normalize_parser.add_argument("--out", dest="out_path", required=True)

    cases_sample_parser = subparsers.add_parser("cases-sample", help="Deterministically sample benchmark cases from DB")
    cases_sample_parser.add_argument("--db", dest="db_path", default=None)
    cases_sample_parser.add_argument("--out", dest="out_path", required=True)
    cases_sample_parser.add_argument("--n", dest="n", type=int, default=10)
    cases_sample_parser.add_argument("--text-engine", dest="text_engine", default="caption")
    cases_sample_parser.add_argument("--text-view", dest="text_view", choices=("robocrys", "caption"), default="caption")
    cases_sample_parser.add_argument("--selection-mode", dest="selection_mode", default="hash")
    cases_sample_parser.add_argument("--query-max-chars", dest="query_max_chars", type=int, default=700)
    cases_sample_parser.add_argument("--query-min-sentences", dest="query_min_sentences", type=int, default=2)
    cases_sample_parser.add_argument("--query-max-sentences", dest="query_max_sentences", type=int, default=5)
    cases_sample_parser.add_argument(
        "--query-mode",
        dest="query_mode",
        choices=("semantic", "first_sentences"),
        default="semantic",
    )
    cases_sample_parser.add_argument(
        "--label-mode",
        dest="label_mode",
        choices=("none", "self"),
        default="none",
    )

    calibrate_retrieval_parser = subparsers.add_parser(
        "calibrate-retrieval",
        help="Sweep retrieval thresholds and w_text values (w_fp is computed as 1 - w_text)",
    )
    calibrate_retrieval_parser.add_argument("--db", dest="db_path", default=None)
    calibrate_retrieval_parser.add_argument("--cases", dest="cases_path", required=True)
    calibrate_retrieval_parser.add_argument("--out", dest="out_dir", required=True)
    calibrate_retrieval_parser.add_argument("--k", dest="k", type=int, default=10)
    calibrate_retrieval_parser.add_argument("--engine", dest="engine", default="auto")
    calibrate_retrieval_parser.add_argument("--model", dest="model_name", default=None)
    calibrate_retrieval_parser.add_argument("--model-version", dest="model_version", default=None)
    calibrate_retrieval_parser.add_argument("--text-engine", dest="text_engine", default="caption")
    calibrate_retrieval_parser.add_argument("--text-view", dest="text_view", choices=("robocrys", "caption"), default="caption")
    calibrate_retrieval_parser.add_argument("--hybrid", dest="hybrid", type=_parse_bool_arg, default=True)
    calibrate_retrieval_parser.add_argument("--redacted", dest="redacted", type=_parse_bool_arg, default=True)
    calibrate_retrieval_parser.add_argument("--text-sim-min", dest="text_sim_min", type=float, default=0.60)
    calibrate_retrieval_parser.add_argument("--text-sim-max", dest="text_sim_max", type=float, default=0.95)
    calibrate_retrieval_parser.add_argument("--text-sim-step", dest="text_sim_step", type=float, default=0.05)
    calibrate_retrieval_parser.add_argument("--fp-sim-min", dest="fp_sim_min", type=float, default=0.85)
    calibrate_retrieval_parser.add_argument("--fp-sim-max", dest="fp_sim_max", type=float, default=0.99)
    calibrate_retrieval_parser.add_argument("--fp-sim-step", dest="fp_sim_step", type=float, default=0.02)
    calibrate_retrieval_parser.add_argument(
        "--w-text-values",
        dest="w_text_values",
        default="0.5,0.6,0.7,0.8,0.9",
        help="Comma-separated w_text values in [0,1]. w_fp is computed as (1 - w_text).",
    )
    calibrate_retrieval_parser.add_argument("--max-cases", dest="max_cases", type=int, default=0)
    calibrate_retrieval_parser.add_argument("--progress-every", dest="progress_every", type=int, default=10)
    calibrate_retrieval_parser.add_argument("--cache-candidates", dest="cache_candidates", type=_parse_bool_arg, default=True)
    calibrate_retrieval_parser.add_argument(
        "--reuse-candidates-cache",
        dest="reuse_candidates_cache",
        type=_parse_bool_arg,
        default=True,
    )
    calibrate_retrieval_parser.add_argument("--candidate-cache-path", dest="candidate_cache_path", default=None)
    calibrate_retrieval_parser.add_argument(
        "--preembed-queries",
        dest="preembed_queries",
        type=_parse_bool_arg,
        default=True,
    )
    calibrate_retrieval_parser.add_argument("--run-name", dest="run_name", default=None)

    gate_retrieval_parser = subparsers.add_parser("gate-retrieval", help="Fail on retrieval metric regressions")
    gate_retrieval_parser.add_argument("--db", dest="db_path", default=None)
    gate_retrieval_parser.add_argument("--cases", dest="cases_path", required=True)
    gate_retrieval_parser.add_argument("--out", dest="out_dir", default=None)
    gate_retrieval_parser.add_argument("--k", dest="k", type=int, default=10)
    gate_retrieval_parser.add_argument("--engine", dest="engine", default="auto")
    gate_retrieval_parser.add_argument("--model", dest="model_name", default=None)
    gate_retrieval_parser.add_argument("--model-version", dest="model_version", default=None)
    gate_retrieval_parser.add_argument("--text-engine", dest="text_engine", default="caption")
    gate_retrieval_parser.add_argument("--text-view", dest="text_view", choices=("robocrys", "caption"), default="caption")
    gate_retrieval_parser.add_argument("--hybrid", dest="hybrid", type=_parse_bool_arg, default=True)
    gate_retrieval_parser.add_argument("--w-text", dest="w_text", type=float, default=0.7)
    gate_retrieval_parser.add_argument("--w-fp", dest="w_fp", type=float, default=0.3)
    gate_retrieval_parser.add_argument("--redacted", dest="redacted", type=_parse_bool_arg, default=True)
    gate_retrieval_parser.add_argument("--baseline-summary", dest="baseline_summary_path", default=None)
    gate_retrieval_parser.add_argument("--baseline-delta", dest="baseline_delta", type=float, default=0.0)
    gate_retrieval_parser.add_argument("--min-hit-at-k", dest="min_hit_at_k", type=float, default=None)
    gate_retrieval_parser.add_argument("--min-mrr", dest="min_mrr", type=float, default=None)
    gate_retrieval_parser.add_argument("--min-ndcg-at-k", dest="min_ndcg_at_k", type=float, default=None)
    gate_retrieval_parser.add_argument("--min-coverage", dest="min_coverage", type=float, default=None)
    gate_retrieval_parser.add_argument("--max-failure-rate", dest="max_failure_rate", type=float, default=None)
    gate_retrieval_parser.add_argument("--run-name", dest="run_name", default=None)


    gen_text_parser = subparsers.add_parser("gen-text", help="Generate cached text documents")
    gen_text_parser.add_argument("--db", dest="db_path", default=None)
    gen_text_parser.add_argument("--engine", dest="engine", default="baseline")
    gen_text_parser.add_argument("--text-view", dest="text_view", choices=("robocrys", "caption"), default=None)
    gen_text_parser.add_argument("--limit", dest="limit", type=int, default=None)
    gen_text_parser.add_argument("--batch", dest="batch", type=int, default=32)
    gen_text_parser.add_argument("--progress-every", dest="progress_every", type=int, default=100)
    gen_text_parser.add_argument("--retry-failed", dest="retry_failed", action="store_true")
    gen_text_parser.add_argument("--force", dest="force", action="store_true")
    gen_text_parser.add_argument("--shard-count", dest="shard_count", type=int, default=1)
    gen_text_parser.add_argument("--shard-index", dest="shard_index", type=int, default=0)
    gen_text_parser.add_argument("--snapshot", dest="snapshot_path", default=None)
    gen_text_parser.add_argument("--snapshot-every", dest="snapshot_every", type=int, default=0)
    gen_text_parser.add_argument("--id", dest="structure_id", default=None)

    embed_text_parser = subparsers.add_parser("embed-text", help="Generate text embeddings from cached text")
    embed_text_parser.add_argument("--db", dest="db_path", default=None)
    embed_text_parser.add_argument("--text-engine", dest="text_engine", default=None)
    embed_text_parser.add_argument("--text-view", dest="text_view", choices=("robocrys", "caption"), default=None)
    embed_text_parser.add_argument("--engine", dest="engine", default="auto")
    embed_text_parser.add_argument("--model", dest="model_name", default=None)
    embed_text_parser.add_argument("--model-version", dest="model_version", default=None)
    embed_text_parser.add_argument("--limit", dest="limit", type=int, default=None)
    embed_text_parser.add_argument("--batch", dest="batch", type=int, default=32)
    embed_text_parser.add_argument("--progress-every", dest="progress_every", type=int, default=100)
    embed_text_parser.add_argument("--retry-failed", dest="retry_failed", action="store_true")
    embed_text_parser.add_argument("--force", dest="force", action="store_true")
    embed_text_parser.add_argument("--shard-count", dest="shard_count", type=int, default=1)
    embed_text_parser.add_argument("--shard-index", dest="shard_index", type=int, default=0)
    embed_text_parser.add_argument("--snapshot", dest="snapshot_path", default=None)
    embed_text_parser.add_argument("--snapshot-every", dest="snapshot_every", type=int, default=0)
    embed_text_parser.add_argument("--all", action="store_true")
    embed_text_parser.add_argument("--id", dest="structure_id", default=None)

    similar_text_parser = subparsers.add_parser("similar-text", help="Text embedding similarity")
    similar_text_parser.add_argument("--db", dest="db_path", default=None)
    similar_text_parser.add_argument("--id", dest="structure_id", required=True)
    similar_text_parser.add_argument("--k", dest="k", type=int, default=10)
    similar_text_parser.add_argument("--engine", dest="engine", default="auto", help="Embedding engine")
    similar_text_parser.add_argument("--model", dest="model_name", default=None)
    similar_text_parser.add_argument("--model-version", dest="model_version", default=None)

    text_search_parser = subparsers.add_parser("text-search", help="Free-text search over text embeddings")
    text_search_parser.add_argument("--db", dest="db_path", default=None)
    text_search_parser.add_argument("--query", dest="query_text", required=True)
    text_search_parser.add_argument("--k", dest="k", type=int, default=10)
    text_search_parser.add_argument("--engine", dest="engine", default="auto", help="Embedding engine")
    text_search_parser.add_argument("--model", dest="model_name", default=None)
    text_search_parser.add_argument("--model-version", dest="model_version", default=None)
    text_search_parser.add_argument("--text-engine", dest="text_engine", default="robocrys")
    text_search_parser.add_argument("--text-view", dest="text_view", choices=("robocrys", "caption"), default="robocrys")
    text_search_parser.add_argument("--hybrid", dest="hybrid", type=_parse_bool_arg, default=False)
    text_search_parser.add_argument("--w-text", dest="w_text", type=float, default=1.0)
    text_search_parser.add_argument("--w-fp", dest="w_fp", type=float, default=0.0)
    text_search_parser.add_argument("--show-text-top", dest="show_text_top", type=int, default=3)
    text_search_parser.add_argument("--export-cifs", dest="export_cifs", default=None)
    text_search_parser.add_argument("--export-top", dest="export_top", type=int, default=None)
    text_search_parser.add_argument("--redacted", dest="redacted", type=_parse_bool_arg, default=True)
    text_search_parser.add_argument("--demo-export", dest="demo_export", action="store_true")
    text_search_parser.add_argument("--format", dest="output_format", choices=("json", "pretty"), default="json")
    text_search_parser.add_argument("--open-cifs", dest="open_cifs", action="store_true")
    text_search_parser.add_argument("--vesta", dest="vesta_path", default=None)

    csp_pack_parser = subparsers.add_parser("csp-pack", help="Build CSP-facing retrieval package")
    csp_pack_parser.add_argument("--db", dest="db_path", default=None)
    csp_pack_parser.add_argument("--query", dest="query_text", default=None)
    csp_pack_parser.add_argument("--id", dest="structure_id", default=None)
    csp_pack_parser.add_argument("--k", dest="k", type=int, default=None)
    csp_pack_parser.add_argument("--engine", dest="engine", default=None, help="Embedding engine")
    csp_pack_parser.add_argument("--model", dest="model_name", default=None)
    csp_pack_parser.add_argument("--model-version", dest="model_version", default=None)
    csp_pack_parser.add_argument("--text-engine", dest="text_engine", default=None)
    csp_pack_parser.add_argument("--text-view", dest="text_view", choices=("robocrys", "caption"), default=None)
    csp_pack_parser.add_argument("--hybrid", dest="hybrid", type=_parse_bool_arg, default=None)
    csp_pack_parser.add_argument("--w-text", dest="w_text", type=float, default=None)
    csp_pack_parser.add_argument("--w-fp", dest="w_fp", type=float, default=None)
    csp_pack_parser.add_argument("--out", dest="out_dir", default=None)
    csp_pack_parser.add_argument("--export-top", dest="export_top", type=int, default=None)
    csp_pack_parser.add_argument("--redacted", dest="redacted", type=_parse_bool_arg, default=None)
    csp_pack_parser.add_argument("--demo-export", dest="demo_export", type=_parse_bool_arg, default=None)
    csp_pack_parser.add_argument("--material-system", dest="material_system", default=None)
    csp_pack_parser.add_argument("--formula", dest="formula", default=None)
    csp_pack_parser.add_argument("--semantic-min-threshold", dest="semantic_min_threshold", type=float, default=None)
    csp_pack_parser.add_argument("--config", dest="config_path", default=None)
    csp_pack_parser.add_argument("--run-name", dest="run_name", default=None)

    bench_retrieval_parser = subparsers.add_parser("bench-retrieval", help="Benchmark retrieval quality on JSONL cases")
    bench_retrieval_parser.add_argument("--db", dest="db_path", default=None)
    bench_retrieval_parser.add_argument("--cases", dest="cases_path", required=True)
    bench_retrieval_parser.add_argument("--k", dest="k", type=int, default=None)
    bench_retrieval_parser.add_argument("--engine", dest="engine", default=None)
    bench_retrieval_parser.add_argument("--model", dest="model_name", default=None)
    bench_retrieval_parser.add_argument("--model-version", dest="model_version", default=None)
    bench_retrieval_parser.add_argument("--text-engine", dest="text_engine", default=None)
    bench_retrieval_parser.add_argument("--text-view", dest="text_view", choices=("robocrys", "caption"), default=None)
    bench_retrieval_parser.add_argument("--hybrid", dest="hybrid", type=_parse_bool_arg, default=None)
    bench_retrieval_parser.add_argument("--w-text", dest="w_text", type=float, default=None)
    bench_retrieval_parser.add_argument("--w-fp", dest="w_fp", type=float, default=None)
    bench_retrieval_parser.add_argument("--redacted", dest="redacted", type=_parse_bool_arg, default=None)
    bench_retrieval_parser.add_argument("--text-sim-threshold", dest="text_sim_threshold", type=float, default=None)
    bench_retrieval_parser.add_argument("--fp-sim-threshold", dest="fp_sim_threshold", type=float, default=None)
    bench_retrieval_parser.add_argument("--max-cases", dest="max_cases", type=int, default=0)
    bench_retrieval_parser.add_argument("--config", dest="config_path", default=None)
    bench_retrieval_parser.add_argument("--out", dest="out_dir", default=None)
    bench_retrieval_parser.add_argument("--run-name", dest="run_name", default=None)

    similar_struct_parser = subparsers.add_parser("similar-struct", help="Structure embedding similarity")
    similar_struct_parser.add_argument("--db", dest="db_path", default=None)
    similar_struct_parser.add_argument("--id", dest="structure_id", required=True)
    similar_struct_parser.add_argument("--method", dest="method", default="fp.simple.v1")
    similar_struct_parser.add_argument("--k", dest="k", type=int, default=10)

    encode_seq_parser = subparsers.add_parser("encode-seq", help="Encode sequences")
    encode_seq_parser.add_argument("--db", dest="db_path", default=None)
    encode_seq_parser.add_argument("--format", dest="format", default="cif_canon")
    encode_seq_parser.add_argument("--all", action="store_true")
    encode_seq_parser.add_argument("--id", dest="structure_id", default=None)

    embed_seq_parser = subparsers.add_parser("embed-seq", help="Embed sequences")
    embed_seq_parser.add_argument("--db", dest="db_path", default=None)
    embed_seq_parser.add_argument("--format", dest="format", default="cif_canon")
    embed_seq_parser.add_argument("--model", dest="model_name", default=None)
    embed_seq_parser.add_argument("--model-version", dest="model_version", default=None)
    embed_seq_parser.add_argument("--all", action="store_true")
    embed_seq_parser.add_argument("--id", dest="structure_id", default=None)

    similar_seq_parser = subparsers.add_parser("similar-seq", help="Sequence embedding similarity")
    similar_seq_parser.add_argument("--db", dest="db_path", default=None)
    similar_seq_parser.add_argument("--id", dest="structure_id", required=True)
    similar_seq_parser.add_argument("--k", dest="k", type=int, default=10)
    similar_seq_parser.add_argument("--format", dest="format", default="cif_canon")
    similar_seq_parser.add_argument("--model", dest="model_name", default=None)
    similar_seq_parser.add_argument("--model-version", dest="model_version", default=None)

    hybrid_parser = subparsers.add_parser("similar-hybrid", help="Hybrid similarity (fusion)")
    hybrid_parser.add_argument("--db", dest="db_path", default=None)
    hybrid_parser.add_argument("--id", dest="structure_id", required=True)
    hybrid_parser.add_argument("--k", dest="k", type=int, default=10)
    hybrid_parser.add_argument("--alpha", dest="alpha", type=float, default=0.5)
    hybrid_parser.add_argument("--beta", dest="beta", type=float, default=0.5)
    hybrid_parser.add_argument("--gamma", dest="gamma", type=float, default=1.0)
    hybrid_parser.add_argument("--sources", dest="sources", default="text,struct,seq")
    crystalcard_parser = subparsers.add_parser("crystalcard", help="Generate CrystalCard semantics")
    crystalcard_parser.add_argument("--db", dest="db_path", default=None)
    crystalcard_parser.add_argument("--id", dest="structure_id", default=None)
    crystalcard_parser.add_argument("--all", action="store_true")
    crystalcard_parser.add_argument("--engine", dest="engine", default="baseline")

    args = parser.parse_args(argv)

    if args.command == "ingest":
        ids = ingest_sample(db_path=args.db_path, count=args.count)
        print(json.dumps({"ingested": len(ids)}, indent=2))
        return 0

    if args.command == "ingest-folder":
        result = ingest_folder(
            db_path=args.db_path,
            folder_path=args.folder_path,
            source=args.source,
            policy_name=args.policy,
            cache_dir=args.cache_dir,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "query":
        filter_spec = _load_filter(args)
        result = query_structures(filter_spec, db_path=args.db_path)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "get":
        result = get_structure(args.structure_id, db_path=args.db_path)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "describe":
        if args.all:
            results = []
            for sid in _all_structure_ids(args.db_path):
                results.append(describe_structure(structure_id=sid, db_path=args.db_path, store=True))
            print(json.dumps({"processed": len(results), "results": results}, indent=2))
            return 0
        if args.cif_path:
            cif_text = _load_cif(args.cif_path)
            result = describe_structure(cif_text=cif_text, store=False)
            print(json.dumps(result, indent=2))
            return 0
        if args.structure_id:
            result = describe_structure(structure_id=args.structure_id, db_path=args.db_path, store=True)
            print(json.dumps(result, indent=2))
            return 0
        print("describe requires --id, --cif, or --all", file=sys.stderr)
        return 2

    if args.command == "fingerprint":
        if args.all:
            results = []
            for sid in _all_structure_ids(args.db_path):
                results.append(fingerprint_structure(structure_id=sid, db_path=args.db_path, store=True))
            print(json.dumps({"processed": len(results), "results": results}, indent=2))
            return 0
        if args.cif_path:
            cif_text = _load_cif(args.cif_path)
            result = fingerprint_structure(cif_text=cif_text, store=False)
            print(json.dumps(result, indent=2))
            return 0
        if args.structure_id:
            result = fingerprint_structure(structure_id=args.structure_id, db_path=args.db_path, store=True)
            print(json.dumps(result, indent=2))
            return 0
        print("fingerprint requires --id, --cif, or --all", file=sys.stderr)
        return 2

    if args.command == "similar":
        if not args.structure_id and not args.cif_path:
            print("similar requires --id or --cif", file=sys.stderr)
            return 2
        cif_text = _load_cif(args.cif_path) if args.cif_path else None
        result = similar_structures(
            structure_id=args.structure_id,
            cif_text=cif_text,
            mode=args.mode,
            k=args.k,
            db_path=args.db_path,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "agent":
        query_text = args.query or args.question
        if not query_text:
            print(
                json.dumps(
                    {"error": "missing_query", "message": "agent requires --query (or legacy --question)"},
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
        try:
            result = run_phase2_agent(
                query=query_text,
                db_path=args.db_path,
                k=args.k,
                embed_engine=args.engine,
                model_name=args.model_name,
                model_version=args.model_version,
                text_engine=args.text_engine,
                text_view=args.text_view,
                hybrid=args.hybrid,
                w_text=args.w_text,
                w_fp=args.w_fp,
                run_name=args.run_name,
            )
        except Exception as exc:  # pylint: disable=broad-except
            print(json.dumps({"error": "agent_failed", "message": str(exc)}, indent=2), file=sys.stderr)
            return 1
        if result.get("errors") is not None:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        if args.format == "pretty":
            print(_render_agent_pretty(result))
        else:
            print(json.dumps(result, indent=2))
        return 0

    if args.command == "audit":
        result = fetch_audit_bundle(args.run_id, db_path=args.db_path)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "novelty":
        result = run_novelty(
            cif_path=args.cif_path,
            db_path=args.db_path,
            threshold=args.threshold,
            k=args.k,
            run_name=args.run_name,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "novelty-check":
        try:
            result = run_novelty_check(
                db_path=args.db_path,
                structure_id=args.structure_id,
                cif_path=args.cif_path,
                k=args.k,
                embed_engine=args.engine,
                model_name=args.model_name,
                model_version=args.model_version,
                text_engine=args.text_engine,
                text_sim_threshold=args.text_sim_threshold,
                fp_sim_threshold=args.fp_sim_threshold,
                force=args.force,
                run_name=args.run_name,
            )
        except Exception as exc:  # pylint: disable=broad-except
            print(json.dumps({"error": "novelty_check_failed", "message": str(exc)}, indent=2), file=sys.stderr)
            return 1
        if result.get("errors") is not None:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "bench":
        iters = args.iters if args.n_queries is None else args.n_queries
        report = run_bench(
            args.db_path,
            iters=iters,
            k=args.k,
            include_novelty=args.include_novelty,
            novelty_iters=args.novelty_iters,
            warm_cache=args.warm_cache,
            timeout_budget_ms=args.timeout_budget_ms,
            profile=args.profile,
        )
        if args.out_path:
            with open(args.out_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "export-run":
        out_path = export_run(db_path=args.db_path, run_id=args.run_id, out_path=args.out_path)
        print(json.dumps({"exported": out_path}, indent=2))
        return 0

    if args.command == "report-run":
        result = report_run(run_id=args.run_id, db_path=args.db_path)
        if "error" in result:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "snapshot":
        target_dir = snapshot_db(db_path=args.db_path, out_dir=args.out_dir)
        print(json.dumps({"snapshot_dir": target_dir}, indent=2))
        return 0

    if args.command == "propose":
        result = propose_candidates(
            db_path=args.db_path,
            run_name=args.run_name,
            candidates_path=args.candidates_path,
            source=args.source,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "report":
        result = generate_report(
            db_path=args.db_path,
            run_id=args.run_id,
            out_dir=args.out_dir,
            k=args.k,
            threshold=args.threshold,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "calibrate-novelty":
        result = calibrate_novelty(
            db_path=args.db_path,
            k=args.k,
            out_dir=args.out_dir,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "cases-normalize":
        result = normalize_cases(in_path=args.in_path, out_path=args.out_path)
        if result.get("errors") is not None:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "cases-sample":
        result = sample_cases(
            db_path=args.db_path,
            out_path=args.out_path,
            n=args.n,
            text_view=args.text_view,
            text_engine=args.text_engine,
            selection_mode=args.selection_mode,
            query_max_chars=args.query_max_chars,
            query_min_sentences=args.query_min_sentences,
            query_max_sentences=args.query_max_sentences,
            query_mode=args.query_mode,
            label_mode=args.label_mode,
        )
        if result.get("errors") is not None:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "calibrate-retrieval":
        try:
            weights = [
                float(item.strip())
                for item in str(args.w_text_values or "").split(",")
                if item.strip()
            ]
            result = run_retrieval_calibration(
                db_path=args.db_path,
                cases_path=args.cases_path,
                out_dir=args.out_dir,
                k=args.k,
                embed_engine=args.engine,
                model_name=args.model_name,
                model_version=args.model_version,
                text_engine=args.text_engine,
                text_view=args.text_view,
                hybrid=args.hybrid,
                redacted=args.redacted,
                text_sim_min=args.text_sim_min,
                text_sim_max=args.text_sim_max,
                text_sim_step=args.text_sim_step,
                fp_sim_min=args.fp_sim_min,
                fp_sim_max=args.fp_sim_max,
                fp_sim_step=args.fp_sim_step,
                w_text_values=weights,
                run_name=args.run_name,
                preembed_queries=args.preembed_queries,
                max_cases=args.max_cases,
                progress_every=args.progress_every,
                cache_candidates=args.cache_candidates,
                reuse_candidates_cache=args.reuse_candidates_cache,
                candidate_cache_path=args.candidate_cache_path,
            )
        except ValueError as exc:
            print(json.dumps({"error": "invalid_arguments", "message": str(exc), "command": "calibrate-retrieval"}, indent=2), file=sys.stderr)
            return 1
        if result.get("errors") is not None:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "gate-retrieval":
        result = run_gate_retrieval(
            db_path=args.db_path,
            cases_path=args.cases_path,
            k=args.k,
            embed_engine=args.engine,
            model_name=args.model_name,
            model_version=args.model_version,
            text_engine=args.text_engine,
            text_view=args.text_view,
            hybrid=args.hybrid,
            w_text=args.w_text,
            w_fp=args.w_fp,
            redacted=args.redacted,
            out_dir=args.out_dir,
            baseline_summary_path=args.baseline_summary_path,
            min_hit_at_k=args.min_hit_at_k,
            min_mrr=args.min_mrr,
            min_ndcg_at_k=args.min_ndcg_at_k,
            min_coverage=args.min_coverage,
            max_failure_rate=args.max_failure_rate,
            baseline_delta=args.baseline_delta,
            run_name=args.run_name,
        )
        if result.get("errors") is not None:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        if not result.get("ok", False):
            print(
                json.dumps(
                    {
                        "error_code": "RETRIEVAL_REGRESSION",
                        "baseline": result.get("baseline"),
                        "current": result.get("current"),
                        "diff": result.get("diff"),
                        "thresholds": result.get("thresholds"),
                        "reasons": result.get("reasons"),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 2
        print(json.dumps(result, indent=2))
        return 0


    if args.command == "gen-text":
        structure_ids = [args.structure_id] if args.structure_id else None
        try:
            result = generate_text_docs(
                db_path=args.db_path,
                engine=args.engine,
                text_view=args.text_view,
                structure_ids=structure_ids,
                limit=args.limit,
                batch=args.batch,
                progress_every=args.progress_every,
                retry_failed=args.retry_failed,
                force=args.force,
                shard_count=args.shard_count,
                shard_index=args.shard_index,
                snapshot_path=args.snapshot_path,
                snapshot_every=args.snapshot_every,
            )
        except ValueError as exc:
            print(
                json.dumps({"error": "invalid_arguments", "message": str(exc), "command": "gen-text"}, indent=2),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "embed-text":
        model_name = args.model_name
        model_version = args.model_version
        structure_ids = [args.structure_id] if args.structure_id else None
        try:
            legacy_text_engine = args.text_engine is None and args.engine in ("baseline", "robocrys")
            if legacy_text_engine:
                text_engine = args.engine
                embed_engine = "auto"
                print(
                    "warning: legacy mode detected (`embed-text --engine <text-engine>`). "
                    "Use `gen-text` + `embed-text --text-engine ... --engine ...` for explicit stage control.",
                    file=sys.stderr,
                )
                result = embed_texts(
                    db_path=args.db_path,
                    engine=text_engine,
                    model_name=model_name,
                    model_version=model_version,
                    text_view=args.text_view,
                    structure_ids=structure_ids,
                    limit=args.limit,
                    batch=args.batch,
                    progress_every=args.progress_every,
                    retry_failed=args.retry_failed,
                    force=args.force,
                    embed_engine=embed_engine,
                    shard_count=args.shard_count,
                    shard_index=args.shard_index,
                    snapshot_path=args.snapshot_path,
                    snapshot_every=args.snapshot_every,
                )
            else:
                text_engine = args.text_engine or "baseline"
                result = embed_text_docs(
                    db_path=args.db_path,
                    text_engine=text_engine,
                    text_view=args.text_view,
                    embed_engine=args.engine,
                    model_name=model_name,
                    model_version=model_version,
                    structure_ids=structure_ids,
                    limit=args.limit,
                    batch=args.batch,
                    progress_every=args.progress_every,
                    retry_failed=args.retry_failed,
                    force=args.force,
                    shard_count=args.shard_count,
                    shard_index=args.shard_index,
                    snapshot_path=args.snapshot_path,
                    snapshot_every=args.snapshot_every,
                )
        except ValueError as exc:
            print(
                json.dumps({"error": "invalid_arguments", "message": str(exc), "command": "embed-text"}, indent=2),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "similar-text":
        model_name = args.model_name
        model_version = args.model_version
        result = similar_text(
            structure_id=args.structure_id,
            db_path=args.db_path,
            k=args.k,
            engine=args.engine,
            model_name=model_name,
            model_version=model_version,
        )
        if "error" in result:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "text-search":
        result = text_search(
            query_text=args.query_text,
            db_path=args.db_path,
            k=args.k,
            embed_engine=args.engine,
            model_name=args.model_name,
            model_version=args.model_version,
            text_engine=args.text_engine,
            text_view=args.text_view,
            hybrid=args.hybrid,
            w_text=args.w_text,
            w_fp=args.w_fp,
            show_text_top=args.show_text_top,
            export_dir=args.export_cifs,
            export_top=args.export_top,
            redacted=args.redacted,
            demo_export=args.demo_export,
        )
        if result.get("errors") is not None:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        if args.output_format == "pretty":
            print(_render_text_search_pretty(result))
        else:
            print(json.dumps(result, indent=2))
        if args.open_cifs:
            open_limit = args.export_top if args.export_top is not None else args.show_text_top
            if open_limit > 0:
                exported_paths: List[str] = []
                for neighbor in result.get("neighbors", []):
                    cif_export = neighbor.get("cif_export") or {}
                    if cif_export.get("status") == "exported":
                        path = cif_export.get("path")
                        if path:
                            exported_paths.append(path)
                    if len(exported_paths) >= open_limit:
                        break
                _open_cif_paths(paths=exported_paths, vesta_path=args.vesta_path)
        return 0

    if args.command == "csp-pack":
        try:
            resolved = _resolve_retrieval_settings(
                args,
                {
                    "k": 10,
                    "engine": DEFAULT_RETRIEVAL_DEFAULTS["engine"],
                    "model_name": DEFAULT_RETRIEVAL_DEFAULTS["model"],
                    "model_version": DEFAULT_RETRIEVAL_DEFAULTS["model_version"],
                    "text_engine": DEFAULT_RETRIEVAL_DEFAULTS["text_engine"],
                    "text_view": DEFAULT_RETRIEVAL_DEFAULTS["text_view"],
                    "hybrid": DEFAULT_RETRIEVAL_DEFAULTS["hybrid"],
                    "w_text": DEFAULT_RETRIEVAL_DEFAULTS["w_text"],
                    "w_fp": DEFAULT_RETRIEVAL_DEFAULTS["w_fp"],
                    "redacted": DEFAULT_RETRIEVAL_DEFAULTS["redacted"],
                    "demo_export": False,
                },
            )
        except ValueError as exc:
            print(json.dumps({"error": "invalid_config", "message": str(exc), "command": "csp-pack"}, indent=2), file=sys.stderr)
            return 1
        result = run_csp_pack(
            db_path=args.db_path,
            query_text=args.query_text,
            structure_id=args.structure_id,
            k=resolved["k"],
            embed_engine=resolved["engine"],
            model_name=resolved["model_name"],
            model_version=resolved["model_version"],
            text_engine=resolved["text_engine"],
            text_view=resolved["text_view"],
            hybrid=resolved["hybrid"],
            w_text=resolved["w_text"],
            w_fp=resolved["w_fp"],
            out_dir=args.out_dir,
            export_top=args.export_top,
            redacted=resolved["redacted"],
            demo_export=resolved["demo_export"],
            run_name=args.run_name,
            material_system=args.material_system,
            formula=args.formula,
            semantic_min_threshold=args.semantic_min_threshold,
        )
        if result.get("errors") is not None:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "bench-retrieval":
        try:
            resolved = _resolve_retrieval_settings(
                args,
                {
                    "k": 10,
                    "engine": DEFAULT_RETRIEVAL_DEFAULTS["engine"],
                    "model_name": DEFAULT_RETRIEVAL_DEFAULTS["model"],
                    "model_version": DEFAULT_RETRIEVAL_DEFAULTS["model_version"],
                    "text_engine": DEFAULT_RETRIEVAL_DEFAULTS["text_engine"],
                    "text_view": DEFAULT_RETRIEVAL_DEFAULTS["text_view"],
                    "hybrid": DEFAULT_RETRIEVAL_DEFAULTS["hybrid"],
                    "w_text": DEFAULT_RETRIEVAL_DEFAULTS["w_text"],
                    "w_fp": DEFAULT_RETRIEVAL_DEFAULTS["w_fp"],
                    "redacted": DEFAULT_RETRIEVAL_DEFAULTS["redacted"],
                    "text_sim_threshold": None,
                    "fp_sim_threshold": None,
                },
            )
        except ValueError as exc:
            print(json.dumps({"error": "invalid_config", "message": str(exc), "command": "bench-retrieval"}, indent=2), file=sys.stderr)
            return 1
        result = run_bench_retrieval(
            db_path=args.db_path,
            cases_path=args.cases_path,
            k=resolved["k"],
            embed_engine=resolved["engine"],
            model_name=resolved["model_name"],
            model_version=resolved["model_version"],
            text_engine=resolved["text_engine"],
            text_view=resolved["text_view"],
            hybrid=resolved["hybrid"],
            w_text=resolved["w_text"],
            w_fp=resolved["w_fp"],
            text_sim_threshold=resolved["text_sim_threshold"],
            fp_sim_threshold=resolved["fp_sim_threshold"],
            redacted=resolved["redacted"],
            out_dir=args.out_dir,
            run_name=args.run_name,
            max_cases=args.max_cases,
        )
        if result.get("errors") is not None:
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "similar-struct":
        result = similar_struct(
            structure_id=args.structure_id,
            db_path=args.db_path,
            method=args.method,
            k=args.k,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "encode-seq":
        structure_ids = [args.structure_id] if args.structure_id else None
        result = encode_sequences(db_path=args.db_path, format=args.format, structure_ids=structure_ids)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "embed-seq":
        structure_ids = [args.structure_id] if args.structure_id else None
        result = embed_sequences(
            db_path=args.db_path,
            format=args.format,
            model_name=args.model_name,
            model_version=args.model_version,
            structure_ids=structure_ids,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "similar-seq":
        result = similar_seq(
            structure_id=args.structure_id,
            db_path=args.db_path,
            k=args.k,
            format=args.format,
            model_name=args.model_name,
            model_version=args.model_version,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "similar-hybrid":
        sources = [item.strip() for item in (args.sources or "").split(",") if item.strip()]
        result = similar_hybrid(
            structure_id=args.structure_id,
            db_path=args.db_path,
            k=args.k,
            sources=sources,
            alpha=args.alpha,
            beta=args.beta,
            gamma=args.gamma,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "crystalcard":
        if args.all:
            results = []
            for sid in _all_structure_ids(args.db_path):
                results.append(
                    build_crystalcard(structure_id=sid, db_path=args.db_path, engine=args.engine, store=True)
                )
            print(json.dumps({"processed": len(results), "results": results}, indent=2))
            return 0
        if args.structure_id:
            result = build_crystalcard(
                structure_id=args.structure_id,
                db_path=args.db_path,
                engine=args.engine,
                store=True,
            )
            print(json.dumps(result, indent=2))
            return 0
        print("crystalcard requires --id or --all", file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
