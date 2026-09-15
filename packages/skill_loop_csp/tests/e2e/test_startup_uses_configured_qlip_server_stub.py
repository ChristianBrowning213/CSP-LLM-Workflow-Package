from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _write_live_stub_config(config_path: Path, root: Path, qlip_cmd: str) -> None:
    crystal = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_crystaldb_server.py').as_posix()}"
    spp = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_spp_server.py').as_posix()}"
    config_path.write_text(
        "\n".join(
            [
                "workspace_root: .sokllm_workspace",
                f"crystaldb_mcp_cmd: {crystal}",
                f"spp_mcp_cmd: {spp}",
                f"qlip_mcp_cmd: {qlip_cmd}",
                f"qlip_mcp_cwd: {root.as_posix()}",
                "qlip_allow_repo_shim: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_startup_uses_configured_qlip_server_stub(workdir) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[2]
    config_path = workdir / "configured_live_stub.yaml"
    qlip_script = root / "tests" / "fakes" / "mcp_qlip_server.py"
    _write_live_stub_config(config_path, root, f"{sys.executable} -u {qlip_script.as_posix()}")

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
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    report = json.loads((workdir / "startup" / "startup_report.json").read_text(encoding="utf-8"))
    qlip_dep = report["dependencies"]["qlip"]
    qlip_probe = qlip_dep["probe"]
    provenance = qlip_dep["provenance"]
    assert report["startup_ok"] is True
    assert str(provenance.get("script_path")) == str(qlip_script.resolve())
    assert bool(provenance.get("is_repo_qlip_shim")) is False
    assert qlip_probe.get("server_marker_payload_sha256") == "stub"
    assert "runs\\shim" not in str(qlip_probe.get("cif_path_a", ""))

