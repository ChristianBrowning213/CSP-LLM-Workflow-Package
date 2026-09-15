from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sok_llm_orchestrator.optimization.action_registry import list_registered_actions


pytestmark = pytest.mark.live_e2e


def _require_live_env() -> None:
    if os.environ.get("RUN_LIVE_E2E_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_E2E_TESTS=1 to run live e2e tests.")
    required = [
        "LLM_BASE_URL",
        "LLM_MODEL",
        "CRYSTALDB_MCP_CMD",
        "SPP_MCP_CMD",
        "QLIP_MCP_CMD",
    ]
    for key in required:
        if not os.environ.get(key):
            pytest.skip(f"Missing {key} for live optimization smoke.")
    if not os.environ.get("LLM_API_KEY") and "localhost" not in os.environ.get("LLM_BASE_URL", ""):
        pytest.skip("Missing LLM_API_KEY for non-local LLM base URL.")


def test_optimization_session_live_smoke(workdir: Path) -> None:
    _require_live_env()
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")

    cfg = workdir / "live_opt_smoke.yaml"
    cfg.write_text(
        "\n".join(
            [
                f"llm_base_url: {os.environ['LLM_BASE_URL']}",
                f"llm_model: {os.environ['LLM_MODEL']}",
                f"llm_api_key: {os.environ.get('LLM_API_KEY', '')}",
                f"crystaldb_mcp_cmd: {os.environ['CRYSTALDB_MCP_CMD']}",
                f"spp_mcp_cmd: {os.environ['SPP_MCP_CMD']}",
                f"qlip_mcp_cmd: {os.environ['QLIP_MCP_CMD']}",
                "optimization_max_iterations: 2",
                "optimization_max_solver_calls: 2",
                "optimization_max_retrieval_calls: 2",
                "optimization_max_failed_iterations: 2",
                "optimization_stagnation_window: 2",
                "optimization_exploration_rate: 0.0",
                "optimization_allow_midloop_clarification: false",
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
            "optimize",
            "start",
            "--mode",
            "live",
            "--query",
            os.environ.get("LIVE_OPT_QUERY", "TiO2 optimize high property x"),
            "--max-iterations",
            "2",
            "--exploration-rate",
            "0.0",
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr

    session_path = Path(proc.stdout.strip().splitlines()[-1])
    session = json.loads(session_path.read_text(encoding="utf-8"))
    assert session["optimization_plan"] is not None
    assert len(session["iteration_history"]) >= 2
    assert session["best_so_far"] is not None

    legal_ids = {item.action_id for item in list_registered_actions()}
    assert all(item["action_id"] in legal_ids for item in session["iteration_history"])

    session_dir = session_path.parent
    iterations_dir = session_dir / "iterations"
    assert iterations_dir.exists()
    assert len(list(iterations_dir.glob("*.json"))) >= 2

    report_path = session_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["session_id"] == session["session_id"]
    assert report["best_so_far"] is not None
    assert report["iteration_count"] >= 2

