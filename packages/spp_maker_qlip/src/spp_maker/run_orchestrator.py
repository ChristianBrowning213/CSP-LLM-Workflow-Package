"""One-command SPP -> calibration -> QLIP handoff orchestration."""

from __future__ import annotations

import json
import os
import platform
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spp_maker import __version__ as spp_maker_version
from spp_maker.io_cif import LoadedCIF, load_cifs_from_dir
from spp_maker.meta_csv import load_meta_map, match_meta_rows
from spp_maker.pot_compat import check_pot_root, render_compat_report
from spp_maker.publish import build_run_id, get_git_sha, kind_to_bucket, kind_to_dir, write_json
from spp_maker.qlip_outputs_index import empty_index, load_index, write_index
from spp_maker.qlip_outputs_packages import PublishedArtifact, publish_registry_artifact
from spp_maker.qlip_package import (
    build_package_payload,
    compute_content_hash,
    render_python_snippet,
    write_package_json,
)


@dataclass(frozen=True)
class RunConfig:
    """Normalized orchestrator configuration."""

    name: str
    cif_dir: Path
    out_dir: Path
    fit_method: str
    calib_score_method: str
    target: float
    max_calib: int | None
    use_bandpass: bool
    convention: str
    min_lambda: float
    max_lambda: float
    calibration_mode: str
    q: float
    r_cut: float | None
    knn: int | None
    min_d: float | None
    d_lo: float | None
    d_hi: float | None
    sigma_lo: float | None
    sigma_hi: float | None
    d_min: float
    d_max: float
    alpha: float
    supercell_target_len: float
    r_max: float
    bin_width: float
    sigma: float
    truncate_sigma: float
    gr_eps: float
    max_pairs: int | None
    meta_csv: Path | None
    property_filter: str | None
    property_mode: str
    publish_to: Path | None


@dataclass(frozen=True)
class RunPaths:
    """Filesystem locations for a single orchestrated run."""

    spp_runs_root: Path
    final_output_root: Path
    run_root: Path
    final_bundle: Path
    input_snapshot: Path
    fit_dir: Path
    fit_spp_root: Path
    fit_manifest: Path
    fit_compat_report: Path
    calibrate_dir: Path
    calibration_json: Path
    scaled_spp_root: Path
    scaled_compat_report: Path
    package_dir: Path
    package_json: Path
    snippet_file: Path
    logs_dir: Path
    run_summary: Path
    timings_json: Path


@dataclass(frozen=True)
class RunResult:
    """Final orchestrator result payload."""

    run_id: str
    run_root: Path
    final_bundle: Path
    content_hash: str
    lambda_used: float
    published: dict[str, str] | None


def _resolve_selected_cifs(config: RunConfig) -> tuple[list[LoadedCIF], int]:
    loaded_all = load_cifs_from_dir(config.cif_dir)
    if not loaded_all:
        raise RuntimeError(f"No CIF files found in directory: {config.cif_dir}")

    selected_indices = list(range(len(loaded_all)))
    if config.meta_csv is not None:
        meta_map = load_meta_map(config.meta_csv)
        meta_match = match_meta_rows(loaded_all, meta_map)
        if config.property_filter is not None:
            if config.property_mode == "include":
                selected_indices = [
                    idx
                    for idx, label in enumerate(meta_match.labels)
                    if label is not None and label == config.property_filter
                ]
            else:
                selected_indices = [
                    idx
                    for idx, label in enumerate(meta_match.labels)
                    if label is not None and label != config.property_filter
                ]
    selected = [loaded_all[idx] for idx in selected_indices]
    if not selected:
        raise RuntimeError("No CIF structures selected after metadata/property filtering.")
    return selected, len(loaded_all)


def _build_paths(*, out_dir: Path, run_id: str) -> RunPaths:
    spp_runs_root = out_dir / "SPP_Runs"
    final_output_root = out_dir / "Final_QLIP_output"
    run_root = spp_runs_root / run_id
    final_bundle = final_output_root / run_id
    return RunPaths(
        spp_runs_root=spp_runs_root,
        final_output_root=final_output_root,
        run_root=run_root,
        final_bundle=final_bundle,
        input_snapshot=run_root / "input_snapshot",
        fit_dir=run_root / "fit",
        fit_spp_root=run_root / "fit" / "spp_root",
        fit_manifest=run_root / "fit" / "manifest.json",
        fit_compat_report=run_root / "fit" / "compat_report_fit.txt",
        calibrate_dir=run_root / "calibrate",
        calibration_json=run_root / "calibrate" / "calibration.json",
        scaled_spp_root=run_root / "calibrate" / "scaled_spp_root",
        scaled_compat_report=run_root / "calibrate" / "compat_report_scaled.txt",
        package_dir=run_root / "package",
        package_json=run_root / "package" / "package.json",
        snippet_file=run_root / "package" / "snippet.py.txt",
        logs_dir=run_root / "logs",
        run_summary=run_root / "logs" / "run_summary.txt",
        timings_json=run_root / "logs" / "timings.json",
    )


