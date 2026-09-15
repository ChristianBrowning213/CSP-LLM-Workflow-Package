"""Audit exact per-structure support for the frozen NASICON SPP corpora."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from spp_maker_qlip.required_pair_extraction import collect_required_pair_distances


REPO_ROOT = Path(__file__).resolve().parents[1]
FORMULA = "Na3Zr2Si2PO12"
PAIR_ORDER = [
    "Na-Na", "Na-Zr", "Na-Si", "Na-P", "Na-O",
    "Zr-Zr", "Si-Zr", "P-Zr", "O-Zr",
    "Si-Si", "P-Si", "O-Si", "P-P", "O-P", "O-O",
]
CONDITIONS = {
    "nasicon_specialist_v1": REPO_ROOT / "data" / "corpora" / "nasicon_specialist_v1",
    "nasicon_specialist_leave_target_out_v1": (
        REPO_ROOT / "data" / "corpora" / "nasicon_specialist_leave_target_out_v1"
    ),
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _record_by_cif(corpus_root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((corpus_root / "records").glob("*.json")):
        records[path.stem] = _load_json(path)
    return records


def _quality_by_pair(condition: str) -> dict[str, dict[str, Any]]:
    short_name = "full" if condition == "nasicon_specialist_v1" else "leave_target_out"
    payload = _load_json(REPO_ROOT / "artifacts" / "nasicon_spp" / short_name / "spp_pot_quality.json")
    return {
        str(row["pair"]): row
        for row in payload.get("pairs", [])
        if isinstance(row, dict) and isinstance(row.get("pair"), str)
    }


def _frozen_generation(condition: str) -> dict[str, Any]:
    short_name = "full" if condition == "nasicon_specialist_v1" else "leave_target_out"
    return _load_json(
        REPO_ROOT / "artifacts" / "nasicon_spp" / short_name / "generation_result_6a.json"
    )


def audit_condition(condition: str, corpus_root: Path) -> list[dict[str, Any]]:
    extraction = collect_required_pair_distances(
        cif_dir=corpus_root / "cifs",
        formula=FORMULA,
        cutoff=6.0,
        supercell=None,
        max_distances_per_pair=None,
    )
    records = _record_by_cif(corpus_root)
    quality = _quality_by_pair(condition)
    frozen = _frozen_generation(condition)
    frozen_evidence = {
        str(row["required_pair"]): row
        for row in frozen.get("corpus_quality", {}).get("pair_evidence_summary", [])
        if isinstance(row, dict) and isinstance(row.get("required_pair"), str)
    }
    per_pair_contributors: dict[str, list[dict[str, Any]]] = {pair: [] for pair in PAIR_ORDER}

    for cif_row in extraction["cifs"]:
        stem = Path(str(cif_row["file"])).stem
        record = records.get(stem, {})
        for pair, stats in cif_row["geometric_pairs_within_cutoff"].items():
            if pair not in per_pair_contributors:
                continue
            per_pair_contributors[pair].append(
                {
                    "structure_id": record.get("internal_id", stem),
                    "source_id": record.get("source_id"),
                    "tier": record.get("topology_tier", "UNANNOTATED"),
                    "count": int(stats["count"]),
                }
            )

    rows: list[dict[str, Any]] = []
    for pair in PAIR_ORDER:
        stats = frozen["pair_stats"][pair]
        evidence = frozen_evidence[pair]
        frozen_stems = {
            Path(str(path)).stem for path in evidence.get("direct_support_candidate_ids", [])
        }
        contributors = sorted(
            [
                row for row in per_pair_contributors[pair]
                if str(row["structure_id"]) in frozen_stems
            ],
            key=lambda row: (-int(row["count"]), str(row["structure_id"])),
        )
        raw_count = int(stats["count"])
        recomputed_count = sum(int(row["count"]) for row in contributors)
        dominant = contributors[0] if contributors else {}
        dominant_count = int(dominant.get("count", 0))
        dominant_fraction = dominant_count / recomputed_count if recomputed_count else 0.0
        frozen_records = [records.get(stem, {}) for stem in frozen_stems]
        tier_1_count = sum(row.get("topology_tier") == "TIER_1_TOPOLOGY" for row in frozen_records)
        tier_2_count = sum(row.get("topology_tier") == "TIER_2_PAIR_COMPLETION" for row in frozen_records)
        pair_quality = quality[pair]
        cap_fraction = float(pair_quality["max_cap_fraction"])
        pot_points = int(pair_quality["raw_point_count"])
        capped_bins = int(round(cap_fraction * pot_points))
        verdict = "PASS" if pair_quality["pot_quality"] == "usable" else "FAIL"
        tiers = []
        if tier_1_count:
            tiers.append("TIER_1_TOPOLOGY")
        if tier_2_count:
            tiers.append("TIER_2_PAIR_COMPLETION")
        rows.append(
            {
                "corpus_id": condition,
                "pair": pair,
                "contributing_structure_count": len(frozen_stems),
                "raw_pair_distance_observations": raw_count,
                "effective_weighted_observations": float(raw_count),
                "observation_weight_policy": "unit_weight_after_0<r<=6.0A_periodic_filter",
                "corpus_quality_preflight_direct_observations": int(evidence["direct_observation_count"]),
                "recomputed_observations_current_corpus": recomputed_count,
                "frozen_count_reproduced_exactly": recomputed_count == raw_count,
                "pot_bin_count": pot_points,
                "capped_bin_count": capped_bins,
                "capped_bin_fraction": cap_fraction,
                "minimum_supported_distance_A": stats["min_distance"],
                "maximum_supported_distance_A": stats["max_distance"],
                "evidence_tiers": "+".join(tiers),
                "tier_1_contributing_structures": tier_1_count,
                "tier_2_contributing_structures": tier_2_count,
                "dominant_structure_id": dominant.get("structure_id", ""),
                "dominant_structure_observations": dominant_count,
                "dominant_structure_fraction": dominant_fraction,
                "one_structure_dominates": dominant_fraction > 0.5,
                "dominance_assessment_basis": "recomputed_per_structure_counts_over_frozen_contributor_set",
                "quality_gate_verdict": verdict,
                "quality_gate_reason": pair_quality["pot_quality_reason"],
            }
        )
    return rows


def _write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# NASICON pair-support audit",
        "",
        "The audit reproduces the frozen SPP extraction exactly: ordered periodic atom/image observations, "
        "automatic per-cell image ranges, a 6.0 Å inclusive cutoff, no per-pair observation cap, and unit "
        "weights. Consequently, effective weighted observations equal the raw observations retained by the "
        "geometry filter. POT curves contain 100 bins from 1.025 to 5.975 Å; the unchanged quality gate fails "
        "a pair when more than 50% of those values equal the maximum cap.",
        "",
        "Raw/effective totals and contributor identities are read from the frozen generation manifest used for "
        "the POT fit. Per-structure counts were not persisted by that generator, so dominance is reconstructed "
        "from the current frozen CIF files over the manifest's contributor set. The CSV explicitly records whether "
        "that reconstruction reproduces the frozen aggregate count; the dominance conclusion is not used to "
        "override the POT quality gate.",
        "",
    ]
    for condition in CONDITIONS:
        condition_rows = [row for row in rows if row["corpus_id"] == condition]
        failed = [row["pair"] for row in condition_rows if row["quality_gate_verdict"] == "FAIL"]
        lines.extend(
            [
                f"## {condition}",
                "",
                f"Structures: {max(int(row['contributing_structure_count']) for row in condition_rows)} maximum contributors to any pair. "
                f"Pair coverage: {sum(int(row['raw_pair_distance_observations']) > 0 for row in condition_rows)}/15. "
                f"Frozen counts exactly reproduced: {sum(bool(row['frozen_count_reproduced_exactly']) for row in condition_rows)}/15. "
                f"Gate failures: {', '.join(failed) if failed else 'none'}.",
                "",
                "| Pair | Structures | Raw/effective observations | Supported range (Å) | Tier evidence | Dominant share | Capped bins | Verdict |",
                "|---|---:|---:|---:|---|---:|---:|---|",
            ]
        )
        for row in condition_rows:
            lines.append(
                f"| {row['pair']} | {row['contributing_structure_count']} | "
                f"{row['raw_pair_distance_observations']}/{row['effective_weighted_observations']:.0f} | "
                f"{float(row['minimum_supported_distance_A']):.3f}–{float(row['maximum_supported_distance_A']):.3f} | "
                f"{row['evidence_tiers']} | {float(row['dominant_structure_fraction']):.3f} | "
                f"{row['capped_bin_count']}/{row['pot_bin_count']} | {row['quality_gate_verdict']} |"
            )
        lines.extend(["", "The pair-level verdict is a curve-support diagnostic, not a statement of thermodynamic accuracy.", ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "artifacts" / "nasicon_spp_quality",
    )
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = [row for condition, root in CONDITIONS.items() for row in audit_condition(condition, root)]
    csv_path = args.out_dir / "NASICON_PAIR_SUPPORT_AUDIT.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _write_report(args.out_dir / "NASICON_PAIR_SUPPORT_REPORT.md", rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
