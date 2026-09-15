"""Statistical Pair Potential benchmark evaluator."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pymatgen.core import Structure

from sca.evaluators.cif_parse import parse_cif
from sca.schemas import BenchmarkEvaluatorResult
from sca.spp.schema import SppArtifact, load_spp_artifact, species_pair_key


class SppBenchmarkEvaluator:
    name = "spp"
    description = "Statistical Pair Potential plausibility scorer."

    def __init__(self) -> None:
        self._cache: dict[str, SppArtifact] = {}

    def evaluate_item(self, item: dict) -> BenchmarkEvaluatorResult:
        artifact_path = item.get("spp_artifact")
        if not artifact_path:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                skipped=True,
                summary="no SPP artifact",
                metrics=_empty_metrics(error="spp_artifact was not provided"),
                error_message="spp_artifact was not provided",
            )
        try:
            artifact = self._load(artifact_path)
        except Exception as exc:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="artifact load failed",
                metrics=_empty_metrics(error=str(exc)),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        structure, parsed = parse_cif(item["path"])
        if structure is None:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="parse failed",
                metrics=_empty_metrics(error=parsed.error_message),
                error_type=parsed.error_type,
                error_message=parsed.error_message,
            )

        try:
            metrics, breakdown = score_structure_with_spp(structure, artifact)
        except Exception as exc:
            return BenchmarkEvaluatorResult(
                name=self.name,
                ok=False,
                summary="failed",
                metrics=_empty_metrics(error=str(exc)),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=True,
            summary="ok",
            metrics=metrics,
            flags={"spp_ok": True},
            details={
                "artifact_path": str(artifact_path),
                "corpus_hash": artifact.corpus_hash,
                "per_pair_breakdown": breakdown,
            },
        )

    def _load(self, artifact_path: str | Path) -> SppArtifact:
        key = str(artifact_path)
        if key not in self._cache:
            self._cache[key] = load_spp_artifact(artifact_path)
        return self._cache[key]


def score_structure_with_spp(
    structure: Structure,
    artifact: SppArtifact,
) -> tuple[dict, list[dict]]:
    cutoff = artifact.cutoff
    total_score = 0.0
    scored_pair_count = 0
    tail_violation_count = 0
    missing_pair_count = 0
    pair_scores: dict[str, float] = defaultdict(float)
    pair_counts: dict[str, int] = defaultdict(int)
    pair_missing: dict[str, int] = defaultdict(int)

    for i, site_i in enumerate(structure):
        for j in range(i + 1, len(structure)):
            site_j = structure[j]
            distance = float(structure.get_distance(i, j))
            if distance > cutoff:
                continue
            key = species_pair_key(site_i.specie.symbol, site_j.specie.symbol)
            table = artifact.species_pairs.get(key)
            if table is None:
                missing_pair_count += 1
                pair_missing[key] += 1
                continue
            penalty, is_tail = _penalty_for_table(distance, table)
            weighted = penalty * table.weight
            total_score += weighted
            scored_pair_count += 1
            pair_scores[key] += weighted
            pair_counts[key] += 1
            if is_tail:
                tail_violation_count += 1

    worst_species_pair = None
    if pair_scores:
        worst_species_pair = max(pair_scores, key=lambda key: pair_scores[key] / pair_counts[key])
    breakdown = [
        {
            "species_pair": key,
            "count": pair_counts.get(key, 0),
            "missing_count": pair_missing.get(key, 0),
            "score": pair_scores.get(key, 0.0),
            "score_per_pair": (
                pair_scores[key] / pair_counts[key] if pair_counts.get(key, 0) else None
            ),
        }
        for key in sorted(set(pair_scores) | set(pair_missing))
    ]
    metrics = {
        "spp_ok": True,
        "spp_total_score": total_score,
        "spp_score_per_atom": total_score / len(structure) if structure else None,
        "spp_score_per_pair": total_score / scored_pair_count if scored_pair_count else None,
        "spp_tail_violation_count": tail_violation_count,
        "spp_missing_pair_count": missing_pair_count,
        "worst_species_pair": worst_species_pair,
    }
    return metrics, breakdown


def _penalty_for_distance(
    distance: float,
    bin_edges: list[float],
    penalties: list[float],
    tail_penalty: float | None,
) -> tuple[float, bool]:
    for index, penalty in enumerate(penalties):
        if bin_edges[index] <= distance < bin_edges[index + 1]:
            return float(penalty), False
    if distance == bin_edges[-1]:
        return float(penalties[-1]), False
    return float(tail_penalty if tail_penalty is not None else max(penalties)), True


def _penalty_for_table(distance: float, table) -> tuple[float, bool]:
    if table.distance_grid is None or table.interpolation_policy == "piecewise_constant":
        return _penalty_for_distance(distance, table.bin_edges, table.penalties, table.tail_penalty)
    if distance < table.distance_grid[0] or distance > table.distance_grid[-1]:
        return float(table.tail_penalty if table.tail_penalty is not None else 0.0), True
    if table.interpolation_policy not in {"linear", "cubic"}:
        raise ValueError(f"Unsupported SPP interpolation policy '{table.interpolation_policy}'")
    from scipy.interpolate import interp1d

    interpolator = interp1d(
        table.distance_grid,
        table.penalties,
        kind=table.interpolation_policy,
        bounds_error=False,
        fill_value=float(table.tail_penalty if table.tail_penalty is not None else 0.0),
    )
    return float(interpolator(distance)), False


def _empty_metrics(error: str | None = None) -> dict:
    return {
        "spp_ok": False,
        "spp_total_score": None,
        "spp_score_per_atom": None,
        "spp_score_per_pair": None,
        "spp_tail_violation_count": None,
        "spp_missing_pair_count": None,
        "worst_species_pair": None,
        "spp_error": error,
    }
