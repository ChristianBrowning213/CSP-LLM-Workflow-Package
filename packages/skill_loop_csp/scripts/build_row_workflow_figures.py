"""Build generic per-row workflow figures from a row-results directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from sok_llm_orchestrator.workflow.row_visualization import (
    approve_visual_qa,
    build_row_workflow_figures,
)


ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Render truthful VESTA/POT workflow figures for successful result rows")
    value.add_argument("--master", type=Path, default=ROOT / "artifacts" / "final_paper_results" / "MASTER_RESULTS.csv")
    value.add_argument("--table-root", type=Path, default=ROOT / "artifacts" / "final_paper_results" / "table_run")
    value.add_argument("--figures-root", type=Path, default=ROOT / "artifacts" / "final_paper_results" / "figures")
    value.add_argument("--only", action="append", default=[])
    value.add_argument("--top-k", type=int, default=4)
    value.add_argument("--vesta-path")
    value.add_argument("--approve-visual-qa", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    if args.approve_visual_qa:
        approve_visual_qa(args.figures_root.resolve(), args.table_root.resolve())
        print(f"approved visual QA records in {args.figures_root.resolve()}")
        return 0
    records = build_row_workflow_figures(
        args.master.resolve(), args.table_root.resolve(), args.figures_root.resolve(),
        only=args.only, top_k=args.top_k, vesta_path=args.vesta_path,
    )
    print(f"built {len(records)} row workflow figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
