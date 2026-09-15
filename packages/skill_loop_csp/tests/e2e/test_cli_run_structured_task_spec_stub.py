from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_cli_run_structured_task_spec_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    task_spec_path = workdir / "task_spec.yaml"
    task_spec_path.write_text(
        "query_text: TiO2 structured cli case\n"
        "composition_target: TiO2\n"
        "solve_mode: feasibility\n"
        "symmetry_request:\n"
        "  space_group: null\n"
        "  hardness: none\n"
        "qlip_objective: qlip.objective.energy_proxy\n",
        encoding="utf-8",
    )

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
            "--task-spec-file",
            str(task_spec_path),
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
    request = json.loads((run_dir / "artifacts" / "qlip_request.json").read_text(encoding="utf-8"))
    task_spec = json.loads((run_dir / "artifacts" / "task_spec.json").read_text(encoding="utf-8"))
    assert task_spec["qlip_objective"] == {"type": "spp_energy"}
    assert request["problem"]["objective"] == {"type": "spp_energy"}