def _coerce_path(value: Path | None) -> str | None:
    return str(value.resolve()) if value is not None else None


def _build_params_payload(
    *,
    config: RunConfig,
    selected_cif_names: list[str],
    num_structures_total: int,
) -> dict[str, Any]:
    return {
        "command": "run",
        "name": config.name,
        "cif_dir": str(config.cif_dir.resolve()),
        "out_dir": str(config.out_dir.resolve()),
        "fit": {
            "method": config.fit_method,
            "r_cut": config.r_cut,
            "knn": config.knn,
            "min_d": config.min_d,
            "d_min": config.d_min,
            "d_max": config.d_max,
            "alpha": config.alpha,
            "supercell_target_len": config.supercell_target_len,
            "r_max": config.r_max,
            "bin_width": config.bin_width,
            "sigma": config.sigma,
            "truncate_sigma": config.truncate_sigma,
            "gr_eps": config.gr_eps,
            "max_pairs": config.max_pairs,
        },
        "calibration": {
            "score_method": config.calib_score_method,
            "mode": config.calibration_mode,
            "target": config.target,
            "q": config.q,
            "max_calib": config.max_calib,
            "bandpass_enabled": bool(config.use_bandpass),
            "bandpass": {
                "d_lo": config.d_lo,
                "d_hi": config.d_hi,
                "sigma_lo": config.sigma_lo,
                "sigma_hi": config.sigma_hi,
            },
            "convention": config.convention,
            "min_lambda": config.min_lambda,
            "max_lambda": config.max_lambda,
        },
        "filters": {
            "meta_csv": _coerce_path(config.meta_csv),
            "property_filter": config.property_filter,
            "property_mode": config.property_mode,
            "num_structures_total": num_structures_total,
            "num_structures_selected": len(selected_cif_names),
            "selected_cif_names": selected_cif_names,
        },
        "publish_to": _coerce_path(config.publish_to),
    }


def _content_hash_params(params_payload: dict[str, Any]) -> dict[str, Any]:
    """Return content-affecting params subset used in deterministic hash."""
    payload = json.loads(json.dumps(params_payload))
    payload.pop("out_dir", None)
    payload.pop("publish_to", None)
    return payload


def _write_input_snapshot(
    *,
    paths: RunPaths,
    params_payload: dict[str, Any],
    selected_cif_names: list[str],
) -> None:
    paths.input_snapshot.mkdir(parents=True, exist_ok=True)
    write_json(paths.input_snapshot / "params.json", params_payload)
    env_payload = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "git_sha": get_git_sha(Path(__file__).resolve().parents[2]),
        "tool": "SPP_Maker",
        "tool_version": spp_maker_version,
    }
    write_json(paths.input_snapshot / "env.json", env_payload)
    (paths.input_snapshot / "cif_list.txt").write_text(
        "".join(f"{name}\n" for name in selected_cif_names),
        encoding="utf-8",
    )


def _invoke_cli_handler(argv: list[str]) -> None:
    from spp_maker import cli as cli_module

    parser = cli_module.build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        raise RuntimeError(f"No handler found for argv: {argv}")
    rc = int(handler(args))
    if rc != 0:
        raise RuntimeError(f"Subcommand returned non-zero exit code {rc}: {' '.join(argv)}")


