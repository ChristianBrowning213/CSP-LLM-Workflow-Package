from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_startup_blocks_if_configured_qlip_server_missing(workdir) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[2]
    missing_script = workdir / "missing_qlip_server.py"
    crystal = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_crystaldb_server.py').as_posix()}"
    spp = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_spp_server.py').as_posix()}"
    qlip = f"{sys.executable} -u {missing_script.as_posix()}"
    config_path = workdir / "configured_live_missing_qlip.yaml"
    config_path.write_text(
        "\n".join(
            [
                "workspace_root: .sokllm_workspace",
                f"crystaldb_mcp_cmd: {crystal}",
                f"spp_mcp_cmd: {spp}",
                f"qlip_mcp_cmd: {qlip}",
                f"qlip_mcp_cwd: {root.as_posix()}",
                "qlip_allow_repo_shim: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--config",
            str(config_path),
            "--workspace",
            str(workdir),
            "doctor",
            "startup",
            "--mode",
            "live",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    report = json.loads((workdir / "startup" / "startup_report.json").read_text(encoding="utf-8"))
    qlip_dep = report["dependencies"]["qlip"]
    assert report["startup_ok"] is False
    assert qlip_dep["failure_code"] == "QLIP_STARTUP_FAILED"

