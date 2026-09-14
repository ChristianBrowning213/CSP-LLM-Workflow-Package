"""MCP tool tests for spp.publish_to_qlip_outputs."""

from __future__ import annotations

import json
from pathlib import Path

from spp_maker_mcp.contracts import MCPServerConfig
from spp_maker_mcp.server import RuntimeContext, invoke_tool


def test_publish_to_qlip_outputs_updates_index_and_latest(tmp_path: Path, spp_root: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    qlip_outputs = tmp_path / "QLIP_Outputs"
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
        "spp.publish_to_qlip_outputs",
        {
            "kind": "spp",
            "artifact_root": str(spp_root),
            "qlip_outputs_path": str(qlip_outputs),
            "name": "pub_demo",
            "overwrite": False,
        },
        runtime=runtime,
    )
    assert response["ok"] is True, response
    result = response["result"]

    index_path = Path(result["index_json_path"])
    latest_path = Path(result["latest_pointer_path"])
    published_path = Path(result["published_path"])
    assert index_path.is_file()
    assert latest_path.is_file()
    assert published_path.is_dir()

    index_obj = json.loads(index_path.read_text(encoding="utf-8"))
    run_ids = [row["run_id"] for row in index_obj["artifacts"]["spp"]["runs"]]
    assert result["published_run_id"] in run_ids
    assert latest_path.read_text(encoding="utf-8").strip() == result["latest_pointer_value"]

