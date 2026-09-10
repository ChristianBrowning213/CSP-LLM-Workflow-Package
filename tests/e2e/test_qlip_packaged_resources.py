from __future__ import annotations

import json

from qlip.resources import base_data_root, bundled_spp_root, schema_path


def test_qlip_runtime_resources_are_available_from_the_package() -> None:
    schema = json.loads(schema_path("MCP_SCHEMA.json").read_text(encoding="utf-8"))
    tool_defs = json.loads(schema_path("MCP_TOOL_DEFS.json").read_text(encoding="utf-8"))
    pots = sorted(bundled_spp_root().glob("*/*.POT"))

    assert "solve_request" in schema
    assert any(tool["name"] == "qlip.solve" for tool in tool_defs)
    assert {path.parent.name for path in pots} == {
        "O-O",
        "O-Sr",
        "O-Ti",
        "Sr-Sr",
        "Sr-Ti",
        "Ti-Ti",
    }
    assert (base_data_root() / "provenance.json").is_file()
