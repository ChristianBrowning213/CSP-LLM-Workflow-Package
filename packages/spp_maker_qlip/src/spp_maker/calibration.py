"""Utilities for SPP lambda calibration and scaled root generation."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from spp_maker.fit_hist import make_uniform_binning
from spp_maker.io_cif import load_cifs_from_dir
from spp_maker.score import score_atoms
from spp_maker.spp_model import MissingPairPolicy, OobPolicy, load_spp_model
from spp_maker.supercell_gr import (
    build_supercell,
    compute_pair_histograms_supercell,
)
from spp_maker.weights import BandpassParams


def _summary(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {
            "mean": 0.0,
            "median": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
        }
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }


@dataclass(frozen=True)
class CalibrationStats:
    """Corpus scoring statistics used for lambda calibration."""

    num_structures: int
    num_edges_total: int
    score_structures: np.ndarray
    score_edges: np.ndarray
    summary: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable stats payload."""
        return {
            "num_structures": int(self.num_structures),
            "num_edges_total": int(self.num_edges_total),
            "score_structures": self.score_structures.tolist(),
            "score_edges": self.score_edges.tolist(),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class LambdaRecommendation:
    """Transparent lambda recommendation payload."""

    lambda_raw_signed: float
    lambda_positive: float
    lambda_used: float
    lambda_clipped: bool
    min_lambda: float
    max_lambda: float
    convention: str
    statistic_value: float
    statistic_magnitude: float
    target: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "lambda_raw": float(self.lambda_raw_signed),
            "lambda_abs": float(self.lambda_positive),
            "lambda_used": float(self.lambda_used),
            "lambda_clipped": bool(self.lambda_clipped),
            "min_lambda": float(self.min_lambda),
            "max_lambda": float(self.max_lambda),
            "convention": str(self.convention),
            "statistic_value": float(self.statistic_value),
            "statistic_magnitude": float(self.statistic_magnitude),
            "target": float(self.target),
        }


def collect_scores_for_corpus(
    *,
    spp_root: Path,
    cif_dir: Path,
    max_n: Optional[int] = None,
    score_method: str = "neighbors",
    r_cut: Optional[float] = 4.0,
    knn: Optional[int] = None,
    min_d: Optional[float] = None,
    use_bandpass: bool = True,
    bandpass: Optional[BandpassParams] = None,
    supercell_target_len: float = 20.0,
    r_max: float = 10.0,
    bin_width: float = 0.05,
    sigma: float = 0.1,
    truncate_sigma: float = 3.0,
    max_pairs: Optional[int] = None,
    oob_policy: OobPolicy = "max",
    missing_pair_policy: MissingPairPolicy = "max_global",
) -> CalibrationStats:
    """
    Score a corpus against an SPP root and return calibration statistics.

    CIFs are loaded in deterministic sorted order, optionally truncated by `max_n`.
    """
    spp_root = Path(spp_root).resolve()
    cif_dir = Path(cif_dir).resolve()
    if not spp_root.is_dir():
        raise ValueError(f"spp_root is not a directory: {spp_root}")
    if not cif_dir.is_dir():
        raise ValueError(f"cif_dir is not a directory: {cif_dir}")

    if score_method not in {"neighbors", "supercell_gr"}:
        raise ValueError(f"score_method must be 'neighbors' or 'supercell_gr', got {score_method}.")
    if score_method == "neighbors":
        if r_cut is not None:
            if not np.isfinite(r_cut) or r_cut <= 0:
                raise ValueError(f"r_cut must be finite and > 0, got {r_cut}.")
        if knn is not None and knn <= 0:
            raise ValueError(f"knn must be > 0, got {knn}.")
        if min_d is not None:
            if not np.isfinite(min_d) or min_d < 0:
                raise ValueError(f"min_d must be finite and >= 0, got {min_d}.")
    else:
        if not np.isfinite(r_max) or r_max <= 0:
            raise ValueError(f"r_max must be finite and > 0, got {r_max}.")
        if not np.isfinite(bin_width) or bin_width <= 0:
            raise ValueError(f"bin_width must be finite and > 0, got {bin_width}.")
        if not np.isfinite(sigma) or sigma <= 0:
            raise ValueError(f"sigma must be finite and > 0, got {sigma}.")
        if not np.isfinite(truncate_sigma) or truncate_sigma <= 0:
            raise ValueError(f"truncate_sigma must be finite and > 0, got {truncate_sigma}.")
        if max_pairs is not None and max_pairs <= 0:
            raise ValueError(f"max_pairs must be > 0 when provided, got {max_pairs}.")
    if max_n is not None and max_n <= 0:
        raise ValueError(f"max_n must be > 0 when provided, got {max_n}.")

    model = load_spp_model(
        spp_root,
        oob_policy=oob_policy,
        missing_pair_policy=missing_pair_policy,
    )
    loaded = load_cifs_from_dir(cif_dir)
    if max_n is not None:
        loaded = loaded[:max_n]
    if not loaded:
        raise ValueError(f"No CIF files available for calibration in: {cif_dir}")

    active_bandpass = (
        bandpass if bandpass is not None else BandpassParams.defaults()
    ) if use_bandpass else None

    structure_scores: list[float] = []
    per_edge_scores: list[float] = []
    num_edges_total = 0
    supercell_binning = (
        make_uniform_binning(d_min=0.0, d_max=float(r_max), bin_width=float(bin_width))
        if score_method == "supercell_gr"
        else None
    )

    for item in loaded:
        if score_method == "neighbors":
            report = score_atoms(
                item.atoms,
                model,
                r_cut=r_cut,
                k=knn,
                min_d=min_d,
                bandpass=active_bandpass,
                use_bandpass=use_bandpass,
            )
            score_total = float(report.total)
            scored_count = int(report.num_scored_edges)
            num_edges_total += int(report.num_edges)
        else:
            assert supercell_binning is not None
            build = build_supercell(
                item.atoms,
                target_len=float(supercell_target_len),
                r_max=float(r_max),
                sigma=float(sigma),
                truncate_sigma=float(truncate_sigma),
            )
            hist = compute_pair_histograms_supercell(
                unit_atoms=item.atoms,
                super_atoms=build.atoms,
                edges=supercell_binning.edges,
                r_max=float(r_max),
                sigma=float(sigma),
                truncate_sigma=float(truncate_sigma),
                max_pairs=max_pairs,
            )
            centers = 0.5 * (supercell_binning.edges[:-1] + supercell_binning.edges[1:])
            score_total = 0.0
            for key in sorted(hist.counts):
                a, b = key
                counts_row = np.asarray(hist.counts[key], dtype=np.float64)
                penalties = np.asarray(
                    [model.penalty(a, b, float(r)) for r in centers],
                    dtype=np.float64,
                )
                score_total += float(np.sum(counts_row * penalties))
            scored_count = int(hist.pair_count_used)
            num_edges_total += int(hist.pair_count_used)

        structure_scores.append(score_total)
        denom = max(1, scored_count)
        per_edge_scores.append(score_total / float(denom))

    score_structures = np.asarray(structure_scores, dtype=np.float64)
    score_edges = np.asarray(per_edge_scores, dtype=np.float64)
    if not np.all(np.isfinite(score_structures)):
        raise ValueError("Non-finite structure scores encountered during calibration.")
    if not np.all(np.isfinite(score_edges)):
        raise ValueError("Non-finite per-edge scores encountered during calibration.")

    summary = {
        "structure_scores": _summary(score_structures),
        "edge_scores": {
            "mean": float(np.mean(score_edges)) if score_edges.size else 0.0,
            "median": float(np.median(score_edges)) if score_edges.size else 0.0,
        },
    }

    return CalibrationStats(
        num_structures=len(loaded),
        num_edges_total=num_edges_total,
        score_structures=score_structures,
        score_edges=score_edges,
        summary=summary,
    )


