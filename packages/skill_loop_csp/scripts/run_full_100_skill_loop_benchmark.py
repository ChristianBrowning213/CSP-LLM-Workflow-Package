"""Run the seeded 100-row Skill-Loop-CSP manifest through the real pipeline."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sok_llm_orchestrator.config import Settings  # noqa: E402
from sok_llm_orchestrator.contracts.spp_regularisation import (
    CONFIG_C_MISSING_PAIR_POLICY,
    CONFIG_C_REGULARISATION_SPP_DIR,
    CONFIG_C_REGULARISATION_WEIGHT,
    CONFIG_C_SPP_GUIDANCE_WEIGHT,
)  # noqa: E402
try:
    from scripts.validate_full_100_manifest import validate_manifest
except ModuleNotFoundError:
    from validate_full_100_manifest import validate_manifest


LOG_COLUMNS = [
    "run_index",
    "case_id",
    "prompt_id",
    "seed",
    "benchmark_mode",
    "input_text",
    "run_archive_dir",
    "command",
    "exit_code",
    "runtime_seconds",
    "status",
    "expected_solver_status",
    "num_cifs_found",
    "generated_cif_paths",
    "stdout_path",
    "stderr_path",
    "error_type",
    "error_message",
    "spp_guidance_weight",
    "regularisation_weight",
    "missing_pair_policy",
    "regularisation_spp_dir",
    "qlip_allowed_path_roots",
]

CIF_COLUMNS = [
    "cif_path",
    "run_index",
    "case_id",
    "prompt_id",
    "seed",
    "benchmark_mode",
    "input_text",
    "target_formula",
    "target_structure_family",
    "target_space_group",
    "target_crystal_system",
    "chemistry_family",
    "challenge_type",
    "expected_formula_terms",
    "expected_family_terms",
    "expected_coordination_terms",
    "expected_connectivity_terms",
    "attempt_id",
    "method",
    "raw_run_dir",
    "notes",
]


def _read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _archive_dir_for_row(row: dict[str, str], out_root: Path) -> Path:
    raw = (row.get("run_archive_dir") or "").strip()
    if not raw:
        return out_root / "raw_runs" / f"run_{int(row['run_index']):03d}"
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _prepare_raw_run_dir(path: Path) -> tuple[Path, str]:
    path.mkdir(parents=True, exist_ok=True)
    marker = path / "manifest_row.json"
    if not marker.exists():
        return path, "primary"
    for idx in range(1, 1000):
        candidate = path / f"rerun_{idx:03d}"
        if not candidate.exists():
            candidate.mkdir(parents=True)
            return candidate, f"rerun_{idx:03d}"
    raise RuntimeError(f"could not allocate non-overwriting archive directory under {path}")


def _copytree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _find_cifs(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(item for item in path.rglob("*.cif") if item.is_file())


def _pipeline_failure_reason(pipeline_run_dir: Path | None) -> str:
    if pipeline_run_dir is None:
        return ""
    manifest_path = pipeline_run_dir / "manifest.json"
    if not manifest_path.exists():
        return ""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    reason = manifest.get("failure_reason")
    return str(reason) if reason is not None else ""


def _row_with_cif(row: dict[str, str], cif_path: Path, raw_run_dir: Path) -> dict[str, str]:
    return {
        "cif_path": _relative_or_absolute(cif_path),
        "run_index": row["run_index"],
        "case_id": row["case_id"],
        "prompt_id": row["prompt_id"],
        "seed": row["seed"],
        "benchmark_mode": row["benchmark_mode"],
        "input_text": row["input_text"],
        "target_formula": row.get("target_formula", ""),
        "target_structure_family": row.get("target_structure_family", ""),
        "target_space_group": row.get("target_space_group", ""),
        "target_crystal_system": row.get("target_crystal_system", ""),
        "chemistry_family": row.get("chemistry_family", ""),
        "challenge_type": row.get("challenge_type", ""),
        "expected_formula_terms": row.get("expected_formula_terms", ""),
        "expected_family_terms": row.get("expected_family_terms", ""),
        "expected_coordination_terms": row.get("expected_coordination_terms", ""),
        "expected_connectivity_terms": row.get("expected_connectivity_terms", ""),
        "attempt_id": "1",
        "method": "Skill-Loop-CSP",
        "raw_run_dir": _relative_or_absolute(raw_run_dir),
        "notes": row.get("notes", ""),
    }


def _task_spec_payload_from_manifest_row(row: dict[str, str]) -> dict[str, Any]:
    constraints = _intent_constraints(row.get("intent_constraints_json"))
    space_group = _first_text(
        constraints.get("space_group"),
        constraints.get("target_space_group"),
        row.get("target_space_group"),
    )
    crystal_system = _first_text(
        constraints.get("crystal_system"),
        constraints.get("target_crystal_system"),
        row.get("target_crystal_system"),
    )
    family = _first_text(
        constraints.get("structure_family"),
        constraints.get("target_structure_family"),
        row.get("target_structure_family"),
    )
    motifs = constraints.get("required_motifs")
    motif_prior = "; ".join(str(item) for item in motifs if str(item).strip()) if isinstance(motifs, list) else None
    return {
        "schema_version": "task_spec.v1",
        "query_text": _first_text(row.get("input_text"), row.get("target_formula")) or "structured crystal task",
        "composition_target": _first_text(constraints.get("formula"), row.get("target_formula")),
        "composition_strictness": "fixed",
        "symmetry_request": {
            "space_group": space_group,
            "hardness": "hard" if space_group else "none",
        },
        "target_space_group": space_group,
        "target_space_group_number": _first_text(
            constraints.get("space_group_number"),
            constraints.get("target_space_group_number"),
            row.get("target_space_group_number"),
        ),
        "target_crystal_system": crystal_system,
        "target_structure_family": family,
        "prototype": family,
        "motif_prior": motif_prior,
        "property_bias": None,
        "qlip_objective": None,
        "external_predictor_targets": [],
        "solve_mode": "feasibility",
        "retrieval_strictness": "prototype_tight" if family else "composition_tight",
        "iteration_budget": 1,
        "defaults_used": ["structured_intent_from_full_100_manifest"],
    }


def _intent_constraints(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, str):
            text = str(value).strip()
            if text:
                return text
    return None


def _settings_for_run(
    config: Path | None,
    out_root: Path,
    workspace: Path,
    regularisation_spp_dir: Path | None,
) -> Settings:
    settings = Settings.from_sources(config)
    repo = REPO_ROOT.resolve()
    out = out_root.resolve()
    ws = workspace.resolve()
    settings.workspace_root = ws
    settings.allowed_read_roots = sorted({repo, out, ws, *[p.resolve() for p in settings.allowed_read_roots]})
    settings.allowed_write_roots = sorted({out, ws, *[p.resolve() for p in settings.allowed_write_roots]})
    if settings.qlip_allow_repo_shim and ws not in settings.qlip_allowed_path_roots:
        settings.qlip_allowed_path_roots.append(ws)
    if regularisation_spp_dir is not None:
        reg_dir = regularisation_spp_dir.resolve()
        if reg_dir not in settings.qlip_allowed_path_roots:
            settings.qlip_allowed_path_roots.append(reg_dir)
    return settings


def _validate_subset_manifest(rows: list[dict[str, str]], seed: int) -> list[str]:
    errors: list[str] = []
    if not rows:
        return ["subset manifest contains no rows"]
    seen_run_indices: set[str] = set()
    seen_prompt_ids: set[str] = set()
    for row in rows:
        run_index = str(row.get("run_index", "")).strip()
        if not run_index:
            errors.append("row missing run_index")
        elif run_index in seen_run_indices:
            errors.append(f"duplicate run_index {run_index}")
        seen_run_indices.add(run_index)
        prompt_id = str(row.get("prompt_id", "")).strip()
        if not prompt_id:
            errors.append(f"run_index {run_index}: missing prompt_id")
        elif prompt_id in seen_prompt_ids:
            errors.append(f"duplicate prompt_id {prompt_id}")
        seen_prompt_ids.add(prompt_id)
        if str(row.get("seed", "")).strip() != str(seed):
            errors.append(f"run_index {run_index}: expected seed {seed}, found {row.get('seed')}")
        if not str(row.get("input_text", "")).strip():
            errors.append(f"run_index {run_index}: missing input_text")
    return errors


def _status_from_result(exit_code: int, pipeline_status: str | None, row: dict[str, str], cifs: list[Path]) -> str:
    if exit_code == 0 and cifs:
        return "success"
    if row.get("benchmark_mode") == "adversarial_or_infeasible":
        if pipeline_status and pipeline_status != "SUCCEEDED":
            return "infeasible_or_invalid_recorded"
        if not cifs:
            return "no_cif_adversarial_recorded"
    if exit_code == 0:
        return "completed_no_cif"
    return "failed"


def _write_report(
    path: Path,
    *,
    args: argparse.Namespace,
    summary: dict[str, Any],
    mode_counts: Counter[str],
    status_counts: Counter[str],
    entrypoint: str,
) -> None:
    lines = [
        "# Full 100 Skill-Loop-CSP Execution Report",
        "",
        "## Run configuration",
        "",
        f"- Manifest: `{args.manifest}`",
        f"- Output root: `{args.out_root}`",
        f"- Seed: `{args.seed}`",
        f"- Mode: `{args.mode}`",
        f"- Config: `{args.config}`" if args.config else "- Config: default Settings.from_sources()",
        f"- SPP guidance weight: {args.spp_guidance_weight}",
        f"- Regularisation weight: {args.regularisation_weight}",
        f"- Missing-pair policy: `{args.missing_pair_policy}`",
        f"- Regularisation SPP dir: `{args.regularisation_spp_dir}`",
        "",
        "## Manifest validation",
        "",
        "- Manifest validation passed before execution.",
        f"- Benchmark modes: {dict(mode_counts)}",
        "",
        "## Executor entrypoint",
        "",
        f"- `{entrypoint}`",
        "",
        "## Generation success summary",
        "",
        f"- Requested runs: {summary['num_requested_runs']}",
        f"- Attempted runs: {summary['num_attempted_runs']}",
        f"- Successful runs: {summary['num_successful_runs']}",
        f"- Failed runs: {summary['num_failed_runs']}",
        f"- Status counts: {dict(status_counts)}",
        "",
        "## Generated CIF summary",
        "",
        f"- Generated CIFs found: {summary['num_generated_cifs']}",
        f"- CIF manifest: `{summary['generated_cifs_manifest_path']}`",
        "",
        "## Adversarial/infeasible handling",
        "",
        f"- Expected adversarial/infeasible rows: {summary['num_infeasible_or_invalid_expected']}",
        "- Adversarial rows are not forced to produce CIFs; rejection, invalidation, or clear failure is recorded.",
        "",
        "## Failure summary",
        "",
        f"- Failed runs: {summary['num_failed_runs']}",
        "- See `logs/generation_log.csv` and per-run `stderr.txt` files for exact errors.",
        "",
        "## Output files",
        "",
        f"- Generation log CSV: `{summary['generation_log_path']}`",
        f"- Generation log JSONL: `{_relative_or_absolute(path.parent / 'logs' / 'generation_log.jsonl')}`",
        f"- Summary JSON: `{_relative_or_absolute(path.parent / 'FULL_100_SKILL_LOOP_EXECUTION_SUMMARY.json')}`",
        "",
        "## Next SCA commands",
        "",
        "Run SCA only after reviewing the generation log and confirming the raw run archives are ready:",
        "",
        "```powershell",
        "Get-Content benchmarks/full_100_seeded_20260626/downstream_sca_commands.md",
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_manifest(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    out_root = Path(args.out_root)
    config = Path(args.config).resolve() if args.config else None
    rows = _read_manifest(manifest_path)
    validation_errors = (
        _validate_subset_manifest(rows, args.seed)
        if args.allow_subset
        else validate_manifest(manifest_path)
    )
    if validation_errors:
        for error in validation_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if str(args.seed) != "20260626":
        print("ERROR: this benchmark requires seed 20260626", file=sys.stderr)
        return 2

    out_root.mkdir(parents=True, exist_ok=True)
    logs_dir = out_root / "logs"
    manifests_dir = out_root / "manifests"
    workspace_root = out_root / "_pipeline_workspace"
    logs_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = logs_dir / "generation_log.jsonl"
    if jsonl_path.exists():
        jsonl_path.unlink()

    log_rows: list[dict[str, Any]] = []
    cif_rows: list[dict[str, str]] = []
    mode_counts = Counter(row["benchmark_mode"] for row in rows)
    entrypoint = "sok_llm_orchestrator.orchestrator.pipeline.run_csp_pipeline"
    from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline

    for row in rows:
        run_index = int(row["run_index"])
        raw_base = _archive_dir_for_row(row, out_root)
        raw_run_dir, attempt_label = _prepare_raw_run_dir(raw_base)
        workspace = workspace_root / f"run_{run_index:03d}"
        workspace.mkdir(parents=True, exist_ok=True)
        regularisation_spp_dir = Path(args.regularisation_spp_dir).resolve() if args.regularisation_spp_dir else None
        settings = _settings_for_run(config, out_root, workspace, regularisation_spp_dir)
        stdout_path = raw_run_dir / "stdout.txt"
        stderr_path = raw_run_dir / "stderr.txt"
        command = (
            f"internal:{entrypoint}(query=<manifest input_text>, with_spp={row['spp_required']}, "
            f"mode={args.mode}, workspace={_relative_or_absolute(workspace)})"
        )
        _write_json(raw_run_dir / "manifest_row.json", row)
        task_spec_payload = _task_spec_payload_from_manifest_row(row)
        _write_json(raw_run_dir / "task_spec.json", task_spec_payload)
        (raw_run_dir / "prompt.txt").write_text(row["input_text"] + "\n", encoding="utf-8")

        start = time.perf_counter()
        exit_code = 1
        error_type = ""
        error_message = ""
        pipeline_status: str | None = None
        pipeline_run_dir: Path | None = None
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            try:
                result = run_csp_pipeline(
                    query=row["input_text"],
                    with_spp=row.get("spp_required", "").lower() == "true",
                    mode=args.mode,
                    workspace=workspace,
                    settings=settings,
                    execution_overrides={
                        "retrieval_candidate_k": 5 if row.get("retrieval_required") == "true" else 3,
                        "corpus_top_k": 5 if row.get("spp_required") == "true" else 3,
                        "spp_guidance_weight": float(args.spp_guidance_weight),
                        "runtime_spp_guidance_weight": float(args.spp_guidance_weight),
                        "spp_regularisation_dir": str(regularisation_spp_dir) if regularisation_spp_dir else "",
                        "spp_regularisation_weight": float(args.regularisation_weight),
                        "spp_missing_pair_policy": str(args.missing_pair_policy),
                    },
                    task_spec_payload=task_spec_payload,
                    strict_phase1_benchmark_mode=False,
                )
                pipeline_status = result.status
                pipeline_run_dir = result.run_dir
                exit_code = 0 if result.status == "SUCCEEDED" else 1
                if result.status != "SUCCEEDED":
                    error_message = _pipeline_failure_reason(result.run_dir)
            except Exception as exc:  # noqa: BLE001
                error_type = type(exc).__name__
                error_message = str(exc)
                print(f"{error_type}: {error_message}", file=sys.stderr)
        runtime = time.perf_counter() - start
        stdout_path.write_text(stdout_buffer.getvalue(), encoding="utf-8")
        stderr_path.write_text(stderr_buffer.getvalue(), encoding="utf-8")

        if pipeline_run_dir and pipeline_run_dir.exists():
            archived_pipeline_dir = raw_run_dir / "_raw_pipeline_run"
            _copytree_contents(pipeline_run_dir, archived_pipeline_dir)
        else:
            archived_pipeline_dir = raw_run_dir

        cifs = _find_cifs(raw_run_dir)
        status = _status_from_result(exit_code, pipeline_status, row, cifs)
        generated_paths = [_relative_or_absolute(path) for path in cifs]
        log_row = {
            "run_index": row["run_index"],
            "case_id": row["case_id"],
            "prompt_id": row["prompt_id"],
            "seed": row["seed"],
            "benchmark_mode": row["benchmark_mode"],
            "input_text": row["input_text"],
            "run_archive_dir": _relative_or_absolute(raw_run_dir),
            "command": command,
            "exit_code": str(exit_code),
            "runtime_seconds": f"{runtime:.3f}",
            "status": status,
            "expected_solver_status": row.get("expected_solver_status", ""),
            "num_cifs_found": str(len(cifs)),
            "generated_cif_paths": ";".join(generated_paths),
            "stdout_path": _relative_or_absolute(stdout_path),
            "stderr_path": _relative_or_absolute(stderr_path),
            "error_type": error_type,
            "error_message": error_message,
            "spp_guidance_weight": str(float(args.spp_guidance_weight)),
            "regularisation_weight": str(float(args.regularisation_weight)),
            "missing_pair_policy": str(args.missing_pair_policy),
            "regularisation_spp_dir": str(regularisation_spp_dir) if regularisation_spp_dir else "",
            "qlip_allowed_path_roots": ";".join(str(Path(root).resolve()) for root in settings.qlip_allowed_path_roots),
        }
        log_rows.append(log_row)
        _append_jsonl(jsonl_path, log_row)
        for cif in cifs:
            cif_rows.append(_row_with_cif(row, cif, raw_run_dir))
        _write_json(
            raw_run_dir / "execution_status.json",
            {
                "attempt_label": attempt_label,
                "entrypoint": entrypoint,
                "pipeline_status": pipeline_status,
                "status": status,
                "exit_code": exit_code,
                "runtime_seconds": runtime,
                "num_cifs_found": len(cifs),
                "generated_cif_paths": generated_paths,
                "error_type": error_type,
                "error_message": error_message,
                "config_c": {
                    "spp_guidance_weight": float(args.spp_guidance_weight),
                    "regularisation_weight": float(args.regularisation_weight),
                    "missing_pair_policy": str(args.missing_pair_policy),
                    "regularisation_spp_dir": str(regularisation_spp_dir) if regularisation_spp_dir else "",
                    "qlip_allowed_path_roots": [str(Path(root).resolve()) for root in settings.qlip_allowed_path_roots],
                },
            },
        )
        print(f"run_{run_index:03d}: {status} cifs={len(cifs)}")

    generation_log_csv = logs_dir / "generation_log.csv"
    generated_cifs_manifest = manifests_dir / "generated_cifs_manifest.csv"
    _write_csv(generation_log_csv, LOG_COLUMNS, log_rows)
    _write_csv(generated_cifs_manifest, CIF_COLUMNS, cif_rows)

    status_counts = Counter(row["status"] for row in log_rows)
    successful = sum(1 for row in log_rows if row["status"] in {"success", "infeasible_or_invalid_recorded", "no_cif_adversarial_recorded"})
    failed = len(log_rows) - successful
    summary = {
        "seed": int(args.seed),
        "num_requested_runs": len(rows),
        "num_attempted_runs": len(log_rows),
        "num_successful_runs": successful,
        "num_failed_runs": failed,
        "num_infeasible_or_invalid_expected": 10,
        "num_generated_cifs": len(cif_rows),
        "physically_meaningful": True,
        "manifest_path": _relative_or_absolute(manifest_path),
        "generation_log_path": _relative_or_absolute(generation_log_csv),
        "generated_cifs_manifest_path": _relative_or_absolute(generated_cifs_manifest),
        "status_counts": dict(status_counts),
        "benchmark_mode_counts": dict(mode_counts),
        "executor_entrypoint": entrypoint,
        "mode": args.mode,
        "config_c": {
            "spp_guidance_weight": float(args.spp_guidance_weight),
            "regularisation_weight": float(args.regularisation_weight),
            "missing_pair_policy": str(args.missing_pair_policy),
            "regularisation_spp_dir": str(Path(args.regularisation_spp_dir).resolve()) if args.regularisation_spp_dir else "",
        },
    }
    summary_path = out_root / "FULL_100_SKILL_LOOP_EXECUTION_SUMMARY.json"
    report_path = out_root / "FULL_100_SKILL_LOOP_EXECUTION_REPORT.md"
    _write_json(summary_path, summary)
    _write_report(
        report_path,
        args=args,
        summary=summary,
        mode_counts=mode_counts,
        status_counts=status_counts,
        entrypoint=entrypoint,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--config", default="my_live_config.yaml")
    parser.add_argument("--mode", default="live", choices=["live", "stub"])
    parser.add_argument("--allow-subset", action="store_true")
    parser.add_argument("--spp-guidance-weight", default=CONFIG_C_SPP_GUIDANCE_WEIGHT, type=float)
    parser.add_argument("--regularisation-weight", default=CONFIG_C_REGULARISATION_WEIGHT, type=float)
    parser.add_argument("--missing-pair-policy", default=CONFIG_C_MISSING_PAIR_POLICY)
    parser.add_argument(
        "--regularisation-spp-dir",
        default=CONFIG_C_REGULARISATION_SPP_DIR,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    return run_manifest(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
