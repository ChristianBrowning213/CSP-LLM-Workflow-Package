"""Report writers for traceable run-bundle inspections."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from sca.traceability.schema import BundleInspectionResult


def write_bundle_inspection_outputs(
    inspections: Iterable[BundleInspectionResult],
    out_csv: str | Path,
    json_out: str | Path,
    markdown: str | Path,
) -> None:
    rows = [inspection.to_row() for inspection in inspections]
    csv_path = Path(out_csv)
    json_path = Path(json_out)
    md_path = Path(markdown)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    md_path.write_text(_bundle_markdown(rows), encoding="utf-8")


def _bundle_markdown(rows: list[dict]) -> str:
    valid_count = sum(1 for row in rows if row.get("bundle_valid") is True)
    lines = [
        "# Traceable Run Bundle Inspection",
        "",
        "## Summary",
        f"- Bundles inspected: {len(rows)}",
        f"- Valid bundles: {valid_count}",
        f"- Invalid bundles: {len(rows) - valid_count}",
        "",
        "## Missing Artifacts",
    ]
    for row in rows:
        missing = row.get("missing_artifacts") or "none"
        lines.append(f"- {row.get('run_id')}: {missing}")
    lines.extend(["", "## Reproducibility Metadata"])
    for row in rows:
        missing = row.get("missing_reproducibility_fields") or "none"
        lines.append(f"- {row.get('run_id')}: missing {missing}")
    lines.extend(["", "## Parse And Crosslink Errors"])
    for row in rows:
        errors = "; ".join(
            value for value in (row.get("parse_errors"), row.get("crosslink_errors")) if value
        )
        lines.append(f"- {row.get('run_id')}: {errors or 'none'}")
    return "\n".join(lines) + "\n"