def _safe_lambda(target: float, denominator: float) -> float:
    if not np.isfinite(target) or target <= 0:
        raise ValueError(f"Target must be finite and > 0, got {target}.")
    if not np.isfinite(denominator):
        return float("inf")
    if np.isclose(float(denominator), 0.0, rtol=0.0, atol=0.0):
        return float("inf")
    value = float(target) / float(denominator)
    if not np.isfinite(value):
        return float("inf")
    return value


def _recommend_lambda_from_stat(
    *,
    statistic_value: float,
    target: float,
    convention: str,
    min_lambda: float,
    max_lambda: float,
) -> LambdaRecommendation:
    if convention not in {"reward", "penalty"}:
        raise ValueError(f"convention must be 'reward' or 'penalty', got {convention}.")
    if not np.isfinite(min_lambda) or min_lambda < 0:
        raise ValueError(f"min_lambda must be finite and >= 0, got {min_lambda}.")
    if not np.isfinite(max_lambda) or max_lambda <= 0:
        raise ValueError(f"max_lambda must be finite and > 0, got {max_lambda}.")
    if max_lambda < min_lambda:
        raise ValueError(f"max_lambda must be >= min_lambda, got {max_lambda} < {min_lambda}.")

    stat = float(statistic_value)
    effective_signed = stat if convention == "reward" else -stat
    raw_signed = _safe_lambda(float(target), effective_signed)
    lambda_abs = abs(raw_signed)

    if not np.isfinite(lambda_abs):
        lambda_used = float(max_lambda)
        clipped = True
    else:
        lambda_used = float(np.clip(lambda_abs, float(min_lambda), float(max_lambda)))
        clipped = not np.isclose(lambda_used, lambda_abs, rtol=0.0, atol=0.0)

    return LambdaRecommendation(
        lambda_raw_signed=float(raw_signed),
        lambda_positive=float(lambda_abs if np.isfinite(lambda_abs) else float("inf")),
        lambda_used=float(lambda_used),
        lambda_clipped=bool(clipped),
        min_lambda=float(min_lambda),
        max_lambda=float(max_lambda),
        convention=str(convention),
        statistic_value=float(stat),
        statistic_magnitude=float(abs(stat)),
        target=float(target),
    )


