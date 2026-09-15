"""Build or approve a non-destructive timestamped LLM-CSP figure package."""

from __future__ import annotations

import argparse
from pathlib import Path

from sok_llm_orchestrator.workflow.timestamped_figure_package import (
    ROOT,
    approve_package_visual_qa,
    build_timestamped_package,
    timestamped_output_root,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New package root; omitted creates the required timestamped name")
    parser.add_argument("--approve-visual-qa", action="store_true")
    parser.add_argument("--master", type=Path, default=ROOT / "artifacts" / "final_paper_results" / "MASTER_RESULTS.csv")
    parser.add_argument("--table-root", type=Path, default=ROOT / "artifacts" / "final_paper_results" / "table_run")
    parser.add_argument("--prior-figures", type=Path, default=ROOT / "artifacts" / "final_paper_results" / "figures")
    parser.add_argument("--vesta-path")
    args = parser.parse_args()
    if args.approve_visual_qa:
        if args.output is None:
            parser.error("--approve-visual-qa requires --output")
        approve_package_visual_qa(args.output)
        print(f"approved visual QA: {args.output.resolve()}")
        return 0
    output = args.output.resolve() if args.output else timestamped_output_root().resolve()
    build_timestamped_package(
        output, master_path=args.master.resolve(), source_table_root=args.table_root.resolve(),
        prior_figures_root=args.prior_figures.resolve(), vesta_path=args.vesta_path,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
