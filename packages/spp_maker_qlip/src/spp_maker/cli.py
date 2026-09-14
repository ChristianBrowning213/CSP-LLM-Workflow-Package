"""Command-line interface for spp_maker."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from spp_maker import __version__ as spp_maker_version
from spp_maker.calibration import (
    CalibrationStats,
    collect_scores_for_corpus,
    recommend_lambda_by_edge_median,
    recommend_lambda_by_structure_median,
    recommend_lambda_quantile,
    scale_spp_root,
)
from spp_maker.covalent_filter import has_covalent_like_contact, load_covalent_rules
from spp_maker.export import export_spp_root
from spp_maker.fit_hist import Binning, accumulate_histograms, make_uniform_binning
from spp_maker.fit_phi import PhiResult, build_phi_from_hist
from spp_maker.gr_dump import dump_gr_csv, parse_pair_values
from spp_maker.io_cif import LoadedCIF, load_cif, load_cifs_from_dir
from spp_maker.meta_csv import load_meta_map, match_meta_rows
from spp_maker.pot_compat import check_pot_root
from spp_maker.publish import (
    ArtifactKind,
    build_run_id,
    copy_or_symlink_tree,
    ensure_qlip_outputs_layout,
    get_git_sha,
    kind_latest_file,
    kind_root_dirname,
    kind_runs_root,
    kind_to_bucket,
    python_version_short,
    to_posix_relative,
    write_json,
)
from spp_maker.run_orchestrator import RunConfig, run_pipeline
from spp_maker.qlip_outputs_index import load_index, write_index
from spp_maker.score import ScoreReport, score_atoms
from spp_maker.spp_model import load_spp_model_with_policies
from spp_maker.supercell_gr import (
    build_supercell,
    compute_pair_histograms_supercell,
    normalize_to_g_of_r,
    species_counts,
)
from spp_maker.weights import BandpassParams, validate_params
from spp_maker.weights_csv import load_structure_weights


class CliUsageError(Exception):
    """Raised for invalid CLI arguments."""


def _parse_species_whitelist(values: Sequence[str] | None) -> list[str] | None:
    if not values:
        return None

    parsed: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for item in raw.split(","):
            symbol = item.strip()
            if symbol and symbol not in seen:
                seen.add(symbol)
                parsed.append(symbol)
    if not parsed:
        raise CliUsageError("species_whitelist is empty after parsing.")
    return parsed


def _validate_neighbor_args(
    *,
    r_cut: float | None,
    knn: int | None,
    min_d: float | None,
    default_r_cut: float = 4.0,
) -> tuple[float | None, int | None]:
    resolved_r_cut = r_cut
    resolved_knn = knn
    if resolved_r_cut is None and resolved_knn is None:
        resolved_r_cut = default_r_cut

    if resolved_r_cut is not None:
        if not math.isfinite(resolved_r_cut) or resolved_r_cut <= 0:
            raise CliUsageError(f"--r_cut must be a finite value > 0, got {resolved_r_cut}.")

    if resolved_knn is not None and resolved_knn <= 0:
        raise CliUsageError(f"--knn must be > 0, got {resolved_knn}.")

    if min_d is not None:
        if not math.isfinite(min_d) or min_d < 0:
            raise CliUsageError(f"--min_d must be finite and >= 0, got {min_d}.")

    return resolved_r_cut, resolved_knn


def _validate_fit_args(args: argparse.Namespace) -> tuple[float | None, int | None]:
    fit_method = str(args.fit_method)
    if fit_method not in {"neighbors", "supercell_gr"}:
        raise CliUsageError(f"Unsupported --fit_method: {fit_method}")

    if not math.isfinite(args.bin_width) or args.bin_width <= 0:
        raise CliUsageError(f"--bin_width must be finite and > 0, got {args.bin_width}.")

    if args.property_filter is not None and args.meta_csv is None:
        raise CliUsageError("--property_filter requires --meta_csv.")
    if args.exclude_covalent and args.covalent_rules is None:
        raise CliUsageError("--exclude_covalent requires --covalent_rules.")
    if args.short_distance_floor is None:
        if args.short_distance_bins is not None or args.short_distance_r_max is not None:
            raise CliUsageError(
                "--short_distance_bins/--short_distance_r_max require --short_distance_floor."
            )
    else:
        if not math.isfinite(args.short_distance_floor) or args.short_distance_floor < 0:
            raise CliUsageError(
                "--short_distance_floor must be finite and >= 0, "
                f"got {args.short_distance_floor}."
            )
        if args.short_distance_bins is not None and args.short_distance_bins <= 0:
            raise CliUsageError(
                f"--short_distance_bins must be > 0, got {args.short_distance_bins}."
            )
        if args.short_distance_r_max is not None and (
            not math.isfinite(args.short_distance_r_max)
        ):
            raise CliUsageError(
                "--short_distance_r_max must be finite, "
                f"got {args.short_distance_r_max}."
            )

    if fit_method == "neighbors":
        r_cut, knn = _validate_neighbor_args(r_cut=args.r_cut, knn=args.knn, min_d=args.min_d)
        if not math.isfinite(args.d_min) or args.d_min < 0:
            raise CliUsageError(f"--d_min must be finite and >= 0, got {args.d_min}.")
        if not math.isfinite(args.d_max) or args.d_max <= args.d_min:
            raise CliUsageError(
                f"--d_max must be finite and > d_min ({args.d_min}), got {args.d_max}."
            )
        if not math.isfinite(args.alpha) or args.alpha <= 0:
            raise CliUsageError(f"--alpha must be finite and > 0, got {args.alpha}.")

        args.shift_phi_resolved = True if args.shift_phi is None else bool(args.shift_phi)
        return r_cut, knn

    # supercell_gr mode
    if args.r_cut is not None or args.knn is not None:
        raise CliUsageError(
            "--r_cut/--knn cannot be used with --fit_method supercell_gr; "
            "use --r_max/--sigma instead."
        )
    if args.min_d is not None:
        raise CliUsageError("--min_d cannot be used with --fit_method supercell_gr.")
    if args.max_pairs is not None and args.max_pairs <= 0:
        raise CliUsageError(f"--max_pairs must be > 0 when provided, got {args.max_pairs}.")

    if not math.isfinite(args.supercell_target_len) or args.supercell_target_len <= 0:
        raise CliUsageError(
            "--supercell_target_len must be finite and > 0, "
            f"got {args.supercell_target_len}."
        )
    if not math.isfinite(args.r_max) or args.r_max <= 0:
        raise CliUsageError(f"--r_max must be finite and > 0, got {args.r_max}.")
    if not math.isfinite(args.sigma) or args.sigma <= 0:
        raise CliUsageError(f"--sigma must be finite and > 0, got {args.sigma}.")
    if not math.isfinite(args.truncate_sigma) or args.truncate_sigma <= 0:
        raise CliUsageError(
            f"--truncate_sigma must be finite and > 0, got {args.truncate_sigma}."
        )
    if not math.isfinite(args.gr_eps) or args.gr_eps <= 0:
        raise CliUsageError(f"--gr_eps must be finite and > 0, got {args.gr_eps}.")
    if args.bin_width <= 0 or not math.isfinite(args.bin_width):
        raise CliUsageError(f"--bin_width must be finite and > 0, got {args.bin_width}.")

    # Dmytro mode is intentionally fixed to the procedure values.
    if not math.isclose(float(args.r_max), 10.0, rel_tol=0.0, abs_tol=1e-12):
        raise CliUsageError("--fit_method supercell_gr requires --r_max 10.0.")
    if not math.isclose(float(args.bin_width), 0.05, rel_tol=0.0, abs_tol=1e-12):
        raise CliUsageError("--fit_method supercell_gr requires --bin_width 0.05.")
    if not math.isclose(float(args.sigma), 0.1, rel_tol=0.0, abs_tol=1e-12):
        raise CliUsageError("--fit_method supercell_gr requires --sigma 0.1.")

    if args.no_bandpass or any(
        value is not None for value in (args.d_lo, args.d_hi, args.sigma_lo, args.sigma_hi)
    ):
        raise CliUsageError(
            "Band-pass flags are not supported with --fit_method supercell_gr; "
            "use --r_max/--sigma instead."
        )

    if args.shift_phi is not None:
        raise CliUsageError(
            "--shift_phi/--no_shift_phi are not supported with --fit_method supercell_gr; "
            "phi is fixed to -ln(g + gr_eps) with no shifting/rescaling."
        )
    args.shift_phi_resolved = False

    return None, None


def _resolve_bandpass(args: argparse.Namespace) -> BandpassParams | None:
    overrides_provided = any(
        value is not None for value in (args.d_lo, args.d_hi, args.sigma_lo, args.sigma_hi)
    )
    if args.no_bandpass:
        if overrides_provided:
            raise CliUsageError(
                "Band-pass overrides (--d_lo/--d_hi/--sigma_lo/--sigma_hi) "
                "cannot be used with --no_bandpass."
            )
        return None

    defaults = BandpassParams.defaults()
    params = BandpassParams(
        d_lo=defaults.d_lo if args.d_lo is None else args.d_lo,
        d_hi=defaults.d_hi if args.d_hi is None else args.d_hi,
        sigma_lo=defaults.sigma_lo if args.sigma_lo is None else args.sigma_lo,
        sigma_hi=defaults.sigma_hi if args.sigma_hi is None else args.sigma_hi,
    )
    try:
        validate_params(params)
    except ValueError as exc:
        raise CliUsageError(str(exc)) from exc
    return params


def _stack_pair_rows(
    pair_map: dict[tuple[str, str], np.ndarray],
    *,
    nbins: int,
) -> tuple[tuple[tuple[str, str], ...], np.ndarray]:
    ordered_pairs: tuple[tuple[str, str], ...] = tuple(sorted(pair_map))
    if not ordered_pairs:
        return ordered_pairs, np.zeros((0, nbins), dtype=np.float64)
    rows = []
    for key in ordered_pairs:
        values = np.asarray(pair_map[key], dtype=np.float64)
        if values.shape != (nbins,):
            raise ValueError(
                f"Pair map row for {key} must have shape ({nbins},), got {values.shape}."
            )
        rows.append(values)
    return ordered_pairs, np.vstack(rows).astype(np.float64, copy=False)


def _build_supercell_phi_result(
    *,
    loaded: Sequence[LoadedCIF],
    weights: np.ndarray,
    binning: Binning,
    species_whitelist: list[str] | None,
    supercell_target_len: float,
    r_max: float,
    sigma: float,
    truncate_sigma: float,
    max_pairs: int | None,
    eps: float = 1e-12,
) -> tuple[PhiResult, dict[str, Any]]:
    whitelist_set = set(species_whitelist) if species_whitelist is not None else None

    weighted_counts_by_pair: dict[tuple[str, str], np.ndarray] = {}
    weighted_g_sum_by_pair: dict[tuple[str, str], np.ndarray] = {}
    pair_weight_sum: dict[tuple[str, str], float] = {}

    total_pairs_seen = 0
    total_weighted_pairs_seen = 0.0
    pair_count_total_est = 0
    pair_count_used = 0

    repeat_counts: dict[tuple[int, int, int], int] = {}
    min_half_extent_values: list[float] = []
    gr_support_ok_all = True

    normalization_convention = (
        "g_AB(r)=counts_AB(r)/(shell(r)*prefactor_AB), "
        "shell=4*pi*r^2*dr, prefactor_AA=N_unit(A)*rho_super(A), "
        "prefactor_AB=N_unit(A)*rho_super(B)+N_unit(B)*rho_super(A) for A!=B"
    )

    for loaded_item, structure_weight in zip(loaded, weights):
        structure_weight = float(structure_weight)
        if structure_weight <= 0.0:
            continue

        unit_atoms = loaded_item.atoms
        build = build_supercell(
            unit_atoms,
            target_len=supercell_target_len,
            r_max=r_max,
            sigma=sigma,
            truncate_sigma=truncate_sigma,
        )
        super_atoms = build.atoms
        repeat_counts[build.repeats] = repeat_counts.get(build.repeats, 0) + 1
        min_half_extent_values.append(float(build.min_half_extent))
        gr_support_ok_all = bool(gr_support_ok_all and build.gr_support_ok)

        hist_result = compute_pair_histograms_supercell(
            unit_atoms=unit_atoms,
            super_atoms=super_atoms,
            edges=binning.edges,
            r_max=r_max,
            sigma=sigma,
            truncate_sigma=truncate_sigma,
            max_pairs=max_pairs,
        )

        counts = hist_result.counts
        if whitelist_set is not None:
            counts = {
                key: values
                for key, values in counts.items()
                if key[0] in whitelist_set and key[1] in whitelist_set
            }

        g_of_r = normalize_to_g_of_r(
            counts=counts,
            edges=binning.edges,
            unit_cell_volume=float(unit_atoms.get_volume()),
            N_by_species_unit=species_counts(unit_atoms),
            N_by_species_super=species_counts(super_atoms),
        )

        total_pairs_seen += int(hist_result.pair_count_used)
        total_weighted_pairs_seen += float(hist_result.pair_count_used) * structure_weight
        pair_count_total_est += int(hist_result.pair_count_total_est)
        pair_count_used += int(hist_result.pair_count_used)

        for key, values in counts.items():
            if key not in weighted_counts_by_pair:
                weighted_counts_by_pair[key] = np.zeros(binning.nbins, dtype=np.float64)
            weighted_counts_by_pair[key] += structure_weight * np.asarray(values, dtype=np.float64)

        for key, values in g_of_r.items():
            if key not in weighted_g_sum_by_pair:
                weighted_g_sum_by_pair[key] = np.zeros(binning.nbins, dtype=np.float64)
                pair_weight_sum[key] = 0.0
            weighted_g_sum_by_pair[key] += structure_weight * np.asarray(values, dtype=np.float64)
            pair_weight_sum[key] += structure_weight

    averaged_g_by_pair: dict[tuple[str, str], np.ndarray] = {}
    for key in sorted(weighted_g_sum_by_pair):
        w = pair_weight_sum.get(key, 0.0)
        if w <= 0.0:
            continue
        averaged_g_by_pair[key] = weighted_g_sum_by_pair[key] / w

    pairs, g_rows = _stack_pair_rows(averaged_g_by_pair, nbins=binning.nbins)
    if pairs:
        counts_rows = np.vstack(
            [
                np.asarray(
                    weighted_counts_by_pair.get(key, np.zeros(binning.nbins, dtype=np.float64)),
                    dtype=np.float64,
                )
                for key in pairs
            ]
        ).astype(np.float64, copy=False)
    else:
        counts_rows = np.zeros((0, binning.nbins), dtype=np.float64)

    phi_rows = -np.log(g_rows + float(eps))

    phi_res = PhiResult(
        binning=binning,
        alpha=0.0,
        shifted=False,
        pairs=pairs,
        p=g_rows,
        phi=phi_rows,
        counts=counts_rows,
    )
    stats: dict[str, Any] = {
        "total_pairs_seen": float(total_pairs_seen),
        "total_weighted_pairs_seen": float(total_weighted_pairs_seen),
        "pair_count_total_est": int(pair_count_total_est),
        "pair_count_used": int(pair_count_used),
        "supercell_repeats": [
            {"repeats": [int(r[0]), int(r[1]), int(r[2])], "count": int(repeat_counts[r])}
            for r in sorted(repeat_counts)
        ],
        "supercell_min_half_extent": (
            float(min(min_half_extent_values)) if min_half_extent_values else None
        ),
        "gr_support_ok": bool(gr_support_ok_all),
        "normalization_convention": normalization_convention,
    }
    return phi_res, stats


def _resolve_bandpass_from_values(
    *,
    use_bandpass: bool,
    d_lo: float | None,
    d_hi: float | None,
    sigma_lo: float | None,
    sigma_hi: float | None,
) -> BandpassParams | None:
    overrides_provided = any(
        value is not None for value in (d_lo, d_hi, sigma_lo, sigma_hi)
    )
    if not use_bandpass:
        if overrides_provided:
            raise CliUsageError(
                "Band-pass overrides (--d_lo/--d_hi/--sigma_lo/--sigma_hi) "
                "cannot be used with --no_bandpass."
            )
        return None

    defaults = BandpassParams.defaults()
    params = BandpassParams(
        d_lo=defaults.d_lo if d_lo is None else d_lo,
        d_hi=defaults.d_hi if d_hi is None else d_hi,
        sigma_lo=defaults.sigma_lo if sigma_lo is None else sigma_lo,
        sigma_hi=defaults.sigma_hi if sigma_hi is None else sigma_hi,
    )
    try:
        validate_params(params)
    except ValueError as exc:
        raise CliUsageError(str(exc)) from exc
    return params


def _run_fit(args: argparse.Namespace) -> int:
    r_cut, knn = _validate_fit_args(args)
    fit_method = str(args.fit_method)
    bandpass = _resolve_bandpass(args) if fit_method == "neighbors" else None
    species_whitelist = _parse_species_whitelist(args.species_whitelist)

    loaded_all = load_cifs_from_dir(args.cif_dir)
    if not loaded_all:
        raise RuntimeError(f"No CIF files found in directory: {args.cif_dir}")
    num_structures_total = len(loaded_all)

    meta_csv_value: str | None = None
    unmatched_meta_rows = 0
    missing_meta_for_cifs = 0
    selected_indices = list(range(num_structures_total))
    meta_match = None
    if args.meta_csv is not None:
        meta_map = load_meta_map(args.meta_csv)
        meta_match = match_meta_rows(loaded_all, meta_map)
        meta_csv_value = str(meta_map.csv_path)
        unmatched_meta_rows = meta_match.unmatched_meta_rows

        if args.property_filter is not None:
            missing_meta_for_cifs = meta_match.missing_meta_for_cifs
            if args.property_mode == "include":
                selected_indices = [
                    i
                    for i, label in enumerate(meta_match.labels)
                    if label is not None and label == args.property_filter
                ]
            else:
                selected_indices = [
                    i
                    for i, label in enumerate(meta_match.labels)
                    if label is not None and label != args.property_filter
                ]

    loaded = [loaded_all[i] for i in selected_indices]
    if not loaded:
        raise RuntimeError("No CIF structures selected after metadata/property filtering.")

    weights = np.ones(len(loaded), dtype=np.float64)
    weights_csv_value = None
    weights_source = "default"
    if args.weights_csv:
        weights = np.asarray(
            load_structure_weights(
                weights_csv=args.weights_csv,
                loaded_cifs=loaded,
            ),
            dtype=np.float64,
        )
        weights_csv_value = str(args.weights_csv.resolve())
        weights_source = "weights_csv"
    elif meta_match is not None:
        selected_meta_weights = [meta_match.weights[i] for i in selected_indices]
        if any(weight is not None for weight in selected_meta_weights):
            weights = np.asarray(
                [
                1.0 if weight is None else float(weight) for weight in selected_meta_weights
                ],
                dtype=np.float64,
            )
            weights_source = "meta_csv"

    excluded_structure_count = 0
    covalent_rules_path: str | None = None
    excluded_by_rule: dict[str, int] = {}
    sample_exclusions: list[dict[str, Any]] = []
    if args.covalent_rules is not None:
        covalent_rules_path = str(args.covalent_rules.resolve())
    if args.exclude_covalent:
        assert args.covalent_rules is not None  # validated in _validate_fit_args
        rules = load_covalent_rules(args.covalent_rules)
        for idx, loaded_item in enumerate(loaded):
            hit, info = has_covalent_like_contact(loaded_item.atoms, rules)
            if hit:
                excluded_structure_count += 1
                weights[idx] = 0.0
                rule_id = str(info.get("matched_rule", {}).get("source_id", "<unknown>"))
                excluded_by_rule[rule_id] = excluded_by_rule.get(rule_id, 0) + 1
                if len(sample_exclusions) < 50:
                    sample_exclusions.append(
                        {
                            "cif_name": Path(loaded_item.path).name,
                            "pair_key": info.get("pair_key"),
                            "threshold": info.get("threshold"),
                            "observed_min_distance": info.get("observed_min_distance"),
                            "atom_indices": info.get("atom_indices"),
                            "matched_rule": info.get("matched_rule"),
                        }
                    )

    total_pairs_seen = 0.0
    total_weighted_pairs_seen = 0.0
    supercell_stats: dict[str, Any] = {}
    if fit_method == "neighbors":
        hist = accumulate_histograms(
            [item.atoms for item in loaded],
            structure_weights=weights.tolist(),
            r_cut=r_cut,
            k=knn,
            min_d=args.min_d,
            bandpass=bandpass,
            species_whitelist=species_whitelist,
            d_min=args.d_min,
            d_max=args.d_max,
            bin_width=args.bin_width,
        )
        phi_res = build_phi_from_hist(
            hist,
            alpha=args.alpha,
            shifted=bool(args.shift_phi_resolved),
        )
        total_pairs_seen = float(hist.total_pairs_seen)
        total_weighted_pairs_seen = float(hist.total_weighted_pairs_seen)
    else:
        binning = make_uniform_binning(
            d_min=0.0,
            d_max=float(args.r_max),
            bin_width=float(args.bin_width),
        )
        phi_res, supercell_stats = _build_supercell_phi_result(
            loaded=loaded,
            weights=weights,
            binning=binning,
            species_whitelist=species_whitelist,
            supercell_target_len=float(args.supercell_target_len),
            r_max=float(args.r_max),
            sigma=float(args.sigma),
            truncate_sigma=float(args.truncate_sigma),
            max_pairs=args.max_pairs,
            eps=float(args.gr_eps),
        )
        total_pairs_seen = float(supercell_stats["total_pairs_seen"])
        total_weighted_pairs_seen = float(supercell_stats["total_weighted_pairs_seen"])
        if args.dump_gr_csv is not None:
            selected_pairs = parse_pair_values(args.dump_gr_pair)
            dump_gr_csv(
                out_dir=args.dump_gr_csv,
                edges=phi_res.binning.edges,
                pairs=phi_res.pairs,
                g_rows=phi_res.p,
                phi_rows=phi_res.phi,
                selected_pairs=selected_pairs,
            )

    manifest_extra = {
        "cif_dir": str(args.cif_dir.resolve()),
        "meta_csv": meta_csv_value,
        "property_filter": args.property_filter,
        "property_mode": args.property_mode,
        "num_structures": len(loaded),
        "num_structures_selected": len(loaded),
        "num_structures_total": num_structures_total,
        "missing_meta_for_cifs": missing_meta_for_cifs,
        "unmatched_meta_rows": unmatched_meta_rows,
        "fit_method": fit_method,
        "supercell_target_len": (
            float(args.supercell_target_len) if fit_method == "supercell_gr" else None
        ),
        "r_max": float(args.r_max) if fit_method == "supercell_gr" else None,
        "bin_width": float(args.bin_width) if fit_method == "supercell_gr" else None,
        "sigma": float(args.sigma) if fit_method == "supercell_gr" else None,
        "truncate_sigma": float(args.truncate_sigma) if fit_method == "supercell_gr" else None,
        "gr_eps": float(args.gr_eps) if fit_method == "supercell_gr" else None,
        "covalent_rules_path": covalent_rules_path,
        "excluded_structure_count": excluded_structure_count,
        "excluded_by_rule": dict(sorted(excluded_by_rule.items())),
        "sample_exclusions": sample_exclusions,
        "r_cut": r_cut,
        "knn": knn,
        "min_d": args.min_d,
        "weights_source": weights_source,
        "bandpass": (
            {
                "enabled": True,
                "d_lo": bandpass.d_lo,
                "d_hi": bandpass.d_hi,
                "sigma_lo": bandpass.sigma_lo,
                "sigma_hi": bandpass.sigma_hi,
            }
            if bandpass is not None
            else {"enabled": False}
        ),
        "weights_csv": weights_csv_value,
        "species_whitelist": species_whitelist,
        "total_pairs_seen": total_pairs_seen,
        "total_weighted_pairs_seen": total_weighted_pairs_seen,
    }
    if fit_method == "supercell_gr":
        manifest_extra["supercell_repeats"] = supercell_stats.get("supercell_repeats")
        manifest_extra["supercell_min_half_extent"] = supercell_stats.get(
            "supercell_min_half_extent"
        )
        manifest_extra["gr_support_ok"] = supercell_stats.get("gr_support_ok")
        manifest_extra["normalization_convention"] = supercell_stats.get(
            "normalization_convention"
        )
        manifest_extra["pair_count_total_est"] = supercell_stats.get("pair_count_total_est")
        manifest_extra["pair_count_used"] = supercell_stats.get("pair_count_used")
        manifest_extra["max_pairs"] = args.max_pairs
    if len(loaded) <= 200:
        manifest_extra["selected_cif_names"] = [Path(item.path).name for item in loaded]
    if args.dump_gr_csv is not None:
        manifest_extra["dump_gr_csv"] = str(args.dump_gr_csv.resolve())
    if args.dump_gr_pair is not None:
        manifest_extra["dump_gr_pair"] = list(args.dump_gr_pair)

    out_root = export_spp_root(
        out_root=args.out_root,
        phi_res=phi_res,
        name=args.name,
        write_manifest=True,
        manifest_extra=manifest_extra,
        short_distance_floor=args.short_distance_floor,
        short_distance_bins=args.short_distance_bins,
        short_distance_r_max=args.short_distance_r_max,
    )

    print(f"CIFs loaded: {num_structures_total}")
    print(f"CIFs selected: {len(loaded)}")
    if args.property_filter is not None:
        print(f"property_filter: {args.property_filter} ({args.property_mode})")
    print(f"Pairs exported: {len(phi_res.pairs)}")
    print(f"nbins: {phi_res.binning.nbins}")
    print(f"fit_method: {fit_method}")
    if fit_method == "neighbors":
        neighbor_label = f"r_cut={r_cut}" if r_cut is not None else f"knn={knn}"
        print(f"alpha: {phi_res.alpha}")
        print(f"neighbor: {neighbor_label}")
    else:
        print(f"supercell_target_len: {args.supercell_target_len}")
        print(f"r_max: {args.r_max}")
        print(f"bin_width: {args.bin_width}")
        print(f"sigma: {args.sigma}")
        print(f"truncate_sigma: {args.truncate_sigma}")
        print(f"gr_eps: {args.gr_eps}")
        print(f"pair_count_used: {supercell_stats.get('pair_count_used')}")
        print(f"pair_count_total_est: {supercell_stats.get('pair_count_total_est')}")
    if args.exclude_covalent:
        print(f"excluded_covalent_structures: {excluded_structure_count}")
    if args.dump_gr_csv is not None:
        print(f"gr_dump_csv: {args.dump_gr_csv}")
    print(f"output: {out_root}")
    return 0


def _validate_score_args(args: argparse.Namespace) -> tuple[float | None, int | None]:
    r_cut, knn = _validate_neighbor_args(r_cut=args.r_cut, knn=args.knn, min_d=args.min_d)
    if args.top_pairs is not None and args.top_pairs <= 0:
        raise CliUsageError(f"--top_pairs must be > 0, got {args.top_pairs}.")
    return r_cut, knn


def _format_pair_map(by_pair: dict[tuple[str, str], float]) -> dict[str, float]:
    return {f"{a}-{b}": float(value) for (a, b), value in sorted(by_pair.items())}


def _top_pairs(report: ScoreReport, n: int | None) -> list[tuple[tuple[str, str], float]]:
    items = sorted(report.by_pair.items(), key=lambda kv: (-kv[1], kv[0]))
    return items if n is None else items[:n]


def _single_structure_output(
    *,
    loaded: LoadedCIF,
    report: ScoreReport,
    json_output: bool,
    top_pairs: int | None,
    name: str | None,
) -> None:
    if json_output:
        payload: dict[str, Any] = {
            "name": name,
            "cif": str(loaded.path),
            "total": float(report.total),
            "num_edges": report.num_edges,
            "num_scored_edges": report.num_scored_edges,
            "skipped_out_of_range": report.skipped_out_of_range,
            "skipped_missing_pair": report.skipped_missing_pair,
            "by_pair": _format_pair_map(report.by_pair),
        }
        if top_pairs is not None:
            payload["top_pairs"] = [
                {"pair": f"{a}-{b}", "score": float(score)}
                for (a, b), score in _top_pairs(report, top_pairs)
            ]
        print(json.dumps(payload, sort_keys=True))
        return

    print(f"CIF: {loaded.path}")
    if name:
        print(f"name: {name}")
    print(f"total: {report.total:.8f}")
    print(f"num_edges: {report.num_edges}")
    print(f"num_scored_edges: {report.num_scored_edges}")
    print(f"skipped_out_of_range: {report.skipped_out_of_range}")
    print(f"skipped_missing_pair: {report.skipped_missing_pair}")
    selected = _top_pairs(report, top_pairs)
    if selected:
        print("by_pair:")
        for (a, b), value in selected:
            print(f"  {a}-{b}: {value:.8f}")


def _run_score(args: argparse.Namespace) -> int:
    r_cut, knn = _validate_score_args(args)

    model = load_spp_model_with_policies(
        args.spp_root,
        oob_policy=args.oob_policy,
        missing_pair_policy=args.missing_pair_policy,
    )
    if not model.pairs:
        raise RuntimeError(f"No pair curves found in SPP root: {args.spp_root}")

    if args.cif is not None:
        structures = [load_cif(args.cif)]
    else:
        assert args.cif_dir is not None
        structures = load_cifs_from_dir(args.cif_dir)
        if not structures:
            raise RuntimeError(f"No CIF files found in directory: {args.cif_dir}")

    use_bandpass = bool(args.use_bandpass)
    bandpass = BandpassParams.defaults() if use_bandpass else None

    totals: list[float] = []
    for loaded in structures:
        report = score_atoms(
            loaded.atoms,
            model,
            r_cut=r_cut,
            k=knn,
            min_d=args.min_d,
            bandpass=bandpass,
            use_bandpass=use_bandpass,
        )
        totals.append(float(report.total))

        if len(structures) == 1:
            _single_structure_output(
                loaded=loaded,
                report=report,
                json_output=args.json_output,
                top_pairs=args.top_pairs,
                name=args.name,
            )
        else:
            if args.json_output:
                payload: dict[str, Any] = {
                    "type": "structure",
                    "name": args.name,
                    "cif": str(loaded.path),
                    "total": float(report.total),
                    "num_edges": report.num_edges,
                    "num_scored_edges": report.num_scored_edges,
                    "skipped_out_of_range": report.skipped_out_of_range,
                    "skipped_missing_pair": report.skipped_missing_pair,
                    "by_pair": _format_pair_map(report.by_pair),
                }
                if args.top_pairs is not None:
                    payload["top_pairs"] = [
                        {"pair": f"{a}-{b}", "score": float(score)}
                        for (a, b), score in _top_pairs(report, args.top_pairs)
                    ]
                print(json.dumps(payload, sort_keys=True))
            else:
                print(
                    f"{Path(loaded.path).name}: total={report.total:.8f} "
                    f"edges={report.num_edges} scored={report.num_scored_edges}"
                )
                if args.top_pairs is not None:
                    for (a, b), score in _top_pairs(report, args.top_pairs):
                        print(f"  {a}-{b}: {score:.8f}")

    if len(structures) > 1:
        mean_total = statistics.mean(totals)
        median_total = statistics.median(totals)
        min_total = min(totals)
        max_total = max(totals)
        if args.json_output:
            payload = {
                "type": "aggregate",
                "name": args.name,
                "num_structures": len(structures),
                "mean_total": float(mean_total),
                "median_total": float(median_total),
                "min_total": float(min_total),
                "max_total": float(max_total),
            }
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                "Aggregate: "
                f"n={len(structures)} mean={mean_total:.8f} median={median_total:.8f} "
                f"min={min_total:.8f} max={max_total:.8f}"
            )

    return 0


def _validate_calibrate_args(args: argparse.Namespace) -> tuple[float | None, int | None]:
    score_method = str(args.score_method)
    if score_method not in {"neighbors", "supercell_gr"}:
        raise CliUsageError(f"--score_method must be neighbors or supercell_gr, got {score_method}.")

    if score_method == "neighbors":
        r_cut, knn = _validate_neighbor_args(r_cut=args.r_cut, knn=args.knn, min_d=args.min_d)
    else:
        r_cut, knn = None, None
        if args.min_d is not None:
            raise CliUsageError(
                "--min_d is not used with --score_method supercell_gr."
            )

    if not math.isfinite(args.target) or args.target <= 0:
        raise CliUsageError(f"--target must be finite and > 0, got {args.target}.")
    if args.mode == "quantile":
        if not math.isfinite(args.q) or args.q < 0.0 or args.q > 1.0:
            raise CliUsageError(f"--q must be in [0,1] for quantile mode, got {args.q}.")
    if args.max_n is not None and args.max_n <= 0:
        raise CliUsageError(f"--max_n must be > 0 when provided, got {args.max_n}.")
    if args.convention not in {"reward", "penalty"}:
        raise CliUsageError(
            f"--convention must be reward or penalty, got {args.convention}."
        )
    if not math.isfinite(args.min_lambda) or args.min_lambda < 0:
        raise CliUsageError(
            f"--min_lambda must be finite and >= 0, got {args.min_lambda}."
        )
    if not math.isfinite(args.max_lambda) or args.max_lambda <= 0:
        raise CliUsageError(
            f"--max_lambda must be finite and > 0, got {args.max_lambda}."
        )
    if args.max_lambda < args.min_lambda:
        raise CliUsageError(
            f"--max_lambda must be >= --min_lambda ({args.min_lambda}), got {args.max_lambda}."
        )
    return r_cut, knn


def _publish_guidance_artifact(
    *,
    artifact_root: Path,
    qlip_outputs: Path,
    name: str,
    params: dict[str, Any],
    checks: dict[str, Any],
) -> tuple[str, Path]:
    kind: ArtifactKind = "guidance"
    qlip_outputs = qlip_outputs.resolve()
    ensure_qlip_outputs_layout(qlip_outputs)

    now_utc = datetime.now(timezone.utc)
    guidance_file = artifact_root / "guidance.json"
    if guidance_file.is_file():
        hash_bytes = guidance_file.read_bytes()
    else:
        hash_bytes = str(artifact_root.resolve()).encode("utf-8")
    run_id = build_run_id(name=name, manifest_bytes=hash_bytes, now_utc=now_utc)

    runs_root = kind_runs_root(qlip_outputs, kind)
    run_dir = runs_root / run_id
    if run_dir.exists():
        raise RuntimeError(f"Run folder already exists: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)

    root_dirname = kind_root_dirname(kind)
    published_root = run_dir / root_dirname
    copy_or_symlink_tree(artifact_root, published_root, mode="copy")

    compat_text = "Compatibility check skipped for non-SPP artifact kind.\n"
    (run_dir / "compat_report.txt").write_text(compat_text, encoding="utf-8")

    script_repo_root = Path(__file__).resolve().parents[2]
    git_sha = get_git_sha(script_repo_root)
    publish_meta: dict[str, Any] = {
        "run_id": run_id,
        "kind": kind,
        "name": name,
        "timestamp_utc": now_utc.isoformat(),
        "source_artifact_root": str(artifact_root.resolve()),
        "git_sha": git_sha,
        "tool": "SPP_Maker",
        "tool_version": spp_maker_version,
        "python_version": python_version_short(),
        "copy_mode": "copy",
        "checks": checks,
        "set_latest": True,
    }
    write_json(run_dir / "publish_meta.json", publish_meta)

    run_rel = to_posix_relative(run_dir, qlip_outputs)
    run_record: dict[str, Any] = {
        "run_id": run_id,
        "kind": kind,
        "name": name,
        "timestamp_utc": now_utc.isoformat(),
        "path": run_rel,
        "source": {
            "source_path": str(artifact_root.resolve()),
            "git_sha": git_sha,
            "tool": "SPP_Maker",
            "tool_version": spp_maker_version,
        },
        "params": params,
        "checks": checks,
    }

    index_path = qlip_outputs / "index.json"
    index_obj = load_index(index_path)
    bucket = kind_to_bucket(kind)
    bucket_obj = dict(index_obj["artifacts"][bucket])
    runs = [
        r
        for r in bucket_obj.get("runs", [])
        if not (isinstance(r, dict) and r.get("run_id") == run_id)
    ]
    runs.append(run_record)
    bucket_obj["runs"] = runs
    bucket_obj["latest"] = run_rel
    index_obj["artifacts"][bucket] = bucket_obj
    write_index(index_path, index_obj)

    kind_latest_file(qlip_outputs, kind).write_text(run_rel + "\n", encoding="utf-8")
    return run_id, run_dir


def _calibration_stats_payload(stats: CalibrationStats) -> dict[str, Any]:
    return {
        "num_structures": int(stats.num_structures),
        "num_edges_total": int(stats.num_edges_total),
        "score_structures": stats.score_structures.tolist(),
        "score_edges": stats.score_edges.tolist(),
        "summary": stats.summary,
    }


def _run_calibrate(args: argparse.Namespace) -> int:
    r_cut, knn = _validate_calibrate_args(args)
    score_method = str(args.score_method)
    if score_method == "neighbors":
        bandpass = _resolve_bandpass_from_values(
            use_bandpass=bool(args.use_bandpass),
            d_lo=args.d_lo,
            d_hi=args.d_hi,
            sigma_lo=args.sigma_lo,
            sigma_hi=args.sigma_hi,
        )
        use_bandpass = bool(args.use_bandpass)
    else:
        use_bandpass = False
        bandpass = None
        if bool(args.use_bandpass) or any(
            value is not None for value in (args.d_lo, args.d_hi, args.sigma_lo, args.sigma_hi)
        ):
            print(
                "Warning: bandpass settings are ignored for --score_method supercell_gr.",
                file=sys.stderr,
            )

    stats = collect_scores_for_corpus(
        spp_root=args.spp_root,
        cif_dir=args.cif_dir,
        max_n=args.max_n,
        score_method=score_method,
        r_cut=r_cut,
        knn=knn,
        min_d=args.min_d,
        use_bandpass=use_bandpass,
        bandpass=bandpass,
        supercell_target_len=20.0,
        r_max=10.0,
        bin_width=0.05,
        sigma=0.1,
        truncate_sigma=3.0,
        oob_policy=args.oob_policy,
        missing_pair_policy=args.missing_pair_policy,
    )

    if args.mode == "structure_median":
        recommendation = recommend_lambda_by_structure_median(
            stats,
            args.target,
            convention=args.convention,
            min_lambda=args.min_lambda,
            max_lambda=args.max_lambda,
        )
    elif args.mode == "edge_median":
        recommendation = recommend_lambda_by_edge_median(
            stats,
            args.target,
            convention=args.convention,
            min_lambda=args.min_lambda,
            max_lambda=args.max_lambda,
        )
    else:
        recommendation = recommend_lambda_quantile(
            stats,
            args.q,
            args.target,
            convention=args.convention,
            min_lambda=args.min_lambda,
            max_lambda=args.max_lambda,
        )
    lambda_used = float(recommendation.lambda_used)

    scaled_root: Path | None = None
    if args.write_scaled_root is not None:
        scaled_root = scale_spp_root(
            in_root=args.spp_root,
            out_root=args.write_scaled_root,
            lambda_=lambda_used,
            convention=args.convention,
            source_calibration_json=(
                str(args.out_json.resolve()) if args.out_json is not None else None
            ),
            min_lambda=float(args.min_lambda),
            max_lambda=float(args.max_lambda),
        )
        compat_report = check_pot_root(scaled_root, strict=True)
        if not compat_report.ok:
            raise RuntimeError(
                "Scaled SPP root failed strict POT compatibility checks "
                f"(checked={compat_report.checked}, failed={compat_report.failed})."
            )

    result_payload: dict[str, Any] = {
        "mode": args.mode,
        "target": float(args.target),
        "q": float(args.q),
        "recommended_lambda": lambda_used,
        "lambda_raw": float(recommendation.lambda_raw_signed),
        "lambda_abs": float(recommendation.lambda_positive),
        "lambda_clipped": bool(recommendation.lambda_clipped),
        "min_lambda": float(args.min_lambda),
        "max_lambda": float(args.max_lambda),
        "lambda_used": lambda_used,
        "convention": str(args.convention),
        "score_method": score_method,
        "bandpass_enabled": bool(use_bandpass),
        "spp_root": str(args.spp_root.resolve()),
        "cif_dir": str(args.cif_dir.resolve()),
        "max_n": args.max_n,
        "neighbor": {
            "r_cut": r_cut,
            "knn": knn,
            "min_d": args.min_d,
        }
        if score_method == "neighbors"
        else None,
        "supercell": (
            {
                "target_len": 20.0,
                "r_max": 10.0,
                "bin_width": 0.05,
                "sigma": 0.1,
                "truncate_sigma": 3.0,
            }
            if score_method == "supercell_gr"
            else None
        ),
        "bandpass": (
            {
                "enabled": True,
                "d_lo": bandpass.d_lo,
                "d_hi": bandpass.d_hi,
                "sigma_lo": bandpass.sigma_lo,
                "sigma_hi": bandpass.sigma_hi,
            }
            if bandpass is not None
            else {"enabled": False}
        ),
        "policies": {
            "oob_policy": args.oob_policy,
            "missing_pair_policy": args.missing_pair_policy,
        },
        "stats": _calibration_stats_payload(stats),
        "scaled_root": str(scaled_root) if scaled_root is not None else None,
    }

    publish_info: dict[str, Any] | None = None
    if args.publish:
        publish_name = args.name or (
            "calibration_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        )
        checks = {
            "calibration": {
                "ok": True,
                "mode": args.mode,
                "target": float(args.target),
                "recommended_lambda": lambda_used,
            }
        }
        params = {
            "mode": args.mode,
            "target": float(args.target),
            "q": float(args.q),
            "score_method": score_method,
            "convention": str(args.convention),
            "min_lambda": float(args.min_lambda),
            "max_lambda": float(args.max_lambda),
            "max_n": args.max_n,
            "oob_policy": args.oob_policy,
            "missing_pair_policy": args.missing_pair_policy,
            "write_scaled_root": str(scaled_root) if scaled_root is not None else None,
        }
        with tempfile.TemporaryDirectory(prefix="spp_maker_calibration_") as tmp_dir:
            guidance_root = Path(tmp_dir) / "guidance"
            guidance_root.mkdir(parents=True, exist_ok=True)
            guidance_payload = {
                "kind": "calibration",
                "name": publish_name,
                "recommended_lambda": lambda_used,
                "mode": args.mode,
                "target": float(args.target),
                "q": float(args.q),
                "score_method": score_method,
                "convention": str(args.convention),
                "spp_root": str(args.spp_root.resolve()),
                "scaled_root": str(scaled_root) if scaled_root is not None else None,
                "stats_summary": stats.summary,
            }
            write_json(guidance_root / "guidance.json", guidance_payload)
            run_id, run_dir = _publish_guidance_artifact(
                artifact_root=guidance_root,
                qlip_outputs=args.qlip_outputs,
                name=publish_name,
                params=params,
                checks=checks,
            )
        publish_info = {
            "run_id": run_id,
            "run_path": str(run_dir),
            "qlip_outputs": str(args.qlip_outputs.resolve()),
        }
        result_payload["published"] = publish_info
    else:
        result_payload["published"] = None

    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        with args.out_json.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(result_payload, handle, indent=2, sort_keys=True)
            handle.write("\n")

    structure_median = stats.summary["structure_scores"]["median"]
    edge_median = stats.summary["edge_scores"]["median"]
    print(f"num_structures: {stats.num_structures}")
    print(f"num_edges_total: {stats.num_edges_total}")
    print(f"median_structure_score: {structure_median:.8f}")
    print(f"median_edge_score: {edge_median:.8f}")
    print(f"score_method: {score_method}")
    print(f"bandpass_enabled: {use_bandpass}")
    print(f"convention: {args.convention}")
    print(f"lambda_raw: {recommendation.lambda_raw_signed:.8f}")
    print(f"lambda_abs: {recommendation.lambda_positive:.8f}")
    print(f"recommended_lambda: {lambda_used:.8f}")
    print(f"lambda_used: {lambda_used:.8f}")
    if scaled_root is not None:
        print(f"scaled_root: {scaled_root}")
    if publish_info is not None:
        print(f"published_run_id: {publish_info['run_id']}")
        print(f"published_run_path: {publish_info['run_path']}")
    return 0


def _validate_run_args(args: argparse.Namespace) -> None:
    if args.property_filter is not None and args.meta_csv is None:
        raise CliUsageError("--property_filter requires --meta_csv.")
    if not math.isfinite(args.target) or args.target <= 0:
        raise CliUsageError(f"--target must be finite and > 0, got {args.target}.")
    if args.max_calib is not None and args.max_calib <= 0:
        raise CliUsageError(f"--max_calib must be > 0 when provided, got {args.max_calib}.")
    if args.r_cut is not None and (not math.isfinite(args.r_cut) or args.r_cut <= 0):
        raise CliUsageError(f"--r_cut must be finite and > 0, got {args.r_cut}.")
    if args.knn is not None and args.knn <= 0:
        raise CliUsageError(f"--knn must be > 0, got {args.knn}.")
    if args.min_d is not None and (not math.isfinite(args.min_d) or args.min_d < 0):
        raise CliUsageError(f"--min_d must be finite and >= 0, got {args.min_d}.")
    if not math.isfinite(args.min_lambda) or args.min_lambda < 0:
        raise CliUsageError(f"--min_lambda must be finite and >= 0, got {args.min_lambda}.")
    if not math.isfinite(args.max_lambda) or args.max_lambda <= 0:
        raise CliUsageError(f"--max_lambda must be finite and > 0, got {args.max_lambda}.")
    if args.max_lambda < args.min_lambda:
        raise CliUsageError(
            f"--max_lambda must be >= --min_lambda ({args.min_lambda}), got {args.max_lambda}."
        )
    if args.fit_method == "neighbors":
        if not math.isfinite(args.d_min) or args.d_min < 0:
            raise CliUsageError(f"--d_min must be finite and >= 0, got {args.d_min}.")
        if not math.isfinite(args.d_max) or args.d_max <= args.d_min:
            raise CliUsageError(
                f"--d_max must be finite and > d_min ({args.d_min}), got {args.d_max}."
            )
        if not math.isfinite(args.alpha) or args.alpha <= 0:
            raise CliUsageError(f"--alpha must be finite and > 0, got {args.alpha}.")
    else:
        if args.max_pairs is not None and args.max_pairs <= 0:
            raise CliUsageError(f"--max_pairs must be > 0 when provided, got {args.max_pairs}.")
        if not math.isclose(float(args.r_max), 10.0, rel_tol=0.0, abs_tol=1e-12):
            raise CliUsageError("--fit_method supercell_gr requires --r_max 10.0.")
        if not math.isclose(float(args.bin_width), 0.05, rel_tol=0.0, abs_tol=1e-12):
            raise CliUsageError("--fit_method supercell_gr requires --bin_width 0.05.")
        if not math.isclose(float(args.sigma), 0.1, rel_tol=0.0, abs_tol=1e-12):
            raise CliUsageError("--fit_method supercell_gr requires --sigma 0.1.")
    if not bool(args.use_bandpass) and any(
        value is not None for value in (args.d_lo, args.d_hi, args.sigma_lo, args.sigma_hi)
    ):
        raise CliUsageError(
            "Band-pass overrides (--d_lo/--d_hi/--sigma_lo/--sigma_hi) "
            "cannot be used with --no_bandpass."
        )
    if not math.isfinite(args.q) or args.q < 0.0 or args.q > 1.0:
        raise CliUsageError(f"--q must be in [0,1], got {args.q}.")


def _run_run(args: argparse.Namespace) -> int:
    _validate_run_args(args)
    config = RunConfig(
        name=str(args.name),
        cif_dir=args.cif_dir.resolve(),
        out_dir=args.out_dir.resolve(),
        fit_method=str(args.fit_method),
        calib_score_method=str(args.calib_score_method),
        target=float(args.target),
        max_calib=args.max_calib,
        use_bandpass=bool(args.use_bandpass),
        convention=str(args.convention),
        min_lambda=float(args.min_lambda),
        max_lambda=float(args.max_lambda),
        calibration_mode=str(args.calib_mode),
        q=float(args.q),
        r_cut=args.r_cut,
        knn=args.knn,
        min_d=args.min_d,
        d_lo=args.d_lo,
        d_hi=args.d_hi,
        sigma_lo=args.sigma_lo,
        sigma_hi=args.sigma_hi,
        d_min=float(args.d_min),
        d_max=float(args.d_max),
        alpha=float(args.alpha),
        supercell_target_len=float(args.supercell_target_len),
        r_max=float(args.r_max),
        bin_width=float(args.bin_width),
        sigma=float(args.sigma),
        truncate_sigma=float(args.truncate_sigma),
        gr_eps=float(args.gr_eps),
        max_pairs=args.max_pairs,
        meta_csv=(None if args.meta_csv is None else args.meta_csv.resolve()),
        property_filter=args.property_filter,
        property_mode=str(args.property_mode),
        publish_to=(None if args.publish_to is None else args.publish_to.resolve()),
    )
    result = run_pipeline(config)
    print(f"run_id: {result.run_id}")
    print(f"run_root: {result.run_root}")
    print(f"final_bundle: {result.final_bundle}")
    print(f"content_hash: {result.content_hash}")
    print(f"lambda_used: {result.lambda_used:.8f}")
    if result.published is not None:
        for key in sorted(result.published):
            print(f"published_{key}: {result.published[key]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spp-maker",
        description="Generate and score SPP data for QLIP-compatible workflows.",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        metavar="{fit,score,calibrate,run}",
        required=True,
    )

    fit_parser = subparsers.add_parser(
        "fit",
        help="Fit SPP potentials from a CIF corpus.",
        description="Fit SPP potentials from a CIF corpus and export QLIP-compatible POT files.",
    )
    fit_parser.add_argument("--cif_dir", type=Path, required=True)
    fit_parser.add_argument("--out_root", type=Path, required=True)
    fit_parser.add_argument(
        "--fit_method",
        choices=("neighbors", "supercell_gr"),
        default="neighbors",
        help="Fitting backend (default: neighbors).",
    )

    neighbor_group = fit_parser.add_mutually_exclusive_group()
    neighbor_group.add_argument(
        "--r_cut",
        type=float,
        default=None,
        help="Neighbor cutoff distance in Angstrom (default: 4.0 if --knn not set).",
    )
    neighbor_group.add_argument(
        "--knn",
        type=int,
        default=None,
        help="Use k-nearest neighbors instead of cutoff radius.",
    )
    fit_parser.add_argument(
        "--min_d",
        type=float,
        default=None,
        help="Optional hard lower bound for accepted distances.",
    )

    fit_parser.add_argument("--d_min", type=float, default=0.5)
    fit_parser.add_argument("--d_max", type=float, default=8.0)
    fit_parser.add_argument("--bin_width", type=float, default=0.05)
    fit_parser.add_argument("--alpha", type=float, default=1e-3)
    fit_parser.add_argument(
        "--supercell_target_len",
        type=float,
        default=20.0,
        help="Target minimum supercell length per axis for supercell_gr (Angstrom).",
    )
    fit_parser.add_argument(
        "--r_max",
        type=float,
        default=10.0,
        help="Maximum distance for supercell_gr histogram accumulation (Angstrom).",
    )
    fit_parser.add_argument(
        "--sigma",
        type=float,
        default=0.1,
        help="Gaussian deposition sigma for supercell_gr (Angstrom).",
    )
    fit_parser.add_argument(
        "--truncate_sigma",
        type=float,
        default=3.0,
        help="Gaussian truncation window in sigma units for supercell_gr (default: 3.0).",
    )
    fit_parser.add_argument(
        "--gr_eps",
        type=float,
        default=1e-12,
        help="Small epsilon used in phi=-ln(g+gr_eps) for supercell_gr.",
    )
    fit_parser.add_argument(
        "--max_pairs",
        type=int,
        default=None,
        help="Optional cap on accepted unit->super distances per structure in supercell_gr.",
    )

    fit_parser.add_argument("--d_lo", type=float, default=None)
    fit_parser.add_argument("--d_hi", type=float, default=None)
    fit_parser.add_argument("--sigma_lo", type=float, default=None)
    fit_parser.add_argument("--sigma_hi", type=float, default=None)
    fit_parser.add_argument(
        "--no_bandpass",
        action="store_true",
        help="Disable band-pass weighting (enabled by default).",
    )

    fit_parser.add_argument(
        "--weights_csv",
        type=Path,
        default=None,
        help="Optional CSV mapping CIF names/paths to structure weights.",
    )
    fit_parser.add_argument(
        "--meta_csv",
        type=Path,
        default=None,
        help="Optional metadata CSV containing property_label (and optional weight).",
    )
    fit_parser.add_argument(
        "--property_filter",
        default=None,
        help="Optional label filter applied to metadata property_label values.",
    )
    fit_parser.add_argument(
        "--property_mode",
        choices=("include", "exclude"),
        default="include",
        help="How to apply property_filter (default: include).",
    )
    fit_parser.add_argument(
        "--species_whitelist",
        action="append",
        default=None,
        help="Allowed species list; may be repeated and/or comma-separated (e.g. 'Na,Cl').",
    )
    fit_parser.add_argument(
        "--covalent_rules",
        type=Path,
        default=None,
        help="Optional covalent-like contact rules (.csv/.yaml/.yml).",
    )
    fit_parser.add_argument(
        "--exclude_covalent",
        action="store_true",
        help="Exclude structures (weight=0) when covalent-like short contacts are found.",
    )
    fit_parser.add_argument(
        "--shift_phi",
        dest="shift_phi",
        action="store_true",
        help="Shift phi curves so each pair has min(phi)=0 (neighbors mode default).",
    )
    fit_parser.add_argument(
        "--no_shift_phi",
        dest="shift_phi",
        action="store_false",
        help="Do not shift phi curves.",
    )
    fit_parser.set_defaults(shift_phi=None)
    fit_parser.add_argument("--name", default="spp_run", help="Run name written to manifest.")
    fit_parser.add_argument(
        "--dump_gr_csv",
        type=Path,
        default=None,
        help="Optional output folder for supercell_gr CSV dumps (r,g,exp_minus_phi).",
    )
    fit_parser.add_argument(
        "--dump_gr_pair",
        action="append",
        default=None,
        help="Optional pair selector for --dump_gr_csv (repeatable, e.g. --dump_gr_pair Li-O).",
    )
    fit_parser.add_argument(
        "--short_distance_floor",
        type=float,
        default=None,
        help="Optional minimum phi penalty applied to short-distance bins during export.",
    )
    short_guard_group = fit_parser.add_mutually_exclusive_group()
    short_guard_group.add_argument(
        "--short_distance_bins",
        type=int,
        default=None,
        help="Apply short-distance floor to first N bins.",
    )
    short_guard_group.add_argument(
        "--short_distance_r_max",
        type=float,
        default=None,
        help="Apply short-distance floor to bins with r <= this threshold.",
    )
    fit_parser.set_defaults(handler=_run_fit)

    score_parser = subparsers.add_parser(
        "score",
        help="Score CIF structure(s) against an exported SPP root.",
        description="Score one CIF or a CIF directory against a fitted SPP root.",
    )
    score_parser.add_argument("--spp_root", type=Path, required=True)
    score_input_group = score_parser.add_mutually_exclusive_group(required=True)
    score_input_group.add_argument("--cif", type=Path, default=None)
    score_input_group.add_argument("--cif_dir", type=Path, default=None)

    score_neighbor_group = score_parser.add_mutually_exclusive_group()
    score_neighbor_group.add_argument(
        "--r_cut",
        type=float,
        default=None,
        help="Neighbor cutoff distance in Angstrom (default: 4.0 if --knn not set).",
    )
    score_neighbor_group.add_argument(
        "--knn",
        type=int,
        default=None,
        help="Use k-nearest neighbors instead of cutoff radius.",
    )
    score_parser.add_argument("--min_d", type=float, default=None)

    score_parser.add_argument(
        "--bandpass",
        dest="use_bandpass",
        action="store_true",
        help="Apply band-pass weighting (default).",
    )
    score_parser.add_argument(
        "--no_bandpass",
        dest="use_bandpass",
        action="store_false",
        help="Disable band-pass weighting during scoring.",
    )
    score_parser.set_defaults(use_bandpass=True)

    score_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit JSON output (single object or JSON lines).",
    )
    score_parser.add_argument(
        "--top_pairs",
        type=int,
        default=None,
        help="Show top N pair contributors.",
    )
    score_parser.add_argument("--name", default=None, help="Optional label in output.")
    score_parser.add_argument(
        "--oob_policy",
        choices=("zero", "clamp", "max"),
        default="max",
        help="Out-of-range distance penalty policy (default: max).",
    )
    score_parser.add_argument(
        "--missing_pair_policy",
        choices=("zero", "max_global", "error"),
        default="max_global",
        help="Missing-pair penalty policy (default: max_global).",
    )
    score_parser.set_defaults(handler=_run_score)

    calibrate_parser = subparsers.add_parser(
        "calibrate",
        help="Calibrate lambda scaling for SPP penalties on a CIF corpus.",
        description="Compute recommended lambda from scoring statistics and optionally export/publish calibration artifacts.",
    )
    calibrate_parser.add_argument("--spp_root", type=Path, required=True)
    calibrate_parser.add_argument("--cif_dir", type=Path, required=True)
    calibrate_parser.add_argument("--out_json", type=Path, default=None)
    calibrate_parser.add_argument(
        "--score_method",
        choices=("neighbors", "supercell_gr"),
        default="neighbors",
        help="Scoring backend used for calibration statistics (default: neighbors).",
    )
    calibrate_parser.add_argument(
        "--mode",
        choices=("structure_median", "edge_median", "quantile"),
        default="structure_median",
    )
    calibrate_parser.add_argument("--target", type=float, required=True)
    calibrate_parser.add_argument("--q", type=float, default=0.5)
    calibrate_parser.add_argument(
        "--convention",
        choices=("reward", "penalty"),
        default="reward",
        help="Interpretation convention for downstream objective wiring.",
    )
    calibrate_parser.add_argument(
        "--min_lambda",
        type=float,
        default=0.0,
        help="Lower clip bound for positive lambda_used.",
    )
    calibrate_parser.add_argument(
        "--max_lambda",
        type=float,
        default=1e9,
        help="Upper clip bound for positive lambda_used.",
    )

    calibrate_neighbor_group = calibrate_parser.add_mutually_exclusive_group()
    calibrate_neighbor_group.add_argument(
        "--r_cut",
        type=float,
        default=None,
        help="Neighbor cutoff distance in Angstrom (default: 4.0 if --knn not set).",
    )
    calibrate_neighbor_group.add_argument(
        "--knn",
        type=int,
        default=None,
        help="Use k-nearest neighbors instead of cutoff radius.",
    )
    calibrate_parser.add_argument("--min_d", type=float, default=None)
    calibrate_parser.add_argument(
        "--bandpass",
        dest="use_bandpass",
        action="store_true",
        help="Apply band-pass weighting (default).",
    )
    calibrate_parser.add_argument(
        "--no_bandpass",
        dest="use_bandpass",
        action="store_false",
        help="Disable band-pass weighting during calibration.",
    )
    calibrate_parser.set_defaults(use_bandpass=True)
    calibrate_parser.add_argument("--d_lo", type=float, default=None)
    calibrate_parser.add_argument("--d_hi", type=float, default=None)
    calibrate_parser.add_argument("--sigma_lo", type=float, default=None)
    calibrate_parser.add_argument("--sigma_hi", type=float, default=None)
    calibrate_parser.add_argument(
        "--oob_policy",
        choices=("zero", "clamp", "max"),
        default="max",
    )
    calibrate_parser.add_argument(
        "--missing_pair_policy",
        choices=("zero", "max_global", "error"),
        default="max_global",
    )
    calibrate_parser.add_argument("--max_n", type=int, default=None)
    calibrate_parser.add_argument("--write_scaled_root", type=Path, default=None)
    calibrate_parser.add_argument("--publish", action="store_true")
    calibrate_parser.add_argument("--qlip_outputs", type=Path, default=Path("QLIP_Outputs"))
    calibrate_parser.add_argument("--name", default=None)
    calibrate_parser.set_defaults(handler=_run_calibrate)

    run_parser = subparsers.add_parser(
        "run",
        help="Run fit -> calibrate -> package -> final QLIP handoff in one command.",
        description="Execute end-to-end SPP pipeline and produce both provenance and QLIP-ready bundles.",
    )
    run_parser.add_argument("--name", default="spp_run")
    run_parser.add_argument("--cif_dir", type=Path, required=True)
    run_parser.add_argument("--out_dir", type=Path, default=Path("."))
    run_parser.add_argument(
        "--fit_method",
        choices=("neighbors", "supercell_gr"),
        default="neighbors",
    )
    run_parser.add_argument(
        "--calib_score_method",
        choices=("neighbors", "supercell_gr"),
        default="neighbors",
    )
    run_neighbor_group = run_parser.add_mutually_exclusive_group()
    run_neighbor_group.add_argument("--r_cut", type=float, default=None)
    run_neighbor_group.add_argument("--knn", type=int, default=None)
    run_parser.add_argument("--min_d", type=float, default=None)
    run_parser.add_argument("--d_min", type=float, default=0.5)
    run_parser.add_argument("--d_max", type=float, default=8.0)
    run_parser.add_argument("--alpha", type=float, default=1e-3)
    run_parser.add_argument("--supercell_target_len", type=float, default=20.0)
    run_parser.add_argument("--r_max", type=float, default=10.0)
    run_parser.add_argument("--bin_width", type=float, default=0.05)
    run_parser.add_argument("--sigma", type=float, default=0.1)
    run_parser.add_argument("--truncate_sigma", type=float, default=3.0)
    run_parser.add_argument("--gr_eps", type=float, default=1e-12)
    run_parser.add_argument("--max_pairs", type=int, default=None)

    run_parser.add_argument(
        "--bandpass",
        dest="use_bandpass",
        action="store_true",
        help="Apply band-pass weighting for calibration scoring (default).",
    )
    run_parser.add_argument(
        "--no_bandpass",
        dest="use_bandpass",
        action="store_false",
        help="Disable band-pass weighting for calibration scoring.",
    )
    run_parser.set_defaults(use_bandpass=True)
    run_parser.add_argument("--d_lo", type=float, default=None)
    run_parser.add_argument("--d_hi", type=float, default=None)
    run_parser.add_argument("--sigma_lo", type=float, default=None)
    run_parser.add_argument("--sigma_hi", type=float, default=None)
    run_parser.add_argument(
        "--calib_mode",
        choices=("structure_median", "edge_median", "quantile"),
        default="structure_median",
    )
    run_parser.add_argument("--target", type=float, required=True)
    run_parser.add_argument("--q", type=float, default=0.5)
    run_parser.add_argument(
        "--convention",
        choices=("reward", "penalty"),
        default="reward",
    )
    run_parser.add_argument("--min_lambda", type=float, default=0.0)
    run_parser.add_argument("--max_lambda", type=float, default=1e9)
    run_parser.add_argument("--max_calib", type=int, default=None)
    run_parser.add_argument("--meta_csv", type=Path, default=None)
    run_parser.add_argument("--property_filter", default=None)
    run_parser.add_argument(
        "--property_mode",
        choices=("include", "exclude"),
        default="include",
    )
    run_parser.add_argument(
        "--publish_to",
        type=Path,
        default=None,
        help="Optional QLIP_Outputs registry path for publishing SPP/guidance/package artifacts.",
    )
    run_parser.set_defaults(handler=_run_run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.error("No subcommand handler configured.")
    try:
        return int(handler(args))
    except CliUsageError as exc:
        parser.error(str(exc))
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