def recommend_lambda_by_structure_median(
    stats: CalibrationStats,
    target_structure_median: float,
    *,
    convention: str = "reward",
    min_lambda: float = 0.0,
    max_lambda: float = 1e9,
) -> LambdaRecommendation:
    """Return lambda so median structure score maps to target value."""
    median = float(np.median(stats.score_structures)) if stats.score_structures.size else 0.0
    return _recommend_lambda_from_stat(
        statistic_value=median,
        target=float(target_structure_median),
        convention=str(convention),
        min_lambda=float(min_lambda),
        max_lambda=float(max_lambda),
    )


def recommend_lambda_by_edge_median(
    stats: CalibrationStats,
    target_edge_median: float,
    *,
    convention: str = "reward",
    min_lambda: float = 0.0,
    max_lambda: float = 1e9,
) -> LambdaRecommendation:
    """Return lambda so median per-structure per-edge score maps to target value."""
    median = float(np.median(stats.score_edges)) if stats.score_edges.size else 0.0
    return _recommend_lambda_from_stat(
        statistic_value=median,
        target=float(target_edge_median),
        convention=str(convention),
        min_lambda=float(min_lambda),
        max_lambda=float(max_lambda),
    )


def recommend_lambda_quantile(
    stats: CalibrationStats,
    q: float,
    target: float,
    *,
    convention: str = "reward",
    min_lambda: float = 0.0,
    max_lambda: float = 1e9,
) -> LambdaRecommendation:
    """Return lambda so structure-score quantile `q` maps to target value."""
    if not np.isfinite(q) or q < 0.0 or q > 1.0:
        raise ValueError(f"q must be in [0,1], got {q}.")
    quant = float(np.quantile(stats.score_structures, q)) if stats.score_structures.size else 0.0
    return _recommend_lambda_from_stat(
        statistic_value=quant,
        target=float(target),
        convention=str(convention),
        min_lambda=float(min_lambda),
        max_lambda=float(max_lambda),
    )


def _scale_pot_file(path: Path, *, lambda_: float, convention: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    out_lines: list[str] = []
    inserted_scale_header = False
    for line in lines:
        parts = line.split()
        if len(parts) == 2:
            try:
                float(parts[0])
                u_val = float(parts[1])
            except ValueError:
                out_lines.append(line)
                continue
            if not inserted_scale_header:
                out_lines.append(f"# scaled_lambda_used: {lambda_}")
                out_lines.append(f"# convention: {convention}")
                inserted_scale_header = True
            out_lines.append(f"{parts[0]} {u_val * lambda_:.8f}")
        else:
            out_lines.append(line)
    if not inserted_scale_header:
        out_lines.insert(0, f"# convention: {convention}")
        out_lines.insert(0, f"# scaled_lambda_used: {lambda_}")
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def scale_spp_root(
    in_root: Path,
    out_root: Path,
    lambda_: float,
    *,
    copy_manifest: bool = True,
    update_manifest: bool = True,
    convention: str = "reward",
    source_calibration_json: Optional[str] = None,
    min_lambda: Optional[float] = None,
    max_lambda: Optional[float] = None,
) -> Path:
    """
    Create a scaled SPP root where every POT U-value is multiplied by `lambda_`.
    """
    if not np.isfinite(lambda_) or lambda_ <= 0:
        raise ValueError(f"lambda_ must be finite and > 0, got {lambda_}.")
    in_root = in_root.resolve()
    out_root = out_root.resolve()
    if not in_root.is_dir():
        raise ValueError(f"in_root is not a directory: {in_root}")
    if out_root.exists():
        raise ValueError(f"out_root already exists: {out_root}")

    shutil.copytree(in_root, out_root)

    pot_files = sorted(out_root.rglob("*.POT"), key=lambda p: str(p.relative_to(out_root)))
    for pot_file in pot_files:
        _scale_pot_file(pot_file, lambda_=float(lambda_), convention=str(convention))

    manifest_path = out_root / "manifest.json"
    if not copy_manifest and manifest_path.is_file():
        manifest_path.unlink()
    elif copy_manifest and (in_root / "manifest.json").is_file() and not manifest_path.is_file():
        shutil.copy2(in_root / "manifest.json", manifest_path)

    if update_manifest:
        manifest_payload: dict[str, Any]
        if manifest_path.is_file():
            with manifest_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            manifest_payload = loaded if isinstance(loaded, dict) else {}
        else:
            manifest_payload = {}
        manifest_payload["lambda"] = float(lambda_)
        manifest_payload["scaled_from"] = str(in_root)
        manifest_payload["scaling_method"] = "multiply_phi_by_lambda"
        manifest_payload["scaling"] = {
            "lambda_used": float(lambda_),
            "convention": str(convention),
            "source_calibration_json": source_calibration_json,
            "min_lambda": None if min_lambda is None else float(min_lambda),
            "max_lambda": None if max_lambda is None else float(max_lambda),
        }
        with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest_payload, handle, indent=2, sort_keys=True)
            handle.write("\n")

    return out_root
