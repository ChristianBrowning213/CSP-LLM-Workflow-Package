from __future__ import annotations

import json
import pytest

from qlip.data.registry import default_registry
from qlip.resources import base_data_root, bundled_spp_root, schema_path


def test_qlip_runtime_resources_are_available_from_the_package() -> None:
    schema = json.loads(schema_path("MCP_SCHEMA.json").read_text(encoding="utf-8"))
    tool_defs = json.loads(schema_path("MCP_TOOL_DEFS.json").read_text(encoding="utf-8"))
    assert "solve_request" in schema
    assert any(tool["name"] == "qlip.solve" for tool in tool_defs)
    with pytest.raises(RuntimeError, match="does not distribute scientific POT assets"):
        bundled_spp_root()
    assert not (base_data_root() / "elements.json").exists()
    assert not (base_data_root() / "radii.json").exists()
    assert not (base_data_root() / "ionic_radii.json").exists()
    assert (base_data_root() / "provenance.json").is_file()
    assert len(default_registry().elements()["records"]) == 118
