from __future__ import annotations

import sys
from pathlib import Path

from sok_llm_orchestrator.mcp.stdio_client import StdioMCPClient


def test_mcp_client_lists_and_calls() -> None:
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_crystaldb_server.py")]
    with StdioMCPClient(cmd, cwd=str(root)) as client:
        tools = client.list_tools()
        assert "crystal.csp_pack" in tools
        response = client.call_tool("crystal.text_search", {"query": "rutile", "k": 1})
        assert response["schema_version"] == "text_search.v1"
