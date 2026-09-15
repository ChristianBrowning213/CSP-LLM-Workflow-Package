import importlib.util
import json
from pathlib import Path

import pytest


def _load_generator():
    path = Path(__file__).resolve().parents[1] / "tools" / "mcp_generate_examples.py"
    spec = importlib.util.spec_from_file_location("mcp_generate_examples", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_generated_examples_validate_against_tool_schemas():
    generator = _load_generator()
    output_paths = generator.generate_examples()
    assert output_paths

    schemas = generator.load_schemas()
    tool_defs = generator.load_tool_defs()
    store = generator.build_schema_store(schemas)

    for tool_name, output_path in [
        ("qlip.validate_request", Path("examples/mcp/validate_request_uniform_grid.json")),
        (
            "qlip.validate_request",
            Path("examples/mcp/validate_request_explicit_fractional_sites.json"),
        ),
        ("qlip.solve", Path("examples/mcp/solve_uniform_grid.json")),
        ("qlip.solve", Path("examples/mcp/solve_explicit_fractional_sites.json")),
    ]:
        schema = generator.build_tool_schema(tool_name, "inputSchema", schemas, tool_defs)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        errors = generator.validate_payload(payload, schema, store)
        assert errors == []
