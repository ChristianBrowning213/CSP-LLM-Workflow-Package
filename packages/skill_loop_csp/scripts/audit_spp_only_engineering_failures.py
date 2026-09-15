"""Audit the preliminary SPP-only 100 using real periodic pair diagnostics."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sok_llm_orchestrator.workflow.spp_only_failure_audit import audit_engineering_results  # noqa: E402


def main() -> int:
    crystal_root = REPO_ROOT.parent / "Crystal-DB"
    benchmark_root = crystal_root / "artifacts" / "spp_only_oxide_benchmark_v1"
    rows = audit_engineering_results(
        results_root=benchmark_root / "results", crystal_root=crystal_root,
        output_csv=benchmark_root / "SPP_ONLY_100_ENGINEERING_FAILURE_AUDIT.csv",
        output_md=benchmark_root / "SPP_ONLY_100_ENGINEERING_FAILURE_AUDIT.md",
    )
    print(json.dumps({"row_count": len(rows), "first_blockers": Counter(row["first_blocker"] for row in rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
