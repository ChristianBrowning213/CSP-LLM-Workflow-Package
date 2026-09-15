"""Validate the finalized PAPER-RESULTS-REDESIGN-1 artifact package."""

from __future__ import annotations

import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "paper_results_final_redesign"


def rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> dict[str, int | str]:
    freeze = json.loads((OUT / "00_design" / "FREEZE_METADATA.json").read_text(encoding="utf-8"))
    manifest = OUT / "00_design" / "BENCHMARK_MANIFEST.csv"
    assert sha256(manifest) == freeze["manifest_sha256"]
    design = rows(manifest)
    assert len(design) == 14
    assert sum(r["benchmark_role"] == "SCAFFOLD_SPP_FACTORIAL" for r in design) == 8
    assert sum(r["benchmark_role"] == "NASICON_EXTENSION" for r in design) == 3

    abx = rows(OUT / "02_rediscovery" / "SPP_CASE_AUDIT.csv")
    nas = rows(OUT / "08_nasicon" / "NASICON_SPP_CASE_AUDIT.csv")
    assert len(abx) == 8 and len(nas) == 3
    assert all(int(r["used_for_spp_count"]) == 10 for r in abx + nas)
    assert all(r["valid_for_ranking"] == "False" for r in abx + nas)
    assert sum(r["coverage_class"] == "STRICT_COMPLETE" for r in abx) == 0
    assert sum(r["coverage_class"] == "STRICT_COMPLETE" for r in nas) == 2
    pair_rows = rows(OUT / "02_rediscovery" / "SPP_PAIR_COVERAGE.csv") + rows(OUT / "08_nasicon" / "NASICON_SPP_COVERAGE.csv")
    assert pair_rows and all(r["fallback_used"] == "False" and r["fallback_source"] == "NA" for r in pair_rows)

    retrieval = rows(OUT / "02_rediscovery" / "RETRIEVAL_RESULTS.csv") + rows(OUT / "08_nasicon" / "NASICON_RETRIEVAL.csv")
    assert retrieval and all(int(r["primary_retrieval_cap"]) == 10 for r in retrieval)
    assert not any(r["used_for_SPP"] == "True" and (r["same_formula_status"] == "True" or r["target_equivalent_status"] == "True" or r["raw_duplicate_status"] == "True" or r["canonical_duplicate_status"] == "True") for r in retrieval)

    held = rows(OUT / "FINAL_HELD_OUT_REDISCOVERY.csv")
    factorial = rows(OUT / "FINAL_SCAFFOLD_SPP_FACTORIAL.csv")
    nas_final = rows(OUT / "FINAL_NASICON_RESULTS.csv")
    abst = rows(OUT / "FINAL_ABSTENTION_RESULTS.csv")
    assert len(held) == 8 and all(r["solver_status"] == "NOT_RUN_INVALID_SPP_QUALITY" for r in held)
    assert len(factorial) == 40
    assert not any(r["SPP_used"] == "True" for r in factorial)
    assert len(nas_final) == 3 and all(r["classification"] == "NASICON_D" for r in nas_final)
    assert len(abst) == 3 and all(r["correct_abstention"] == "True" and r["bogus_CIF"] == "False" and r["software_failure"] == "False" for r in abst)
    dof = rows(OUT / "03_factorial" / "SCAFFOLD_DOF.csv")
    assert sorted(int(r["feasible_assignment_count"]) for r in dof if r["scaffold_type"] == "TIGHT") == [1] * 8
    assert sorted(int(r["feasible_assignment_count"]) for r in dof if r["scaffold_type"] == "LOOSE") == [2] * 8

    grid = rows(OUT / "10_boundary" / "GRID8" / "GRID8_REFERENCE_RECOVERY.csv")
    assert len(grid) == 7 and sum(r["reference_top1"] == "True" for r in grid) == 3
    assert not any("GRID64" in str(path).upper() for path in OUT.rglob("*"))

    report = (OUT / "FINAL_RESULTS_REPORT.md").read_text(encoding="utf-8")
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    expected = [
        "## 1. Traceable execution across the frozen breadth benchmark",
        "## 2. Prospective held-out known-crystal recovery",
        "## 3. Complementary roles of scaffolds and retrieval-derived SPPs",
        "## 4. SPP-guided extension to NASICON/NZP crystallography",
        "## 5. Representability and abstention",
        "## 6. GRID8 boundary experiment",
        "## 7. Negative and unexpected findings",
        "## 8. Manuscript-safe claims",
        "## 9. Claims that are NOT supported",
    ]
    assert headings == expected and "RESULT_D" in report and "NASICON_D" in report

    for stem in ("figure_a_held_out_recovery", "figure_b_scaffold_spp_factorial", "figure_c_nasicon_extension"):
        png, pdf, svg = (OUT / "figures" / f"{stem}.{suffix}" for suffix in ("png", "pdf", "svg"))
        with Image.open(png) as image:
            image.verify(); assert image.width >= 1800 and image.height >= 900
        pdf_bytes = pdf.read_bytes()
        assert pdf_bytes.startswith(b"%PDF-") and b"/Type /Page" in pdf_bytes and pdf_bytes.rstrip().endswith(b"%%EOF")
        ET.parse(svg)
    for name in ("figure_a_data.csv", "figure_b_data.csv", "figure_c_data.csv"):
        assert rows(OUT / "figures" / name)

    protected = rows(OUT / "PROTECTED_HASH_VERIFICATION.csv")
    assert protected and all(r["status"] == "PASS" for r in protected)
    hashes = rows(OUT / "OUTPUT_HASH_MANIFEST.csv")
    for row in hashes:
        path = ROOT / row["path"]
        assert path.is_file() and sha256(path) == row["sha256"] and path.stat().st_size == int(row["size_bytes"])
    return {"targets": 8, "nasicon_targets": 3, "valid_primary_spp": 0, "negative_controls": 3, "figures": 3, "protected_hash_rows": len(protected), "output_hash_rows": len(hashes), "status": "PASS"}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