def _fit_cli_args(config: RunConfig, paths: RunPaths) -> list[str]:
    argv: list[str] = [
        "fit",
        "--cif_dir",
        str(config.cif_dir),
        "--out_root",
        str(paths.fit_spp_root),
        "--fit_method",
        config.fit_method,
        "--name",
        config.name,
    ]
    if config.fit_method == "neighbors":
        if config.r_cut is not None:
            argv.extend(["--r_cut", str(config.r_cut)])
        if config.knn is not None:
            argv.extend(["--knn", str(config.knn)])
        if config.min_d is not None:
            argv.extend(["--min_d", str(config.min_d)])
        argv.extend(
            [
                "--d_min",
                str(config.d_min),
                "--d_max",
                str(config.d_max),
                "--bin_width",
                str(config.bin_width),
                "--alpha",
                str(config.alpha),
            ]
        )
    else:
        argv.extend(
            [
                "--supercell_target_len",
                str(config.supercell_target_len),
                "--r_max",
                str(config.r_max),
                "--bin_width",
                str(config.bin_width),
                "--sigma",
                str(config.sigma),
                "--truncate_sigma",
                str(config.truncate_sigma),
                "--gr_eps",
                str(config.gr_eps),
            ]
        )
        if config.max_pairs is not None:
            argv.extend(["--max_pairs", str(config.max_pairs)])

    if config.meta_csv is not None:
        argv.extend(["--meta_csv", str(config.meta_csv)])
    if config.property_filter is not None:
        argv.extend(["--property_filter", config.property_filter])
        argv.extend(["--property_mode", config.property_mode])
    return argv


def _calibrate_cli_args(config: RunConfig, paths: RunPaths) -> list[str]:
    argv: list[str] = [
        "calibrate",
        "--spp_root",
        str(paths.fit_spp_root),
        "--cif_dir",
        str(config.cif_dir),
        "--out_json",
        str(paths.calibration_json),
        "--score_method",
        config.calib_score_method,
        "--mode",
        config.calibration_mode,
        "--target",
        str(config.target),
        "--q",
        str(config.q),
        "--convention",
        config.convention,
        "--min_lambda",
        str(config.min_lambda),
        "--max_lambda",
        str(config.max_lambda),
        "--write_scaled_root",
        str(paths.scaled_spp_root),
    ]
    if config.max_calib is not None:
        argv.extend(["--max_n", str(config.max_calib)])

    if config.calib_score_method == "neighbors":
        if config.r_cut is not None:
            argv.extend(["--r_cut", str(config.r_cut)])
        if config.knn is not None:
            argv.extend(["--knn", str(config.knn)])
        if config.min_d is not None:
            argv.extend(["--min_d", str(config.min_d)])
        if not config.use_bandpass:
            argv.append("--no_bandpass")
        if config.d_lo is not None:
            argv.extend(["--d_lo", str(config.d_lo)])
        if config.d_hi is not None:
            argv.extend(["--d_hi", str(config.d_hi)])
        if config.sigma_lo is not None:
            argv.extend(["--sigma_lo", str(config.sigma_lo)])
        if config.sigma_hi is not None:
            argv.extend(["--sigma_hi", str(config.sigma_hi)])
    else:
        argv.append("--no_bandpass")
    return argv


def _copy_final_bundle(paths: RunPaths) -> None:
    if paths.final_bundle.exists():
        raise RuntimeError(f"Final bundle already exists: {paths.final_bundle}")
    paths.final_bundle.mkdir(parents=True, exist_ok=False)
    shutil.copy2(paths.package_json, paths.final_bundle / "package.json")
    shutil.copytree(paths.scaled_spp_root, paths.final_bundle / "spp_root")
    guidance_dir = paths.final_bundle / "guidance"
    guidance_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths.calibration_json, guidance_dir / "calibration.json")
    shutil.copy2(paths.scaled_compat_report, paths.final_bundle / "compat_report.txt")
    (paths.final_bundle / "README.txt").write_text(
        "Copy this folder into your QLIP repo.\n"
        "Point SPPCollection at ./spp_root and use guidance/calibration.json.\n",
        encoding="utf-8",
    )


def _run_record_by_id(index_obj: dict[str, Any], *, bucket: str, run_id: str) -> dict[str, Any]:
    for record in index_obj["artifacts"][bucket]["runs"]:
        if isinstance(record, dict) and record.get("run_id") == run_id:
            return record
    raise RuntimeError(f"Could not find run_id {run_id!r} in bucket {bucket!r}.")


