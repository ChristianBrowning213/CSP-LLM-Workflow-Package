"""Smoke test for scripts/print_qlip_snippet.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_print_qlip_snippet_contains_root_and_sppcollection() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(src_path) if not existing else f"{src_path}{os.pathsep}{existing}"

    spp_root = "out/demo_prop_spp/demo/spp_all"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/print_qlip_snippet.py",
            "--spp_root",
            spp_root,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=repo_root,
    )
    assert result.returncode == 0, result.stderr
    assert spp_root in result.stdout
    assert "SPPCollection" in result.stdout
