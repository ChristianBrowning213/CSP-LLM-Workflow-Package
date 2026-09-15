from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_cli_run_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["FAKE_CRYSTAL_ALLOW_EXPORT"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--workspace",
            str(workdir),
            "run",
            "--mode",
            "stub",
            "--query",
            "TiO2 rutile-like",
            "--with-spp",
            "true",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
    run_dir = Path(proc.stdout.strip().splitlines()[-1])
    assert (run_dir / "manifest.json").exists()
