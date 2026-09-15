"""Dataset C driver for Paper_scaffolds_september.

Runs the frozen csv_workflow_v1 scientific method (identical retrieval, SPP
contract, corrected QLIP objective, solver settings) but engages the reusable
family topology scaffold from ``paper_scaffolds_library`` for every row. This is
the paired counterpart of Dataset B: same request, same specialist corpus, same
request-conditioned SPP; the only intervention is the higher-order scaffold.

It reuses ``sok_llm_orchestrator.workflow.csv_workflow`` end to end (row-bundle
layout, manifest, preflight, exactly-once guards, separate SCA stage) via a
narrow config wrapper that flips ``scaffold_mode`` on for supported families.

Usage:
    python scripts/run_paper_scaffolds_c.py --input DATASET_C.csv --output outputs/.../dataset_C [--dry-run|--preflight-only|--resume]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from sok_llm_orchestrator.workflow import csv_workflow as cw  # noqa: E402
from sok_llm_orchestrator.workflow.component_paths import ComponentRoots  # noqa: E402
from sok_llm_orchestrator.workflow.paper_scaffolds_library import resolve_policy  # noqa: E402

SCAFFOLD_MODE = "loose"  # cation orbits accept every target cation (real QLIP DOF)

_ORIGINAL_WORKFLOW_CONFIG = cw._workflow_config


def _scaffold_workflow_config(row, row_root, roots):
    config = _ORIGINAL_WORKFLOW_CONFIG(row, row_root, roots)
    family = str(row.structured_task.get("family") or "")
    if resolve_policy(family) is None:
        raise cw.CsvWorkflowError(
            f"row {row.row_id}: family {family!r} has no reusable scaffold in paper_scaffolds_library"
        )
    return replace(
        config,
        native_qlip=False,
        scaffold_mode=SCAFFOLD_MODE,
        scaffold_dir=None,
        cell_mode="native",
        native_grid_density=None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rows", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--retry-technical-failures", action="store_true")
    args = parser.parse_args(argv)

    roots = ComponentRoots.load(_REPO)
    cw._workflow_config = _scaffold_workflow_config  # noqa: SLF001 - deliberate experiment wrapper
    try:
        result = cw.generate_batch(
            input_path=args.input.resolve(),
            output_root=args.output.resolve(),
            roots=roots,
            rows=[value for value in (args.rows.split(",") if args.rows else []) if value] or None,
            dry_run=bool(args.dry_run),
            preflight_only=bool(args.preflight_only),
            resume=bool(args.resume),
            fail_fast=bool(args.fail_fast),
            retry_technical_failures=bool(args.retry_technical_failures),
        )
    finally:
        cw._workflow_config = _ORIGINAL_WORKFLOW_CONFIG
    import json

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
