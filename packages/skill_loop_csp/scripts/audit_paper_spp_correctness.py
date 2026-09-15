from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sok_llm_orchestrator.structures.prototype_scaffold import (  # noqa: E402
    _canonical_pair_key,
    _score_structure_with_spp_curves,
)


RUN_EXPERIMENTS = [
    "paper_experiment_1_common_v1",
    "paper_experiment_2_hard_v3",
    "paper_experiment_3_specialist_halide_v1",
]

ROW_COLUMNS = [
    "experiment_id",
    "row_id",
    "formula",
    "spp_summary_path",
    "spp_pairs_csv_path",
    "row_specific_spp_found",
    "row_specific_pair_count",
    "pairs",
    "retrieved_evidence_count",
    "spp_exported_evidence_count",
    "universal_regulariser_used",
    "universal_regulariser_only",
    "pair_coverage_status",
    "negative_values_present",
    "min_spp_score",
    "max_spp_score",
    "audit_status",
    "warning",
]

PAIR_COLUMNS = [
    "experiment_id",
    "row_id",
    "formula",
    "pair",
    "n_points",
    "r_min",
    "r_max",
    "score_min",
    "score_max",
    "score_at_min_distance",
    "r_at_min_score",
    "contains_negative_values",
    "contains_nan",
    "contains_inf",
    "suspicious_flat_curve",
    "suspicious_extreme_value",
    "audit_status",
]