def _write_minimal_qlip_outputs_tree(
    *,
    source_registry: Path,
    destination_tree: Path,
    published: dict[str, PublishedArtifact],
) -> None:
    destination_tree.mkdir(parents=True, exist_ok=True)
    source_index = load_index(source_registry / "index.json")
    mini_index = empty_index()

    for kind in ("spp", "guidance", "package"):
        pub = published[kind]
        kind_dir = kind_to_dir(kind)  # type: ignore[arg-type]
        src_run_dir = source_registry / kind_dir / "runs" / pub.run_id
        dst_runs_root = destination_tree / kind_dir / "runs"
        dst_runs_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_run_dir, dst_runs_root / pub.run_id)
        (destination_tree / kind_dir / "latest.txt").write_text(
            f"{kind_dir}/runs/{pub.run_id}\n",
            encoding="utf-8",
        )

        bucket = kind_to_bucket(kind)  # type: ignore[arg-type]
        run_record = _run_record_by_id(source_index, bucket=bucket, run_id=pub.run_id)
        mini_index["artifacts"][bucket]["runs"] = [run_record]
        mini_index["artifacts"][bucket]["latest"] = f"{kind_dir}/runs/{pub.run_id}"

    schema_src = source_registry / "schema" / "qlip_outputs_index.schema.json"
    if schema_src.is_file():
        schema_dst = destination_tree / "schema"
        schema_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(schema_src, schema_dst / "qlip_outputs_index.schema.json")

    write_index(destination_tree / "index.json", mini_index)


