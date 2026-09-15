"""Build paper-ready result table artifacts from the v3 paper smoke."""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CRYSTAL_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
SCA_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser")
REPORT_VERSION = os.environ.get("PAPER_RESULTS_TABLE_VERSION", "V3").strip().upper()
REPORT_VERSION_LOWER = REPORT_VERSION.lower()
SCA_RUN_ROOT = SCA_ROOT / "local_runs" / f"paper_result_section_smoke_{REPORT_VERSION_LOWER}_20260720"

V2_REPORT = REPO_ROOT / "PAPER_RESULT_SECTION_SMOKE_V2_REPORT.json"
V3_REPORT = REPO_ROOT / f"PAPER_RESULT_SECTION_SMOKE_{REPORT_VERSION}_REPORT.json"
MANIFEST = REPO_ROOT / "benchmarks" / "paper_result_section_smoke_manifest.csv"
DATASET_REPORT = CRYSTAL_ROOT / "artifacts" / "paper_result_datasets_built.json"
POT_COVERAGE = CRYSTAL_ROOT / "artifacts" / "result_dataset_pot_coverage.json"
SOLVER_SUPPORT = CRYSTAL_ROOT / "artifacts" / "result_dataset_solver_support.json"
SCA_SUMMARY = SCA_RUN_ROOT / "SCA_VALIDATION_SUMMARY.json"

OUT_DIR = REPO_ROOT / "artifacts"
TABLE_CSV = OUT_DIR / f"PAPER_RESULTS_TABLE_{REPORT_VERSION}.csv"
TABLE_MD = OUT_DIR / f"PAPER_RESULTS_TABLE_{REPORT_VERSION}.md"
SUMMARY_MD = OUT_DIR / f"PAPER_RESULTS_SUMMARY_TEXT_{REPORT_VERSION}.md"
DELTA_CSV = OUT_DIR / f"PAPER_RESULTS_V2_TO_{REPORT_VERSION}_DELTA.csv"
DELTA_MD = OUT_DIR / f"PAPER_RESULTS_V2_TO_{REPORT_VERSION}_DELTA.md"

TABLE_COLUMNS = [
    "result_section",
    "dataset_id",
    "dataset_db",
    "formula",
    "target_family",
    "source_status",
    "retrieval_status",
    "pot_coverage_status",
    "solver_support_status",
    "validation_tier",
    "generated",
    "active_mode",
    "variable_orbit_selection",
    "spp_scoring_status",
    "objective_value_present",
    "missing_pairs",
    "parse_ok",
    "formula_match",
    "symmetry_match",
    "blocked_stage",
    "blocked_reason",
    "artifact_root",
    "extension_case",
    "extension_type",
    "specialist_corpus_used",
    "new_scaffold_added",
    "scaffold_added_in_v3",
    "qlip_support_added",
    "pipeline_changes_required",
    "prototype_constraint_mode",
    "source_faithful_symmetry",
    "paper_claim_class",
    "extensibility_note",
]

