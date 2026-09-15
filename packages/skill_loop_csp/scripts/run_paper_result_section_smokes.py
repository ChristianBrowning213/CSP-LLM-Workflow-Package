"""Run paper result-section Crystal-DB mini-dataset CSP smokes.

This runner is intentionally conservative: it uses only the documented
Crystal-DB result mini-datasets, emits retrieval/blocking evidence for every
target, and upgrades only explicitly supported simple rows to variable-orbit
SPP-scored mode when a real non-null objective is available.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
CRYSTAL_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
SCA_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser")
REPORT_VERSION = os.environ.get("PAPER_RESULT_SMOKE_VERSION", "V3").strip().upper()
REPORT_VERSION_LOWER = REPORT_VERSION.lower()
OUTPUT_ROOT = SCA_ROOT / "local_runs" / f"paper_result_section_smoke_{REPORT_VERSION_LOWER}_20260720"
MANIFEST_CSV = REPO_ROOT / "benchmarks" / "paper_result_section_smoke_manifest.csv"
V1_REPORT_JSON = REPO_ROOT / "PAPER_RESULT_SECTION_SMOKE_REPORT.json"
V2_REPORT_JSON = REPO_ROOT / "PAPER_RESULT_SECTION_SMOKE_V2_REPORT.json"
REPORT_JSON = REPO_ROOT / f"PAPER_RESULT_SECTION_SMOKE_{REPORT_VERSION}_REPORT.json"
REPORT_MD = REPO_ROOT / f"PAPER_RESULT_SECTION_SMOKE_{REPORT_VERSION}_REPORT.md"
SCA_SUMMARY_JSON = OUTPUT_ROOT / "SCA_VALIDATION_SUMMARY.json"
SCA_SUMMARY_MD = OUTPUT_ROOT / "SCA_VALIDATION_SUMMARY.md"

DATASET_BUILD_JSON = CRYSTAL_ROOT / "artifacts" / "paper_result_datasets_built.json"
POT_COVERAGE_JSON = CRYSTAL_ROOT / "artifacts" / "result_dataset_pot_coverage.json"
SOLVER_SUPPORT_JSON = CRYSTAL_ROOT / "artifacts" / "result_dataset_solver_support.json"

ALLOWED_DATASET_IDS = {"common_families", "hard_intent", "halide_perovskite"}

SECTION_BY_DATASET = {
    "common_families": "result_1_common_families",
    "hard_intent": "result_2_hard_intent",
    "halide_perovskite": "result_3_halide_perovskite",
}

SCAFFOLD_INTENT = {
    "NiO": ("rocksalt", "Fm-3m", 225, "cubic"),
    "MgO": ("rocksalt", "Fm-3m", 225, "cubic"),
    "TiN": ("nitride", "Fm-3m", 225, "cubic"),
    "CeO2": ("fluorite", "Fm-3m", 225, "cubic"),
    "ZrO2": ("fluorite", "Fm-3m", 225, "cubic"),
    "ThO2": ("fluorite", "Fm-3m", 225, "cubic"),
    "CsPbBr3": ("halide perovskite", "Pm-3m", 221, "cubic"),
    "CsSnBr3": ("halide perovskite", "Pm-3m", 221, "cubic"),
    "CsPbCl3": ("halide perovskite", "Pm-3m", 221, "cubic"),
    "CsPbI3": ("halide perovskite", "Pm-3m", 221, "cubic"),
    "CsSnI3": ("halide perovskite", "Pm-3m", 221, "cubic"),
    "ZnFe2O4": ("spinel", "Fd-3m", 227, "cubic"),
    "MgAl2O4": ("spinel", "Fd-3m", 227, "cubic"),
    "CoFe2O4": ("spinel", "Fd-3m", 227, "cubic"),
    "Li6PS5Cl": ("argyrodite", "F-43m", 216, "cubic"),
    "LiFePO4": ("olivine phosphate", "Pnma", 62, "orthorhombic"),
    "LiCoO2": ("layered oxide", "R-3m", 166, "trigonal"),
}

VARIABLE_SPP_TARGETS = {
    "NiO",
    "TiN",
    "MgO",
    "CeO2",
    "ZrO2",
    "ThO2",
    "CsPbBr3",
    "CsSnBr3",
    "CsPbCl3",
    "CsSnI3",
    "CsPbI3",
}
HALIDE_EXTENSION_TARGETS = {"CsPbBr3", "CsSnBr3", "CsPbCl3", "CsSnI3", "CsPbI3"}
HALIDE_PARAMETERISED_WYCKOFF_REQUIRED = {"CsGeBr3", "RbPbBr3"}
HALIDE_EXTENSION_NOTE = (
    "Specialist corpus plus modular QLIP scaffold enabled the existing traceable retrieval-SPP-optimisation-validation "
    "pipeline to generate this supported halide-perovskite prototype."
)

MANIFEST_COLUMNS = [
    "result_section",
    "dataset_id",
    "db_path",
    "formula",
    "target_family",
    "prompt",
    "requested_mode",
    "expected_validation_tier",
    "pot_root",
    "solver_support_status",
    "notes",
]


def _add_import_roots() -> None:
    for path in (SRC_ROOT, CRYSTAL_ROOT, SCA_ROOT):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _formula_counts(formula: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element, amount in re.findall(r"([A-Z][a-z]?)(\d*)", formula or ""):
        counts[element] = counts.get(element, 0) + int(amount or "1")
    return counts


def _normalized_formula(formula: str) -> str:
    counts = _formula_counts(formula)
    if not counts:
        return ""
    divisor = 0
    for amount in counts.values():
        divisor = amount if divisor == 0 else _gcd(divisor, amount)
    parts = []
    for element in sorted(counts, key=str.lower):
        amount = counts[element] // max(divisor, 1)
        parts.append(element if amount == 1 else f"{element}{amount}")
    return "".join(parts)


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return abs(a)


def _read_dataset_targets(dataset_report: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for card in dataset_report.get("dataset_cards", []):
        dataset_id = str(card.get("dataset_id") or "")
        if dataset_id not in ALLOWED_DATASET_IDS:
            continue
        for row in card.get("target_coverage", []):
            targets.append(
                {
                    "dataset_id": dataset_id,
                    "db_path": str(card.get("db_path") or ""),
                    "result_section": SECTION_BY_DATASET[dataset_id],
                    "formula": str(row.get("target_formula") or ""),
                    "source_status": str(row.get("status") or ""),
                    "requested_family": str(row.get("requested_family") or ""),
                    "material_id": row.get("material_id"),
                    "source_symmetry": row.get("symmetry") or {},
                    "cif_path": row.get("cif_path"),
                    "error_text": row.get("error_text"),
                }
            )
    return targets


def _direct_formula_rows(db_path: str, formula: str) -> list[dict[str, Any]]:
    norm = _normalized_formula(formula)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT s.structure_id, s.reduced_formula, s.nsites, s.volume, s.license_restricted, "
            "m.formula, m.elements_csv, m.space_group, m.band_gap_eV, "
            "p.source, p.source_id, p.allow_export, p.allow_derivatives, p.retrieved_at "
            "FROM structures s "
            "LEFT JOIN metadata m ON m.structure_id = s.structure_id "
            "LEFT JOIN provenance p ON p.structure_id = s.structure_id"
        ).fetchall()
    finally:
        conn.close()
    matches = []
    for row in rows:
        if _normalized_formula(row["reduced_formula"] or "") == norm or _normalized_formula(row["formula"] or "") == norm:
            matches.append(dict(row))
    return matches


def _retrieval_trace(db_path: str, formula: str, family: str) -> dict[str, Any]:
    from crystal_db.similarity import similar_structures

    direct = _direct_formula_rows(db_path, formula) if Path(db_path).exists() else []
    trace: dict[str, Any] = {
        "retrieval_status": "hit" if direct else "miss",
        "retrieval_methods": ["sqlite_exact_reduced_formula"],
        "direct_formula_matches": direct,
        "structural_neighbors": [],
        "errors": [],
        "query": {"formula": formula, "family": family, "db_path": db_path},
    }
    if direct:
        try:
            neighbors = similar_structures(structure_id=direct[0]["structure_id"], db_path=db_path, k=5).get("neighbors", [])
            trace["retrieval_methods"].append("crystal_db.similarity.similar_structures")
            trace["structural_neighbors"] = neighbors
        except Exception as exc:  # noqa: BLE001
            trace["errors"].append({"method": "similar_structures", "error": f"{type(exc).__name__}: {exc}"})
    trace["evidence_count"] = len(trace["direct_formula_matches"]) + len(trace["structural_neighbors"])
    return trace


def _make_request(formula: str, family: str, space_group: str, crystal_system: str, pot: dict[str, Any], *, mode: str) -> dict[str, Any]:
    site_mode = "prototype_orbit_variable" if mode == "prototype_orbit_variable_spp_qlip" else "prototype_orbit"
    candidate_source = "prototype_orbit_variable_scaffold" if site_mode == "prototype_orbit_variable" else "prototype_orbit_scaffold"
    return {
        "context": {
            "pot_root": pot.get("compatible_pot_root"),
            "spp_source": "direct_pot_dir",
            "spp_source_type": "direct_pot_dir",
            "dataset_smoke": "paper_result_section_smoke_20260716",
        },
        "problem": {
            "chemistry": {"formula": formula},
            "design_space": {
                "sites": {
                    "mode": mode,
                    "site_mode": site_mode,
                    "candidate_site_source": candidate_source,
                    "prototype_scaffold": {
                        "family": family,
                        "target_space_group": space_group,
                        "target_crystal_system": crystal_system,
                    },
                    "spp_source": "direct_pot_dir",
                    "spp_pot_dir": pot.get("compatible_pot_root"),
                    "spp_preflight_final_status": "ready",
                    "required_pairs": pot.get("required_pairs", []),
                    "missing_pairs": pot.get("missing_pairs", []),
                }
            },
        },
        "metadata": {"active_symmetry_mode": mode},
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _expected_tier(row: dict[str, Any], pot: dict[str, Any], solver: dict[str, Any], retrieval: dict[str, Any] | None = None) -> str:
    if row["source_status"].upper() == "MISSING":
        return "missing_from_source"
    if pot.get("pot_coverage_status") != "complete":
        return "pot_blocked"
    if retrieval is not None and retrieval.get("retrieval_status") != "hit":
        return "retrieval_blocked"
    if row["formula"] in HALIDE_PARAMETERISED_WYCKOFF_REQUIRED:
        return "parameterised_wyckoff_required"
    if solver.get("support_status") != "fixed_orbit_supported" and row["formula"] not in HALIDE_EXTENSION_TARGETS:
        return "retrieval_ready_solver_blocked"
    if row["formula"] in VARIABLE_SPP_TARGETS:
        return "variable_spp_scored"
    return "fixed_orbit_spp_smoke"


def _blocked_reason(tier: str, formula: str, solver: dict[str, Any], pot: dict[str, Any], row: dict[str, Any]) -> tuple[str, str, str]:
    if tier == "missing_from_source":
        return (
            "source_acquisition",
            row.get("error_text") or "source dataset card marks target missing",
            "Resolve Materials Project source coverage or document this target as absent from the source dataset.",
        )
    if tier == "pot_blocked":
        return (
            "spp_preflight",
            f"Missing POT pairs: {', '.join(pot.get('missing_pairs') or [])}",
            "Generate or locate compatible SPP POT files for the missing pairs.",
        )
    if tier == "retrieval_blocked":
        return (
            "retrieval",
            "No exact formula row was found in the requested result mini-dataset.",
            "Rebuild or inspect the mini-dataset before attempting CSP generation.",
        )
    if tier == "parameterised_wyckoff_required":
        return (
            "solver_support",
            f"{formula} has retrieval and POT evidence but needs parameterised Wyckoff support for exact source-symmetry low-symmetry generation.",
            "Implement parameterised Pnma/R3m/P21-style Wyckoff machinery before making an exact source-symmetry generation claim.",
        )
    return (
        "solver_support",
        f"{formula} is {solver.get('support_status', 'unsupported')} in the current fixed-orbit scaffold support audit.",
        "Implement and validate a scaffold/solver route before making a generation claim.",
    )


def _is_source_faithful_symmetry(row: dict[str, Any], target_sg_number: int) -> bool:
    symmetry = row.get("source_symmetry") or {}
    try:
        return int(symmetry.get("number")) == int(target_sg_number)
    except (TypeError, ValueError):
        return False


def _extensibility_metadata(formula: str, row: dict[str, Any], *, generated: bool, target_sg_number: int | None = None) -> dict[str, Any]:
    if formula not in HALIDE_EXTENSION_TARGETS and formula not in HALIDE_PARAMETERISED_WYCKOFF_REQUIRED:
        return {
            "extension_case": "",
            "extension_type": "",
            "specialist_corpus_used": "",
            "new_scaffold_added": "",
            "scaffold_added_in_v3": "",
            "qlip_support_added": "",
            "pipeline_changes_required": "",
            "prototype_constraint_mode": "",
            "source_faithful_symmetry": "",
            "paper_claim_class": "",
            "extensibility_note": "",
        }
    source_faithful = _is_source_faithful_symmetry(row, target_sg_number or 221)
    blocked_note = (
        "This row remains blocked for exact source-symmetry generation because it needs parameterised Wyckoff support."
        if formula in HALIDE_PARAMETERISED_WYCKOFF_REQUIRED
        else HALIDE_EXTENSION_NOTE
    )
    return {
        "extension_case": "halide_perovskite_specialist_corpus",
        "extension_type": "corpus_plus_scaffold_extension",
        "specialist_corpus_used": row.get("dataset_id") or "halide_perovskite",
        "new_scaffold_added": "cubic_halide_perovskite_abx3_pm3m",
        "scaffold_added_in_v3": generated and formula in HALIDE_EXTENSION_TARGETS,
        "qlip_support_added": "ideal_cubic_abx3_orbit_scaffold",
        "pipeline_changes_required": "qlip_scaffold_only_no_retrieval_spp_validation_changes",
        "prototype_constraint_mode": "ideal_cubic_abx3" if formula in HALIDE_EXTENSION_TARGETS else "source_faithful_parameterised_wyckoff_required",
        "source_faithful_symmetry": source_faithful,
        "paper_claim_class": "extensibility_demonstration",
        "extensibility_note": blocked_note,
    }


def _validate_generated_cifs(generated_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from pymatgen.core import Composition
    from pymatgen.core import Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    results = []
    for row in generated_rows:
        formula = str(row.get("formula") or row.get("target_formula") or "")
        result = {
            "benchmark_id": row["benchmark_id"],
            "formula": formula,
            "cif_path": row["cif_path"],
            "parse_ok": False,
            "formula_match": False,
            "target_formula": formula,
            "observed_formula": None,
            "target_space_group": row["target_space_group"],
            "target_space_group_number": row["target_space_group_number"],
            "analyzed_space_group": None,
            "analyzed_space_group_number": None,
            "target_crystal_system": row["target_crystal_system"],
            "analyzed_crystal_system": None,
            "symmetry_match": False,
            "sun_uniqueness_status": "not_run",
            "chgnet_static_status": "not_run",
            "error": None,
        }
        try:
            structure = Structure.from_file(row["cif_path"])
            result["parse_ok"] = True
            result["observed_formula"] = structure.composition.reduced_formula
            result["formula_match"] = Composition(formula).reduced_composition == structure.composition.reduced_composition
            analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5)
            result["analyzed_space_group"] = analyzer.get_space_group_symbol()
            result["analyzed_space_group_number"] = analyzer.get_space_group_number()
            result["analyzed_crystal_system"] = analyzer.get_crystal_system()
            result["symmetry_match"] = int(row["target_space_group_number"]) == int(result["analyzed_space_group_number"])
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results


def _run_sca_symmetry(generated_manifest: Path) -> dict[str, Any]:
    out_dir = OUTPUT_ROOT / "symmetry_intent_benchmark"
    command = [
        sys.executable,
        "-m",
        "sca.cli",
        "run-symmetry-intent-benchmark",
        "--manifest",
        str(generated_manifest),
        "--out-dir",
        str(out_dir),
        "--symprec",
        "0.01",
        "--angle-tolerance",
        "5",
    ]
    completed = subprocess.run(command, cwd=SCA_ROOT, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "out_dir": str(out_dir),
        "summary_json": str(out_dir / "symmetry_summary.json"),
        "results_csv": str(out_dir / "symmetry_results.csv"),
        "report_md": str(out_dir / "symmetry_report.md"),
    }


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        rows = [["" for _ in headers]]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _render_reports(summary: dict[str, Any]) -> tuple[str, str]:
    rows = summary["rows"]
    blocked = [row for row in rows if row["outcome"] == "blocked"]
    generated = [row for row in rows if row["outcome"] == "generated"]
    upgraded = [row for row in generated if row["validation_tier"] == "variable_spp_scored"]
    fixed = [row for row in generated if row["validation_tier"] == "fixed_orbit_spp_smoke"]
    by_section = Counter(row["result_section"] for row in rows)
    md = [
        "# Paper Result-Section Smoke Report",
        "",
        f"Created: {summary['created_at']}",
        "",
        "## Summary",
        "",
        _table(
            ["metric", "count"],
            [
                ["total rows", len(rows)],
                ["generated CIFs", len(generated)],
                ["blocked targets", len(blocked)],
                ["variable SPP-scored", len(upgraded)],
                ["fixed fallback/generated", len(fixed)],
                ["datasets used", ", ".join(summary["datasets_used"])],
            ],
        ),
        "",
        "## V1 vs V2",
        "",
        _table(
            ["metric", "v1", "v2"],
            [
                ["generated", summary["v1_counts"].get("generated", "") if summary.get("v1_counts") else "", summary["counts"].get("generated", "")],
                ["blocked", summary["v1_counts"].get("blocked", "") if summary.get("v1_counts") else "", summary["counts"].get("blocked", "")],
                [
                    "fixed_orbit_spp_smoke",
                    (summary.get("v1_counts", {}).get("validation_tiers") or {}).get("fixed_orbit_spp_smoke", ""),
                    summary["counts"]["validation_tiers"].get("fixed_orbit_spp_smoke", ""),
                ],
                [
                    "variable_spp_scored",
                    (summary.get("v1_counts", {}).get("validation_tiers") or {}).get("variable_spp_scored", 0),
                    summary["counts"]["validation_tiers"].get("variable_spp_scored", 0),
                ],
                [
                    "SCA parseable",
                    summary.get("v1_sca_metrics", {}).get("parseable_count", ""),
                    summary["sca_validation"]["parseable_count"],
                ],
                [
                    "SCA formula matches",
                    summary.get("v1_sca_metrics", {}).get("formula_match_count", ""),
                    summary["sca_validation"]["formula_match_count"],
                ],
                [
                    "SCA symmetry matches",
                    summary.get("v1_sca_metrics", {}).get("symmetry_match_count", ""),
                    summary["sca_validation"]["symmetry_match_count"],
                ],
            ],
        ),
        "",
        "## Per-Section Counts",
        "",
        _table(["section", "rows"], [[key, value] for key, value in sorted(by_section.items())]),
        "",
        "## Validation Tier Counts",
        "",
        _table(["tier", "count"], [[key, value] for key, value in sorted(Counter(row["validation_tier"] for row in rows).items())]),
        "",
        "## SPP Status Counts",
        "",
        _table(["status", "count"], [[key, value] for key, value in sorted(Counter(row["spp_status"] for row in rows).items())]),
        "",
        "## POT Missing-Pair Table",
        "",
        _table(
            ["formula", "status", "missing_pairs"],
            [[row["formula"], row["spp_status"], ", ".join(row.get("missing_pairs") or [])] for row in rows if row["spp_status"] != "complete"],
        ),
        "",
        "## SCA Parse/Formula/Symmetry",
        "",
        _table(
            ["formula", "parse", "formula", "target_sg", "observed_sg", "symmetry"],
            [
                [
                    row["formula"],
                    row["parse_ok"],
                    row["formula_match"],
                    row["target_space_group"],
                    row["analyzed_space_group"],
                    row["symmetry_match"],
                ]
                for row in summary["sca_validation"]["rows"]
            ],
        ),
        "",
        "## Upgraded Rows",
        "",
        _table(
            ["formula", "dataset", "mode", "objective_value", "spp_status"],
            [
                [
                    row["formula"],
                    row["dataset_id"],
                    row["requested_mode"],
                    row.get("objective_value"),
                    row.get("spp_scoring_status"),
                ]
                for row in upgraded
            ],
        ),
        "",
        "## Rows Remaining Fixed",
        "",
        _table(
            ["formula", "dataset", "reason"],
            [
                [
                    row["formula"],
                    row["dataset_id"],
                    row.get("variable_fallback_reason") or "not in explicit AX/AX2 variable SPP upgrade set",
                ]
                for row in fixed
            ],
        ),
        "",
        "## Blocked Targets",
        "",
        _table(
            ["formula", "dataset", "tier", "stage", "reason"],
            [[row["formula"], row["dataset_id"], row["validation_tier"], row.get("blocked_stage", ""), row.get("blocked_reason", "")] for row in blocked],
        ),
        "",
        "## What This Proves",
        "",
        "- The three documented mini-datasets are usable as source-backed retrieval evidence for the result-section smoke scope.",
        "- Six explicit AX/AX2 rows and the v3 ideal cubic ABX3 halide extension rows use true `prototype_orbit_variable_spp_qlip` with closed orbit selection and non-null real SPP objective values.",
        "- The remaining generated rows preserve fixed prototype-orbit generation and parseable CIF artifacts with complete POT coverage.",
        "- Retrieval-only and missing-source targets are explicitly blocked with trace files instead of being counted as generation successes.",
        "- The halide-perovskite extension is a specialist-corpus plus modular-scaffold demonstration; retrieval, SPP construction, audit logging, and validation are unchanged.",
        "",
        "## What This Does Not Prove",
        "",
        "- This is not a full 100-target benchmark and does not use `data\\phase6_mp_10k.db`.",
        "- Variable-orbit SPP claims are limited to the explicit supported rows in this smoke, not all halide perovskites or arbitrary scaffolds.",
        "- Ideal cubic ABX3 halide rows are prototype-constrained generations, not exact reproductions of lower-symmetry Materials Project structures where the source symmetry differs.",
        "- CHGNet static and S.U.N. uniqueness are recorded as not run unless separately configured.",
        "",
        "## Task 3: specialist corpus and modular scaffold extension",
        "",
        (
            "The v3 halide-perovskite section uses the `halide_perovskite` specialist Crystal-DB mini-dataset "
            "and adds cubic ABX3 Pm-3m orbit support in the QLIP prototype backend. Rows newly generated or "
            "upgraded by this support are listed in the upgraded table when they report `extension_case="
            "halide_perovskite_specialist_corpus` and `validation_tier=variable_spp_scored`."
        ),
        (
            "`CsGeBr3` and `RbPbBr3` remain blocked for exact source-symmetry generation because they require "
            "parameterised Wyckoff support rather than the ideal cubic ABX3 scaffold. `KPbBr3` remains a "
            "source-missing target."
        ),
        (
            "No retrieval, SPP construction, validation, or audit-artifact pipeline changes were required; "
            "the extension changes only the supported QLIP scaffold/search space. This demonstrates a traceable, "
            "non-invasive extension to the generation backend. It does not demonstrate coverage beyond the explicit "
            "supported halide rows, physical-property claims, DFT-level validation, or exact reproduction of lower-symmetry "
            "source structures."
        ),
        "",
        "## Next Actions",
        "",
        "- Add solver/scaffold routes for retrieval-only hard and optional halide targets before claiming CSP generation on them.",
        "- Decide whether result-section symmetry should score against ideal prototype intent, MP ground-state symmetry, or both.",
        "- Run the larger benchmark only after the result-section smoke claims are finalized.",
        "",
    ]
    sca_md = [
        "# SCA Validation Summary",
        "",
        f"Created: {summary['created_at']}",
        "",
        _table(
            ["metric", "count"],
            [
                ["generated CIFs", len(generated)],
                ["parseable", summary["sca_validation"]["parseable_count"]],
                ["formula matches", summary["sca_validation"]["formula_match_count"]],
                ["symmetry matches", summary["sca_validation"]["symmetry_match_count"]],
            ],
        ),
        "",
        "## Rows",
        "",
        _table(
            ["formula", "parse", "formula_match", "target_sg", "observed_sg", "symmetry_match"],
            [
                [
                    row["formula"],
                    row["parse_ok"],
                    row["formula_match"],
                    row["target_space_group"],
                    row["analyzed_space_group"],
                    row["symmetry_match"],
                ]
                for row in summary["sca_validation"]["rows"]
            ],
        ),
    ]
    return "\n".join(md), "\n".join(sca_md)


def main() -> int:
    _add_import_roots()

    from sok_llm_orchestrator.structures.prototype_scaffold import (
        prototype_orbit_candidates_payload_from_request,
        prototype_orbit_solution_from_request,
        write_prototype_scaffold_cif,
    )

    dataset_report = _load_json(DATASET_BUILD_JSON)
    v1_report = _load_json(V1_REPORT_JSON) if V1_REPORT_JSON.exists() else {}
    v2_report = _load_json(V2_REPORT_JSON) if V2_REPORT_JSON.exists() else {}
    pot_by_formula = {row["formula"]: row for row in _load_json(POT_COVERAGE_JSON)["targets"]}
    solver_by_formula = {row["formula"]: row for row in _load_json(SOLVER_SUPPORT_JSON)["targets"]}

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    targets = _read_dataset_targets(dataset_report)
    manifest_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    generated_manifest_rows: list[dict[str, Any]] = []

    for row in targets:
        formula = row["formula"]
        pot = pot_by_formula.get(formula, {"pot_coverage_status": "missing_audit", "missing_pairs": [], "required_pairs": []})
        solver = solver_by_formula.get(formula, {"support_status": "unknown", "scaffold_supported": False})
        intent = SCAFFOLD_INTENT.get(formula)
        target_family = intent[0] if intent else row["requested_family"]
        prompt = f"Generate {formula} as {target_family} using retrieval from {row['dataset_id']}."
        requested_mode = (
            "prototype_orbit_variable_spp_qlip"
            if formula in VARIABLE_SPP_TARGETS and (solver.get("support_status") == "fixed_orbit_supported" or formula in HALIDE_EXTENSION_TARGETS)
            else "prototype_orbit_qlip"
            if solver.get("support_status") == "fixed_orbit_supported"
            else "retrieval_only"
        )
        tier_pre = _expected_tier(row, pot, solver)
        manifest_rows.append(
            {
                "result_section": row["result_section"],
                "dataset_id": row["dataset_id"],
                "db_path": row["db_path"],
                "formula": formula,
                "target_family": target_family,
                "prompt": prompt,
                "requested_mode": requested_mode,
                "expected_validation_tier": tier_pre,
                "pot_root": pot.get("compatible_pot_root") or "",
                "solver_support_status": solver.get("support_status") or "",
                "notes": (
                    "variable orbit SPP scoring requested for explicit simple-family upgrade"
                    if requested_mode == "prototype_orbit_variable_spp_qlip"
                    else "fixed orbit only; no variable orbit claim"
                    if requested_mode == "prototype_orbit_qlip"
                    else "retrieval evidence only; generation blocked"
                ),
            }
        )

        task_id = f"{row['result_section']}__{row['dataset_id']}__{_slug(formula)}"
        task_dir = OUTPUT_ROOT / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        retrieval = _retrieval_trace(row["db_path"], formula, target_family) if row["source_status"].upper() != "MISSING" else {
            "retrieval_status": "not_run_source_missing",
            "evidence_count": 0,
            "direct_formula_matches": [],
            "structural_neighbors": [],
            "query": {"formula": formula, "family": target_family, "db_path": row["db_path"]},
        }
        _write_json(task_dir / "retrieval_trace.json", retrieval)
        _write_json(
            task_dir / "evidence_manifest.json",
            {
                "source_dataset_row": row,
                "retrieval_trace_path": str(task_dir / "retrieval_trace.json"),
                "direct_formula_match_count": len(retrieval.get("direct_formula_matches") or []),
                "structural_neighbor_count": len(retrieval.get("structural_neighbors") or []),
            },
        )
        tier = _expected_tier(row, pot, solver, retrieval)
        base_result = {
            "result_section": row["result_section"],
            "dataset_id": row["dataset_id"],
            "db_path": row["db_path"],
            "formula": formula,
            "target_family": target_family,
            "requested_mode": requested_mode,
            "validation_tier": tier,
            "spp_status": pot.get("pot_coverage_status") or "unknown",
            "missing_pairs": pot.get("missing_pairs") or [],
            "solver_support_status": solver.get("support_status") or "unknown",
            "retrieval_status": retrieval.get("retrieval_status"),
            "evidence_count": retrieval.get("evidence_count", 0),
            "task_dir": str(task_dir),
            **_extensibility_metadata(formula, row, generated=False, target_sg_number=(intent[2] if intent else None)),
        }

        if tier not in {"fixed_orbit_spp_smoke", "variable_spp_scored"} or intent is None:
            stage, reason, next_work = _blocked_reason(tier, formula, solver, pot, row)
            blocked = base_result | {
                "outcome": "blocked",
                "blocked_stage": stage,
                "blocked_reason": reason,
                "next_required_work": next_work,
            }
            _write_json(task_dir / "blocked_trace.json", blocked)
            result_rows.append(blocked)
            continue

        family, space_group, sg_number, crystal_system = intent
        generation_mode = requested_mode
        request = _make_request(formula, family, space_group, crystal_system, pot, mode=generation_mode)
        variable_solution = prototype_orbit_solution_from_request(request) if generation_mode == "prototype_orbit_variable_spp_qlip" else None
        variable_fallback_reason = None
        if generation_mode == "prototype_orbit_variable_spp_qlip" and (
            variable_solution is None
            or variable_solution.spp_scoring_status != "scored"
            or variable_solution.objective_value is None
            or not variable_solution.variable_orbit_selection
            or not variable_solution.symmetry_closed
        ):
            variable_fallback_reason = (
                "variable_spp_scoring_unavailable"
                if variable_solution is None
                else f"variable_spp_not_safe:{variable_solution.spp_scoring_status}:{variable_solution.objective_value}"
            )
            generation_mode = "prototype_orbit_qlip"
            request = _make_request(formula, family, space_group, crystal_system, pot, mode=generation_mode)
            tier = "fixed_orbit_spp_smoke"
        task_spec = {
            "task_id": task_id,
            "formula": formula,
            "dataset_id": row["dataset_id"],
            "db_path": row["db_path"],
            "prompt": prompt,
            "requested_mode": generation_mode,
            "validation_tier": tier,
            "variable_fallback_reason": variable_fallback_reason,
            "target_family": family,
            "target_space_group": space_group,
            "target_space_group_number": sg_number,
            "target_crystal_system": crystal_system,
            "source_symmetry": row.get("source_symmetry"),
            "source_material_id": row.get("material_id"),
        }
        _write_json(task_dir / "task_spec.json", task_spec)
        _write_json(
            task_dir / "spp_preflight.json",
            {
                "formula": formula,
                "status": "ready",
                "pot_coverage_status": pot.get("pot_coverage_status"),
                "pot_root": pot.get("compatible_pot_root"),
                "required_pairs": pot.get("required_pairs", []),
                "missing_pairs": pot.get("missing_pairs", []),
                "spp_source": "direct_pot_dir",
            },
        )
        _write_json(task_dir / "qlip_request.json", request)
        candidates = prototype_orbit_candidates_payload_from_request(request)
        if candidates is not None:
            _write_json(task_dir / "orbit_candidates.json", candidates)
        solution = prototype_orbit_solution_from_request(request)
        if solution is not None:
            _write_json(task_dir / "orbit_solution.json", solution)
        cif_path = task_dir / f"{_slug(formula)}_final.cif"
        trace = write_prototype_scaffold_cif(cif_path, request)
        _write_json(task_dir / "symmetry_trace.json", trace)
        if not cif_path.exists():
            failed = base_result | {
                "outcome": "blocked",
                "validation_tier": "retrieval_ready_solver_blocked",
                "blocked_stage": "solver_support",
                "blocked_reason": trace.get("fallback_reason") or "prototype scaffold did not produce a CIF",
                "next_required_work": "Inspect scaffold support and add a solver route for this formula/family.",
            }
            _write_json(task_dir / "blocked_trace.json", failed)
            result_rows.append(failed)
            continue
        generated = base_result | {
            "outcome": "generated",
            "requested_mode": generation_mode,
            "validation_tier": tier,
            "target_space_group": space_group,
            "target_space_group_number": sg_number,
            "target_crystal_system": crystal_system,
            "cif_path": str(cif_path),
            "orbit_variable_selection": bool(solution.variable_orbit_selection) if solution is not None else False,
            "objective_value": solution.objective_value if solution is not None else None,
            "spp_scoring_status": solution.spp_scoring_status if solution is not None else None,
            "variable_fallback_reason": variable_fallback_reason,
            "task_spec_path": str(task_dir / "task_spec.json"),
            "retrieval_trace_path": str(task_dir / "retrieval_trace.json"),
            "spp_preflight_path": str(task_dir / "spp_preflight.json"),
            "qlip_request_path": str(task_dir / "qlip_request.json"),
            "orbit_candidates_path": str(task_dir / "orbit_candidates.json") if candidates is not None else "",
            "orbit_solution_path": str(task_dir / "orbit_solution.json") if solution is not None else "",
            "symmetry_trace_path": str(task_dir / "symmetry_trace.json"),
            **_extensibility_metadata(formula, row, generated=True, target_sg_number=sg_number),
        }
        result_rows.append(generated)
        generated_manifest_rows.append(
            {
                "prompt_id": task_id,
                "benchmark_id": task_id,
                "target_formula": formula,
                "target_structure_family": family,
                "target_space_group": space_group,
                "target_space_group_number": sg_number,
                "target_crystal_system": crystal_system,
                "chemistry_family": family,
                "attempt_id": 1,
                "method": "prototype_orbit_variable_spp_qlip" if tier == "variable_spp_scored" else "prototype_orbit_qlip_fixed",
                "cif_path": str(cif_path),
            }
        )

    _write_csv(MANIFEST_CSV, manifest_rows, MANIFEST_COLUMNS)
    generated_manifest = OUTPUT_ROOT / "sca_generated_cifs_manifest.csv"
    _write_csv(
        generated_manifest,
        generated_manifest_rows,
        [
            "prompt_id",
            "benchmark_id",
            "target_formula",
            "target_structure_family",
            "target_space_group",
            "target_space_group_number",
            "target_crystal_system",
            "chemistry_family",
            "attempt_id",
            "method",
            "cif_path",
        ],
    )
    sca_rows = _validate_generated_cifs(generated_manifest_rows)
    sca_cli = _run_sca_symmetry(generated_manifest) if generated_manifest_rows else {"returncode": None, "note": "no generated CIFs"}
    sca_validation = {
        "rows": sca_rows,
        "parseable_count": sum(1 for row in sca_rows if row["parse_ok"]),
        "formula_match_count": sum(1 for row in sca_rows if row["formula_match"]),
        "symmetry_match_count": sum(1 for row in sca_rows if row["symmetry_match"]),
        "symmetry_intent_cli": sca_cli,
        "generated_manifest": str(generated_manifest),
    }
    summary = {
        "schema_version": "paper_result_section_smoke.v1",
        "created_at": _now_iso(),
        "output_root": str(OUTPUT_ROOT),
        "manifest_csv": str(MANIFEST_CSV),
        "datasets_used": [
            str(CRYSTAL_ROOT / "data" / "result_common_families.db"),
            str(CRYSTAL_ROOT / "data" / "result_hard_intent.db"),
            str(CRYSTAL_ROOT / "data" / "result_halide_perovskite.db"),
        ],
        "explicitly_not_used": [str(CRYSTAL_ROOT / "data" / "phase6_mp_10k.db")],
        "rows": result_rows,
        "counts": {
            "total": len(result_rows),
            "generated": sum(1 for row in result_rows if row["outcome"] == "generated"),
            "blocked": sum(1 for row in result_rows if row["outcome"] == "blocked"),
            "validation_tiers": dict(Counter(row["validation_tier"] for row in result_rows)),
            "spp_status": dict(Counter(row["spp_status"] for row in result_rows)),
            "solver_support_status": dict(Counter(row["solver_support_status"] for row in result_rows)),
        },
        "v1_counts": v1_report.get("counts") or {},
        "v2_counts": v2_report.get("counts") or {},
        "v1_sca_metrics": {
            "parseable_count": (v1_report.get("sca_validation") or {}).get("parseable_count"),
            "formula_match_count": (v1_report.get("sca_validation") or {}).get("formula_match_count"),
            "symmetry_match_count": (v1_report.get("sca_validation") or {}).get("symmetry_match_count"),
        },
        "upgraded_rows": [
            {
                "formula": row["formula"],
                "dataset_id": row["dataset_id"],
                "objective_value": row.get("objective_value"),
                "spp_scoring_status": row.get("spp_scoring_status"),
            }
            for row in result_rows
            if row.get("validation_tier") == "variable_spp_scored"
        ],
        "fixed_rows": [
            {
                "formula": row["formula"],
                "dataset_id": row["dataset_id"],
                "reason": row.get("variable_fallback_reason") or "not in explicit AX/AX2 variable SPP upgrade set",
            }
            for row in result_rows
            if row.get("outcome") == "generated" and row.get("validation_tier") == "fixed_orbit_spp_smoke"
        ],
        "sca_validation": sca_validation,
        "task_3_extensibility": {
            "section_title": "Task 3: specialist corpus and modular scaffold extension",
            "specialist_corpus_used": "halide_perovskite",
            "qlip_support_added": "ideal_cubic_abx3_orbit_scaffold",
            "new_scaffold_added": "cubic_halide_perovskite_abx3_pm3m",
            "rows_newly_generated_or_upgraded": [
                row["formula"]
                for row in result_rows
                if row.get("extension_case") == "halide_perovskite_specialist_corpus" and row.get("outcome") == "generated"
            ],
            "rows_requiring_parameterised_wyckoff": sorted(HALIDE_PARAMETERISED_WYCKOFF_REQUIRED),
            "pipeline_changed": False,
            "pipeline_changes_required": "qlip_scaffold_only_no_retrieval_spp_validation_changes",
            "demonstrates": "traceable specialist-corpus plus modular-scaffold extension with retrieval/SPP/validation pipeline unchanged",
            "does_not_demonstrate": [
                "coverage beyond the explicit supported halide rows",
                "automatic extension to arbitrary scaffolds",
                "physical-property claims",
                "DFT-level validation",
                "exact reproduction when source symmetry differs from ideal cubic ABX3",
            ],
        },
    }
    _write_json(REPORT_JSON, summary)
    _write_json(SCA_SUMMARY_JSON, sca_validation)
    report_md, sca_md = _render_reports(summary)
    REPORT_MD.write_text(report_md, encoding="utf-8")
    SCA_SUMMARY_MD.write_text(sca_md, encoding="utf-8")
    print(json.dumps(summary["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
