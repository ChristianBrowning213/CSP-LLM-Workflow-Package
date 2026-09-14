"""MCP tool tests for spp.check_compat."""

from __future__ import annotations

from pathlib import Path

from spp_maker_mcp.contracts import MCPServerConfig
from spp_maker_mcp.server import RuntimeContext, invoke_tool


def test_check_compat_tool_on_fixture_spp_root(tmp_path: Path, spp_root: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config = MCPServerConfig(
        allowed_read_roots=[str(spp_root.resolve()), str(tmp_path.resolve())],
        allowed_write_roots=[str(tmp_path.resolve())],
        max_cif_count=100,
        max_runtime_seconds=600,
        max_output_bytes=100_000_000,
    )
    runtime = RuntimeContext(
        config=config,
        read_roots=(spp_root.resolve(), tmp_path.resolve()),
        write_roots=(tmp_path.resolve(),),
        repo_root=repo_root.resolve(),
    )

    response = invoke_tool(
        "spp.check_compat",
        {"spp_root": str(spp_root), "strict": True},
        runtime=runtime,
    )
    assert response["ok"] is True, response
    assert response["error"] is None
    assert response["result"]["ok"] is True
    assert int(response["result"]["files_checked"]) > 0
    assert int(response["result"]["failed_count"]) == 0