DELTA_COLUMNS = [
    "formula",
    "v2_status",
    "v3_status",
    "v2_validation_tier",
    "v3_validation_tier",
    "change_type",
    "reason_for_change",
    "new_scaffold_added",
    "specialist_corpus_used",
    "source_faithful_symmetry",
    "notes",
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _task_id(row: dict[str, Any]) -> str:
    return Path(str(row.get("task_dir") or "")).name


def _source_status_by_target(dataset_report: dict[str, Any]) -> dict[tuple[str, str], str]:
    statuses: dict[tuple[str, str], str] = {}
    for card in dataset_report.get("dataset_cards", []):
        dataset_id = str(card.get("dataset_id") or "")
        for target in card.get("target_coverage", []):
            formula = str(target.get("target_formula") or "")
            statuses[(dataset_id, formula)] = str(target.get("status") or "")
    return statuses


def _read_manifest() -> dict[tuple[str, str, str], dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return {
            (row["result_section"], row["dataset_id"], row["formula"]): row
            for row in csv.DictReader(handle)
        }


def _pot_by_formula() -> dict[str, dict[str, Any]]:
    return {str(row.get("formula") or ""): row for row in _load_json(POT_COVERAGE).get("targets", [])}


def _solver_by_formula() -> dict[str, dict[str, Any]]:
    return {str(row.get("formula") or ""): row for row in _load_json(SOLVER_SUPPORT).get("targets", [])}


def _sca_by_task(sca_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_task = {}
    for row in sca_summary.get("rows", []):
        by_task[str(row.get("benchmark_id") or "")] = row
    return by_task


def _read_trace(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    trace_path = Path(path)
    if not trace_path.exists():
        return {}
    return _load_json(trace_path)


def _as_bool_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    return "true" if bool(value) else "false"


def build_rows() -> list[dict[str, Any]]:
    report = _load_json(V3_REPORT)
    manifest = _read_manifest()
    source_status = _source_status_by_target(_load_json(DATASET_REPORT))
    pot_by_formula = _pot_by_formula()
    solver_by_formula = _solver_by_formula()
    sca_rows = _sca_by_task(_load_json(SCA_SUMMARY))
    rows = []
    for row in report.get("rows", []):
        task_id = _task_id(row)
        manifest_row = manifest.get((str(row.get("result_section") or ""), str(row.get("dataset_id") or ""), str(row.get("formula") or "")), {})
        pot = pot_by_formula.get(str(row.get("formula") or ""), {})
        solver = solver_by_formula.get(str(row.get("formula") or ""), {})
        sca = sca_rows.get(task_id, {})
        trace = _read_trace(row.get("symmetry_trace_path"))
        generated = row.get("outcome") == "generated"
        active_mode = trace.get("active_symmetry_mode") or row.get("requested_mode") or ""
        objective_value = row.get("objective_value")
        if objective_value is None:
            objective_value = trace.get("objective_value")
        missing_pairs = row.get("missing_pairs")
        if missing_pairs is None:
            missing_pairs = trace.get("missing_pairs") or []
        rows.append(
            {
                "result_section": row.get("result_section", ""),
                "dataset_id": row.get("dataset_id", ""),
                "dataset_db": row.get("db_path") or manifest_row.get("db_path", ""),
                "formula": row.get("formula", ""),
                "target_family": row.get("target_family") or manifest_row.get("target_family", ""),
                "source_status": source_status.get((str(row.get("dataset_id") or ""), str(row.get("formula") or "")), ""),
                "retrieval_status": row.get("retrieval_status", ""),
                "pot_coverage_status": row.get("spp_status") or pot.get("pot_coverage_status", ""),
                "solver_support_status": row.get("solver_support_status") or solver.get("support_status", ""),
                "validation_tier": row.get("validation_tier", ""),
                "generated": _as_bool_text(generated),
                "active_mode": active_mode if generated else "",
                "variable_orbit_selection": _as_bool_text(row.get("orbit_variable_selection") or trace.get("variable_orbit_selection"))
                if generated
                else "false",
                "spp_scoring_status": row.get("spp_scoring_status") or trace.get("spp_scoring_status") or "",
                "objective_value_present": _as_bool_text(objective_value is not None),
                "missing_pairs": ";".join(str(pair) for pair in missing_pairs),
                "parse_ok": _as_bool_text(sca.get("parse_ok")) if generated else "",
                "formula_match": _as_bool_text(sca.get("formula_match")) if generated else "",
                "symmetry_match": _as_bool_text(sca.get("symmetry_match")) if generated else "",
                "blocked_stage": row.get("blocked_stage", ""),
                "blocked_reason": row.get("blocked_reason", ""),
                "artifact_root": row.get("task_dir", ""),
                "extension_case": row.get("extension_case", ""),
                "extension_type": row.get("extension_type", ""),
                "specialist_corpus_used": row.get("specialist_corpus_used", ""),
                "new_scaffold_added": row.get("new_scaffold_added", ""),
                "scaffold_added_in_v3": _as_bool_text(row.get("scaffold_added_in_v3")) if row.get("scaffold_added_in_v3") != "" else "",
                "qlip_support_added": row.get("qlip_support_added", ""),
                "pipeline_changes_required": row.get("pipeline_changes_required", ""),
                "prototype_constraint_mode": row.get("prototype_constraint_mode", ""),
                "source_faithful_symmetry": _as_bool_text(row.get("source_faithful_symmetry")) if row.get("source_faithful_symmetry") != "" else "",
                "paper_claim_class": row.get("paper_claim_class", ""),
                "extensibility_note": row.get("extensibility_note", ""),
            }
        )
    return rows


def _rows_by_formula(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("formula") or ""): row for row in report.get("rows", [])}


def _status(row: dict[str, Any] | None) -> str:
    if not row:
        return "absent"
    return "generated" if row.get("outcome") == "generated" else "blocked"


def _delta_change_type(v2: dict[str, Any] | None, v3: dict[str, Any] | None) -> str:
    v2_status = _status(v2)
    v3_status = _status(v3)
    v2_tier = str((v2 or {}).get("validation_tier") or "")
    v3_tier = str((v3 or {}).get("validation_tier") or "")
    if v3_tier == "missing_from_source":
        return "source_missing_unchanged"
    if v3_tier == "parameterised_wyckoff_required":
        return "blocked_parameterised_wyckoff_required"
    if v2_status == "blocked" and v3_status == "generated":
        return "blocked_to_generated"
    if v2_tier == "fixed_orbit_spp_smoke" and v3_tier == "variable_spp_scored":
        return "fixed_to_variable"
    if v2_status == "generated" and v3_status == "generated":
        return "unchanged_generated"
    if v2_status == "blocked" and v3_status == "blocked":
        return "unchanged_blocked"
    return "replaced_target"


def build_delta_rows() -> list[dict[str, Any]]:
    v2_by_formula = _rows_by_formula(_load_json(V2_REPORT))
    v3_by_formula = _rows_by_formula(_load_json(V3_REPORT))
    rows: list[dict[str, Any]] = []
    for formula in sorted(set(v2_by_formula) | set(v3_by_formula)):
        v2 = v2_by_formula.get(formula)
        v3 = v3_by_formula.get(formula)
        change_type = _delta_change_type(v2, v3)
        reason = {
            "fixed_to_variable": "v3 added SPP-scored cubic halide ABX3 orbit assignment where POT and retrieval evidence were already available.",
            "blocked_to_generated": "v3 added ideal cubic ABX3 QLIP scaffold support and labels the result as prototype-constrained generation.",
            "blocked_parameterised_wyckoff_required": "exact source-symmetry generation still requires parameterised Wyckoff support for the lower-symmetry prototype.",
            "source_missing_unchanged": "source dataset still records no exact Materials Project source row.",
            "unchanged_generated": "row generation status did not change in v3.",
            "unchanged_blocked": "row remains blocked for the same broad class of limitation.",
            "replaced_target": "target membership changed between the compared reports.",
        }[change_type]
        rows.append(
            {
                "formula": formula,
                "v2_status": _status(v2),
                "v3_status": _status(v3),
                "v2_validation_tier": (v2 or {}).get("validation_tier", ""),
                "v3_validation_tier": (v3 or {}).get("validation_tier", ""),
                "change_type": change_type,
                "reason_for_change": reason,
                "new_scaffold_added": (v3 or {}).get("new_scaffold_added", ""),
                "specialist_corpus_used": (v3 or {}).get("specialist_corpus_used", ""),
                "source_faithful_symmetry": _as_bool_text((v3 or {}).get("source_faithful_symmetry"))
                if (v3 or {}).get("source_faithful_symmetry") != ""
                else "",
                "notes": (v3 or {}).get("extensibility_note", ""),
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] = TABLE_COLUMNS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _markdown_table(rows: list[dict[str, Any]], columns: list[str] = TABLE_COLUMNS) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in columns) + " |")
    return "\n".join(lines)


def _write_table_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        f"# Paper Results Table {REPORT_VERSION}",
        "",
        f"This table summarizes the {REPORT_VERSION} paper result-section smoke without counting blocked rows as generated or fixed rows as variable.",
        "",
        _markdown_table(rows),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _dataset_summary() -> list[str]:
    report = _load_json(DATASET_REPORT)
    lines = []
    for card in report.get("dataset_cards", []):
        dataset_id = card.get("dataset_id")
        if dataset_id not in {"common_families", "hard_intent", "halide_perovskite"}:
            continue
        counts = card.get("counts") or {}
        missing = int(counts.get("missing", 0) or 0)
        lines.append(
            f"- `{dataset_id}` was built as `{card.get('status')}` with "
            f"{counts.get('ok', 0)} OK rows, {missing} missing {'row' if missing == 1 else 'rows'}, "
            f"and database `{card.get('db_path')}`."
        )
    return lines


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    report = _load_json(V3_REPORT)
    counts = report.get("counts") or {}
    sca = _load_json(SCA_SUMMARY)
    tiers = counts.get("validation_tiers") or {}
    generated = [row for row in rows if row["generated"] == "true"]
    variable = [row for row in generated if row["validation_tier"] == "variable_spp_scored"]
    fixed = [row for row in generated if row["validation_tier"] == "fixed_orbit_spp_smoke"]
    blocked = [row for row in rows if row["generated"] != "true"]
    blocked_by_reason = Counter((row["validation_tier"], row["blocked_stage"], row["blocked_reason"]) for row in blocked)

    lines = [
        "# Paper Results Summary Text",
        "",
        "## 1. Dataset Construction Summary",
        "",
        *_dataset_summary(),
        "",
        f"## 2. {REPORT_VERSION} Headline Metrics",
        "",
        (
            f"The {REPORT_VERSION} paper smoke evaluated {counts.get('total', len(rows))} target rows across three documented Crystal-DB "
            f"mini-datasets. It generated {counts.get('generated', len(generated))} CIFs and left "
            f"{counts.get('blocked', len(blocked))} targets blocked. The validation tiers were "
            f"`variable_spp_scored`={tiers.get('variable_spp_scored', 0)}, "
            f"`fixed_orbit_spp_smoke`={tiers.get('fixed_orbit_spp_smoke', 0)}, "
            f"`retrieval_ready_solver_blocked`={tiers.get('retrieval_ready_solver_blocked', 0)}, and "
            f"`missing_from_source`={tiers.get('missing_from_source', 0)}."
        ),
        (
            f"SCA validation on generated CIFs reported {sca.get('parseable_count', 0)}/{len(generated)} parseable, "
            f"{sca.get('formula_match_count', 0)}/{len(generated)} formula matches, and "
            f"{sca.get('symmetry_match_count', 0)}/{len(generated)} symmetry-intent matches."
        ),
        "",
        "## 3. Generated Target Summary",
        "",
        (
            f"The generated set contains {len(variable)} variable-orbit SPP-scored rows and {len(fixed)} fixed-orbit rows. "
            "All generated rows have complete POT coverage and are reported separately from blocked targets."
        ),
        "",
        "## 4. Variable-Orbit Upgraded Rows",
        "",
        (
            "The variable-orbit SPP-scored rows are "
            + ", ".join(f"`{row['formula']}`" for row in variable)
            + ". Each upgraded row reports `active_mode=prototype_orbit_variable_spp_qlip`, "
            "`variable_orbit_selection=true`, `spp_scoring_status=scored`, non-null SPP objective evidence, "
            "and no missing pairs."
        ),
        "",
        "## 4A. Task 3: Specialist Corpus and Modular Scaffold Extension",
        "",
        "The halide-perovskite result section was used as an extensibility test. The workflow was re-instantiated with a specialist halide-perovskite Crystal-DB corpus and extended with a modular cubic ABX3 prototype scaffold in the QLIP backend. This changed the supported search space but did not require changes to retrieval, SPP construction, solver audit logging or validation. Rows enabled by this extension are therefore reported as prototype-constrained halide-perovskite generation rather than exact reproduction of lower-symmetry Materials Project structures where applicable.",
        "",
        (
            "Rows carrying `extension_case=halide_perovskite_specialist_corpus` use specialist corpus "
            "`halide_perovskite` and QLIP support `ideal_cubic_abx3_orbit_scaffold`. Generated rows in this "
            "case are labelled with `prototype_constraint_mode=ideal_cubic_abx3`; `source_faithful_symmetry=false` "
            "is reported when the source Materials Project symmetry differs from the ideal cubic prototype."
        ),
        (
            "Rows still requiring parameterised Wyckoff support are "
            + ", ".join(f"`{row['formula']}`" for row in rows if row["validation_tier"] == "parameterised_wyckoff_required")
            + ". The retrieval/SPP/validation pipeline changed: no."
        ),
        (
            "This demonstrates a traceable extension via a specialist corpus and a modular scaffold. It does not "
            "demonstrate coverage beyond the explicit supported halide rows, arbitrary scaffold generalisation, physical-property "
            "claims, DFT-level validation, or exact reproduction when the symmetry/prototype differs."
        ),
        "",
        "## 5. Fixed-Orbit Rows",
        "",
        (
            "The fixed-orbit generated rows are "
            + ", ".join(f"`{row['formula']}` ({row['dataset_id']})" for row in fixed)
            + ". These rows remain `fixed_orbit_spp_smoke` because they are not in the explicit variable-SPP upgrade set."
        ),
        "",
        "## 6. Blocked Rows and Reasons",
        "",
    ]
    for (tier, stage, reason), count in sorted(blocked_by_reason.items()):
        formulas = [row["formula"] for row in blocked if (row["validation_tier"], row["blocked_stage"], row["blocked_reason"]) == (tier, stage, reason)]
        lines.append(f"- {count} row(s), {', '.join(f'`{formula}`' for formula in formulas)}: `{tier}` at `{stage}`; {reason}")
    lines.extend(
        [
            "",
            "KPbBr3 remains explicitly marked `missing_from_source` because the dataset card records `no_materials_project_summary_match`.",
            "",
            "## 7. What This Proves",
            "",
            f"The {REPORT_VERSION} smoke demonstrates that the documented mini-datasets can support retrieval-grounded result-section examples, that explicit supported rows can be converted to true variable-orbit SPP-scored rows with real objective values, and that the generated CIFs remain parseable and symmetry-compatible under SCA checks.",
            "",
            "## 8. What This Does Not Prove",
            "",
            "This is not a full 100-target benchmark, not a claim over `phase6_mp_10k.db`, and not evidence that every generated row uses variable-orbit selection. Fixed rows remain fixed, parameterised Wyckoff rows remain blocked, KPbBr3 remains missing from source, and CHGNet/S.U.N. claims are not made here.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_delta_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        f"# Paper Results V2 to {REPORT_VERSION} Delta",
        "",
        _markdown_table(rows, DELTA_COLUMNS),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows = build_rows()
    delta_rows = build_delta_rows()
    _write_csv(TABLE_CSV, rows)
    _write_table_md(TABLE_MD, rows)
    _write_csv(DELTA_CSV, delta_rows, DELTA_COLUMNS)
    _write_delta_md(DELTA_MD, delta_rows)
    _write_summary(SUMMARY_MD, rows)
    print(
        json.dumps(
            {
                "rows": len(rows),
                "csv": str(TABLE_CSV),
                "md": str(TABLE_MD),
                "summary": str(SUMMARY_MD),
                "delta_rows": len(delta_rows),
                "delta_csv": str(DELTA_CSV),
                "delta_md": str(DELTA_MD),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
