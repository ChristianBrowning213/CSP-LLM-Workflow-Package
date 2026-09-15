"""End-to-end text-to-crystal benchmark runner."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from sca.benchmark_protocols.direct import run_direct_cif_benchmark
from sca.io import discover_cif_files


PROMPT_COLUMNS = [
    "prompt_id",
    "paper_source",
    "benchmark_family",
    "input_text",
    "target_formula",
    "target_structure_family",
    "target_space_group",
    "target_crystal_system",
    "reference_cif_path",
    "reference_id",
    "num_attempts",
    "expected_metrics",
    "required_tools",
    "notes",
]


def run_e2e_text_benchmark(
    *,
    prompts: str | Path,
    generator_command: str,
    out_dir: str | Path,
    num_attempts: int,
    protocols: str,
    summary: str | Path,
    markdown: str | Path,
    results: str | Path | None = None,
    json_out: str | Path | None = None,
    protocol_match_level: str = "contextual_only",
) -> dict[str, Any]:
    prompts_path = Path(prompts)
    prompt_frame = pd.read_csv(prompts_path, dtype=str).fillna("")
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    run_rows = []
    manifest_rows = []

    for _, prompt in prompt_frame.iterrows():
        prompt_id = _cell(prompt, "prompt_id")
        prompt_dir = out_root / prompt_id
        if prompt_dir.exists():
            shutil.rmtree(prompt_dir)
        prompt_dir.mkdir(parents=True, exist_ok=True)
        attempts = int(num_attempts)
        command = _format_command(generator_command, prompt, prompt_dir, attempts)
        completed = subprocess.run(command, shell=True, capture_output=True, text=True)
        (prompt_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (prompt_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        cifs = discover_cif_files(prompt_dir)
        run_rows.append(
            {
                "prompt_id": prompt_id,
                "input_text": _cell(prompt, "input_text"),
                "out_dir": str(prompt_dir),
                "generator_command": command,
                "exit_code": completed.returncode,
                "stdout_path": str(prompt_dir / "stdout.txt"),
                "stderr_path": str(prompt_dir / "stderr.txt"),
                "num_cifs": len(cifs),
                "status": "ok" if completed.returncode == 0 else "generator_failed",
            }
        )
        for index, cif_path in enumerate(cifs, start=1):
            manifest_rows.append(_manifest_row(prompt, prompts_path, cif_path, index, attempts))

    run_log = out_root / "generation_log.csv"
    pd.DataFrame(run_rows).to_csv(run_log, index=False)
    generated_manifest = out_root / "generated_cifs_manifest.csv"
    pd.DataFrame(manifest_rows, columns=_manifest_columns()).to_csv(generated_manifest, index=False)

    result_path = Path(results) if results else out_root / "e2e_benchmark_results.csv"
    json_path = Path(json_out) if json_out else Path(summary).with_suffix(".json")
    benchmark_result = run_direct_cif_benchmark(
        cif_folder=None,
        manifest=generated_manifest,
        protocols=protocols,
        out_csv=result_path,
        summary_csv=summary,
        json_out=json_path,
        markdown=markdown,
        evaluators="auto",
        include_relaxation=False,
        relax_backend="chgnet",
        hull_reference=None,
        reference_corpus=None,
        protocol_match_level=protocol_match_level,
        path_col="cif_path",
        attempt_col="attempt_id",
        target_col="benchmark_id",
        method_col="paper_source",
    )
    _append_e2e_sections(markdown, run_rows)
    return {
        "prompts": len(prompt_frame),
        "generated_cifs": len(manifest_rows),
        "generation_log": str(run_log),
        "manifest": str(generated_manifest),
        **benchmark_result,
    }


def _manifest_row(prompt: pd.Series, prompts_path: Path, cif_path: Path, attempt_id: int, attempts: int) -> dict[str, Any]:
    reference = _resolve_prompt_path(_cell(prompt, "reference_cif_path"), prompts_path.parent)
    return {
        "cif_path": str(cif_path.resolve()),
        "sample_id": f"{_cell(prompt, 'prompt_id')}_{attempt_id}",
        "prompt_id": _cell(prompt, "prompt_id"),
        "benchmark_id": _cell(prompt, "prompt_id"),
        "target_formula": _cell(prompt, "target_formula"),
        "target_space_group": _cell(prompt, "target_space_group"),
        "target_structure_family": _cell(prompt, "target_structure_family"),
        "reference_cif_path": str(reference) if reference else "",
        "target_cif_path": str(reference) if reference else "",
        "reference_id": _cell(prompt, "reference_id"),
        "attempt_id": attempt_id,
        "attempt_rank": attempt_id,
        "num_attempts": attempts,
        "method": "e2e_text_generator",
        "paper_source": _cell(prompt, "paper_source"),
        "dataset_scope": _cell(prompt, "benchmark_family"),
        "paper_protocol": _cell(prompt, "expected_metrics"),
        "prompt": _cell(prompt, "input_text"),
        "notes": _cell(prompt, "notes"),
    }


def _format_command(template: str, prompt: pd.Series, out_dir: Path, attempts: int) -> str:
    replacements = {
        "prompt": _cell(prompt, "input_text"),
        "prompt_id": _cell(prompt, "prompt_id"),
        "out_dir": str(out_dir),
        "num_attempts": str(attempts),
        "target_formula": _cell(prompt, "target_formula"),
        "target_space_group": _cell(prompt, "target_space_group"),
        "target_structure_family": _cell(prompt, "target_structure_family"),
    }
    command = template
    for key, value in replacements.items():
        command = command.replace("{" + key + "}", _quote(value))
    return command


def _quote(value: str) -> str:
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def _append_e2e_sections(markdown: str | Path, run_rows: list[dict[str, Any]]) -> None:
    path = Path(markdown)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [
        "",
        "# E2E Text-to-Crystal Benchmark Report",
        "",
        "## Prompt set",
        "",
        f"- Prompts: {len(run_rows)}",
        f"- Generated CIFs: {sum(int(row['num_cifs']) for row in run_rows)}",
        "",
        "## Generation success",
        "",
        "| prompt_id | status | exit_code | num_cifs |",
        "|---|---|---:|---:|",
    ]
    for row in run_rows:
        lines.append(f"| {row['prompt_id']} | {row['status']} | {row['exit_code']} | {row['num_cifs']} |")
    lines.extend(
        [
            "",
            "## Traceability audit",
            "",
            "Generation stdout/stderr paths and command templates are recorded in `generation_log.csv`.",
        ]
    )
    path.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")


def _resolve_prompt_path(value: str, base: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def _manifest_columns() -> list[str]:
    return [
        "cif_path",
        "sample_id",
        "prompt_id",
        "benchmark_id",
        "target_formula",
        "target_space_group",
        "target_structure_family",
        "reference_cif_path",
        "target_cif_path",
        "reference_id",
        "attempt_id",
        "attempt_rank",
        "num_attempts",
        "method",
        "paper_source",
        "dataset_scope",
        "paper_protocol",
        "prompt",
        "notes",
    ]


def _cell(row: pd.Series, key: str) -> str:
    if key not in row:
        return ""
    value = row[key]
    if value is None or str(value).lower() == "nan":
        return ""
    return str(value).strip()
