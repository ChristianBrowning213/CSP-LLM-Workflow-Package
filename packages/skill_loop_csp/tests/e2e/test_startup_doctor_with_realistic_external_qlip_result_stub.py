from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_startup_doctor_with_realistic_external_qlip_result_stub(workdir) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["FAKE_QLIP_EXT_SHAPE_MODE"] = "valid"
    crystal_cmd = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_crystaldb_server.py').as_posix()}"
    spp_cmd = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_spp_server.py').as_posix()}"
    qlip_cmd = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_qlip_server_external_shape.py').as_posix()}"
    cfg = workdir / "startup_external_qlip.yaml"
    cfg.write_text(
        "\n".join(
            [
                "workspace_root: .sokllm_workspace",
                f"crystaldb_mcp_cmd: {crystal_cmd}",
                f"spp_mcp_cmd: {spp_cmd}",
                f"qlip_mcp_cmd: {qlip_cmd}",
                f"qlip_mcp_cwd: {root.as_posix()}",
                "qlip_allow_repo_shim: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "sok_llm_orchestrator.cli",
            "--config",
            str(cfg),
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
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    report = json.loads((workdir / "startup" / "startup_report.json").read_text(encoding="utf-8"))
    qlip = report["dependencies"]["qlip"]
    assert report["startup_ok"] is True
    assert qlip["semantic_ok"] is True
    assert qlip["probe"]["cif_source_a"] == "inline"

