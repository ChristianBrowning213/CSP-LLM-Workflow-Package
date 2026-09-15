"""Literature-aware comparison reports for full intent benchmark runs."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


HEADLINE_ORDER = [
    "parse_validity_rate",
    "formula_composition_satisfaction",
    "pre_dft_validity_rate",
    "bad_contact_rate",
    "intent_satisfaction_score_mean",
    "global_uniqueness",
    "target_family_coverage",
    "stability",
    "novelty",
]


def build_literature_comparison_report(
    *,
    run_root: str | Path,
    comparators: str | Path,
    out_markdown: str | Path,
    out_json: str | Path,
) -> dict[str, Any]:
    """Build markdown and JSON reports that join run metrics to sourced literature rows."""

    root = Path(run_root)
    comparator_rows = _read_comparators(Path(comparators))
    headline_metrics = collect_headline_metrics(root)
    unique_summary = collect_unique_verifiable_summary(root)
    symmetry_summary = collect_symmetry_intent_summary(root)
    mlip_summary = collect_mlip_surrogate_summary(root)
    grouped = group_comparators(comparator_rows)
    report = {
        "run_root": str(root),
        "headline_metrics": headline_metrics,
        "unique_verifiable_csp_summary": unique_summary,
        "symmetry_intent_summary": symmetry_summary,
        "mlip_surrogate_summary": mlip_summary,
        "symmetry_contextual_comparators": _symmetry_contextual_comparators(comparator_rows),
        "comparator_counts": {name: len(rows) for name, rows in grouped.items()},
        "comparator_groups": grouped,
        "interpretation": _interpretation_rows(),
        "inputs": _input_status(root, Path(comparators)),
    }

    out_json_path = Path(out_json)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(_json_clean(report), indent=2), encoding="utf-8")

    out_markdown_path = Path(out_markdown)
    out_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    out_markdown_path.write_text(render_literature_comparison_markdown(report), encoding="utf-8")
    return {"markdown": str(out_markdown_path), "json": str(out_json_path), "comparators": len(comparator_rows)}


def collect_headline_metrics(run_root: str | Path) -> dict[str, dict[str, Any]]:
    """Collect headline metrics from available run artifacts with graceful fallbacks."""

    root = Path(run_root)
    full_summary = _read_json(root / "reports" / "FULL_100_INTENT_BENCHMARK_SUMMARY.json")
    direct = _read_csv(root / "sca_direct_benchmark" / "benchmark_results.csv")
    intent = _read_csv(root / "sca_intent_benchmark" / "intent_results.csv")
    sun = _read_first_json(
        [
            root / "sun_benchmark_v2" / "sun_summary.json",
            root / "sun_benchmark" / "sun_summary.json",
            root / "reports" / "sun_summary.json",
        ]
    )

    parse_validity = _first_number(_bool_rate(intent, "parse_ok"), _bool_rate(direct, "parse_ok"), full_summary.get("parse_validity_rate"))
    formula_satisfaction = _first_number(
        _bool_rate(intent, "intent_formula_satisfied"),
        _bool_rate(direct, "target_formula_match"),
        full_summary.get("intent_formula_satisfaction_rate"),
    )
    pre_dft_validity = _first_number(_bool_rate(direct, "pre_dft_valid"), full_summary.get("pre_dft_validity_rate"))
    bad_contact_rate = _first_number(_bad_contact_rate(direct), full_summary.get("bad_contact_rate"))
    intent_score = _first_number(_mean(intent, "intent_satisfaction_score"), full_summary.get("intent_satisfaction_score_mean"))
    unique_count = _number_or_none(sun.get("num_unique_structures"))
    generated_count = _number_or_none(sun.get("num_generated"))
    uniqueness_rate = _first_number(sun.get("uniqueness_rate"), (unique_count / generated_count if unique_count is not None and generated_count else None))
    family = _target_family_coverage(intent)
    stability_status = str(sun.get("stability_status") or "not_computable")
    novelty = _novelty_status(sun)

    return {
        "parse_validity_rate": _metric(parse_validity, "rate", "higher_is_better", "intent/direct benchmark results"),
        "formula_composition_satisfaction": _metric(formula_satisfaction, "rate", "higher_is_better", "intent formula satisfaction"),
        "pre_dft_validity_rate": _metric(pre_dft_validity, "rate", "higher_is_better", "direct pre-DFT validity"),
        "bad_contact_rate": _metric(bad_contact_rate, "rate", "lower_is_better", "direct bad-contact check"),
        "intent_satisfaction_score_mean": _metric(intent_score, "score", "higher_is_better", "intent benchmark results"),
        "global_uniqueness": {
            "value": uniqueness_rate,
            "display": _count_rate_display(unique_count, generated_count, uniqueness_rate),
            "unit": "rate",
            "direction": "higher_is_better",
            "status": "ok" if uniqueness_rate is not None else "unavailable",
            "source": "SUN summary",
            "count": unique_count,
            "denominator": generated_count,
        },
        "target_family_coverage": family,
        "stability": {
            "value": None,
            "display": stability_status,
            "unit": None,
            "direction": "higher_is_better",
            "status": stability_status,
            "source": "SUN summary" if sun else "missing SUN summary",
            "reason": sun.get("stability_required_inputs") or "Stability remains pending unless hull or energy inputs are supplied.",
        },
        "novelty": novelty,
    }


def collect_unique_verifiable_summary(run_root: str | Path) -> dict[str, dict[str, Any]]:
    """Collect traceable/unique CSP metrics when the composite summary exists."""

    root = Path(run_root)
    data = _read_json(root / "sca_unique_benchmark" / "unique_summary.json")
    rows = data.get("rows") or []
    metrics = {
        "traceable_constraint_grounded_csp_score": _unique_metric(rows, "traceable_constraint_grounded_csp_score"),
        "audit_bundle_score": _unique_metric(rows, "audit_bundle_score"),
        "output_validity": _unique_metric(rows, "output_validity"),
        "evidence_trace_score": _unique_metric(rows, "evidence_trace_score"),
        "solver_certificate_score": _unique_metric(rows, "solver_certificate_score"),
    }
    for metric in metrics.values():
        metric["source"] = "unique/verifiable CSP summary" if rows else "missing unique/verifiable CSP summary"
    return metrics


def collect_symmetry_intent_summary(run_root: str | Path) -> dict[str, dict[str, Any]]:
    """Collect dedicated symmetry intent metrics when available."""

    root = Path(run_root)
    data = _read_json(root / "symmetry_intent_benchmark" / "symmetry_summary.json")
    metric_units = {
        "space_group_exact_match_rate": "rate",
        "crystal_system_match_rate": "rate",
        "family_symmetry_compatible_rate": "rate",
        "mean_symmetry_score": "score",
    }
    metrics = {
        name: _metric(_number_or_none(data.get(name)), unit, "higher_is_better", "symmetry intent summary")
        for name, unit in metric_units.items()
    }
    if not data:
        for metric in metrics.values():
            metric["source"] = "missing symmetry intent summary"
    return metrics


def collect_mlip_surrogate_summary(run_root: str | Path) -> dict[str, dict[str, Any]]:
    """Collect CHGNet static/relaxation summaries when available."""

    root = Path(run_root)
    static = _read_json(root / "stability_chgnet_static" / "chgnet_static_summary.json")
    relax = _read_json(root / "stability_chgnet_relax" / "chgnet_relax_summary.json")
    static_energy = static.get("chgnet_energy_per_atom") or {}
    static_force = static.get("max_force_ev_per_angstrom") or {}
    relax_before = relax.get("max_force_before") or {}
    relax_after = relax.get("max_force_after") or {}
    return {
        "chgnet_static_ok_rate": _metric(_number_or_none(static.get("chgnet_ok_rate")), "rate", "higher_is_better", _source(static, "CHGNet static summary")),
        "median_chgnet_energy_per_atom": _metric(_number_or_none(static_energy.get("median")), "eV/atom", "contextual", _source(static, "CHGNet static summary")),
        "median_chgnet_max_force": _metric(_number_or_none(static_force.get("median")), "eV/A", "lower_is_better", _source(static, "CHGNet static summary")),
        "mean_chgnet_max_force": _metric(_number_or_none(static_force.get("mean")), "eV/A", "lower_is_better", _source(static, "CHGNet static summary")),
        "max_chgnet_max_force": _metric(_number_or_none(static_force.get("max")), "eV/A", "lower_is_better", _source(static, "CHGNet static summary")),
        "chgnet_relax_ok_rate": _metric(_number_or_none(relax.get("relax_ok_rate")), "rate", "higher_is_better", _source(relax, "CHGNet relaxation summary")),
        "relax_force_before_median": _metric(_number_or_none(relax_before.get("median")), "eV/A", "lower_is_better", _source(relax, "CHGNet relaxation summary")),
        "relax_force_after_median": _metric(_number_or_none(relax_after.get("median")), "eV/A", "lower_is_better", _source(relax, "CHGNet relaxation summary")),
        "relax_status": {
            "value": None,
            "display": str(relax.get("status") or "unavailable"),
            "unit": None,
            "direction": "contextual",
            "status": str(relax.get("status") or "unavailable"),
            "source": _source(relax, "CHGNet relaxation summary"),
            "reason": "MLIP relaxation diagnostic only; not DFT and not an energy-above-hull claim.",
        },
    }


def group_comparators(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "direct_contextual_anchors": [],
        "not_comparable_without_reference_cifs": [],
        "not_comparable_without_stability_hull_relaxation": [],
        "needs_manual_check": [],
    }
    for row in rows:
        group = _comparator_group(row)
        groups[group].append(row)
    return groups


def render_literature_comparison_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Literature-Aware Comparison Report",
        "",
        f"- Run root: `{report['run_root']}`",
        "- This report is comparison context, not a leaderboard claim.",
        "",
        "## Our Current Headline Metrics",
        "",
    ]
    metric_rows = []
    for name in HEADLINE_ORDER:
        metric = report["headline_metrics"].get(name, {})
        metric_rows.append(
            {
                "metric": name,
                "value": metric.get("display", _fmt(metric.get("value"))),
                "status": metric.get("status"),
                "source": metric.get("source"),
                "note": metric.get("reason", ""),
            }
        )
    lines.extend(_markdown_table(metric_rows, ["metric", "value", "status", "source", "note"]))
    lines.extend(["", "## Unique / Verifiable CSP Summary", ""])
    unique_rows = []
    for name, metric in report.get("unique_verifiable_csp_summary", {}).items():
        unique_rows.append(
            {
                "metric": name,
                "value": metric.get("display", _fmt(metric.get("value"))),
                "status": metric.get("status"),
                "source": metric.get("source"),
            }
        )
    lines.extend(_markdown_table(unique_rows, ["metric", "value", "status", "source"]))
    lines.extend(["", "## Symmetry Intent Benchmark Summary", ""])
    symmetry_rows = []
    for name, metric in report.get("symmetry_intent_summary", {}).items():
        symmetry_rows.append(
            {
                "metric": name,
                "value": metric.get("display", _fmt(metric.get("value"))),
                "status": metric.get("status"),
                "source": metric.get("source"),
            }
        )
    lines.extend(_markdown_table(symmetry_rows, ["metric", "value", "status", "source"]))
    lines.extend(["", "### CrysText Contextual Symmetry Anchors", ""])
    anchors = [_comparator_markdown_row(row) for row in report.get("symmetry_contextual_comparators", [])]
    if anchors:
        lines.extend(_markdown_table(anchors, ["paper", "system", "scope", "metric", "value", "status", "source", "reason"]))
    else:
        lines.append("No CrysText space-group contextual rows were available.")
    lines.extend(["", "## CHGNet MLIP Surrogate Summary", ""])
    mlip_rows = []
    for name, metric in report.get("mlip_surrogate_summary", {}).items():
        mlip_rows.append(
            {
                "metric": name,
                "value": metric.get("display", _fmt(metric.get("value"))),
                "status": metric.get("status"),
                "source": metric.get("source"),
                "note": metric.get("reason", ""),
            }
        )
    lines.extend(_markdown_table(mlip_rows, ["metric", "value", "status", "source", "note"]))
    lines.extend(
        [
            "",
            "CHGNet static and relaxation values are surrogate MLIP pre-DFT diagnostics. They are not DFT energies, energy-above-hull values, or thermodynamic stability claims.",
        ]
    )
    lines.extend(["", "## Interpretation", ""])
    for row in report["interpretation"]:
        lines.append(f"- {row}")

    headings = [
        ("direct_contextual_anchors", "Direct / Contextual Anchors"),
        ("not_comparable_without_reference_cifs", "Not Comparable Without Reference CIFs Or Dataset Protocols"),
        ("not_comparable_without_stability_hull_relaxation", "Not Comparable Without Stability, Hull, Or Relaxation Inputs"),
        ("needs_manual_check", "Needs Manual Check"),
    ]
    for key, title in headings:
        rows = report["comparator_groups"].get(key, [])
        lines.extend(["", f"## {title}", ""])
        if key == "needs_manual_check":
            lines.append("Rows in this section are cautions only; they are not claims.")
            lines.append("")
        if not rows:
            lines.append("No rows.")
            continue
        lines.extend(
            _markdown_table(
                [_comparator_markdown_row(row) for row in rows],
                ["paper", "system", "scope", "metric", "value", "status", "source", "reason"],
            )
        )

    lines.extend(
        [
            "",
            "## Source And Availability Notes",
            "",
            "- Source URLs are carried through from `data/paper_comparators/crystal_generation_comparators.csv`.",
            "- `needs_manual_check` rows are intentionally separated and must not be converted into quantitative claims.",
            "- Stability and novelty stay pending unless S.U.N. inputs include a real hull, energy, or reference-corpus basis.",
            "",
        ]
    )
    return "\n".join(lines)


def _read_comparators(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = []
        for row in csv.DictReader(handle):
            cleaned = {key: _empty_to_none(value) for key, value in row.items()}
            rows.append(cleaned)
        return rows


def _input_status(root: Path, comparators: Path) -> dict[str, Any]:
    paths = {
        "full_intent_summary": root / "reports" / "FULL_100_INTENT_BENCHMARK_SUMMARY.json",
        "direct_results": root / "sca_direct_benchmark" / "benchmark_results.csv",
        "intent_results": root / "sca_intent_benchmark" / "intent_results.csv",
        "sun_summary_v2": root / "sun_benchmark_v2" / "sun_summary.json",
        "sun_summary": root / "sun_benchmark" / "sun_summary.json",
        "unique_summary": root / "sca_unique_benchmark" / "unique_summary.json",
        "symmetry_summary": root / "symmetry_intent_benchmark" / "symmetry_summary.json",
        "chgnet_static_summary": root / "stability_chgnet_static" / "chgnet_static_summary.json",
        "chgnet_relax_summary": root / "stability_chgnet_relax" / "chgnet_relax_summary.json",
        "comparators": comparators,
    }
    return {name: {"path": str(path), "exists": path.exists()} for name, path in paths.items()}


def _comparator_group(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").lower()
    if status == "needs_manual_check":
        return "needs_manual_check"
    haystack = " ".join(str(row.get(key) or "").lower() for key in ("task_type", "dataset_scope", "metric_name_normalized", "reason"))
    if any(term in haystack for term in ("stability", "hull", "relax", "metastable", "stable_", "formation_energy", "eV/atom".lower())):
        return "not_comparable_without_stability_hull_relaxation"
    if str(row.get("comparability_to_our_100_prompt_run") or "") == "not_comparable":
        return "not_comparable_without_reference_cifs"
    return "direct_contextual_anchors"


def _symmetry_contextual_comparators(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = {"space_group_match_rate", "composition_and_sg_match_rate", "composition_match_rate"}
    return [
        row
        for row in rows
        if str(row.get("paper_name") or "").lower().startswith("crystext")
        and str(row.get("metric_name_normalized") or "") in wanted
    ]


def _comparator_markdown_row(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("value")
    unit = row.get("unit")
    return {
        "paper": row.get("paper_name"),
        "system": row.get("system_name"),
        "scope": row.get("dataset_scope"),
        "metric": row.get("metric_name_normalized"),
        "value": f"{value} {unit}".strip() if unit and value is not None else value,
        "status": row.get("status"),
        "source": f"[source]({row.get('source_url')})" if row.get("source_url") else "",
        "reason": row.get("reason") or row.get("quote_or_source_note"),
    }


def _interpretation_rows() -> list[str]:
    return [
        "Our run is not an MP-20/MPTS-52 leaderboard run.",
        "The primary claim is controlled, traceable text-to-CSP execution.",
        "Existing one-shot or data-hungry models often optimise distributional validity, coverage, and structure-match metrics.",
        "This workflow emphasises instruction following, formula control, solver-backed generation, and auditability.",
        "Do not claim wins over MP-20, Lang2Str, or CrysText structure-match metrics unless exact reference protocols are run.",
    ]


def _unique_metric(rows: list[dict[str, Any]], metric_name: str) -> dict[str, Any]:
    value = None
    for row in rows:
        if row.get("metric") == metric_name:
            value = _first_number(row.get("value"), row.get(metric_name))
            break
    if value is None and rows:
        value = _first_number(rows[0].get(metric_name))
    return _metric(value, "score", "higher_is_better", "unique/verifiable CSP summary")


def _target_family_coverage(intent: pd.DataFrame) -> dict[str, Any]:
    if intent.empty or "target_structure_family" not in intent:
        return _unavailable("missing intent target-family rows")
    total = int(intent["target_structure_family"].dropna().astype(str).replace("", pd.NA).dropna().nunique())
    if total == 0:
        return _unavailable("no target families recorded")
    if "parse_ok" in intent:
        represented = int(intent[_bool_mask(intent["parse_ok"])]["target_structure_family"].dropna().astype(str).replace("", pd.NA).dropna().nunique())
    else:
        represented = total
    value = represented / total if total else None
    return {
        "value": value,
        "display": f"{represented}/{total}",
        "unit": "families",
        "direction": "higher_is_better",
        "status": "ok",
        "source": "intent benchmark results",
        "count": represented,
        "denominator": total,
    }


def _novelty_status(sun: dict[str, Any]) -> dict[str, Any]:
    if not sun:
        return {
            "value": None,
            "display": "not_checked/not_computable",
            "unit": None,
            "direction": "higher_is_better",
            "status": "unavailable",
            "source": "missing SUN summary",
            "reason": "No SUN novelty summary was found.",
        }
    checked = _number_or_none(sun.get("novelty_checked_count"))
    novelty_rate = _number_or_none(sun.get("novelty_rate"))
    if not checked:
        return {
            "value": None,
            "display": "not_checked/not_computable",
            "unit": None,
            "direction": "higher_is_better",
            "status": "not_checked",
            "source": "SUN summary",
            "reason": "No reference corpus was supplied for novelty checking.",
        }
    return _metric(novelty_rate, "rate", "higher_is_better", "SUN summary")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_first_json(paths: list[Path]) -> dict[str, Any]:
    for path in paths:
        data = _read_json(path)
        if data:
            return data
    return {}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _bool_rate(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame:
        return None
    values = [_as_bool(value) for value in frame[column].tolist()]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _bad_contact_rate(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    if "has_bad_contacts" in frame:
        return _bool_rate(frame, "has_bad_contacts")
    if "num_bad_contacts" in frame:
        values = pd.to_numeric(frame["num_bad_contacts"], errors="coerce").dropna()
        return float((values > 0).sum() / len(values)) if len(values) else None
    return None


def _mean(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number_or_none(value)
        if number is not None:
            return number
    return None


def _number_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "1.0", "yes"}:
        return True
    if normalized in {"false", "0", "0.0", "no"}:
        return False
    return None


def _bool_mask(series: pd.Series) -> pd.Series:
    return series.map(lambda value: _as_bool(value) is True)


def _metric(value: float | None, unit: str | None, direction: str, source: str) -> dict[str, Any]:
    return {
        "value": value,
        "display": _fmt(value),
        "unit": unit,
        "direction": direction,
        "status": "ok" if value is not None else "unavailable",
        "source": source,
    }


def _source(data: dict[str, Any], present_name: str) -> str:
    return present_name if data else f"missing {present_name.lower()}"


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "value": None,
        "display": "unavailable",
        "unit": None,
        "direction": "higher_is_better",
        "status": "unavailable",
        "source": "missing input",
        "reason": reason,
    }


def _count_rate_display(count: float | None, denominator: float | None, rate: float | None) -> str:
    if count is not None and denominator:
        return f"{int(count)}/{int(denominator)}"
    return _fmt(rate)


def _fmt(value: Any) -> str:
    number = _number_or_none(value)
    if number is None:
        return "not_computable"
    return f"{number:.3f}"


def _empty_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_clean(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["No rows."]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(row.get(column)) for column in columns) + " |")
    return lines


def _markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.replace("\n", " ").replace("|", "\\|")
