"""Compute paper-comparable A-E benchmark summaries from SCA result CSVs."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from sca.paper_benchmarks.comparators import built_in_comparators
from sca.paper_benchmarks.schema import (
    PaperBenchmarkMetric,
    PaperBenchmarkSummary,
    PaperComparator,
    load_comparator_csv,
    load_paper_manifest,
)

MetricFn = Callable[[pd.DataFrame, str | None], list[PaperBenchmarkMetric]]


GROUP_LABELS = {
    "A_validity": "A. Validity",
    "B_structure_reproduction": "B. Structure reproduction",
    "C_mlip_stability": "C. MLIP stability and predicted metastability",
    "D_relaxation": "D. Relaxation",
    "E_novelty_sun": "E. Novelty, uniqueness, and SUN",
}


def build_paper_benchmark_summary(
    results_csv: str | Path,
    manifest_csv: str | Path,
    comparator_values: str | Path | None = None,
    include_built_in_comparators: bool = False,
    group_col: str = "benchmark_group",
    id_col: str = "benchmark_id",
    attempt_col: str = "attempt_id",
    reference_required_policy: str = "warn",
) -> PaperBenchmarkSummary:
    results = pd.read_csv(results_csv)
    manifest_targets, manifest_comparators, warnings = load_paper_manifest(manifest_csv)
    if reference_required_policy not in {"warn", "skip", "fail"}:
        raise ValueError("reference_required_policy must be one of warn, skip, fail")
    if reference_required_policy == "fail" and warnings:
        raise ValueError("; ".join(warnings))
    if comparator_values:
        extra_comparators, comparator_warnings = load_comparator_csv(comparator_values)
        manifest_comparators.extend(extra_comparators)
        warnings.extend(comparator_warnings)
    comparators = []
    if include_built_in_comparators:
        comparators.extend(built_in_comparators())
    comparators.extend(manifest_comparators)
    comparators = _dedupe_comparators(comparators)

    if group_col not in results.columns:
        results = _attach_manifest_group(results, manifest_targets, id_col=id_col, group_col=group_col)

    metric_rows = []
    metric_rows.extend(_compute_scope_metrics("global", "all", results, attempt_col))
    if group_col in results.columns:
        for group, frame in results.groupby(group_col, dropna=False):
            group_name = str(group) if _present(group) else "unassigned"
            metric_rows.extend(_compute_scope_metrics("group", group_name, frame, attempt_col))
    if id_col in results.columns:
        group_lookup = {target.benchmark_id: target.benchmark_group for target in manifest_targets}
        for benchmark_id, frame in results.groupby(id_col, dropna=False):
            if not _present(benchmark_id):
                continue
            group_name = group_lookup.get(str(benchmark_id), _first_present(frame, group_col) or "unassigned")
            metric_rows.extend(_compute_scope_metrics("benchmark", group_name, frame, attempt_col, str(benchmark_id)))

    rows = [_metric_to_row(metric) for metric in metric_rows]
    rows.extend(_comparator_rows(metric_rows, comparators))
    return PaperBenchmarkSummary(rows=rows, warnings=warnings)


def write_summary_outputs(
    summary: PaperBenchmarkSummary,
    out_csv: str | Path,
    out_json: str | Path,
    markdown: str | Path | None = None,
) -> None:
    out_csv = Path(out_csv)
    out_json = Path(out_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summary.rows).to_csv(out_csv, index=False)
    out_json.write_text(
        json.dumps({"rows": summary.rows, "warnings": summary.warnings}, indent=2),
        encoding="utf-8",
    )
    if markdown:
        markdown_path = Path(markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown_report(summary), encoding="utf-8")


def render_markdown_report(summary: PaperBenchmarkSummary) -> str:
    rows = summary.rows
    lines = [
        "# SCA Paper-Comparable Benchmark Report",
        "",
        "## Dataset / manifest",
        "",
        f"- Summary rows: {len(rows)}",
        f"- Manifest warnings: {len(summary.warnings)}",
    ]
    if summary.warnings:
        lines.extend(f"- {warning}" for warning in summary.warnings[:20])
    for group, heading in GROUP_LABELS.items():
        lines.extend(["", f"## {heading}", ""])
        group_rows = [row for row in rows if row.get("benchmark_group") == group and not row.get("comparator_name")]
        lines.extend(_markdown_table(group_rows[:20]))
    lines.extend(["", "## Comparator results", ""])
    lines.extend(_markdown_table([row for row in rows if row.get("comparator_name")][:50]))
    lines.extend(["", "## Not-computable metrics", ""])
    not_computable = [row for row in rows if _to_float(row.get("n_not_computable")) and not row.get("comparator_name")]
    lines.extend(_markdown_table(not_computable[:50]))
    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- Surrogate MLIP scores are not DFT.",
            "- Local novelty is not global novelty.",
            "- Paper-derived target subset results are not full MP-20/MPTS-52 leaderboard results unless the manifest explicitly says so.",
            "- Predicted hull metrics require a local reference hull.",
            "- Relaxation metrics require actual relaxed structures.",
        ]
    )
    return "\n".join(lines) + "\n"


def _compute_scope_metrics(
    scope: str,
    group: str,
    frame: pd.DataFrame,
    attempt_col: str,
    benchmark_id: str | None = None,
) -> list[PaperBenchmarkMetric]:
    metrics: list[PaperBenchmarkMetric] = []
    metrics.extend(_validity_metrics(scope, "A_validity", frame))
    metrics.extend(_structure_metrics(scope, "B_structure_reproduction", frame, attempt_col, benchmark_id))
    metrics.extend(_mlip_metrics(scope, "C_mlip_stability", frame))
    metrics.extend(_relaxation_metrics(scope, "D_relaxation", frame))
    metrics.extend(_novelty_metrics(scope, "E_novelty_sun", frame))
    return metrics


def _validity_metrics(scope: str, group: str, frame: pd.DataFrame) -> list[PaperBenchmarkMetric]:
    return [
        _bool_rate_metric(scope, group, "parse_validity_rate", frame, ["parse_ok"]),
        _bool_rate_metric(scope, group, "composition_match_rate", frame, ["target_formula_match"]),
        _bool_rate_metric(scope, group, "pre_dft_validity_rate", frame, ["pre_dft_valid"]),
        _bool_rate_metric(scope, group, "geometry_ok_rate", frame, ["geometry_ok"]),
        _bool_rate_metric(scope, group, "bond_reasonable_rate", frame, ["bond_lengths_reasonable"]),
        _numeric_predicate_rate(scope, group, "bad_contact_rate", frame, ["num_bad_contacts"], lambda s: s > 0),
        _median_metric(scope, group, "median_min_distance", frame, ["min_distance"]),
        _median_metric(scope, group, "median_bad_contacts", frame, ["num_bad_contacts"]),
        _hard_fail_count(scope, group, frame),
    ]


def _structure_metrics(
    scope: str,
    group: str,
    frame: pd.DataFrame,
    attempt_col: str,
    benchmark_id: str | None,
) -> list[PaperBenchmarkMetric]:
    metrics = [
        _bool_rate_metric(scope, group, "structure_match_rate", frame, ["structure_match"]),
        _bool_rate_metric(scope, group, "match_rate", frame, ["structure_match"]),
        _bool_rate_metric(scope, group, "anonymous_match_rate", frame, ["anonymous_match"]),
        _bool_rate_metric(scope, group, "supercell_match_rate", frame, ["supercell_match"]),
        _mean_metric(scope, group, "mean_rms_dist", frame, ["rms_dist"]),
        _median_metric(scope, group, "median_rms_dist", frame, ["rms_dist"]),
        _min_metric(scope, group, "best_rms_dist", frame, ["rms_dist"]),
        _mean_metric(scope, group, "mean_max_dist", frame, ["max_dist"]),
        _mean_metric(scope, group, "structure_rmse", frame, ["rms_dist"]),
        _mean_metric(scope, group, "structure_rmse_relaxed", frame, ["rms_dist_after", "relaxed_rms_dist"]),
    ]
    match_series = _bool_series(frame, _column(frame, ["structure_match"]))
    if match_series is None:
        metrics.extend(
            [
                _not_computable(scope, group, "match_rate_n1", len(frame), "missing required columns: structure_match"),
                _not_computable(scope, group, "match_rate_nk", len(frame), "missing required columns: structure_match"),
            ]
        )
        return metrics
    ordered = _ordered_attempts(frame, attempt_col)
    first = ordered.head(1) if benchmark_id else ordered.groupby(_group_series(ordered), dropna=False).head(1)
    first_series = _bool_series(first, _column(first, ["structure_match"]))
    metrics.append(_series_rate_metric(scope, group, "match_rate_n1", first_series, len(first)))
    if benchmark_id:
        any_match = bool(match_series.fillna(False).any())
        metrics.append(PaperBenchmarkMetric(scope, group, "match_rate_nk", float(any_match), 1, 1, 0))
    else:
        any_by_target = ordered.assign(_match=match_series).groupby(_group_series(ordered), dropna=False)["_match"].agg(
            lambda values: pd.NA if values.isna().all() else bool(values.fillna(False).any())
        )
        metrics.append(_series_rate_metric(scope, group, "match_rate_nk", any_by_target, len(any_by_target)))
    return metrics


def _mlip_metrics(scope: str, group: str, frame: pd.DataFrame) -> list[PaperBenchmarkMetric]:
    force_cols = [
        "chgnet_forces_max",
        "m3gnet_forces_max",
        "mace_forces_max",
        "sevennet_forces_max",
        "mlip_max_force",
    ]
    return [
        _bool_rate_metric(scope, group, "chgnet_ok_rate", frame, ["chgnet_ok"]),
        _bool_rate_metric(scope, group, "m3gnet_ok_rate", frame, ["m3gnet_ok"]),
        _bool_rate_metric(scope, group, "mace_ok_rate", frame, ["mace_ok"]),
        _bool_rate_metric(scope, group, "sevennet_ok_rate", frame, ["sevennet_ok"]),
        _bool_rate_metric(scope, group, "mlip_ensemble_ok_rate", frame, ["mlip_ensemble_ok", "evaluator_mlip_ensemble_ok"]),
        _bool_rate_metric(scope, group, "mlip_consensus_stable_rate", frame, ["mlip_consensus_stable_flag"]),
        _bool_rate_metric(scope, group, "mlip_disagreement_rate", frame, ["mlip_disagreement_flag"]),
        _median_metric(scope, group, "median_mlip_mean_energy", frame, ["mlip_mean_energy_per_atom", "mlip_energy_mean"]),
        _median_metric(scope, group, "median_mlip_energy_std", frame, ["mlip_energy_std_per_atom", "mlip_energy_std"]),
        _median_metric(scope, group, "median_mlip_max_force", frame, force_cols, combine="row_max"),
        _ehull_rate(scope, group, frame, 0.00),
        _ehull_rate(scope, group, frame, 0.05),
        _ehull_rate(scope, group, frame, 0.10),
        _ehull_rate(scope, group, frame, 0.15),
        _ehull_rate(scope, group, frame, 0.15, metric_name="predicted_metastable_rate_ehull_0_15"),
        PaperBenchmarkMetric(scope, group, "metastability_threshold", 0.15, len(frame), len(frame), 0, "eV/atom"),
    ]


def _relaxation_metrics(scope: str, group: str, frame: pd.DataFrame) -> list[PaperBenchmarkMetric]:
    return [
        _bool_rate_metric(scope, group, "relax_success_rate", frame, ["relax_ok"]),
        _median_metric(scope, group, "median_energy_drop_per_atom", frame, ["energy_drop_per_atom"]),
        _median_metric(scope, group, "median_max_force_before", frame, ["max_force_before"]),
        _median_metric(scope, group, "median_max_force_after", frame, ["max_force_after"]),
        _numeric_predicate_rate(scope, group, "force_threshold_success_rate_0_20", frame, ["max_force_after"], lambda s: s <= 0.20),
        _numeric_predicate_rate(scope, group, "force_threshold_success_rate_0_10", frame, ["max_force_after"], lambda s: s <= 0.10),
        _rmse_improvement_rate(scope, group, frame),
        _median_metric(scope, group, "median_rmse_before", frame, ["rms_dist_before"]),
        _median_metric(scope, group, "median_rmse_after", frame, ["rms_dist_after"]),
        _median_delta_metric(scope, group, "median_rmse_delta", frame, ["rms_dist_before"], ["rms_dist_after"]),
        _median_delta_metric(scope, group, "rmse_improvement_after_relaxation", frame, ["rms_dist_before"], ["rms_dist_after"]),
        _mean_metric(scope, group, "relaxed_rmse", frame, ["rms_dist_after"]),
        _bool_rate_metric(scope, group, "structure_preservation_rate", frame, ["structure_match_after"]),
        _collapse_rate(scope, group, frame),
    ]


def _novelty_metrics(scope: str, group: str, frame: pd.DataFrame) -> list[PaperBenchmarkMetric]:
    unique = _unique_series(frame)
    novel = _novel_series(frame)
    stable = _stable_proxy_series(frame)
    sun = None
    if unique is not None and novel is not None and stable is not None:
        aligned = pd.concat([unique, novel, stable], axis=1).dropna()
        sun = aligned.all(axis=1) if not aligned.empty else pd.Series(dtype=bool)
    return [
        _series_rate_metric(scope, group, "unique_rate", unique, len(frame), "local uniqueness"),
        _bool_rate_metric(scope, group, "duplicate_rate", frame, ["is_duplicate"]),
        _bool_rate_metric(scope, group, "known_match_rate", frame, ["known_match"]),
        _series_rate_metric(scope, group, "local_novelty_rate", novel, len(frame), "local novelty relative to supplied reference corpus"),
        _bool_rate_metric(scope, group, "novel_by_structure_matcher_rate", frame, ["novel_by_structure_matcher"]),
        _series_rate_metric(scope, group, "sun_rate", sun, len(frame), "SUN uses local novelty and surrogate stability proxy"),
        _series_count_metric(scope, group, "sun_count", sun, len(frame), "SUN uses local novelty and surrogate stability proxy"),
    ]


def _metric_to_row(metric: PaperBenchmarkMetric) -> dict[str, Any]:
    return {
        "summary_scope": metric.summary_scope,
        "benchmark_group": metric.benchmark_group,
        "metric_name": metric.metric_name,
        "our_value": metric.our_value,
        "n_total": metric.n_total,
        "n_computable": metric.n_computable,
        "n_not_computable": metric.n_not_computable,
        "comparator_name": None,
        "comparator_value": None,
        "comparator_direction": None,
        "beats_comparator": None,
        "delta": None,
        "unit": metric.unit,
        "notes": metric.notes,
    }


def _comparator_rows(metrics: list[PaperBenchmarkMetric], comparators: list[PaperComparator]) -> list[dict[str, Any]]:
    by_metric = {}
    for metric in metrics:
        if metric.summary_scope in {"global", "group"}:
            by_metric.setdefault(metric.metric_name, metric)
    rows = []
    for comparator in comparators:
        metric = by_metric.get(comparator.metric_name)
        if metric is None or metric.our_value is None:
            rows.append(
                {
                    "summary_scope": "comparator",
                    "benchmark_group": "all",
                    "metric_name": comparator.metric_name,
                    "our_value": None,
                    "n_total": 0 if metric is None else metric.n_total,
                    "n_computable": 0 if metric is None else metric.n_computable,
                    "n_not_computable": 1 if metric is None else metric.n_not_computable,
                    "comparator_name": comparator.comparator_name,
                    "comparator_value": comparator.comparator_value,
                    "comparator_direction": comparator.comparator_direction,
                    "beats_comparator": None,
                    "delta": None,
                    "unit": comparator.unit,
                    "notes": _join_notes("metric not computable", comparator.notes),
                }
            )
            continue
        beats = _beats(metric.our_value, comparator)
        rows.append(
            {
                "summary_scope": "comparator",
                "benchmark_group": metric.benchmark_group,
                "metric_name": comparator.metric_name,
                "our_value": metric.our_value,
                "n_total": metric.n_total,
                "n_computable": metric.n_computable,
                "n_not_computable": metric.n_not_computable,
                "comparator_name": comparator.comparator_name,
                "comparator_value": comparator.comparator_value,
                "comparator_direction": comparator.comparator_direction,
                "beats_comparator": beats,
                "delta": metric.our_value - comparator.comparator_value,
                "unit": comparator.unit or metric.unit,
                "notes": comparator.notes,
            }
        )
    return rows


def _dedupe_comparators(comparators: list[PaperComparator]) -> list[PaperComparator]:
    seen = set()
    deduped = []
    for comparator in comparators:
        key = (
            comparator.metric_name,
            comparator.comparator_name,
            comparator.comparator_value,
            comparator.comparator_direction,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(comparator)
    return deduped


def _beats(value: float, comparator: PaperComparator) -> bool:
    if comparator.comparator_direction == "higher_is_better":
        return value >= comparator.comparator_value
    if comparator.comparator_direction == "lower_is_better":
        return value <= comparator.comparator_value
    return abs(value - comparator.comparator_value) <= abs(comparator.comparator_value)


def _bool_rate_metric(scope: str, group: str, name: str, frame: pd.DataFrame, aliases: list[str]) -> PaperBenchmarkMetric:
    column = _column(frame, aliases)
    series = _bool_series(frame, column)
    return _series_rate_metric(scope, group, name, series, len(frame), _missing_note(aliases) if series is None else None)


def _series_rate_metric(
    scope: str,
    group: str,
    name: str,
    series: pd.Series | None,
    n_total: int,
    notes: str | None = None,
) -> PaperBenchmarkMetric:
    if series is None:
        return _not_computable(scope, group, name, n_total, notes)
    clean = series.dropna()
    if clean.empty:
        return PaperBenchmarkMetric(scope, group, name, None, n_total, 0, n_total, notes=notes)
    return PaperBenchmarkMetric(scope, group, name, float(clean.mean()), n_total, len(clean), n_total - len(clean), notes=notes)


def _series_count_metric(scope: str, group: str, name: str, series: pd.Series | None, n_total: int, notes: str | None = None) -> PaperBenchmarkMetric:
    if series is None:
        return _not_computable(scope, group, name, n_total, notes)
    clean = series.dropna()
    if clean.empty:
        return PaperBenchmarkMetric(scope, group, name, None, n_total, 0, n_total, notes=notes)
    return PaperBenchmarkMetric(scope, group, name, float(clean.sum()), n_total, len(clean), n_total - len(clean), notes=notes)


def _numeric_predicate_rate(scope: str, group: str, name: str, frame: pd.DataFrame, aliases: list[str], predicate) -> PaperBenchmarkMetric:
    series = _numeric_series(frame, aliases)
    if series is None:
        return _not_computable(scope, group, name, len(frame), _missing_note(aliases))
    clean = series.dropna()
    if clean.empty:
        return PaperBenchmarkMetric(scope, group, name, None, len(frame), 0, len(frame))
    values = predicate(clean)
    return PaperBenchmarkMetric(scope, group, name, float(values.mean()), len(frame), len(clean), len(frame) - len(clean))


def _median_metric(scope: str, group: str, name: str, frame: pd.DataFrame, aliases: list[str], combine: str | None = None) -> PaperBenchmarkMetric:
    series = _numeric_series(frame, aliases, combine=combine)
    if series is None:
        return _not_computable(scope, group, name, len(frame), _missing_note(aliases))
    clean = series.dropna()
    return PaperBenchmarkMetric(scope, group, name, float(clean.median()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean))


def _mean_metric(scope: str, group: str, name: str, frame: pd.DataFrame, aliases: list[str]) -> PaperBenchmarkMetric:
    series = _numeric_series(frame, aliases)
    if series is None:
        return _not_computable(scope, group, name, len(frame), _missing_note(aliases))
    clean = series.dropna()
    return PaperBenchmarkMetric(scope, group, name, float(clean.mean()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean))


def _min_metric(scope: str, group: str, name: str, frame: pd.DataFrame, aliases: list[str]) -> PaperBenchmarkMetric:
    series = _numeric_series(frame, aliases)
    if series is None:
        return _not_computable(scope, group, name, len(frame), _missing_note(aliases))
    clean = series.dropna()
    return PaperBenchmarkMetric(scope, group, name, float(clean.min()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean))


def _median_delta_metric(scope: str, group: str, name: str, frame: pd.DataFrame, before_aliases: list[str], after_aliases: list[str]) -> PaperBenchmarkMetric:
    before = _numeric_series(frame, before_aliases)
    after = _numeric_series(frame, after_aliases)
    if before is None or after is None:
        return _not_computable(scope, group, name, len(frame), _missing_note(before_aliases + after_aliases))
    delta = before - after
    clean = delta.dropna()
    return PaperBenchmarkMetric(scope, group, name, float(clean.median()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean))


def _hard_fail_count(scope: str, group: str, frame: pd.DataFrame) -> PaperBenchmarkMetric:
    parse = _bool_series(frame, _column(frame, ["parse_ok"]))
    valid = _bool_series(frame, _column(frame, ["pre_dft_valid"]))
    if parse is None and valid is None:
        return _not_computable(scope, group, "hard_fail_count", len(frame), "missing required columns: parse_ok, pre_dft_valid")
    fail = pd.Series(False, index=frame.index)
    computable = pd.Series(False, index=frame.index)
    if parse is not None:
        fail = fail | (parse == False)  # noqa: E712
        computable = computable | parse.notna()
    if valid is not None:
        fail = fail | (valid == False)  # noqa: E712
        computable = computable | valid.notna()
    return PaperBenchmarkMetric(scope, group, "hard_fail_count", float(fail[computable].sum()), len(frame), int(computable.sum()), len(frame) - int(computable.sum()))


def _ehull_rate(scope: str, group: str, frame: pd.DataFrame, threshold: float, metric_name: str | None = None) -> PaperBenchmarkMetric:
    name = metric_name or f"predicted_ehull_rate_{threshold:.2f}".replace(".", "_")
    series = _numeric_series(frame, ["predicted_energy_above_hull", "energy_above_hull"])
    if series is None:
        return _not_computable(scope, group, name, len(frame), "missing required columns: predicted_energy_above_hull")
    clean = series.dropna()
    if clean.empty:
        return PaperBenchmarkMetric(scope, group, name, None, len(frame), 0, len(frame), unit="eV/atom")
    return PaperBenchmarkMetric(scope, group, name, float((clean <= threshold).mean()), len(frame), len(clean), len(frame) - len(clean), "eV/atom")


def _rmse_improvement_rate(scope: str, group: str, frame: pd.DataFrame) -> PaperBenchmarkMetric:
    before = _numeric_series(frame, ["rms_dist_before"])
    after = _numeric_series(frame, ["rms_dist_after"])
    if before is None or after is None:
        return _not_computable(scope, group, "rmse_improvement_rate", len(frame), "missing required columns: rms_dist_before, rms_dist_after")
    valid = before.notna() & after.notna()
    improved = (after[valid] < before[valid])
    if improved.empty:
        return PaperBenchmarkMetric(scope, group, "rmse_improvement_rate", None, len(frame), 0, len(frame))
    return PaperBenchmarkMetric(scope, group, "rmse_improvement_rate", float(improved.mean()), len(frame), len(improved), len(frame) - len(improved))


def _collapse_rate(scope: str, group: str, frame: pd.DataFrame) -> PaperBenchmarkMetric:
    if "relax_error" in frame.columns:
        errors = frame["relax_error"].fillna("").astype(str).str.contains("collapse", case=False)
        return PaperBenchmarkMetric(scope, group, "collapse_rate", float(errors.mean()), len(frame), len(frame), 0)
    return _not_computable(scope, group, "collapse_rate", len(frame), "missing required columns: relax_error")


def _unique_series(frame: pd.DataFrame) -> pd.Series | None:
    representative = _bool_series(frame, _column(frame, ["is_unique_representative"]))
    duplicate = _bool_series(frame, _column(frame, ["is_duplicate"]))
    if representative is None and duplicate is None:
        return None
    unique = pd.Series(pd.NA, index=frame.index, dtype="boolean")
    if duplicate is not None:
        unique = duplicate.map(lambda value: None if pd.isna(value) else not bool(value)).astype("boolean")
    if representative is not None:
        unique = unique.mask(representative.notna(), representative)
    return unique


def _novel_series(frame: pd.DataFrame) -> pd.Series | None:
    novelty = _bool_series(frame, _column(frame, ["novel_by_structure_matcher"]))
    known = _bool_series(frame, _column(frame, ["known_match"]))
    if novelty is None and known is None:
        return None
    novel = pd.Series(pd.NA, index=frame.index, dtype="boolean")
    if known is not None:
        novel = known.map(lambda value: None if pd.isna(value) else not bool(value)).astype("boolean")
    if novelty is not None:
        novel = novel.mask(novelty.notna(), novelty)
    return novel


def _stable_proxy_series(frame: pd.DataFrame) -> pd.Series | None:
    ehull = _numeric_series(frame, ["predicted_energy_above_hull", "energy_above_hull"])
    if ehull is not None and ehull.notna().any():
        return (ehull <= 0.15).astype("boolean")
    return _bool_series(frame, _column(frame, ["mlip_consensus_stable_flag"]))


def _numeric_series(frame: pd.DataFrame, aliases: list[str], combine: str | None = None) -> pd.Series | None:
    columns = [column for column in aliases if column in frame.columns]
    if not columns:
        return None
    if combine == "row_max":
        numeric = frame[columns].apply(pd.to_numeric, errors="coerce")
        return numeric.max(axis=1)
    return pd.to_numeric(frame[columns[0]], errors="coerce")


def _bool_series(frame: pd.DataFrame, column: str | None) -> pd.Series | None:
    if column is None:
        return None
    return frame[column].map(_bool_or_na).astype("boolean")


def _bool_or_na(value: Any) -> bool | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def _column(frame: pd.DataFrame, aliases: list[str]) -> str | None:
    for alias in aliases:
        if alias in frame.columns:
            return alias
    return None


def _not_computable(scope: str, group: str, name: str, n_total: int, notes: str | None = None) -> PaperBenchmarkMetric:
    return PaperBenchmarkMetric(scope, group, name, None, n_total, 0, n_total, notes=notes or "not computable")


def _missing_note(aliases: list[str]) -> str:
    return "missing required columns: " + ", ".join(aliases)


def _ordered_attempts(frame: pd.DataFrame, attempt_col: str) -> pd.DataFrame:
    if attempt_col in frame.columns:
        return frame.assign(_attempt_order=pd.to_numeric(frame[attempt_col], errors="coerce")).sort_values("_attempt_order")
    return frame


def _group_series(frame: pd.DataFrame) -> pd.Series:
    if "benchmark_id" in frame.columns:
        return frame["benchmark_id"]
    if "query_id" in frame.columns:
        return frame["query_id"]
    if "target_formula" in frame.columns:
        return frame["target_formula"]
    return pd.Series("all", index=frame.index)


def _attach_manifest_group(results: pd.DataFrame, targets, id_col: str, group_col: str) -> pd.DataFrame:
    if id_col not in results.columns:
        return results
    group_lookup = {target.benchmark_id: target.benchmark_group for target in targets}
    results = results.copy()
    results[group_col] = results[id_col].map(group_lookup)
    return results


def _first_present(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame.columns:
        return None
    for value in frame[column]:
        if _present(value):
            return str(value)
    return None


def _present(value: Any) -> bool:
    return value is not None and not pd.isna(value) and str(value).strip() != ""


def _to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _join_notes(*notes: str | None) -> str | None:
    present = [note for note in notes if note]
    return "; ".join(present) if present else None


def _markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No rows."]
    columns = ["summary_scope", "metric_name", "our_value", "n_computable", "comparator_name", "beats_comparator", "notes"]
    lines = ["|" + "|".join(columns) + "|", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in rows:
        lines.append("|" + "|".join(_markdown_cell(row.get(column)) for column in columns) + "|")
    return lines


def _markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def rows_as_dicts(metrics: list[PaperBenchmarkMetric]) -> list[dict[str, Any]]:
    return [asdict(metric) for metric in metrics]
