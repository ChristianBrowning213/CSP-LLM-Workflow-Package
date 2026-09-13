from __future__ import annotations

import os
from pathlib import Path

import llm_csp
from llm_csp.agentic.models import ActorRole, ToolCall
from llm_csp.agentic.tools import ADAPTER_REGISTRY, ToolDependencies, ToolExecutionContext, execute_tool
from llm_csp.schemas import RetrievalConfig


def test_installed_agentic_tool_surface_and_read_only_execution(tmp_path) -> None:
    if os.environ.get("LLM_CSP_EXPECT_INSTALLED") == "1":
        assert "site-packages" in str(Path(llm_csp.__file__).resolve()).lower()
    assert {name.value for name in ADAPTER_REGISTRY} == {
        "search_crystal_db", "run_csp", "validate_candidate", "inspect_run",
    }
    context = ToolExecutionContext(
        "installed_smoke", str(tmp_path / "agent"),
        retrieval_configs={"fixture": RetrievalConfig(db_path=tmp_path / "fixture.db", embed_engine="hash")},
    )
    call = ToolCall(
        "call", "search_crystal_db", {"query": "fixture", "retrieval_ref": "fixture"}, ActorRole.ORCHESTRATOR,
    )
    execution = execute_tool(
        call,
        context,
        dependencies=ToolDependencies(retrieval=lambda **kwargs: {
            "status": "ok", "query": {"text": kwargs["query_text"]}, "errors": None,
            "backend_status": {"ready": True},
            "neighbors": [{"structure_id": "fixture", "rank": 1, "score": 1.0,
                           "provenance": {"allow_export": 1}}],
        }),
    )
    assert execution.result.status == "retrieval_success"
    assert execution.result.provenance["read_only"] is True
    assert not (tmp_path / "agent").exists()
