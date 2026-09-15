from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.spp_regularisation import (
    CONFIG_C_MISSING_PAIR_POLICY,
    CONFIG_C_REGULARISATION_SPP_DIR,
    CONFIG_C_REGULARISATION_WEIGHT,
    CONFIG_C_SPP_GUIDANCE_WEIGHT,
)


def _slug_from_text(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    slug = "_".join(words[:8])
    return slug[:80] or "text_request"


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative_paths(paths: list[Path], root: Path) -> list[str]:
    out: list[str] = []
    for path in paths:
        try:
            out.append(str(path.resolve().relative_to(root.resolve())))
        except ValueError:
            out.append(str(path.resolve()))
    return sorted(out)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_csp_pipeline(**kwargs: Any) -> Any:
    from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline

    return run_csp_pipeline(**kwargs)


def parse_prompt_lines(text: str) -> list[str]:
    prompts: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        prompts.append(line)
    return prompts


def run_system_text(
    text: str,
    *,
    out_root: Path | str = Path("local_runs"),
    run_id: str | None = None,
    run_root: Path | str | None = None,
    mode: str = "live",
    config: Path | str | None = None,
    with_spp: bool = True,
    regularisation_spp_dir: Path | str | None = CONFIG_C_REGULARISATION_SPP_DIR,
    regularisation_weight: float = CONFIG_C_REGULARISATION_WEIGHT,
    spp_guidance_weight: float = CONFIG_C_SPP_GUIDANCE_WEIGHT,
    missing_pair_policy: str = CONFIG_C_MISSING_PAIR_POLICY,
) -> dict[str, Any]:
    prompt = text.strip()
    if not prompt:
        raise ValueError("Text request is empty.")
    if mode not in {"stub", "live"}:
        raise ValueError(f"Unsupported mode: {mode}")

    base_dir = Path(out_root).resolve()
    if run_root is not None:
        resolved_run_root = Path(run_root).resolve()
    elif run_id:
        resolved_run_root = base_dir / run_id
    else:
        resolved_run_root = base_dir / f"{_timestamp()}_{_slug_from_text(prompt)}"
    workspace = resolved_run_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    cfg_path = Path(config).resolve() if config else None
    settings = Settings.from_sources(cfg_path)
    settings.workspace_root = workspace
    settings.allowed_read_roots = [workspace, Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace]

    status = "FAILED"
    failure_reason: str | None = None
    pipeline_run_dir: Path | None = None
    pipeline_manifest: Path | None = None
    try:
        execution_overrides = None
        if with_spp and regularisation_spp_dir:
            regularisation_dir = Path(regularisation_spp_dir).resolve()
            settings.qlip_allowed_path_roots = sorted(
                {Path(root).resolve() for root in [*settings.qlip_allowed_path_roots, regularisation_dir]},
                key=str,
            )
            execution_overrides = {
                "allow_partial_spp_guidance": True,
                "allow_qlip_without_spp": True,
                "spp_guidance_weight": float(spp_guidance_weight),
                "runtime_spp_guidance_weight": float(spp_guidance_weight),
                "spp_regularisation_dir": str(regularisation_dir),
                "spp_regularisation_weight": float(regularisation_weight),
                "spp_missing_pair_policy": str(missing_pair_policy),
                "entrypoint_config_path": str(cfg_path) if cfg_path else "",
                "entrypoint_cwd": str(Path.cwd().resolve()),
            }
        result = _run_csp_pipeline(
            query=prompt,
            with_spp=with_spp,
            mode=mode,
            workspace=workspace,
            settings=settings,
            execution_overrides=execution_overrides,
        )
        status = str(result.status)
        pipeline_run_dir = Path(result.run_dir)
        pipeline_manifest = Path(result.manifest_path)
        manifest = _read_manifest(pipeline_manifest)
        failure_reason = manifest.get("failure_reason") if isinstance(manifest.get("failure_reason"), str) else None
    except Exception as exc:  # noqa: BLE001
        failure_reason = str(exc)
    cif_search_root = pipeline_run_dir if pipeline_run_dir is not None and pipeline_run_dir.exists() else workspace
    cif_paths = sorted(cif_search_root.rglob("*.cif"))
    summary = {
        "schema_version": "system_text_entrypoint.v1",
        "input": {"text": prompt},
        "mode": mode,
        "status": status,
        "run_root": str(resolved_run_root),
        "workspace": str(workspace),
        "pipeline_run_dir": str(pipeline_run_dir) if pipeline_run_dir is not None else None,
        "pipeline_manifest": str(pipeline_manifest) if pipeline_manifest is not None else None,
        "failure_reason": failure_reason,
        "generated_cifs": _relative_paths(cif_paths, resolved_run_root),
    }
    summary_path = resolved_run_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


def run_text_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_system_text(*args, **kwargs)


def run_text_batch(
    prompts: list[str],
    *,
    out_root: Path | str = Path("local_runs"),
    batch_id: str | None = None,
    mode: str = "live",
    config: Path | str | None = None,
    with_spp: bool = True,
    stop_on_error: bool = False,
    regularisation_spp_dir: Path | str | None = None,
    regularisation_weight: float = CONFIG_C_REGULARISATION_WEIGHT,
    spp_guidance_weight: float = CONFIG_C_SPP_GUIDANCE_WEIGHT,
    missing_pair_policy: str = CONFIG_C_MISSING_PAIR_POLICY,
) -> dict[str, Any]:
    if not prompts:
        raise ValueError("No text requests found.")
    batch_root = Path(out_root).resolve() / (batch_id or f"{_timestamp()}_text_batch")
    runs_dir = batch_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for index, prompt in enumerate(prompts, start=1):
        run_name = f"run_{index:03d}"
        summary = run_system_text(
            prompt,
            run_root=runs_dir / run_name,
            mode=mode,
            config=config,
            with_spp=with_spp,
            regularisation_spp_dir=regularisation_spp_dir,
            regularisation_weight=regularisation_weight,
            spp_guidance_weight=spp_guidance_weight,
            missing_pair_policy=missing_pair_policy,
        )
        rows.append(
            {
                "index": index,
                "run_id": run_name,
                "text": prompt,
                "status": summary.get("status"),
                "summary_path": summary.get("summary_path"),
                "failure_reason": summary.get("failure_reason"),
                "generated_cifs": list(summary.get("generated_cifs", [])),
            }
        )
        if bool(stop_on_error) and summary.get("status") != "SUCCEEDED":
            break

    succeeded = sum(1 for row in rows if row.get("status") == "SUCCEEDED")
    failed = len(rows) - succeeded
    batch_summary = {
        "schema_version": "system_text_batch.v1",
        "batch_root": str(batch_root),
        "count": len(rows),
        "succeeded": succeeded,
        "failed": failed,
        "runs": rows,
    }

    (batch_root / "batch_summary.json").write_text(
        json.dumps(batch_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_lines = [
        "# Text Batch Summary",
        "",
        f"- Total: {len(rows)}",
        f"- Succeeded: {succeeded}",
        f"- Failed: {failed}",
        "",
        "| Run | Status | CIFs |",
        "| --- | --- | ---: |",
    ]
    for row in rows:
        md_lines.append(f"| {row['run_id']} | {row['status']} | {len(row['generated_cifs'])} |")
    (batch_root / "batch_summary.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    with (batch_root / "generation_log.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["index", "run_id", "text", "status", "summary_path", "failure_reason", "generated_cif_count"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "index": row["index"],
                    "run_id": row["run_id"],
                    "text": row["text"],
                    "status": row["status"],
                    "summary_path": row["summary_path"],
                    "failure_reason": row["failure_reason"],
                    "generated_cif_count": len(row["generated_cifs"]),
                }
            )
    with (batch_root / "generation_log.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    with (batch_root / "generated_cifs_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["run_id", "cif_path"])
        writer.writeheader()
        for row in rows:
            for cif_path in row["generated_cifs"]:
                writer.writerow({"run_id": row["run_id"], "cif_path": cif_path})

    batch_summary["summary_path"] = str(batch_root / "batch_summary.json")
    return batch_summary
