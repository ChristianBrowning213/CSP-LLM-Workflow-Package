"""Dry-run behavior tests for spp.run_pipeline MCP tool."""

from __future__ import annotations

from pathlib import Path

from spp_maker_mcp.contracts import MCPServerConfig
from spp_maker_mcp.server import RuntimeContext, invoke_tool


def test_run_pipeline_dry_run_stays_in_temp_root(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cif_root = (repo_root / "tests" / "fixtures" / "cifs").resolve()

    config = MCPServerConfig(
        allowed_read_roots=[str(cif_root), str(tmp_path.resolve())],
        allowed_write_roots=[str(tmp_path.resolve())],
        max_cif_count=100,
        max_runtime_seconds=600,
        max_output_bytes=100_000_000,
    )
    runtime = RuntimeContext(
        config=config,
        read_roots=(cif_root, tmp_path.resolve()),
        write_roots=(tmp_path.resolve(),),
        repo_root=repo_root.resolve(),
    )

    out_dir = tmp_path / "out"
    response = invoke_tool(
        "spp.run_pipeline",
        {
            "trace_id": "trace_dry_run_test",
            "cif_dir": str(cif_root),
            "out_dir": str(out_dir),
            "name": "dry_run_demo",
            "fit": {"fit_method": "neighbors"},
            "calibration": {"target": 5.0},
            "dry_run": True,
        },
        runtime=runtime,
    )

    assert response["ok"] is True, response
    assert response["error"] is None
    assert response["result"]["dry_run"] is True
    assert response["trace_id"] == "trace_dry_run_test"

    run_root = Path(response["result"]["run_root"])
    final_bundle = Path(response["result"]["final_bundle"])
    log_path = Path(response["result"]["log_path"])

    assert str(run_root).startswith(str(tmp_path.resolve()))
    assert str(final_bundle).startswith(str(tmp_path.resolve()))
    assert str(log_path).startswith(str(tmp_path.resolve()))

    assert not run_root.exists()
    assert not final_bundle.exists()
    assert log_path.is_file()