def _write_summary(
    *,
    path: Path,
    run_id: str,
    status: str,
    failure_stage: str | None,
    failure_message: str | None,
    lambda_used: float | None,
    paths: RunPaths,
    published: dict[str, str] | None,
) -> None:
    lines = [
        f"run_id: {run_id}",
        f"status: {status}",
        f"run_root: {paths.run_root}",
        f"final_bundle: {paths.final_bundle}",
    ]
    if lambda_used is not None:
        lines.append(f"lambda_used: {lambda_used:.12g}")
    if failure_stage is not None:
        lines.append(f"failure_stage: {failure_stage}")
    if failure_message is not None:
        lines.append(f"failure_message: {failure_message}")
    if published is not None:
        for key in sorted(published):
            lines.append(f"published_{key}: {published[key]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_pipeline(config: RunConfig) -> RunResult:
    """Execute fit -> calibrate -> package -> final bundle pipeline."""
    out_dir = config.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    selected_cifs, num_structures_total = _resolve_selected_cifs(config)
    selected_cif_names = [Path(item.path).name for item in selected_cifs]

    params_payload = _build_params_payload(
        config=config,
        selected_cif_names=selected_cif_names,
        num_structures_total=num_structures_total,
    )
    content_hash = compute_content_hash(
        params_payload=_content_hash_params(params_payload),
        cif_names=selected_cif_names,
    )
    run_id = build_run_id(
        name=config.name,
        manifest_bytes=content_hash.encode("utf-8"),
        now_utc=datetime.now(timezone.utc),
    )
    paths = _build_paths(out_dir=out_dir, run_id=run_id)

    for folder in (
        paths.spp_runs_root,
        paths.final_output_root,
        paths.run_root,
        paths.fit_dir,
        paths.calibrate_dir,
        paths.package_dir,
        paths.logs_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    _write_input_snapshot(paths=paths, params_payload=params_payload, selected_cif_names=selected_cif_names)

    timings: dict[str, float] = {}
    lambda_used: float | None = None
    published_paths: dict[str, str] | None = None
    published_artifacts: dict[str, PublishedArtifact] | None = None
    status = "success"
    failure_stage: str | None = None
    failure_message: str | None = None
    current_stage = "initialization"

    try:
        current_stage = "fit"
        t0 = time.perf_counter()
        _invoke_cli_handler(_fit_cli_args(config, paths))
        timings["fit"] = time.perf_counter() - t0
        shutil.copy2(paths.fit_spp_root / "manifest.json", paths.fit_manifest)

        current_stage = "fit_compat"
        t0 = time.perf_counter()
        fit_report = check_pot_root(paths.fit_spp_root, strict=True)
        paths.fit_compat_report.write_text(render_compat_report(fit_report) + "\n", encoding="utf-8")
        timings["fit_compat"] = time.perf_counter() - t0
        if not fit_report.ok:
            raise RuntimeError(
                "Raw fitted SPP root failed strict POT compatibility checks "
                f"(checked={fit_report.checked}, failed={fit_report.failed})."
            )

        current_stage = "calibrate"
        t0 = time.perf_counter()
        _invoke_cli_handler(_calibrate_cli_args(config, paths))
        timings["calibrate"] = time.perf_counter() - t0

        current_stage = "scaled_compat"
        t0 = time.perf_counter()
        scaled_report = check_pot_root(paths.scaled_spp_root, strict=True)
        paths.scaled_compat_report.write_text(
            render_compat_report(scaled_report) + "\n",
            encoding="utf-8",
        )
        timings["scaled_compat"] = time.perf_counter() - t0
        if not scaled_report.ok:
            raise RuntimeError(
                "Scaled SPP root failed strict POT compatibility checks "
                f"(checked={scaled_report.checked}, failed={scaled_report.failed})."
            )

        calibration_payload = json.loads(paths.calibration_json.read_text(encoding="utf-8"))
        lambda_used = float(calibration_payload["lambda_used"])

        current_stage = "package"
        t0 = time.perf_counter()
        run_spp_rel = os.path.relpath(paths.scaled_spp_root, start=paths.package_dir).replace("\\", "/")
        run_guidance_rel = os.path.relpath(
            paths.calibration_json,
            start=paths.package_dir,
        ).replace("\\", "/")
        package_payload = build_package_payload(
            run_id=run_id,
            name=config.name,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            content_hash=content_hash,
            lambda_used=lambda_used,
            convention=config.convention,
            fit_method=config.fit_method,
            calibration_method=config.calib_score_method,
            corpus={
                "cif_dir": str(config.cif_dir.resolve()),
                "num_structures_total": int(num_structures_total),
                "num_structures_selected": len(selected_cif_names),
            },
            run_paths={
                "spp_root": run_spp_rel,
                "guidance": run_guidance_rel,
            },
            final_paths={
                "spp_root": "spp_root",
                "guidance": "guidance/calibration.json",
            },
            provenance={
                "git_sha": get_git_sha(Path(__file__).resolve().parents[2]),
                "tool": "SPP_Maker",
                "tool_version": spp_maker_version,
            },
        )
        write_package_json(paths.package_json, package_payload)
        paths.snippet_file.write_text(render_python_snippet(spp_root="./spp_root"), encoding="utf-8")
        timings["package"] = time.perf_counter() - t0

        current_stage = "final_bundle"
        t0 = time.perf_counter()
        _copy_final_bundle(paths)
        timings["final_bundle"] = time.perf_counter() - t0

        if config.publish_to is not None:
            current_stage = "publish"
            t0 = time.perf_counter()
            qlip_outputs = config.publish_to.resolve()
            guidance_root = paths.calibrate_dir / "guidance_artifact"
            guidance_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths.calibration_json, guidance_root / "guidance.json")

            published_spp = publish_registry_artifact(
                kind="spp",
                artifact_root=paths.scaled_spp_root,
                qlip_outputs=qlip_outputs,
                name=f"{config.name}_scaled",
                params={
                    "pipeline_run_id": run_id,
                    "kind": "spp",
                    "content_hash": content_hash,
                },
            )
            published_guidance = publish_registry_artifact(
                kind="guidance",
                artifact_root=guidance_root,
                qlip_outputs=qlip_outputs,
                name=f"{config.name}_guidance",
                params={
                    "pipeline_run_id": run_id,
                    "kind": "guidance",
                    "lambda_used": lambda_used,
                },
                checks={
                    "calibration": {
                        "ok": True,
                        "lambda_used": lambda_used,
                        "convention": config.convention,
                    }
                },
            )
            published_package = publish_registry_artifact(
                kind="package",
                artifact_root=paths.package_dir,
                qlip_outputs=qlip_outputs,
                name=f"{config.name}_package",
                params={
                    "pipeline_run_id": run_id,
                    "kind": "package",
                    "content_hash": content_hash,
                },
                checks={
                    "package": {
                        "ok": True,
                        "content_hash": content_hash,
                    }
                },
            )
            published_artifacts = {
                "spp": published_spp,
                "guidance": published_guidance,
                "package": published_package,
            }
            published_paths = {key: item.run_rel for key, item in published_artifacts.items()}

            _write_minimal_qlip_outputs_tree(
                source_registry=qlip_outputs,
                destination_tree=paths.final_bundle / "qlip_outputs_tree",
                published=published_artifacts,
            )
            timings["publish"] = time.perf_counter() - t0

    except Exception as exc:
        status = "failed"
        failure_stage = current_stage
        failure_message = str(exc)
        raise
    finally:
        write_json(paths.timings_json, timings)
        _write_summary(
            path=paths.run_summary,
            run_id=run_id,
            status=status,
            failure_stage=failure_stage,
            failure_message=failure_message,
            lambda_used=lambda_used,
            paths=paths,
            published=published_paths,
        )

    assert lambda_used is not None
    return RunResult(
        run_id=run_id,
        run_root=paths.run_root,
        final_bundle=paths.final_bundle,
        content_hash=content_hash,
        lambda_used=lambda_used,
        published=published_paths,
    )
