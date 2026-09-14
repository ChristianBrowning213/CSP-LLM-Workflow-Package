"""Schema stability tests for MCP tool contracts."""

from __future__ import annotations

import json
from pathlib import Path

from spp_maker_mcp import server


def test_tool_schemas_snapshot_stable() -> None:
    schemas = server.get_tool_schemas()
    assert sorted(schemas.keys()) == [
        "spp.check_compat",
        "spp.package_for_qlip",
        "spp.publish_to_qlip_outputs",
        "spp.run_pipeline",
    ]

    snapshot_path = Path(__file__).resolve().parent / "snapshots" / "tool_schemas.json"
    expected = snapshot_path.read_text(encoding="utf-8")
    observed = json.dumps(schemas, sort_keys=True, indent=2) + "\n"
    assert observed == expected

