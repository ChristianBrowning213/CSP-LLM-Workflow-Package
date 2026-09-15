from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_startup_doctor_with_realistic_qlip_server_stub(workdir) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[2]
    crystal_cmd = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_crystaldb_server.py').as_posix()}"
    spp_cmd = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_spp_server.py').as_posix()}"
    qlip_script = root / "tests" / "fakes" / "mcp_qlip_server_realistic.py"
    qlip_cmd = f"{sys.executable} -u {qlip_script.as_posix()}"
    cfg = workdir / "startup_realistic_qlip.yaml"
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
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["FAKE_MCP_RESPONSE_ID_STRING"] = "1"
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
    qlip_dep = report["dependencies"]["qlip"]
    assert report["startup_ok"] is True
    assert qlip_dep["semantic_ok"] is True
    assert qlip_dep["probe"]["server_marker_payload_sha256"] == "realistic"
    assert str(qlip_dep["provenance"]["script_path"]) == str(qlip_script.resolve())

