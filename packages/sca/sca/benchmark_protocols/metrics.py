"""Metric extraction and comparator matrix for literature protocols."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from sca.benchmark_protocols.schema import BenchmarkProtocol, ComparatorResult, MetricResult


def compute_metric_results(
    results_csv: str | Path,
    target_col: str = "benchmark_id",
    attempt_col: str = "attempt_id",
) -> dict[str, MetricResult]:
    frame = pd.read_csv(results_csv)
    metrics = [
        _row_count(frame, "A_validity", "total_cif_count"),
        _bool_count(frame, "A_validity", "parse_clean_count", ["parse_ok"], True),
        _bool_count(frame, "A_validity", "parse_failure_count", ["parse_ok"], False),
        _bool_count(frame, "A_validity", "invalid_species_count", ["chemical_species_valid"], False),
        _bool_rate(frame, "A_validity", "parse_validity_rate", ["parse_ok"]),
        _bool_rate(frame, "A_validity", "pre_dft_validity_rate", ["pre_dft_valid"]),
        _min_distance_pass(frame),
        _bool_rate(frame, "A_validity", "composition_match_rate", ["target_formula_match"]),
        _bool_rate(frame, "A_validity", "space_group_match_rate", ["space_group_consistent"]),
        _composition_and_sg(frame),
        _bad_contact_rate(frame),
        _median_numeric(frame, "A_validity", "median_min_distance", ["min_distance"], "angstrom"),
        _bool_rate(frame, "B_structure_reproduction", "structure_match_rate", ["structure_match"]),
        _bool_rate(frame, "B_structure_reproduction", "anonymous_match_rate", ["anonymous_match"]),
        _bool_rate(frame, "B_structure_reproduction", "supercell_match_rate", ["supercell_match"]),
        _attempt_match_rate(frame, "match_rate_n1", target_col, attempt_col, first_only=True),
        _attempt_match_rate(frame, "match_rate_nk", target_col, attempt_col, first_only=False),
        _mean_numeric(frame, "B_structure_reproduction", "mean_rms_dist", ["rms_dist"]),
        _median_numeric(frame, "B_structure_reproduction", "median_rms_dist", ["rms_dist"]),
        _min_numeric(frame, "B_structure_reproduction", "best_rms_dist", ["rms_dist"]),
        _best_of_k(frame, "best_of_k_rms", ["rms_dist"], target_col, lower=True),
        _best_of_k(frame, "best_of_k_mlip_score", ["mlip_energy_mean"], target_col, lower=True),
        _best_of_k(frame, "best_of_k_relaxed_rms", ["rms_dist_after", "relaxed_rms_dist"], target_col, lower=True),
        _mean_numeric(frame, "D_relaxation", "relaxed_rms_dist", ["rms_dist_after", "relaxed_rms_dist"]),
        _rmse_improvement(frame),
        _ehull_rate(frame, 0.00),
        _ehull_rate(frame, 0.05),
        _ehull_rate(frame, 0.10),
        _ehull_rate(frame, 0.15),
        _ehull_rate(frame, 0.15, "within_threshold_rate_0_15"),
        _bool_rate(frame, "C_mlip_stability", "mlip_consensus_stable_rate", ["mlip_consensus_stable_flag"]),
        _bool_rate(frame, "C_mlip_stability", "mlip_disagreement_rate", ["mlip_disagreement_flag"]),
        _ehull_count(frame, "stable_count", upper=0.0),
        _ehull_count(frame, "metastable_count", lower=0.0, upper=0.15),
        _ehull_count(frame, "within_threshold_count", upper=0.15),
        _bool_rate(frame, "D_relaxation", "relax_success_rate", ["relax_ok"]),
        _median_numeric(frame, "D_relaxation", "median_energy_drop", ["energy_drop_per_atom"]),
        _median_numeric(frame, "D_relaxation", "median_max_force_before", ["max_force_before"]),
        _median_numeric(frame, "D_relaxation", "median_max_force_after", ["max_force_after"]),
        _force_rate(frame, 0.20),
        _force_rate(frame, 0.10),
        _mean_numeric(frame, "D_relaxation", "rms_before", ["rms_dist_before"]),
        _mean_numeric(frame, "D_relaxation", "rms_after", ["rms_dist_after", "relaxed_rms_dist"]),
        _rmse_improvement_rate(frame),
        _collapse_rate(frame),
        _mae(frame, "E_property", "formation_energy_mae", ["formation_energy_error"]),
        _mae(frame, "E_property", "band_gap_mae", ["band_gap_error"]),
        _mae(frame, "E_property", "target_property_mae", ["property_error"]),
        _bool_rate(frame, "E_property", "property_hit_rate_within_tolerance", ["property_target_ok"]),
    ]
    return {metric.metric_name: metric for metric in metrics}


def build_comparator_matrix(
    protocols: list[BenchmarkProtocol],
    metrics: dict[str, MetricResult],
    protocol_match_level: str,
) -> list[dict[str, Any]]:
    rows = []
    for protocol in protocols:
        metric = metrics.get(protocol.metric_name)
        if metric is None:
            metric = MetricResult(
                protocol.benchmark_family,
                protocol.metric_name,
                None,
                0,
                0,
                0,
                protocol.unit,
                protocol.required_inputs,
                "metric not implemented",
            )
        missing = _missing_inputs(protocol.required_inputs, metric, metric.n_total)
        comparable_level = protocol_match_level if metric.n_computable else "not_comparable"
        beats, delta = _compare(metric.our_value, protocol.comparator_value, protocol.direction)
        if missing:
            beats = None
        result = ComparatorResult(
            benchmark_family=protocol.benchmark_family,
            metric_name=protocol.metric_name,
            our_value=metric.our_value,
            paper_value=protocol.comparator_value,
            paper_name=protocol.paper_name,
            comparator_name=protocol.protocol_id,
            direction=protocol.direction,
            unit=protocol.unit or metric.unit,
            beats_paper=beats,
            delta=delta,
            dataset_scope=protocol.dataset_scope,
            protocol_match_level=comparable_level,
            n_total=metric.n_total,
            n_computable=metric.n_computable,
            n_not_computable=metric.n_not_computable,
            required_inputs_missing=",".join(missing),
            notes=_join_notes(protocol.source_label, protocol.notes, metric.notes),
        )
        rows.append(asdict(result))
    return rows


def metric_rows(metrics: dict[str, MetricResult]) -> list[dict[str, Any]]:
    return [asdict(metric) | {"required_inputs_missing": ",".join(metric.required_inputs_missing)} for metric in metrics.values()]


def _compare(value: float | None, paper: float, direction: str) -> tuple[bool | None, float | None]:
    if value is None:
        return None, None
    delta = value - paper
    if direction in {"higher_is_better", "threshold_lower"}:
        return value >= paper, delta
    if direction in {"lower_is_better", "threshold_upper"}:
        return value <= paper, delta
    return None, delta


def _missing_inputs(required: tuple[str, ...], metric: MetricResult, n_total: int) -> tuple[str, ...]:
    if metric.n_computable:
        return ()
    if metric.required_inputs_missing:
        return metric.required_inputs_missing
    return required if required else ("metric_inputs",) if n_total else ("results",)


def _bool_rate(frame: pd.DataFrame, family: str, name: str, aliases: list[str]) -> MetricResult:
    series = _bool_series(frame, aliases)
    if series is None:
        return _not_computable(frame, family, name, aliases)
    clean = series.dropna()
    return MetricResult(family, name, float(clean.mean()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean), required_inputs_missing=() if len(clean) else tuple(aliases))


def _row_count(frame: pd.DataFrame, family: str, name: str) -> MetricResult:
    return MetricResult(family, name, float(len(frame)), len(frame), len(frame), 0, "count")


def _bool_count(frame: pd.DataFrame, family: str, name: str, aliases: list[str], expected: bool) -> MetricResult:
    series = _bool_series(frame, aliases)
    if series is None:
        return _not_computable(frame, family, name, aliases)
    clean = series.dropna()
    return MetricResult(
        family,
        name,
        float((clean == expected).sum()) if not clean.empty else None,
        len(frame),
        len(clean),
        len(frame) - len(clean),
        "count",
        () if len(clean) else tuple(aliases),
    )


def _min_distance_pass(frame: pd.DataFrame) -> MetricResult:
    series = _numeric_series(frame, ["min_distance"])
    if series is None:
        return _not_computable(frame, "A_validity", "min_distance_pass_rate", ["min_distance"])
    clean = series.dropna()
    return MetricResult("A_validity", "min_distance_pass_rate", float((clean > 0.5).mean()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean), "angstrom", () if len(clean) else ("min_distance",))


def _composition_and_sg(frame: pd.DataFrame) -> MetricResult:
    comp = _bool_series(frame, ["target_formula_match"])
    sg = _bool_series(frame, ["space_group_consistent"])
    if comp is None or sg is None:
        return _not_computable(frame, "A_validity", "composition_and_sg_match_rate", ["target_formula_match", "space_group_consistent"])
    valid = comp.notna() & sg.notna()
    both = comp[valid] & sg[valid]
    return MetricResult("A_validity", "composition_and_sg_match_rate", float(both.mean()) if len(both) else None, len(frame), int(valid.sum()), len(frame) - int(valid.sum()), required_inputs_missing=() if valid.any() else ("target_formula_match", "space_group_consistent"))


def _attempt_match_rate(frame: pd.DataFrame, name: str, target_col: str, attempt_col: str, first_only: bool) -> MetricResult:
    match = _bool_series(frame, ["structure_match"])
    if match is None or target_col not in frame.columns:
        return _not_computable(frame, "B_structure_reproduction", name, ["structure_match", target_col])
    work = frame.copy()
    work["_match"] = match
    if attempt_col in work.columns:
        work["_attempt"] = pd.to_numeric(work[attempt_col], errors="coerce")
        work = work.sort_values([target_col, "_attempt"])
    grouped = work.groupby(target_col, dropna=False)
    values = grouped["_match"].first() if first_only else grouped["_match"].agg(lambda s: pd.NA if s.isna().all() else bool(s.fillna(False).any()))
    clean = values.dropna()
    return MetricResult("B_structure_reproduction", name, float(clean.mean()) if not clean.empty else None, len(values), len(clean), len(values) - len(clean), required_inputs_missing=() if len(clean) else ("structure_match", target_col))


def _best_of_k(frame: pd.DataFrame, name: str, aliases: list[str], target_col: str, lower: bool) -> MetricResult:
    series = _numeric_series(frame, aliases)
    if series is None or target_col not in frame.columns:
        return _not_computable(frame, "B_structure_reproduction", name, aliases + [target_col])
    work = frame.copy()
    work["_value"] = series
    values = work.groupby(target_col, dropna=False)["_value"].min() if lower else work.groupby(target_col, dropna=False)["_value"].max()
    clean = values.dropna()
    return MetricResult("B_structure_reproduction", name, float(clean.mean()) if not clean.empty else None, len(values), len(clean), len(values) - len(clean), required_inputs_missing=() if len(clean) else tuple(aliases + [target_col]))


def _ehull_rate(frame: pd.DataFrame, threshold: float, name: str | None = None) -> MetricResult:
    metric_name = name or f"predicted_ehull_rate_{threshold:.2f}".replace(".", "_")
    series = _numeric_series(frame, ["predicted_energy_above_hull", "energy_above_hull"])
    if series is None:
        return _not_computable(frame, "C_mlip_stability", metric_name, ["predicted_energy_above_hull"])
    clean = series.dropna()
    return MetricResult("C_mlip_stability", metric_name, float((clean <= threshold).mean()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean), "eV/atom", () if len(clean) else ("predicted_energy_above_hull",))


def _ehull_count(frame: pd.DataFrame, name: str, lower: float | None = None, upper: float | None = None) -> MetricResult:
    series = _numeric_series(frame, ["predicted_energy_above_hull", "energy_above_hull"])
    if series is None:
        return _not_computable(frame, "C_mlip_stability", name, ["predicted_energy_above_hull"])
    clean = series.dropna()
    mask = pd.Series(True, index=clean.index)
    if lower is not None:
        mask &= clean > lower
    if upper is not None:
        mask &= clean <= upper
    return MetricResult("C_mlip_stability", name, float(mask.sum()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean), "count", () if len(clean) else ("predicted_energy_above_hull",))


def _force_rate(frame: pd.DataFrame, threshold: float) -> MetricResult:
    series = _numeric_series(frame, ["max_force_after"])
    name = f"force_threshold_success_rate_{threshold:.2f}".replace(".", "_")
    if series is None:
        return _not_computable(frame, "D_relaxation", name, ["max_force_after"])
    clean = series.dropna()
    return MetricResult("D_relaxation", name, float((clean <= threshold).mean()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean), required_inputs_missing=() if len(clean) else ("max_force_after",))


def _rmse_improvement_rate(frame: pd.DataFrame) -> MetricResult:
    before = _numeric_series(frame, ["rms_dist_before"])
    after = _numeric_series(frame, ["rms_dist_after", "relaxed_rms_dist"])
    if before is None or after is None:
        return _not_computable(frame, "D_relaxation", "rms_improvement_rate", ["rms_dist_before", "rms_dist_after"])
    valid = before.notna() & after.notna()
    improved = after[valid] < before[valid]
    return MetricResult("D_relaxation", "rms_improvement_rate", float(improved.mean()) if len(improved) else None, len(frame), int(valid.sum()), len(frame) - int(valid.sum()), required_inputs_missing=() if valid.any() else ("rms_dist_before", "rms_dist_after"))


def _rmse_improvement(frame: pd.DataFrame) -> MetricResult:
    before = _numeric_series(frame, ["rms_dist_before"])
    after = _numeric_series(frame, ["rms_dist_after", "relaxed_rms_dist"])
    if before is None or after is None:
        return _not_computable(frame, "D_relaxation", "rmse_improvement", ["rms_dist_before", "rms_dist_after"])
    delta = before - after
    clean = delta.dropna()
    return MetricResult("D_relaxation", "rmse_improvement", float(clean.median()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean), required_inputs_missing=() if len(clean) else ("rms_dist_before", "rms_dist_after"))


def _collapse_rate(frame: pd.DataFrame) -> MetricResult:
    if "relax_error" in frame.columns:
        errors = frame["relax_error"].fillna("").astype(str).str.contains("collapse", case=False)
        return MetricResult("D_relaxation", "collapse_rate", float(errors.mean()), len(frame), len(frame), 0)
    ratio = _volume_ratio(frame)
    if ratio is None:
        return _not_computable(frame, "D_relaxation", "collapse_rate", ["relax_error", "volume", "relaxed_volume"])
    clean = ratio.dropna()
    return MetricResult("D_relaxation", "collapse_rate", float((clean < 0.5).mean()) if len(clean) else None, len(frame), len(clean), len(frame) - len(clean))


def _mae(frame: pd.DataFrame, family: str, name: str, aliases: list[str]) -> MetricResult:
    series = _numeric_series(frame, aliases)
    if series is None:
        return _not_computable(frame, family, name, aliases)
    clean = series.dropna().abs()
    return MetricResult(family, name, float(clean.mean()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean), required_inputs_missing=() if len(clean) else tuple(aliases))


def _bad_contact_rate(frame: pd.DataFrame) -> MetricResult:
    series = _numeric_series(frame, ["num_bad_contacts"])
    if series is None:
        return _not_computable(frame, "A_validity", "bad_contact_rate", ["num_bad_contacts"])
    clean = series.dropna()
    return MetricResult("A_validity", "bad_contact_rate", float((clean > 0).mean()) if not clean.empty else None, len(frame), len(clean), len(frame) - len(clean), required_inputs_missing=() if len(clean) else ("num_bad_contacts",))


def _mean_numeric(frame: pd.DataFrame, family: str, name: str, aliases: list[str], unit: str | None = None) -> MetricResult:
    return _numeric_metric(frame, family, name, aliases, "mean", unit)


def _median_numeric(frame: pd.DataFrame, family: str, name: str, aliases: list[str], unit: str | None = None) -> MetricResult:
    return _numeric_metric(frame, family, name, aliases, "median", unit)


def _min_numeric(frame: pd.DataFrame, family: str, name: str, aliases: list[str], unit: str | None = None) -> MetricResult:
    return _numeric_metric(frame, family, name, aliases, "min", unit)


def _numeric_metric(frame: pd.DataFrame, family: str, name: str, aliases: list[str], reducer: str, unit: str | None) -> MetricResult:
    series = _numeric_series(frame, aliases)
    if series is None:
        return _not_computable(frame, family, name, aliases)
    clean = series.dropna()
    value = None
    if not clean.empty:
        value = float(getattr(clean, reducer)())
    return MetricResult(family, name, value, len(frame), len(clean), len(frame) - len(clean), unit, () if len(clean) else tuple(aliases))


def _volume_ratio(frame: pd.DataFrame) -> pd.Series | None:
    before = _numeric_series(frame, ["volume", "generated_volume"])
    after = _numeric_series(frame, ["relaxed_volume"])
    if before is None or after is None:
        return None
    return after / before


def _numeric_series(frame: pd.DataFrame, aliases: list[str]) -> pd.Series | None:
    for alias in aliases:
        if alias in frame.columns:
            return pd.to_numeric(frame[alias], errors="coerce")
    return None


def _bool_series(frame: pd.DataFrame, aliases: list[str]) -> pd.Series | None:
    for alias in aliases:
        if alias in frame.columns:
            return frame[alias].map(_to_bool).astype("boolean")
    return None


def _to_bool(value: Any) -> bool | None:
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


def _not_computable(frame: pd.DataFrame, family: str, name: str, missing: list[str]) -> MetricResult:
    return MetricResult(family, name, None, len(frame), 0, len(frame), required_inputs_missing=tuple(missing), notes="not_computable")


def _join_notes(*notes: str | None) -> str | None:
    present = [note for note in notes if note]
    return "; ".join(present) if present else None
