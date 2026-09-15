# -*- coding: utf-8 -*-
"""Validate the composed NASICON VESTA workflow figure and frozen provenance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "figures" / "paper_nasicon" / "vesta" / "nasicon_workflow_vesta_manifest.json"
EXPECTED_CANONICAL_PAIRS = ["Na-O", "Zr-O", "Si-O", "P-O"]
EXPECTED_DISPLAY_LABELS = ["Na–O", "Zr–O", "Si–O", "P–O"]
EXPECTED_COLORS = ["#2878b5", "#188a9a", "#e69f00", "#8c62aa"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate() -> dict[str, Any]:
    require(MANIFEST_PATH.is_file(), f"Missing provenance manifest: {MANIFEST_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    panel3 = next((panel for panel in manifest.get("workflow_panels", []) if panel.get("panel") == 3), None)
    require(panel3 is not None, "Panel 3 provenance is missing")
    require(panel3.get("layout") == "2x2 pair-specific subplots", "Panel 3 is not the required 2x2 layout")
    require(panel3.get("pairs") == EXPECTED_CANONICAL_PAIRS, "Canonical ASCII subplot order is incorrect")

    curves = panel3.get("subplot_curves", [])
    require(len(curves) == 4, "Panel 3 must record exactly four subplots")
    require([row.get("canonical_pair") for row in curves] == EXPECTED_CANONICAL_PAIRS, "Per-subplot canonical pair IDs are incorrect")
    require([row.get("display_pair") for row in curves] == EXPECTED_DISPLAY_LABELS, "UTF-8 display labels are incorrect")
    require([str(row.get("color", "")).lower() for row in curves] == EXPECTED_COLORS, "Pair colours are incorrect")
    require(all(row.get("curve_count") == 1 for row in curves), "Each subplot must contain exactly one curve")

    shared_x = panel3.get("shared_x_limits_angstrom")
    shared_y = panel3.get("shared_y_limits")
    require(isinstance(shared_x, list) and len(shared_x) == 2 and shared_x[0] < shared_x[1], "Shared x limits are invalid")
    require(isinstance(shared_y, list) and len(shared_y) == 2 and shared_y[0] < shared_y[1], "Shared y limits are invalid")
    require(all(row.get("x_limits") == shared_x for row in curves), "Subplots do not all use the common x limits")
    require(all(row.get("y_limits") == shared_y for row in curves), "Subplots do not all use the common y limits")
    require(panel3.get("warning") == "Diagnostic only; not a calibrated energy scale.", "Diagnostic-only warning changed")

    for row in curves:
        source = Path(row["source_artifact"])
        require(source.is_file(), f"Missing frozen POT source: {source}")
        require(sha256(source) == row["source_sha256"], f"Frozen POT hash changed: {source}")

    outputs = {Path(row["path"]).suffix.lower(): row for row in manifest.get("workflow_outputs", [])}
    require(set(outputs) == {".png", ".pdf", ".svg"}, "PNG, PDF, and SVG outputs must all be recorded")
    for suffix, row in outputs.items():
        path = Path(row["path"])
        require(path.is_file() and path.stat().st_size > 100, f"Missing or empty {suffix} output: {path}")
        require(sha256(path) == row["sha256"], f"Recorded output hash is stale: {path}")

    png_path = Path(outputs[".png"]["path"])
    with Image.open(png_path) as image:
        image.verify()
    with Image.open(png_path) as image:
        dimensions = image.size
        require(dimensions[0] >= 3000 and dimensions[1] >= 1000, "PNG resolution is unexpectedly small")
        require(any(low < 240 for low, _high in image.convert("RGB").getextrema()), "PNG appears blank")

    pdf_path = Path(outputs[".pdf"]["path"])
    require(pdf_path.read_bytes().startswith(b"%PDF"), "PDF signature is invalid")
    svg_path = Path(outputs[".svg"]["path"])
    svg_text = svg_path.read_text(encoding="utf-8")
    require("<svg" in svg_text[:1000], "SVG root element is missing")
    require(all(label in svg_text for label in EXPECTED_DISPLAY_LABELS), "Rendered SVG does not preserve all typographic en-dash labels")

    protected_before = manifest.get("protected_scientific_artifact_hashes_before")
    protected_after = manifest.get("protected_scientific_artifact_hashes_after")
    require(protected_before == protected_after, "Protected before/after hash maps differ")
    require(manifest.get("scientific_artifacts_modified") is False, "Manifest reports scientific-artifact modification")
    for path_text, expected_hash in protected_before.items():
        path = Path(path_text)
        require(path.is_file(), f"Protected scientific artifact is missing: {path}")
        require(sha256(path) == expected_hash, f"Protected scientific artifact hash changed: {path}")

    return {
        "dimensions": dimensions,
        "outputs": {suffix: row["path"] for suffix, row in outputs.items()},
        "protected_artifact_count": len(protected_before),
    }


def main() -> int:
    try:
        result = validate()
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS: UTF-8 labels, canonical pair IDs, one curve per subplot, shared limits, "
        "PNG/PDF/SVG integrity, provenance, and protected scientific hashes"
    )
    print(f"PNG dimensions: {result['dimensions'][0]} x {result['dimensions'][1]}")
    print(f"Protected scientific artifacts verified: {result['protected_artifact_count']}")
    for suffix, path in sorted(result["outputs"].items()):
        print(f"{suffix[1:].upper()}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
