from crystal_db.mcp import server


def test_mcp_exposes_complete_source_runtime_tools():
    assert set(server.TOOL_REGISTRY) == {
        "crystal.text_search",
        "crystal.agent",
        "crystal.novelty_check",
        "crystal.csp_pack",
        "crystal.status",
        "crystal.bench_retrieval",
    }
    defaults = server.load_config(None)
    assert defaults["model"] == "text-embedding-bge-m3"
    assert defaults["model_version"] == "lmstudio_v1"
    assert "db_path" not in defaults


def test_mcp_policy_mode_controls_demo_export(monkeypatch):
    monkeypatch.setenv("CRYSTALDB_POLICY_MODE", "safe")
    assert server._resolve_common_settings({"demo_export": True}, {})["demo_export"] is False
    monkeypatch.setenv("CRYSTALDB_POLICY_MODE", "demo")
    assert server._resolve_common_settings({"demo_export": True}, {})["demo_export"] is True


def test_mcp_missing_database_is_a_structured_tool_error(tmp_path):
    arguments = {
        "db_path": str(tmp_path / "missing.db"), "query": "probe", "k": 2,
        "embed_engine": "hash", "model": "hash-embed", "model_version": "v1",
        "text_engine": "caption", "text_view": "caption",
    }
    try:
        server.execute_tool("crystal.text_search", arguments)
    except server.ToolExecutionError as exc:
        assert exc.code == "missing_db"
        assert exc.payload["errors"]["code"] == "missing_db"
    else:
        raise AssertionError("missing database must not be reported as a successful search")
