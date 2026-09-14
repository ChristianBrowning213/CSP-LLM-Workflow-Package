"""Run baseline vs property-conditioned SPP demo end-to-end."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# Allow running this script without editable install.
if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

import numpy as np

from spp_maker.export import export_spp_root
from spp_maker.fit_hist import accumulate_histograms
from spp_maker.fit_phi import build_phi_from_hist
from spp_maker.io_cif import LoadedCIF, load_cifs_from_dir
from spp_maker.meta_csv import load_meta_map, match_meta_rows
from spp_maker.score import ScoreReport, score_atoms
from spp_maker.spp_model import load_spp_model
from spp_maker.weights import BandpassParams, validate_params


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Demo: compare baseline vs property-conditioned SPP models."
    )
    parser.add_argument("--cif_dir", type=Path, required=True)
    parser.add_argument("--meta_csv", type=Path, required=True)
    parser.add_argument("--property_filter", required=True)
    parser.add_argument("--out_dir", type=Path, default=Path("out/demo_prop_spp"))
    parser.add_argument("--name", default="demo")
    parser.add_argument("--eval_cif_dir", type=Path, default=None)
    parser.add_argument("--max_eval", type=int, default=200)

    neighbor_group = parser.add_mutually_exclusive_group()
    neighbor_group.add_argument("--r_cut", type=float, default=4.0)
    neighbor_group.add_argument("--knn", type=int, default=None)
    parser.add_argument("--min_d", type=float, default=None)

    parser.add_argument("--d_min", type=float, default=0.5)
    parser.add_argument("--d_max", type=float, default=8.0)
    parser.add_argument("--bin_width", type=float, default=0.05)
    parser.add_argument("--alpha", type=float, default=1e-3)

    parser.add_argument("--no_bandpass", action="store_true")
    parser.add_argument("--d_lo", type=float, default=None)
    parser.add_argument("--d_hi", type=float, default=None)
    parser.add_argument("--sigma_lo", type=float, default=None)
    parser.add_argument("--sigma_hi", type=float, default=None)

    parser.add_argument("--shift_phi", dest="shift_phi", action="store_true")
    parser.add_argument("--no_shift_phi", dest="shift_phi", action="store_false")
    parser.set_defaults(shift_phi=True)

    parser.add_argument("--short_distance_floor", type=float, default=None)
    short_guard_group = parser.add_mutually_exclusive_group()
    short_guard_group.add_argument("--short_distance_bins", type=int, default=None)
    short_guard_group.add_argument("--short_distance_r_max", type=float, default=None)

    parser.add_argument("--top_n_shift", type=int, default=10)
    parser.add_argument("--top_m_pairs", type=int, default=8)
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> tuple[float | None, int | None]:
    if not args.cif_dir.is_dir():
        raise ValueError(f"--cif_dir is not a directory: {args.cif_dir}")
    if not args.meta_csv.is_file():
        raise ValueError(f"--meta_csv is not a file: {args.meta_csv}")
    if args.eval_cif_dir is not None and not args.eval_cif_dir.is_dir():
        raise ValueError(f"--eval_cif_dir is not a directory: {args.eval_cif_dir}")

    if args.r_cut is not None:
        if not math.isfinite(args.r_cut) or args.r_cut <= 0:
            raise ValueError(f"--r_cut must be finite and > 0, got {args.r_cut}.")
    if args.knn is not None and args.knn <= 0:
        raise ValueError(f"--knn must be > 0, got {args.knn}.")
    if args.min_d is not None:
        if not math.isfinite(args.min_d) or args.min_d < 0:
            raise ValueError(f"--min_d must be finite and >= 0, got {args.min_d}.")

    if not math.isfinite(args.d_min) or args.d_min < 0:
        raise ValueError(f"--d_min must be finite and >= 0, got {args.d_min}.")
    if not math.isfinite(args.d_max) or args.d_max <= args.d_min:
        raise ValueError(
            f"--d_max must be finite and > d_min ({args.d_min}), got {args.d_max}."
        )
    if not math.isfinite(args.bin_width) or args.bin_width <= 0:
        raise ValueError(f"--bin_width must be finite and > 0, got {args.bin_width}.")
    if not math.isfinite(args.alpha) or args.alpha <= 0:
        raise ValueError(f"--alpha must be finite and > 0, got {args.alpha}.")
    if args.max_eval <= 0:
        raise ValueError(f"--max_eval must be > 0, got {args.max_eval}.")
    if args.top_n_shift <= 0:
        raise ValueError(f"--top_n_shift must be > 0, got {args.top_n_shift}.")
    if args.top_m_pairs <= 0:
        raise ValueError(f"--top_m_pairs must be > 0, got {args.top_m_pairs}.")
    if args.short_distance_floor is None:
        if args.short_distance_bins is not None or args.short_distance_r_max is not None:
            raise ValueError(
                "--short_distance_bins/--short_distance_r_max require --short_distance_floor."
            )
    else:
        if not math.isfinite(args.short_distance_floor) or args.short_distance_floor < 0:
            raise ValueError(
                "--short_distance_floor must be finite and >= 0, "
                f"got {args.short_distance_floor}."
            )
        if args.short_distance_bins is not None and args.short_distance_bins <= 0:
            raise ValueError(
                f"--short_distance_bins must be > 0, got {args.short_distance_bins}."
            )
        if args.short_distance_r_max is not None and (
            not math.isfinite(args.short_distance_r_max)
        ):
            raise ValueError(
                "--short_distance_r_max must be finite, "
                f"got {args.short_distance_r_max}."
            )

    return args.r_cut, args.knn


def _resolve_bandpass(args: argparse.Namespace) -> BandpassParams | None:
    overrides = any(
        value is not None for value in (args.d_lo, args.d_hi, args.sigma_lo, args.sigma_hi)
    )
    if args.no_bandpass:
        if overrides:
            raise ValueError(
                "Band-pass overrides cannot be provided with --no_bandpass."
            )
        return None

    defaults = BandpassParams.defaults()
    params = BandpassParams(
        d_lo=defaults.d_lo if args.d_lo is None else args.d_lo,
        d_hi=defaults.d_hi if args.d_hi is None else args.d_hi,
        sigma_lo=defaults.sigma_lo if args.sigma_lo is None else args.sigma_lo,
        sigma_hi=defaults.sigma_hi if args.sigma_hi is None else args.sigma_hi,
    )
    validate_params(params)
    return params


def _weights_from_meta(meta_weights: tuple[float | None, ...]) -> list[float] | None:
    if not any(weight is not None for weight in meta_weights):
        return None
    return [1.0 if weight is None else float(weight) for weight in meta_weights]


def _fit_and_export(
    *,
    loaded: list[LoadedCIF],
    weights: list[float] | None,
    out_root: Path,
    name: str,
    r_cut: float | None,
    knn: int | None,
    min_d: float | None,
    bandpass: BandpassParams | None,
    d_min: float,
    d_max: float,
    bin_width: float,
    alpha: float,
    shift_phi: bool,
    short_distance_floor: float | None,
    short_distance_bins: int | None,
    short_distance_r_max: float | None,
    manifest_extra: dict[str, Any],
) -> None:
    hist = accumulate_histograms(
        [item.atoms for item in loaded],
        structure_weights=weights,
        r_cut=r_cut,
        k=knn,
        min_d=min_d,
        bandpass=bandpass,
        d_min=d_min,
        d_max=d_max,
        bin_width=bin_width,
    )
    phi_res = build_phi_from_hist(hist, alpha=alpha, shifted=shift_phi)
    manifest_extra = dict(manifest_extra)
    manifest_extra["total_pairs_seen"] = hist.total_pairs_seen
    manifest_extra["total_weighted_pairs_seen"] = hist.total_weighted_pairs_seen
    export_spp_root(
        out_root=out_root,
        phi_res=phi_res,
        name=name,
        manifest_extra=manifest_extra,
        short_distance_floor=short_distance_floor,
        short_distance_bins=short_distance_bins,
        short_distance_r_max=short_distance_r_max,
    )


def _summary_stats(values: np.ndarray) -> dict[str, float]:
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }


def _top_pairs(report: ScoreReport, limit: int) -> list[dict[str, float | str]]:
    ranked = sorted(report.by_pair.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"pair": f"{a}-{b}", "score": float(score)} for (a, b), score in ranked]


def _pair_delta_common(
    report_all: ScoreReport,
    report_prop: ScoreReport,
    limit: int,
) -> list[dict[str, float | str]]:
    common = set(report_all.by_pair).intersection(report_prop.by_pair)
    rows = []
    for pair in common:
        a, b = pair
        s_all = float(report_all.by_pair[pair])
        s_prop = float(report_prop.by_pair[pair])
        rows.append((pair, s_all, s_prop, s_prop - s_all))
    rows.sort(key=lambda row: (-abs(row[3]), row[0]))
    rows = rows[:limit]
    return [
        {
            "pair": f"{a}-{b}",
            "score_all": s_all,
            "score_prop": s_prop,
            "delta": delta,
        }
        for (a, b), s_all, s_prop, delta in rows
    ]


def _write_summary_txt(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    rows = report["rows"]
    top_shifted = report["top_shifted"]

    lines = []
    lines.append(f"Demo: {report['metadata']['name']}")
    lines.append(f"Property filter: {report['metadata']['property_filter']}")
    lines.append(
        "Counts: "
        f"train_all={report['counts']['num_train_all']}, "
        f"train_prop={report['counts']['num_train_prop']}, "
        f"eval={report['counts']['num_eval']}"
    )
    lines.append("")
    lines.append("Summary stats")
    lines.append("metric       score_all     score_prop    delta")
    for metric in ("mean", "median", "std", "min", "max"):
        lines.append(
            f"{metric:<11}"
            f"{summary['score_all'][metric]:>12.6f} "
            f"{summary['score_prop'][metric]:>12.6f} "
            f"{summary['delta'][metric]:>12.6f}"
        )
    lines.append("")
    lines.append(f"Top shifted structures (n={min(10, len(top_shifted))})")
    for item in top_shifted[:10]:
        lines.append(
            f"- {item['cif_name']}: delta={item['delta']:.6f}, "
            f"score_all={item['score_all']:.6f}, score_prop={item['score_prop']:.6f}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    try:
        r_cut, knn = _validate_args(args)
        bandpass = _resolve_bandpass(args)

        loaded_all = load_cifs_from_dir(args.cif_dir)
        if not loaded_all:
            raise ValueError(f"No CIF files found in directory: {args.cif_dir}")

        meta_map = load_meta_map(args.meta_csv)
        meta_all_match = match_meta_rows(loaded_all, meta_map)

        prop_indices = [
            idx for idx, label in enumerate(meta_all_match.labels) if label == args.property_filter
        ]
        if not prop_indices:
            raise ValueError(
                f"property_filter selected zero CIFs: {args.property_filter!r}. "
                "Check --meta_csv labels."
            )

        loaded_prop = [loaded_all[i] for i in prop_indices]
        weights_all = _weights_from_meta(meta_all_match.weights)
        weights_prop = (
            None
            if weights_all is None
            else [weights_all[i] for i in prop_indices]
        )

        base_dir = args.out_dir / args.name
        spp_all_root = base_dir / "spp_all"
        spp_prop_root = base_dir / f"spp_prop_{args.property_filter}"
        base_dir.mkdir(parents=True, exist_ok=True)

        fit_params = {
            "r_cut": r_cut,
            "knn": knn,
            "min_d": args.min_d,
            "d_min": args.d_min,
            "d_max": args.d_max,
            "bin_width": args.bin_width,
            "alpha": args.alpha,
            "shift_phi": args.shift_phi,
            "short_distance_floor": args.short_distance_floor,
            "short_distance_bins": args.short_distance_bins,
            "short_distance_r_max": args.short_distance_r_max,
            "bandpass": (
                {
                    "enabled": bandpass is not None,
                    "d_lo": None if bandpass is None else bandpass.d_lo,
                    "d_hi": None if bandpass is None else bandpass.d_hi,
                    "sigma_lo": None if bandpass is None else bandpass.sigma_lo,
                    "sigma_hi": None if bandpass is None else bandpass.sigma_hi,
                }
            ),
        }

        _fit_and_export(
            loaded=loaded_all,
            weights=weights_all,
            out_root=spp_all_root,
            name=f"{args.name}_all",
            r_cut=r_cut,
            knn=knn,
            min_d=args.min_d,
            bandpass=bandpass,
            d_min=args.d_min,
            d_max=args.d_max,
            bin_width=args.bin_width,
            alpha=args.alpha,
            shift_phi=args.shift_phi,
            short_distance_floor=args.short_distance_floor,
            short_distance_bins=args.short_distance_bins,
            short_distance_r_max=args.short_distance_r_max,
            manifest_extra={
                "demo_name": args.name,
                "demo_role": "all",
                "meta_csv": str(meta_map.csv_path),
                "property_filter": None,
                "num_structures_selected": len(loaded_all),
                "num_structures_total": len(loaded_all),
                "unmatched_meta_rows": meta_all_match.unmatched_meta_rows,
                "missing_meta_for_cifs": meta_all_match.missing_meta_for_cifs,
            },
        )
        _fit_and_export(
            loaded=loaded_prop,
            weights=weights_prop,
            out_root=spp_prop_root,
            name=f"{args.name}_prop_{args.property_filter}",
            r_cut=r_cut,
            knn=knn,
            min_d=args.min_d,
            bandpass=bandpass,
            d_min=args.d_min,
            d_max=args.d_max,
            bin_width=args.bin_width,
            alpha=args.alpha,
            shift_phi=args.shift_phi,
            short_distance_floor=args.short_distance_floor,
            short_distance_bins=args.short_distance_bins,
            short_distance_r_max=args.short_distance_r_max,
            manifest_extra={
                "demo_name": args.name,
                "demo_role": "property",
                "meta_csv": str(meta_map.csv_path),
                "property_filter": args.property_filter,
                "num_structures_selected": len(loaded_prop),
                "num_structures_total": len(loaded_all),
                "unmatched_meta_rows": meta_all_match.unmatched_meta_rows,
                "missing_meta_for_cifs": meta_all_match.missing_meta_for_cifs,
                "selected_cif_names": [Path(item.path).name for item in loaded_prop],
            },
        )

        eval_dir = args.eval_cif_dir if args.eval_cif_dir is not None else args.cif_dir
        eval_loaded = load_cifs_from_dir(eval_dir)
        if not eval_loaded:
            raise ValueError(f"No CIF files found in evaluation directory: {eval_dir}")
        eval_loaded = eval_loaded[: args.max_eval]
        eval_meta_match = match_meta_rows(eval_loaded, meta_map)

        model_all = load_spp_model(spp_all_root)
        model_prop = load_spp_model(spp_prop_root)

        rows: list[dict[str, Any]] = []
        reports_by_cif: dict[str, tuple[ScoreReport, ScoreReport]] = {}
        for idx, loaded in enumerate(eval_loaded):
            label = eval_meta_match.labels[idx]
            report_all = score_atoms(
                loaded.atoms,
                model_all,
                r_cut=r_cut,
                k=knn,
                min_d=args.min_d,
                bandpass=bandpass,
                use_bandpass=bandpass is not None,
            )
            report_prop = score_atoms(
                loaded.atoms,
                model_prop,
                r_cut=r_cut,
                k=knn,
                min_d=args.min_d,
                bandpass=bandpass,
                use_bandpass=bandpass is not None,
            )
            score_all = float(report_all.total)
            score_prop = float(report_prop.total)
            delta = score_prop - score_all
            cif_name = Path(loaded.path).name
            rows.append(
                {
                    "cif_name": cif_name,
                    "cif_path": str(loaded.path),
                    "label": label,
                    "score_all": score_all,
                    "score_prop": score_prop,
                    "delta": delta,
                }
            )
            reports_by_cif[str(loaded.path)] = (report_all, report_prop)

        score_all_arr = np.asarray([row["score_all"] for row in rows], dtype=np.float64)
        score_prop_arr = np.asarray([row["score_prop"] for row in rows], dtype=np.float64)
        delta_arr = np.asarray([row["delta"] for row in rows], dtype=np.float64)
        if not (np.all(np.isfinite(score_all_arr)) and np.all(np.isfinite(score_prop_arr))):
            raise ValueError("Non-finite score values encountered in evaluation.")

        sorted_rows = sorted(rows, key=lambda row: (-abs(row["delta"]), row["cif_name"]))
        top_rows = sorted_rows[: args.top_n_shift]
        top_shifted: list[dict[str, Any]] = []
        for row in top_rows:
            key = str(row["cif_path"])
            report_all, report_prop = reports_by_cif[key]
            enriched = dict(row)
            enriched["top_pairs_all"] = _top_pairs(report_all, args.top_m_pairs)
            enriched["top_pairs_prop"] = _top_pairs(report_prop, args.top_m_pairs)
            enriched["pair_deltas_common"] = _pair_delta_common(
                report_all, report_prop, args.top_m_pairs
            )
            top_shifted.append(enriched)

        report = {
            "metadata": {
                "name": args.name,
                "cif_dir": str(args.cif_dir.resolve()),
                "eval_cif_dir": str(eval_dir.resolve()),
                "meta_csv": str(meta_map.csv_path),
                "property_filter": args.property_filter,
                "params": fit_params,
                "top_n_shift": args.top_n_shift,
                "top_m_pairs": args.top_m_pairs,
            },
            "counts": {
                "num_train_all": len(loaded_all),
                "num_train_prop": len(loaded_prop),
                "num_eval": len(eval_loaded),
            },
            "rows": rows,
            "summary": {
                "score_all": _summary_stats(score_all_arr),
                "score_prop": _summary_stats(score_prop_arr),
                "delta": _summary_stats(delta_arr),
            },
            "top_shifted": top_shifted,
        }

        report_path = base_dir / "report.json"
        with report_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")

        summary_path = base_dir / "summary.txt"
        _write_summary_txt(summary_path, report)

        print(f"Demo completed: {args.name}")
        print(f"spp_all: {spp_all_root}")
        print(f"spp_prop: {spp_prop_root}")
        print(f"report: {report_path}")
        print(f"summary: {summary_path}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
