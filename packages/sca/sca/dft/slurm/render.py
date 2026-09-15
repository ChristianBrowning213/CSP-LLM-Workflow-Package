"""Deterministic Slurm script generation and guarded scheduler interaction."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from sca.dft.io import write_json
from sca.dft.schema import DFTExecutionRecord, DFTStatus
from sca.dft.slurm.schema import SlurmConfig

Runner = Callable[..., subprocess.CompletedProcess[str]]


def render_slurm_script(config: SlurmConfig, calculation_id: str, seed: str) -> str:
    directives = [
        "#!/bin/bash",
        f"#SBATCH --job-name=sca-{_safe(calculation_id)}",
        f"#SBATCH --partition={config.partition}",
        f"#SBATCH --time={config.walltime}",
        f"#SBATCH --nodes={config.nodes}",
        f"#SBATCH --ntasks={config.ntasks}",
        f"#SBATCH --cpus-per-task={config.cpus_per_task}",
        f"#SBATCH --mem={config.memory}",
    ]
    if config.account:
        directives.append(f"#SBATCH --account={config.account}")
    for key, value in sorted(config.extra_scheduler_options.items()):
        flag = key.replace("_", "-")
        directives.append(f"#SBATCH --{flag}" if value is True else f"#SBATCH --{flag}={value}")
    body = ["", "set -euo pipefail", ""]
    body.extend(f"module load {module}" for module in config.modules)
    if config.modules:
        body.append("")
    body.extend(
        [
            f"srun {config.executable} {_safe(seed)} > stdout.txt 2> stderr.txt",
            "",
        ]
    )
    return "\n".join(directives + body)


def submit_calculation(
    calculation_dir: str | Path,
    *,
    runner: Runner = subprocess.run,
) -> DFTExecutionRecord:
    root = Path(calculation_dir)
    calculation = json.loads((root / "calculation.json").read_text(encoding="utf-8"))
    record = DFTExecutionRecord(calculation_id=calculation["calculation_id"], calculation_dir=str(root))
    if shutil.which("sbatch") is None and runner is subprocess.run:
        return record.model_copy(update={"message": "Slurm sbatch executable is unavailable"})
    result = runner(["sbatch", "submit.slurm"], cwd=root, capture_output=True, text=True, check=False)
    match = re.search(r"Submitted batch job\s+(\d+)", result.stdout or "")
    if result.returncode != 0 or not match:
        return record.model_copy(update={"status": DFTStatus.FAILED, "message": (result.stderr or result.stdout).strip()})
    submitted = record.model_copy(
        update={
            "status": DFTStatus.QUEUED,
            "slurm_job_id": match.group(1),
            "submit_time_utc": datetime.now(timezone.utc).isoformat(),
            "submit_command": ["sbatch", "submit.slurm"],
        }
    )
    write_json(root / "execution.json", submitted)
    return submitted


def query_status(record: DFTExecutionRecord, *, runner: Runner = subprocess.run) -> DFTExecutionRecord:
    if not record.slurm_job_id:
        return record
    if shutil.which("sacct") is None and runner is subprocess.run:
        return record.model_copy(update={"status": DFTStatus.UNKNOWN, "message": "Slurm sacct executable is unavailable"})
    result = runner(
        ["sacct", "-j", record.slurm_job_id, "--noheader", "--parsable2", "--format=State"],
        capture_output=True,
        text=True,
        check=False,
    )
    state = (result.stdout or "").strip().split("|", 1)[0].split("+", 1)[0].upper()
    normalized = {
        "PENDING": DFTStatus.QUEUED,
        "CONFIGURING": DFTStatus.QUEUED,
        "RUNNING": DFTStatus.RUNNING,
        "COMPLETED": DFTStatus.COMPLETED,
        "FAILED": DFTStatus.FAILED,
        "CANCELLED": DFTStatus.FAILED,
        "OUT_OF_MEMORY": DFTStatus.FAILED,
        "TIMEOUT": DFTStatus.TIMEOUT,
    }.get(state, DFTStatus.UNKNOWN)
    return record.model_copy(
        update={
            "status": normalized,
            "status_checked_utc": datetime.now(timezone.utc).isoformat(),
            "message": None if result.returncode == 0 else (result.stderr or "sacct failed").strip(),
        }
    )


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "calculation"