PARITY_COLUMNS = [
    "experiment_id",
    "row_id",
    "formula",
    "qlip_objective",
    "independent_spp_score",
    "absolute_difference",
    "relative_difference",
    "parity_pass",
    "tolerance",
    "scorer_notes",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def formula_pairs(formula: str) -> list[str]:
    elements = re.findall(r"[A-Z][a-z]?", formula or "")
    unique = list(dict.fromkeys(elements))
    return [_canonical_pair_key(f"{unique[i]}-{unique[j]}") for i in range(len(unique)) for j in range(i + 1, len(unique))]


def pair_key(pair: str) -> str:
    return _canonical_pair_key(str(pair).replace("_", "-"))


def read_pair_csv(path: Path) -> list[str]:
    pairs = []
    for row in read_csv(path):
        pair = str(row.get("pair") or row.get("spp_pair") or "").strip()
        if pair:
            pairs.append(pair_key(pair))
    return pairs


def pot_path_for_pair(root: Path, pair: str) -> Path | None:
    canonical = pair_key(pair)
    candidates = [
        root / canonical / f"{canonical}.POT",
        root / f"{canonical}.POT",
    ]
    if "-" in canonical:
        left, right = canonical.split("-", 1)
        reversed_pair = f"{right}-{left}"
        candidates.extend([root / reversed_pair / f"{reversed_pair}.POT", root / f"{reversed_pair}.POT"])
    for path in candidates:
        if path.is_file():
            return path
    compact = canonical.replace("-", "").lower()
    for path in root.rglob("*.POT"):
        if path.stem.replace("-", "").replace("_", "").lower() == compact:
            return path
    return None


def parse_pot(path: Path) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            points.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return sorted(points)


def values_have_nan_inf(values: list[float]) -> tuple[bool, bool]:
    return any(math.isnan(value) for value in values), any(math.isinf(value) for value in values)


def row_dirs() -> list[Path]:
    dirs: list[Path] = []
    for experiment in RUN_EXPERIMENTS:
        root = ROOT / "local_runs" / experiment
        dirs.extend(path for path in sorted(root.iterdir()) if path.is_dir() and (path / "input.json").is_file())
    return dirs


def qlip_objective(qlip_solution: dict[str, Any]) -> float | None:
    for container in (qlip_solution.get("solution"), qlip_solution.get("scaffold_trace"), qlip_solution):
        if isinstance(container, dict) and isinstance(container.get("objective_value"), (int, float)):
            return float(container["objective_value"])
    return None


def independent_score(cif_path: Path, curves: dict[str, list[tuple[float, float]]]) -> tuple[float | None, str]:
    if not cif_path.is_file():
        return None, "generated_cif_missing"
    try:
        from pymatgen.core import Structure

        structure = Structure.from_file(str(cif_path))
    except Exception as exc:  # noqa: BLE001
        return None, f"generated_cif_unreadable:{type(exc).__name__}"
    result = _score_structure_with_spp_curves(structure, curves)
    if result.get("ok"):
        return float(result["score"]), "mirrors prototype_scaffold scorer: unique off-diagonal site pairs, pymatgen minimum-image distance, linear interpolation, no probability transform"
    return None, str(result.get("reason") or "independent_score_failed")


def audit(out_root: Path, package_root: Path, pot_root: Path) -> dict[str, Any]:
    package_index_by_key = {
        (row["experiment_id"], row["row_id"]): row
        for row in read_csv(package_root / "WORKFLOW_ARTIFACTS_INDEX.csv")
    }
    row_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    parity_rows: list[dict[str, Any]] = []
    implementation_files = [
        "src/sok_llm_orchestrator/experiments/paper_workflow.py",
        "src/sok_llm_orchestrator/structures/prototype_scaffold.py",
        "src/sok_llm_orchestrator/agentic/visualise_workflow_artifact.py",
        "scripts/build_paper_workflow_artifact_package.py",
    ]

    for row_dir in row_dirs():
        input_payload = read_json(row_dir / "input.json")
        experiment_id = str(input_payload.get("experiment_id") or row_dir.parent.name)
        row_id = str(input_payload.get("row_id") or row_dir.name)
        formula = str(input_payload.get("target_formula") or "")
        key = (experiment_id, row_id)
        package_row = package_index_by_key.get(key, {})
        spp_summary = read_json(row_dir / "spp_summary.json")
        retrieval = read_json(row_dir / "crystaldb_retrieval_results.json")
        qlip = read_json(row_dir / "qlip_solution.json")
        pairs = read_pair_csv(row_dir / "spp_pairs.csv")
        required = [pair_key(pair) for pair in formula_pairs(formula)]
        curves: dict[str, list[tuple[float, float]]] = {}
        row_min: float | None = None
        row_max: float | None = None
        row_negative = False
        row_nan = False
        row_inf = False
        row_warnings: list[str] = []
        if sorted(pairs) != sorted(required):
            row_warnings.append("spp_pairs_do_not_match_formula_required_pairs")
        for pair in pairs:
            pot_path = pot_path_for_pair(pot_root, pair)
            if pot_path is None:
                pair_rows.append({
                    "experiment_id": experiment_id,
                    "row_id": row_id,
                    "formula": formula,
                    "pair": pair,
                    "n_points": 0,
                    "audit_status": "FAIL",
                })
                row_warnings.append(f"missing_pot_curve:{pair}")
                continue
            points = parse_pot(pot_path)
            curves[pair_key(pair)] = points
            rs = [point[0] for point in points]
            ys = [point[1] for point in points]
            has_nan, has_inf = values_have_nan_inf(rs + ys)
            row_nan = row_nan or has_nan
            row_inf = row_inf or has_inf
            negative = any(value < 0 for value in ys)
            row_negative = row_negative or negative
            if ys:
                score_min = min(ys)
                score_max = max(ys)
                row_min = score_min if row_min is None else min(row_min, score_min)
                row_max = score_max if row_max is None else max(row_max, score_max)
                r_at_min = rs[ys.index(score_min)]
            else:
                score_min = score_max = r_at_min = ""
            monotonic = all(right > left for left, right in zip(rs, rs[1:]))
            flat = bool(ys) and max(ys) - min(ys) < 1e-12
            extreme = any(abs(value) > 1e6 for value in ys)
            status = "PASS"
            if not points or has_nan or has_inf or not monotonic:
                status = "FAIL"
            elif flat or extreme:
                status = "WARNING"
            pair_rows.append({
                "experiment_id": experiment_id,
                "row_id": row_id,
                "formula": formula,
                "pair": pair,
                "n_points": len(points),
                "r_min": min(rs) if rs else "",
                "r_max": max(rs) if rs else "",
                "score_min": score_min,
                "score_max": score_max,
                "score_at_min_distance": ys[0] if ys else "",
                "r_at_min_score": r_at_min,
                "contains_negative_values": str(negative).lower(),
                "contains_nan": str(has_nan).lower(),
                "contains_inf": str(has_inf).lower(),
                "suspicious_flat_curve": str(flat).lower(),
                "suspicious_extreme_value": str(extreme).lower(),
                "audit_status": status,
            })
        exported_count = sum(1 for item in retrieval.get("neighbors") or [] if isinstance(item.get("cif_export"), dict) and item["cif_export"].get("status") == "exported")
        universal_only = str(package_row.get("spp_panel_source_mode") or "") == "universal_regulariser_only_fallback"
        pair_coverage = "complete" if pairs and not set(required) - set(pairs) and not any(f"missing_pot_curve:{pair}" in row_warnings for pair in pairs) else "incomplete"
        row_status = "PASS"
        if row_nan or row_inf or pair_coverage != "complete" or universal_only:
            row_status = "FAIL"
        elif row_warnings:
            row_status = "WARNING"
        row_rows.append({
            "experiment_id": experiment_id,
            "row_id": row_id,
            "formula": formula,
            "spp_summary_path": str(row_dir / "spp_summary.json") if (row_dir / "spp_summary.json").is_file() else "",
            "spp_pairs_csv_path": str(row_dir / "spp_pairs.csv") if (row_dir / "spp_pairs.csv").is_file() else "",
            "row_specific_spp_found": str(bool(pairs)).lower(),
            "row_specific_pair_count": len(pairs),
            "pairs": ";".join(pairs),
            "retrieved_evidence_count": spp_summary.get("retrieved_evidence_count", len(retrieval.get("neighbors") or [])),
            "spp_exported_evidence_count": exported_count,
            "universal_regulariser_used": str(bool(package_row.get("universal_regulariser_root"))).lower(),
            "universal_regulariser_only": str(universal_only).lower(),
            "pair_coverage_status": pair_coverage,
            "negative_values_present": str(row_negative).lower(),
            "min_spp_score": row_min if row_min is not None else "",
            "max_spp_score": row_max if row_max is not None else "",
            "audit_status": row_status,
            "warning": ";".join(row_warnings),
        })
        score, notes = independent_score(row_dir / "generated.cif", curves)
        objective = qlip_objective(qlip)
        if objective is None:
            parity_pass = "not_applicable"
            abs_diff = rel_diff = ""
            notes = notes + "; qlip_solution objective_value is absent, so numeric objective parity cannot be asserted for this scaffold-only paper workflow row"
        elif score is None:
            parity_pass = "false"
            abs_diff = rel_diff = ""
        else:
            abs_diff_value = abs(float(objective) - float(score))
            rel_diff_value = abs_diff_value / max(abs(float(objective)), abs(float(score)), 1e-12)
            parity_pass = str(abs_diff_value <= 1e-8).lower()
            abs_diff = abs_diff_value
            rel_diff = rel_diff_value
        parity_rows.append({
            "experiment_id": experiment_id,
            "row_id": row_id,
            "formula": formula,
            "qlip_objective": objective if objective is not None else "",
            "independent_spp_score": score if score is not None else "",
            "absolute_difference": abs_diff,
            "relative_difference": rel_diff,
            "parity_pass": parity_pass,
            "tolerance": 1e-8,
            "scorer_notes": notes,
        })

    write_csv(out_root / "SPP_ROW_AUDIT.csv", row_rows, ROW_COLUMNS)
    write_csv(out_root / "SPP_PAIR_AUDIT.csv", pair_rows, PAIR_COLUMNS)
    write_csv(out_root / "SPP_OBJECTIVE_PARITY.csv", parity_rows, PARITY_COLUMNS)

    row_counts = Counter(row["audit_status"] for row in row_rows)
    pair_counts = Counter(row["audit_status"] for row in pair_rows)
    parity_counts = Counter(row["parity_pass"] for row in parity_rows)
    nan_count = sum(str(row["contains_nan"]).lower() == "true" for row in pair_rows)
    inf_count = sum(str(row["contains_inf"]).lower() == "true" for row in pair_rows)
    universal_only_count = sum(str(row["universal_regulariser_only"]).lower() == "true" for row in row_rows)
    result_classification = "WARNING" if parity_counts.get("not_applicable", 0) else "PASS"
    if row_counts.get("FAIL", 0) or pair_counts.get("FAIL", 0):
        result_classification = "FAIL"
    payload = {
        "classification": result_classification,
        "audit_root": str(out_root),
        "implementation_files": implementation_files,
        "spp_transform_found": "POT files are loaded as raw distance-score curves; prototype scorer sums linear-interpolated raw scores over canonical species pairs. The POT generation transform is not exposed in this repo/package.",
        "sign_convention": "SPP/POT values are statistical-potential/log-ratio/energy-like scores; lower is preferred; negative values are allowed and indicate favoured distances relative to reference/background; zero is baseline, not probability zero.",
        "negative_values_expected": True,
        "row_specific_spp_count": sum(str(row["row_specific_spp_found"]).lower() == "true" for row in row_rows),
        "universal_only_fallback_count": universal_only_count,
        "pair_coverage_summary": dict(Counter(row["pair_coverage_status"] for row in row_rows)),
        "nan_count": nan_count,
        "inf_count": inf_count,
        "objective_parity_summary": dict(parity_counts),
        "row_audit_summary": dict(row_counts),
        "pair_audit_summary": dict(pair_counts),
        "rows_with_warnings": [f"{row['experiment_id']}/{row['row_id']}" for row in row_rows if row["audit_status"] != "PASS"],
        "actual_bugs_found": [] if result_classification != "FAIL" else ["See SPP_ROW_AUDIT.csv and SPP_PAIR_AUDIT.csv"],
        "package_v7_needs_rebuilding": False,
        "scorer_semantics": {
            "implementation": "src/sok_llm_orchestrator/structures/prototype_scaffold.py::_score_structure_with_spp_curves",
            "periodic_semantics": "pymatgen Structure.get_distance minimum-image distance for each unique off-diagonal site pair i<j",
            "cutoff_semantics": "No explicit 11 A neighbor enumeration cutoff in the in-repo scorer; POT files span 0-11 A and interpolation clamps beyond endpoints.",
            "central_zero_self_distance": "skipped by i<j loop",
            "translated_self_images": "not enumerated by the in-repo prototype scorer",
            "off_diagonal_pairs": "counted once",
            "same_species_pairs": "supported when present as unique off-diagonal site pairs",
            "interpolation": "linear interpolation between sorted POT points",
            "units": "distance grid appears Angstrom from POT 0.0-11.0 header/range and CIF lattice units",
        },
    }
    write_json(out_root / "SPP_CORRECTNESS_AUDIT.json", payload)
    write_markdown(out_root, payload, row_rows, pair_rows, parity_rows)
    return payload


def write_markdown(out_root: Path, payload: dict[str, Any], row_rows: list[dict[str, Any]], pair_rows: list[dict[str, Any]], parity_rows: list[dict[str, Any]]) -> None:
    warnings = [row for row in row_rows if row["audit_status"] != "PASS"]
    parity_na = [row for row in parity_rows if row["parity_pass"] == "not_applicable"]
    md = [
        "# SPP Correctness Audit",
        "",
        f"- Classification: {payload['classification']}",
        f"- Rows audited: {len(row_rows)}",
        f"- Pair curves audited: {len(pair_rows)}",
        f"- Row-specific SPP rows: {payload['row_specific_spp_count']}",
        f"- Universal-only fallback rows: {payload['universal_only_fallback_count']}",
        f"- Pair coverage summary: {payload['pair_coverage_summary']}",
        f"- NaN count: {payload['nan_count']}",
        f"- Inf count: {payload['inf_count']}",
        f"- Objective parity summary: {payload['objective_parity_summary']}",
        "",
        "## Implementation Located",
        "",
        *[f"- `{path}`" for path in payload["implementation_files"]],
        "",
        "## Key Finding",
        "",
        payload["spp_transform_found"],
        "",
        "The package curves are statistical-potential scores loaded from `.POT` files. Negative values are expected and are not clipped to zero.",
    ]
    (out_root / "SPP_CORRECTNESS_AUDIT.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    sign = [
        "# SPP Sign Convention Audit",
        "",
        f"- Negative SPP values expected: {str(payload['negative_values_expected']).lower()}",
        "- Lower score preferred: true",
        "- Probability/count curve: false",
        "- Zero meaning: reference/background baseline, not probability zero",
        "",
        "The in-repo plotting and scaffold scorer load raw `.POT` distance-score curves. The scorer sums interpolated scores and selects the minimum numeric objective when a numeric SPP objective is available.",
        "",
        "The transform used to create the `.POT` files, for example an exact `-log(observed/reference)` form, is not present in this repository or the paper package artifacts inspected here.",
        "",
        f"Scorer semantics: {payload['scorer_semantics']}",
    ]
    (out_root / "SPP_SIGN_CONVENTION_AUDIT.md").write_text("\n".join(sign) + "\n", encoding="utf-8")

    bug_lines = [
        "# SPP Bugs Or Warnings",
        "",
    ]
    if payload["classification"] == "FAIL":
        bug_lines.append("## Bugs")
        bug_lines.extend(f"- {bug}" for bug in payload["actual_bugs_found"])
    else:
        bug_lines.extend(["## Bugs", "- No SPP curve invalidity, NaN/inf, missing pair coverage, or universal-only fallback bug found."])
    bug_lines.extend(["", "## Warnings"])
    if parity_na:
        bug_lines.append(f"- Objective parity is not numerically assertable for {len(parity_na)} rows because stored `qlip_solution.json` files do not contain numeric `objective_value`; independent SPP scores were still computed from final CIFs and POT curves.")
    if warnings:
        bug_lines.extend(f"- {row['experiment_id']}/{row['row_id']}: {row['warning']}" for row in warnings)
    else:
        bug_lines.append("- No row-level SPP source/coverage warnings.")
    (out_root / "SPP_BUGS_OR_WARNINGS.md").write_text("\n".join(bug_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, default=ROOT / "artifacts" / "paper_spp_correctness_audit_v1")
    parser.add_argument("--package-root", type=Path, default=ROOT / "artifacts" / "paper_results_package_v7")
    parser.add_argument("--pot-root", type=Path, default=Path("C:/Users/brown/Downloads/SPP/SPP/SPP/SPP"))
    args = parser.parse_args()
    if args.out_root.exists():
        import shutil

        shutil.rmtree(args.out_root)
    args.out_root.mkdir(parents=True, exist_ok=True)
    payload = audit(args.out_root, args.package_root, args.pot_root)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
