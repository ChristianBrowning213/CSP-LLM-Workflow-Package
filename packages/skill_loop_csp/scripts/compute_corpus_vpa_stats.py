"""Compute a robust volume-per-atom (VPA) statistic over a Crystal-DB corpus.

Generic, reusable analysis utility -- NOT a scientific pipeline runner.  It
reads directly from a Crystal-DB sqlite corpus resolved through the same
``data/corpora/registry.json`` used by the production ``route_corpus``
function, parses every CIF with pymatgen, and reports median/quartile VPA
statistics with full provenance.  Intended to freeze a single
target-independent ``GLOBAL_VPA`` constant before the composition_scaled
cell-mode experiment, but takes no NASICON-specific assumptions itself.

Usage:
    python scripts/compute_corpus_vpa_stats.py mp_stable_10k_v1 \
        --exclude-formula Na3Zr2Si2PO12 --exclude-formula Na3Ti2(PO4)3 \
        --exclude-formula LiZr2(PO4)3 \
        --out artifacts/.../GLOBAL_VPA_PREFLIGHT.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Structure

from sok_llm_orchestrator.retrieval.specialist_corpora import resolve_corpus


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_vpa_stats(
    corpus_id: str,
    *,
    exclude_reduced_formulas: frozenset[str] = frozenset(),
    registry_path: Path | None = None,
) -> dict[str, Any]:
    resolved = resolve_corpus(corpus_id, registry_path) if registry_path else resolve_corpus(corpus_id)
    database = Path(resolved["database"])
    corpus_hash = _sha256_file(database)
    con = sqlite3.connect(str(database))
    try:
        cur = con.cursor()
        cur.execute("SELECT structure_id, cif_text, reduced_formula, volume, license_restricted FROM structures")
        rows = cur.fetchall()
    finally:
        con.close()

    total = len(rows)
    excluded_license = 0
    excluded_target_formula = 0
    unparseable = 0
    excluded_degenerate = 0
    vpa_records: list[dict[str, Any]] = []

    for structure_id, cif_text, reduced_formula, volume, license_restricted in rows:
        if int(license_restricted or 0) != 0:
            excluded_license += 1
            continue
        try:
            structure = Structure.from_str(str(cif_text), fmt="cif")
            parsed_reduced = structure.composition.reduced_formula
        except Exception:
            unparseable += 1
            continue
        if parsed_reduced in exclude_reduced_formulas:
            excluded_target_formula += 1
            continue
        num_sites = len(structure)
        parsed_volume = float(structure.volume)
        if num_sites <= 0 or parsed_volume <= 0.0:
            excluded_degenerate += 1
            continue
        vpa_records.append({
            "structure_id": str(structure_id),
            "reduced_formula": parsed_reduced,
            "num_sites": int(num_sites),
            "volume": parsed_volume,
            "vpa": parsed_volume / num_sites,
            "stored_volume": float(volume) if volume is not None else None,
        })

    included = len(vpa_records)
    vpa_values = sorted(record["vpa"] for record in vpa_records)
    if not vpa_values:
        raise RuntimeError(f"no usable structures survived filtering for corpus '{corpus_id}'")

    median = statistics.median(vpa_values)
    quantiles = statistics.quantiles(vpa_values, n=4, method="inclusive")

    return {
        "schema_version": "corpus_vpa_stats.v1",
        "corpus_id": corpus_id,
        "corpus_role": resolved.get("role"),
        "corpus_source": resolved.get("source"),
        "database_path": str(database),
        "database_sha256": corpus_hash,
        "filtering_rules": [
            "license_restricted == 0",
            "cif_text parses with pymatgen Structure.from_str(fmt='cif')",
            "parsed reduced_formula not in the excluded target-formula set",
            "num_sites > 0 and pymatgen-parsed volume > 0",
        ],
        "excluded_reduced_formulas": sorted(exclude_reduced_formulas),
        "structure_count_total": total,
        "excluded_license_restricted": excluded_license,
        "excluded_unparseable": unparseable,
        "excluded_target_formula_match": excluded_target_formula,
        "excluded_degenerate": excluded_degenerate,
        "included_count": included,
        "global_vpa_median_A3_per_atom": median,
        "vpa_q1_A3_per_atom": quantiles[0],
        "vpa_q3_A3_per_atom": quantiles[2],
        "vpa_min_A3_per_atom": vpa_values[0],
        "vpa_max_A3_per_atom": vpa_values[-1],
        "included_records": vpa_records,
    }


def _write_markdown(stats: dict[str, Any], path: Path) -> None:
    lines = [
        "# GLOBAL_VPA_PREFLIGHT",
        "",
        f"- corpus_id: `{stats['corpus_id']}`",
        f"- corpus_role: `{stats['corpus_role']}`",
        f"- corpus_source: {stats['corpus_source']}",
        f"- database_path: `{stats['database_path']}`",
        f"- database_sha256: `{stats['database_sha256']}`",
        "",
        "## Filtering rules (applied in order)",
        *[f"1. {rule}" for rule in stats["filtering_rules"]],
        f"- excluded_reduced_formulas: {', '.join(stats['excluded_reduced_formulas']) or '(none)'}",
        "",
        "## Counts",
        f"- structure_count_total: {stats['structure_count_total']}",
        f"- excluded_license_restricted: {stats['excluded_license_restricted']}",
        f"- excluded_unparseable: {stats['excluded_unparseable']}",
        f"- excluded_target_formula_match: {stats['excluded_target_formula_match']}",
        f"- excluded_degenerate: {stats['excluded_degenerate']}",
        f"- included_count: {stats['included_count']}",
        "",
        "## GLOBAL_VPA statistic",
        f"- median (GLOBAL_VPA): **{stats['global_vpa_median_A3_per_atom']:.6f} A^3/atom**",
        f"- Q1: {stats['vpa_q1_A3_per_atom']:.6f}",
        f"- Q3: {stats['vpa_q3_A3_per_atom']:.6f}",
        f"- min: {stats['vpa_min_A3_per_atom']:.6f}",
        f"- max: {stats['vpa_max_A3_per_atom']:.6f}",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_id")
    parser.add_argument("--exclude-formula", action="append", default=[], dest="exclude_formulas")
    parser.add_argument("--registry-path", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--out-md", type=Path, default=None, help="Optional output Markdown path")
    args = parser.parse_args()

    excluded = frozenset(Composition(value).reduced_formula for value in args.exclude_formulas)
    stats = compute_vpa_stats(args.corpus_id, exclude_reduced_formulas=excluded, registry_path=args.registry_path)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.out_md:
        _write_markdown(stats, args.out_md)
    print(f"GLOBAL_VPA median = {stats['global_vpa_median_A3_per_atom']:.6f} A^3/atom over {stats['included_count']} structures")


if __name__ == "__main__":
    main()
