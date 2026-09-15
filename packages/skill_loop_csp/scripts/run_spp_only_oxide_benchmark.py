"""Run the frozen 50+50 scaffold-free oxide benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sok_llm_orchestrator.workflow.spp_only_benchmark import (  # noqa: E402
    SPPOnlyBenchmarkPolicy,
    run_spp_only_benchmark,
)


def main() -> int:
    crystal_root = REPO_ROOT.parent / "Crystal-DB"
    default_root = crystal_root / "artifacts" / "spp_only_oxide_benchmark_v1"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, default=default_root / "frozen_benchmark.json")
    parser.add_argument("--crystal-root", type=Path, default=crystal_root)
    parser.add_argument("--output-root", type=Path, default=default_root / "results")
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--spp-corpus-size", type=int, default=30)
    parser.add_argument("--max-new-targets", type=int)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    rows = run_spp_only_benchmark(
        frozen_path=args.frozen, crystal_root=args.crystal_root, output_root=args.output_root,
        policy=SPPOnlyBenchmarkPolicy(candidate_retrieval_depth=args.candidate_k, spp_corpus_size=args.spp_corpus_size),
        resume=not args.no_resume,
        max_new_targets=args.max_new_targets,
    )
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row["final_classification"])
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({"row_count": len(rows), "terminal_classifications": counts, "output_root": str(args.output_root.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
