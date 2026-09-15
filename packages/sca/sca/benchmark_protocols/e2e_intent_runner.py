"""Full intent-driven Skill-Loop-CSP benchmark orchestration."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pandas as pd

from sca.benchmark_protocols.direct import run_direct_cif_benchmark
from sca.benchmark_protocols.intent_prompts import INTENT_COLUMNS, build_intent_prompt_manifest
from sca.io import discover_cif_files
from sca.traceability.adapters.llm_csp_archive import detect_llm_csp_archive, load_llm_csp_archive, write_traceable_bundle
from sca.traceability.io import inspect_run_bundle
from sca.unique_benchmarks.summary import build_unique_csp_summary


RUN_DIRS = [
    "prompts",
    "skill_loop_raw_runs",
    "generated_cifs",
    "manifests",
    "sca_direct_benchmark",
    "sca_intent_benchmark",
    "sca_unique_benchmark",
    "diagnostics",
    "logs",
    "environment",
    "reports",
]

GENERATION_LOG_COLUMNS = [
    "run_index",
    "prompt_id",
    "seed",
    "benchmark_mode",
    "input_text",
    "target_formula",
    "target_structure_family",
    "skill_loop_archive_dir",
    "command",
    "exit_code",
    "runtime_seconds",
    "status",
    "num_cifs_found",
    "generated_cif_paths",
    "stdout_path",
    "stderr_path",
    "error_type",
    "error_message",
]

GENERATED_CIF_MANIFEST_COLUMNS = [
    "cif_path",
    "run_index",
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
    "intent_specificity",
    "expected_formula_terms",
    "expected_family_terms",
    "expected_coordination_terms",
    "expected_connectivity_terms",
    "expected_motifs_or_priors",
    "intent_constraints_json",
    "reference_cif_path",
    "attempt_id",
    "method",
    "raw_run_dir",
    "run_dir",
    "notes",
]

TASK_SPEC_SIDECAR_NAME = "task_spec.json"


def ensure_run_layout(run_root: str | Path) -> dict[str, Path]:
    root = Path(run_root)
    paths = {"root": root}
    for name in RUN_DIRS:
        paths[name] = root / name
        paths[name].mkdir(parents=True, exist_ok=True)
    return paths


def run_skill_loop_intent_benchmark(
    *,
    prompts: str | Path,
    skill_loop_command: str,
    out_root: str | Path,
    seed: int,
    num_attempts: int = 1,
    require_100: bool = True,
) -> dict[str, Any]:
    paths = ensure_run_layout(out_root)
    prompt_frame = pd.read_csv(prompts, dtype=str).fillna("")
    _validate_prompt_frame(prompt_frame, seed, require_100=require_100)
    log_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []

    for _, row in prompt_frame.iterrows():
        run_index = int(row["run_index"])
        run_dir = paths["skill_loop_raw_runs"] / f"run_{run_index:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_row = _series_to_dict(row)
        manifest_row["num_attempts"] = str(num_attempts)
        (run_dir / "manifest_row.json").write_text(json.dumps(manifest_row, indent=2), encoding="utf-8")
        (run_dir / "prompt.txt").write_text(str(row["input_text"]), encoding="utf-8")
        task_spec_path = run_dir / TASK_SPEC_SIDECAR_NAME
        task_spec_path.write_text(json.dumps(_task_spec_payload_from_row(row), indent=2, sort_keys=True), encoding="utf-8")
        command = _format_command(skill_loop_command, row, run_dir, seed, task_spec_path)
        stdout_path = run_dir / "stdout.txt"
        stderr_path = run_dir / "stderr.txt"
        started = time.perf_counter()
        exit_code = None
        error_type = ""
        error_message = ""
        try:
            completed = subprocess.run(command, shell=True, capture_output=True, text=True)
            exit_code = completed.returncode
            stdout_path.write_text(completed.stdout, encoding="utf-8")
            stderr_path.write_text(completed.stderr, encoding="utf-8")
        except Exception as exc:
            exit_code = -1
            error_type = type(exc).__name__
            error_message = str(exc)
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(str(exc), encoding="utf-8")
        runtime = time.perf_counter() - started
        cifs = discover_cif_files(run_dir)
        copied = []
        for attempt, cif_path in enumerate(cifs, start=1):
            target = paths["generated_cifs"] / f"run_{run_index:03d}_attempt_{attempt:03d}_{cif_path.name}"
            shutil.copy2(cif_path, target)
            copied.append(target)
            manifest_rows.append(_generated_manifest_row(row, target, attempt, run_dir))
        status = _generation_status(row, exit_code, copied, run_dir)
        log_row = {
            "run_index": run_index,
            "prompt_id": row["prompt_id"],
            "seed": row["seed"],
            "benchmark_mode": row["benchmark_mode"],
            "input_text": row["input_text"],
            "target_formula": row["target_formula"],
            "target_structure_family": row["target_structure_family"],
            "skill_loop_archive_dir": str(run_dir),
            "command": command,
            "exit_code": exit_code,
            "runtime_seconds": round(runtime, 6),
            "status": status,
            "num_cifs_found": len(copied),
            "generated_cif_paths": ";".join(str(path) for path in copied),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "error_type": error_type,
            "error_message": error_message,
        }
        log_rows.append(log_row)

    logs = paths["logs"]
    pd.DataFrame(log_rows, columns=GENERATION_LOG_COLUMNS).to_csv(logs / "generation_log.csv", index=False)
    with (logs / "generation_log.jsonl").open("w", encoding="utf-8") as handle:
        for row in log_rows:
            handle.write(json.dumps(row) + "\n")
    manifest_path = paths["manifests"] / "generated_cifs_manifest_for_sca.csv"
    pd.DataFrame(manifest_rows, columns=GENERATED_CIF_MANIFEST_COLUMNS).to_csv(manifest_path, index=False)
    return {
        "prompts": len(prompt_frame),
        "generated_cifs": len(manifest_rows),
        "generation_log": str(logs / "generation_log.csv"),
        "manifest": str(manifest_path),
    }


def run_full_intent_benchmark_evaluation(
    *,
    run_root: str | Path,
    manifest: str | Path,
    seed: int,
) -> dict[str, Any]:
    paths = ensure_run_layout(run_root)
    manifest_path = Path(manifest)
    conversion_summary = _convert_archives(paths)
    direct = run_direct_cif_benchmark(
        cif_folder=None,
        manifest=manifest_path,
        protocols="all",
        out_csv=paths["sca_direct_benchmark"] / "benchmark_results.csv",
        summary_csv=paths["sca_direct_benchmark"] / "benchmark_summary.csv",
        json_out=paths["sca_direct_benchmark"] / "benchmark_summary.json",
        markdown=paths["sca_direct_benchmark"] / "benchmark_report.md",
        evaluators="auto",
        include_relaxation=False,
        relax_backend="chgnet",
        hull_reference=None,
        reference_corpus=None,
        protocol_match_level="contextual_only",
        path_col="cif_path",
        attempt_col="attempt_id",
        target_col="prompt_id",
        method_col="method",
    )
    intent = run_direct_cif_benchmark(
        cif_folder=None,
        manifest=manifest_path,
        protocols="all",
        out_csv=paths["sca_intent_benchmark"] / "intent_results.csv",
        summary_csv=paths["sca_intent_benchmark"] / "intent_summary.csv",
        json_out=paths["sca_intent_benchmark"] / "intent_summary.json",
        markdown=paths["sca_intent_benchmark"] / "intent_report.md",
        evaluators="cif_parse,geometry,intent_satisfaction",
        include_relaxation=False,
        relax_backend="chgnet",
        hull_reference=None,
        reference_corpus=None,
        protocol_match_level="contextual_only",
        path_col="cif_path",
        attempt_col="attempt_id",
        target_col="prompt_id",
        method_col="method",
    )
    unique = build_unique_csp_summary(
        results=paths["sca_intent_benchmark"] / "intent_results.csv",
        bundles=paths["sca_unique_benchmark"] / "traceable_bundles",
        out_csv=paths["sca_unique_benchmark"] / "unique_summary.csv",
        json_out=paths["sca_unique_benchmark"] / "unique_summary.json",
        markdown=paths["sca_unique_benchmark"] / "unique_report.md",
    )
    diagnostics = _write_diagnostics(paths, paths["sca_intent_benchmark"] / "intent_results.csv")
    reports = write_full_intent_report(paths, seed=seed)
    return {
        "conversion_summary": str(conversion_summary),
        "direct": direct,
        "intent": intent,
        "unique": unique,
        "diagnostics": diagnostics,
        "report": reports["markdown"],
        "summary_json": reports["json"],
    }


def run_full_skill_loop_intent_benchmark(
    *,
    skill_loop_command: str,
    out_root: str | Path,
    seed: int,
    num_prompts: int,
    num_attempts: int = 1,
    skip_generation: bool = False,
    skip_evaluation: bool = False,
) -> dict[str, Any]:
    paths = ensure_run_layout(out_root)
    prompts_csv = paths["prompts"] / f"intent_prompts_{num_prompts}.csv"
    prompts_json = paths["prompts"] / f"intent_prompts_{num_prompts}.json"
    if not skip_generation:
        build_intent_prompt_manifest(out_csv=prompts_csv, out_json=prompts_json, seed=seed, num_prompts=num_prompts)
        generation = run_skill_loop_intent_benchmark(
            prompts=prompts_csv,
            skill_loop_command=skill_loop_command,
            out_root=out_root,
            seed=seed,
            num_attempts=num_attempts,
            require_100=num_prompts == 100,
        )
    else:
        generation = {"manifest": str(paths["manifests"] / "generated_cifs_manifest_for_sca.csv")}
    evaluation = None
    if not skip_evaluation:
        evaluation = run_full_intent_benchmark_evaluation(
            run_root=out_root,
            manifest=generation["manifest"],
            seed=seed,
        )
    return {"prompts": str(prompts_csv), "generation": generation, "evaluation": evaluation}


def write_full_intent_report(paths: dict[str, Path], *, seed: int) -> dict[str, str]:
    reports = paths["reports"]
    summary = _summary_json(paths, seed)
    summary_path = reports / "FULL_100_INTENT_BENCHMARK_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path = reports / "FULL_100_INTENT_BENCHMARK_REPORT.md"
    md_path.write_text(_report_markdown(paths, summary), encoding="utf-8")
    return {"markdown": str(md_path), "json": str(summary_path)}


def _validate_prompt_frame(frame: pd.DataFrame, seed: int, *, require_100: bool) -> None:
    missing = [column for column in INTENT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Intent prompt manifest missing columns: {', '.join(missing)}")
    if require_100 and len(frame) != 100:
        raise ValueError(f"Intent benchmark manifest must contain exactly 100 rows; found {len(frame)}")
    seeds = {str(value) for value in frame["seed"].tolist()}
    if seeds != {str(seed)}:
        raise ValueError(f"Intent manifest seed must be fixed at {seed}; found {sorted(seeds)}")


def _format_command(template: str, row: pd.Series, out_dir: Path, seed: int, task_spec_path: Path | None = None) -> str:
    replacements = {
        "prompt": str(row["input_text"]),
        "prompt_id": str(row["prompt_id"]),
        "run_index": str(row["run_index"]),
        "seed": str(seed),
        "out_dir": str(out_dir),
        "target_formula": str(row["target_formula"]),
        "target_space_group": str(row.get("target_space_group", "")),
        "target_crystal_system": str(row.get("target_crystal_system", "")),
        "target_structure_family": str(row.get("target_structure_family", "")),
        "task_spec_json": str(task_spec_path or (out_dir / TASK_SPEC_SIDECAR_NAME)),
        "benchmark_mode": str(row["benchmark_mode"]),
    }
    command = template
    for key, value in replacements.items():
        command = command.replace("{" + key + "}", _quote(value))
    return command


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _task_spec_payload_from_row(row: pd.Series) -> dict[str, Any]:
    data = _series_to_dict(row)
    constraints = _intent_constraints(data.get("intent_constraints_json"))
    space_group = _first_text(
        constraints.get("space_group"),
        constraints.get("target_space_group"),
        data.get("target_space_group"),
    )
    crystal_system = _first_text(
        constraints.get("crystal_system"),
        constraints.get("target_crystal_system"),
        data.get("target_crystal_system"),
    )
    family = _first_text(
        constraints.get("structure_family"),
        constraints.get("target_structure_family"),
        data.get("target_structure_family"),
    )
    motifs = constraints.get("required_motifs")
    motif_prior = "; ".join(str(item) for item in motifs if str(item).strip()) if isinstance(motifs, list) else None
    return {
        "schema_version": "task_spec.v1",
        "query_text": _first_text(data.get("input_text"), data.get("target_formula")) or "structured crystal task",
        "composition_target": _first_text(constraints.get("formula"), data.get("target_formula")),
        "composition_strictness": "fixed",
        "symmetry_request": {
            "space_group": space_group,
            "hardness": "hard" if space_group else "none",
        },
        "target_space_group": space_group,
        "target_space_group_number": _first_text(
            constraints.get("space_group_number"),
            constraints.get("target_space_group_number"),
            data.get("target_space_group_number"),
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
        "defaults_used": ["structured_intent_from_sca_manifest"],
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


def _series_to_dict(row: pd.Series) -> dict[str, Any]:
    return {str(key): ("" if pd.isna(value) else value) for key, value in row.items()}


def _generated_manifest_row(row: pd.Series, cif_path: Path, attempt_id: int, run_dir: Path) -> dict[str, Any]:
    data = _series_to_dict(row)
    return {
        **{key: data.get(key, "") for key in GENERATED_CIF_MANIFEST_COLUMNS if key in data},
        "cif_path": str(cif_path.resolve()),
        "attempt_id": attempt_id,
        "method": "skill_loop_csp",
        "raw_run_dir": str(run_dir.resolve()),
        "run_dir": str(run_dir.resolve()),
        "notes": data.get("notes", ""),
    }


def _generation_status(row: pd.Series, exit_code: int | None, copied: list[Path], run_dir: Path) -> str:
    mode = str(row.get("benchmark_mode", ""))
    if exit_code == 0 and copied:
        return "ok"
    if mode == "adversarial_or_infeasible" and _has_infeasible_status(run_dir):
        return "infeasible_or_invalid"
    if exit_code == 0:
        return "no_cif"
    return "generator_failed"


def _has_infeasible_status(run_dir: Path) -> bool:
    for path in run_dir.rglob("*.json"):
        try:
            text = path.read_text(encoding="utf-8").lower()
        except Exception:
            continue
        if "infeasible" in text or "invalid" in text:
            return True
    return False


def _convert_archives(paths: dict[str, Path]) -> Path:
    out_dir = paths["sca_unique_benchmark"] / "traceable_bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for archive in sorted(path for path in paths["skill_loop_raw_runs"].iterdir() if path.is_dir()):
        if not detect_llm_csp_archive(archive):
            rows.append({"run_id": archive.name, "archive": str(archive), "bundle_valid": False, "conversion_errors": "archive_not_detected"})
            continue
        target = out_dir / archive.name
        try:
            bundle = load_llm_csp_archive(archive, run_id=archive.name)
            result = write_traceable_bundle(bundle, target)
            inspection = inspect_run_bundle(target)
            rows.append(
                {
                    **result["manifest_row"],
                    "archive": str(archive),
                    "bundle_valid": inspection.bundle_valid,
                    "missing_artifacts": ";".join(inspection.missing_artifacts),
                    "parse_errors": ";".join(inspection.parse_errors),
                }
            )
        except Exception as exc:
            rows.append({"run_id": archive.name, "archive": str(archive), "bundle_dir": str(target), "bundle_valid": False, "conversion_errors": str(exc)})
    summary = paths["sca_unique_benchmark"] / "bundle_conversion_summary.csv"
    pd.DataFrame(rows).to_csv(summary, index=False)
    return summary


def _write_diagnostics(paths: dict[str, Path], results_csv: Path) -> dict[str, str]:
    frame = pd.read_csv(results_csv) if results_csv.exists() else pd.DataFrame()
    outputs = {}
    for column, filename in (
        ("benchmark_mode", "grouped_by_benchmark_mode.csv"),
        ("chemistry_family", "grouped_by_chemistry_family.csv"),
        ("challenge_type", "grouped_by_challenge_type.csv"),
    ):
        out = paths["diagnostics"] / filename
        _grouped(frame, column).to_csv(out, index=False)
        outputs[column] = str(out)
    worst = paths["diagnostics"] / "worst_20_intent_failures.csv"
    if "intent_satisfaction_score" in frame:
        frame.sort_values("intent_satisfaction_score", na_position="first").head(20).to_csv(worst, index=False)
    else:
        pd.DataFrame().to_csv(worst, index=False)
    outputs["worst_20"] = str(worst)
    return outputs


def _grouped(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame.empty or column not in frame:
        return pd.DataFrame(columns=[column, "num_rows"])
    grouped = frame.groupby(column, dropna=False)
    rows = []
    for value, group in grouped:
        rows.append(
            {
                column: value,
                "num_rows": len(group),
                "parse_validity_rate": _bool_rate(group, "parse_ok"),
                "intent_satisfaction_score_mean": _mean(group, "intent_satisfaction_score"),
                "intent_formula_satisfaction_rate": _bool_rate(group, "intent_formula_satisfied"),
                "bad_contact_rate": _bool_rate(group, "has_bad_contacts"),
            }
        )
    return pd.DataFrame(rows)


def _summary_json(paths: dict[str, Path], seed: int) -> dict[str, Any]:
    generation = _read_csv(paths["logs"] / "generation_log.csv")
    intent = _read_csv(paths["sca_intent_benchmark"] / "intent_results.csv")
    unique = _read_csv(paths["sca_unique_benchmark"] / "unique_summary.csv")
    return {
        "seed": seed,
        "num_prompts": int(len(generation)) if not generation.empty else None,
        "num_generation_attempts": int(len(generation)) if not generation.empty else None,
        "num_generated_cifs": int(len(intent)) if not intent.empty else None,
        "parse_validity_rate": _bool_rate(intent, "parse_ok"),
        "pre_dft_validity_rate": _bool_rate(intent, "pre_dft_valid"),
        "bad_contact_rate": _bool_rate(intent, "has_bad_contacts"),
        "intent_satisfaction_score_mean": _mean(intent, "intent_satisfaction_score"),
        "intent_formula_satisfaction_rate": _bool_rate(intent, "intent_formula_satisfied"),
        "intent_family_satisfaction_rate": _bool_rate(intent, "intent_family_satisfied"),
        "intent_space_group_satisfaction_rate": _bool_rate(intent, "intent_space_group_satisfied"),
        "unique_csp_score_mean": _summary_value(unique, "traceable_constraint_grounded_csp_score"),
        "audit_bundle_complete_rate": _summary_value(unique, "audit_bundle_score"),
        "run_root": str(paths["root"]),
    }


def _report_markdown(paths: dict[str, Path], summary: dict[str, Any]) -> str:
    sections = [
        "Run configuration",
        "Prompt distribution",
        "Skill-Loop-CSP generation summary",
        "CIF validity summary",
        "Intent satisfaction summary",
        "Literature-style benchmark summary",
        "Unique traceability benchmark summary",
        "Results by benchmark mode",
        "Results by chemistry family",
        "Results by challenge type",
        "Best examples",
        "Worst failures",
        "Dummy/invalid species failures",
        "Bad-contact failures",
        "Intent mismatch failures",
        "Adversarial/infeasible prompt handling",
        "Not-computable metrics",
        "Recommended generator fixes",
        "Reproducibility",
        "Output file index",
    ]
    lines = ["# Full 100 Intent Benchmark Report", ""]
    for section in sections:
        lines.extend([f"## {section}", ""])
        if section == "Run configuration":
            lines.append(f"- Seed: {summary.get('seed')}")
            lines.append(f"- Run root: {summary.get('run_root')}")
        elif section == "Intent satisfaction summary":
            lines.append(f"- Mean score: {_fmt(summary.get('intent_satisfaction_score_mean'))}")
            lines.append(f"- Formula satisfaction: {_fmt(summary.get('intent_formula_satisfaction_rate'))}")
            lines.append(f"- Family satisfaction: {_fmt(summary.get('intent_family_satisfaction_rate'))}")
        elif section == "CIF validity summary":
            lines.append(f"- Parse validity rate: {_fmt(summary.get('parse_validity_rate'))}")
            lines.append(f"- Bad contact rate: {_fmt(summary.get('bad_contact_rate'))}")
        elif section == "Output file index":
            for path in sorted(paths["root"].rglob("*")):
                if path.is_file() and path.suffix.lower() in {".csv", ".json", ".md", ".jsonl"}:
                    lines.append(f"- {path}")
        else:
            lines.append("See the CSV and JSON artifacts in this run directory for detailed rows.")
        lines.append("")
    return "\n".join(lines)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _bool_rate(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame:
        return None
    values = [_as_bool(value) for value in frame[column].tolist()]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _mean(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _summary_value(frame: pd.DataFrame, metric: str) -> float | None:
    if frame.empty:
        return None
    if "metric" in frame.columns and "value" in frame.columns:
        match = frame.loc[frame["metric"] == metric, "value"]
        if not match.empty:
            return float(match.iloc[0])
    if metric in frame.columns:
        return _mean(frame, metric)
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _fmt(value: Any) -> str:
    return "not_computable" if value is None else f"{float(value):.3f}"
