"""Independent frozen family-recovery classifier for Paper 1 generated candidates.

This is deliberately separate from SCA. It answers one question per generated
candidate:

    Does the generated candidate classify into the *requested* prototype family?

It reuses the exact pre-generation family-assignment rules that were used to build
the frozen benchmark (``scripts.build_paper1_simple_ordered_benchmark.classify_structure``
plus ``PROTOTYPE_RULES``): recomputed space group (pymatgen ``SpacegroupAnalyzer``,
symprec 0.01), reduced/anonymised stoichiometry, ordering, primitive-cell size and
an AFLOW Strukturbericht prototype match.

It operates on the generated candidate only. It never reads the held-out target
CIF coordinates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from pymatgen.core import Structure
from pymatgen.analysis.prototypes import AflowPrototypeMatcher
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_paper1_simple_ordered_benchmark import (  # noqa: E402
    CLASSIFIER_VERSION,
    classify_structure,
)

METHOD_VERSION = "paper1_family_recovery.v1"

# Frozen symmetry signature for each requested family (SG number, anonymised formula).
# This mirrors PROTOTYPE_RULES / the 221+ABC3 perovskite branch of classify_structure
# and is used only as an informational secondary signal when the AFLOW tag match fails.
REQUESTED_FAMILY_SYMMETRY: dict[str, tuple[int, str]] = {
    "rocksalt_b1": (225, "AB"),
    "cscl_b2": (221, "AB"),
    "zinc_blende_b3": (216, "AB"),
    "fluorite_antifluorite": (225, "AB2"),
    "oxide_perovskite": (221, "ABC3"),
    "halide_perovskite": (221, "ABC3"),
}
FAMILY_ORDER = (
    "rocksalt_b1",
    "cscl_b2",
    "zinc_blende_b3",
    "fluorite_antifluorite",
    "oxide_perovskite",
    "halide_perovskite",
)

RESULT_FIELDS = (
    "condition",
    "row_id",
    "formula",
    "requested_family",
    "detected_family",
    "verdict",
    "classifier_method",
    "classifier_status",
    "detected_space_group_symbol",
    "detected_space_group_number",
    "primitive_atom_count",
    "anonymous_formula",
    "aflow_strukturbericht",
    "aflow_tags_observed",
    "symmetry_consistent_with_requested",
    "classifier_reason",
    "candidate_sha256",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _safe_symmetry(structure: Structure) -> tuple[str | None, int | None, int | None, str | None]:
    try:
        analyzer = SpacegroupAnalyzer(structure, symprec=0.01)
        number = int(analyzer.get_space_group_number())
        symbol = str(analyzer.get_space_group_symbol())
        try:
            primitive = analyzer.get_primitive_standard_structure()
        except Exception:
            primitive = structure.get_primitive_structure()
        anon = str(primitive.composition.anonymized_formula)
        return symbol, number, len(primitive), anon
    except Exception:
        return None, None, None, None


def _symmetry_consistent(requested_family: str, number: int | None, anon: str | None) -> bool:
    want = REQUESTED_FAMILY_SYMMETRY.get(requested_family)
    if want is None or number is None or anon is None:
        return False
    return (number, anon) == want


def classify_candidate(
    *, condition: str, row_id: str, requested_family: str, formula: str, candidate: Path,
    matcher: AflowPrototypeMatcher,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "condition": condition,
        "row_id": row_id,
        "formula": formula,
        "requested_family": requested_family,
        "classifier_method": f"{METHOD_VERSION} (wraps {CLASSIFIER_VERSION})",
    }
    if not candidate.is_file():
        row.update(verdict="NO_CANDIDATE", classifier_status="NO_CANDIDATE", detected_family="")
        return row
    row["candidate_sha256"] = sha256_file(candidate)
    structure = Structure.from_file(str(candidate))
    symbol, number, prim_atoms, anon = _safe_symmetry(structure)
    row.update(
        detected_space_group_symbol=symbol,
        detected_space_group_number=number,
        primitive_atom_count=prim_atoms,
        anonymous_formula=anon,
    )
    try:
        tags = sorted(
            {
                str(m.get("tags", {}).get("strukturbericht"))
                for m in (matcher.get_prototypes(structure) or [])
            }
        )
    except Exception:
        tags = []
    row["aflow_tags_observed"] = ";".join(t for t in tags if t and t != "None")
    row["symmetry_consistent_with_requested"] = _symmetry_consistent(requested_family, number, anon)

    decision, code, reason = classify_structure(structure, matcher=matcher)
    row["classifier_status"] = code
    row["classifier_reason"] = reason
    if decision is not None:
        detected = str(decision["family"])
        row["detected_family"] = detected
        row["aflow_strukturbericht"] = decision.get("aflow_strukturbericht", "")
        row["verdict"] = "FAMILY_PASS" if detected == requested_family else "FAMILY_FAIL"
    else:
        row["detected_family"] = ""
        row["verdict"] = "NOT_CLASSIFIABLE"
    return row


def _load_targets(freeze_manifest: Path) -> list[dict[str, str]]:
    data = json.loads(freeze_manifest.read_text(encoding="utf-8"))
    return [
        {
            "row_id": str(t["row_id"]),
            "family": str(t["family"]),
            "formula": str(t.get("reduced_formula") or t.get("formula") or ""),
        }
        for t in data["targets"]
    ]


def evaluate(
    *, freeze_manifest: Path, primary_root: Path, ablation_root: Path | None, ablation_manifest: Path | None,
    out_dir: Path,
) -> dict[str, Any]:
    matcher = AflowPrototypeMatcher()
    targets = _load_targets(freeze_manifest)
    rows: list[dict[str, Any]] = []

    for target in targets:
        rows.append(
            classify_candidate(
                condition="C_RETRIEVAL_CONDITIONED",
                row_id=target["row_id"],
                requested_family=target["family"],
                formula=target["formula"],
                candidate=primary_root / target["row_id"] / "generated" / "candidate.cif",
                matcher=matcher,
            )
        )

    ablation_rows: set[str] = set()
    if ablation_root is not None and ablation_manifest is not None and ablation_manifest.is_file():
        ablation_ids = [
            str(t["row_id"])
            for t in json.loads(ablation_manifest.read_text(encoding="utf-8"))["targets"]
        ]
        ablation_rows = set(ablation_ids)
        by_id = {t["row_id"]: t for t in targets}
        for row_id in ablation_ids:
            target = by_id[row_id]
            rows.append(
                classify_candidate(
                    condition="B_GLOBAL_REGULATOR_ONLY",
                    row_id=row_id,
                    requested_family=target["family"],
                    formula=target["formula"],
                    candidate=ablation_root / row_id / "generated" / "candidate.cif",
                    matcher=matcher,
                )
            )

    write_csv(out_dir / "FAMILY_RECOVERY_RESULTS.csv", rows, RESULT_FIELDS)
    write_json(
        out_dir / "FAMILY_RECOVERY_RESULTS.json",
        {"schema_version": "paper1_family_recovery_results.v1", "method": METHOD_VERSION, "rows": rows},
    )

    summary_rows = _summarize(rows)
    write_csv(
        out_dir / "FAMILY_RECOVERY_SUMMARY.csv",
        summary_rows,
        ("condition", "family", "candidates", "family_pass", "family_fail", "not_classifiable", "no_candidate",
         "recovery_rate"),
    )
    _write_report(out_dir / "FAMILY_RECOVERY_REPORT.md", rows, summary_rows, ablation_rows)
    return {"rows": rows, "summary": summary_rows}


def _summarize(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for condition in ("C_RETRIEVAL_CONDITIONED", "B_GLOBAL_REGULATOR_ONLY"):
        cond_rows = [r for r in rows if r["condition"] == condition]
        if not cond_rows:
            continue
        for family in (*FAMILY_ORDER, "__all__"):
            fam_rows = cond_rows if family == "__all__" else [r for r in cond_rows if r["requested_family"] == family]
            if not fam_rows:
                continue
            verdicts = Counter(r["verdict"] for r in fam_rows)
            classifiable = len(fam_rows) - verdicts["NO_CANDIDATE"]
            out.append(
                {
                    "condition": condition,
                    "family": family,
                    "candidates": len(fam_rows) - verdicts["NO_CANDIDATE"],
                    "family_pass": verdicts["FAMILY_PASS"],
                    "family_fail": verdicts["FAMILY_FAIL"],
                    "not_classifiable": verdicts["NOT_CLASSIFIABLE"],
                    "no_candidate": verdicts["NO_CANDIDATE"],
                    "recovery_rate": round(verdicts["FAMILY_PASS"] / classifiable, 4) if classifiable else "",
                }
            )
    return out


def _write_report(
    path: Path, rows: Sequence[dict[str, Any]], summary_rows: Sequence[dict[str, Any]], ablation_rows: set[str]
) -> None:
    lines = [
        "# Paper 1 independent family-recovery classifier",
        "",
        f"Method: `{METHOD_VERSION}` wrapping the frozen benchmark classifier `{CLASSIFIER_VERSION}`.",
        "",
        "This analysis is independent of SCA. It runs the frozen pre-generation family-assignment "
        "rules on each **generated candidate** and asks whether it classifies into the requested "
        "prototype family. Held-out target CIF coordinates are never read.",
        "",
        "Verdicts: `FAMILY_PASS` (generated candidate classified as the requested family), "
        "`FAMILY_FAIL` (classified as a different supported family), `NOT_CLASSIFIABLE` (frozen "
        "classifier returned an exclusion code — e.g. no AFLOW prototype match, cell too large).",
        "",
        "## Summary",
        "",
        "| Condition | Family | Candidates | FAMILY_PASS | FAMILY_FAIL | NOT_CLASSIFIABLE | Recovery rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in summary_rows:
        lines.append(
            f"| {s['condition']} | {s['family']} | {s['candidates']} | {s['family_pass']} | "
            f"{s['family_fail']} | {s['not_classifiable']} | {s['recovery_rate']} |"
        )
    lines += ["", "## Per-candidate (condition C, primary benchmark)", "",
              "| Row | Requested | Detected | Verdict | Detected SG | AFLOW | Sym-consistent |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        if r["condition"] != "C_RETRIEVAL_CONDITIONED":
            continue
        lines.append(
            f"| {r['row_id']} | {r['requested_family']} | {r.get('detected_family') or '—'} | "
            f"{r['verdict']} | {r.get('detected_space_group_symbol') or '—'} | "
            f"{r.get('aflow_strukturbericht') or '—'} | {r.get('symmetry_consistent_with_requested')} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    art = REPO_ROOT / "artifacts" / "paper1_spp_positive_domain"
    parser.add_argument("--freeze-manifest", type=Path, default=art / "freeze_v1" / "FROZEN_BENCHMARK_MANIFEST.json")
    parser.add_argument("--primary-root", type=Path, default=REPO_ROOT / "outputs" / "paper1_simple_ordered_v1")
    parser.add_argument(
        "--ablation-root",
        type=Path,
        default=REPO_ROOT / "outputs" / "paper1_spp_ablation_v1" / "global_regulator_only",
    )
    parser.add_argument(
        "--ablation-manifest",
        type=Path,
        default=art / "ablation_freeze_v1" / "FROZEN_SPP_ABLATION_MANIFEST.json",
    )
    parser.add_argument("--out-dir", type=Path, default=art / "results")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = evaluate(
        freeze_manifest=args.freeze_manifest.resolve(),
        primary_root=args.primary_root.resolve(),
        ablation_root=args.ablation_root.resolve(),
        ablation_manifest=args.ablation_manifest.resolve(),
        out_dir=args.out_dir.resolve(),
    )
    counts = Counter((r["condition"], r["verdict"]) for r in result["rows"])
    print(json.dumps({f"{c}/{v}": n for (c, v), n in sorted(counts.items())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
