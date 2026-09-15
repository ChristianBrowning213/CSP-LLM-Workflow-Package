"""Assemble final paper figures from approved generic row figures."""

from __future__ import annotations

import argparse
from pathlib import Path

from sok_llm_orchestrator.workflow.paper_figures import approve_paper_visual_qa, build_paper_figures


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build final paper figures from row artifacts")
    parser.add_argument("--master", type=Path, default=ROOT / "artifacts" / "final_paper_results" / "MASTER_RESULTS.csv")
    parser.add_argument("--table-root", type=Path, default=ROOT / "artifacts" / "final_paper_results" / "table_run")
    parser.add_argument("--figures-root", type=Path, default=ROOT / "artifacts" / "final_paper_results" / "figures")
    parser.add_argument("--approve-visual-qa", action="store_true")
    args = parser.parse_args()
    if args.approve_visual_qa:
        approve_paper_visual_qa(args.figures_root.resolve())
        print("approved paper-figure visual QA")
    else:
        records = build_paper_figures(args.master.resolve(), args.table_root.resolve(), args.figures_root.resolve())
        print(f"built {len(records)} final paper figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
