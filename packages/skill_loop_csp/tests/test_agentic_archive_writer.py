from __future__ import annotations

import ast
from contextlib import contextmanager
import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic import (
    redact_trace_for_display,
    run_placeholder_agentic_cycle_record,
    run_agent_and_archive_trace,
    write_agentic_llm_trace_markdown,
    write_agentic_llm_trace,
    write_agentic_run_record,
)
from sok_llm_orchestrator.agentic.archive import (
    AGENT_TRACE_ARCHIVE_RUN_SCHEMA_VERSION,
    ARCHIVE_WRITE_SCHEMA_VERSION,
    LLM_TRACE_MARKDOWN_WRITE_SCHEMA_VERSION,
    LLM_TRACE_WRITE_SCHEMA_VERSION,
)
import sok_llm_orchestrator.agentic.archive as archive_module


@contextmanager
def _repo_local_tempdir() -> Path:
    parent = Path.cwd() / "test_workdir" / "agentic_pytest_tmp"
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"case_{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def test_archive_writer_creates_expected_plain_files_and_round_trips_json() -> None:
    run_record = run_placeholder_agentic_cycle_record(
        {
            "overall_goal": "Improve benchmark performance.",
            "run_goal": "Prepare archive-ready outputs.",
            "stage": "wide_exploration",
            "run_id": "run_101",
        }
    )

    with _repo_local_tempdir() as root:
        out = write_agentic_run_record(run_record, root)
        names = sorted(path.name for path in root.iterdir())

        assert names == ["agentic_run_record.json", "agentic_run_summary.md"]
        assert out["schema_version"] == ARCHIVE_WRITE_SCHEMA_VERSION
        assert out["run_id"] == "run_101"
        round_tripped = json.loads(Path(out["record_json_path"]).read_text(encoding="utf-8"))
        assert round_tripped == run_record
        assert round_tripped["tool_validation_results"][0]["valid"] is True
        assert round_tripped["tool_validation_summary"]["proposal_count"] == 1
        assert round_tripped["proposal_readiness"]["status"] == "all_valid"
        assert Path(out["summary_markdown_path"]).exists()
        assert json.loads(json.dumps(out))["schema_version"] == ARCHIVE_WRITE_SCHEMA_VERSION


def test_archive_writer_skips_markdown_when_disabled() -> None:
    run_record = run_placeholder_agentic_cycle_record(
        {
            "overall_goal": "test",
            "run_goal": "test",
            "stage": "wide_exploration",
            "run_id": "run_102",
        }
    )

    with _repo_local_tempdir() as root:
        out = write_agentic_run_record(run_record, root, write_markdown=False)
        names = sorted(path.name for path in root.iterdir())

        assert names == ["agentic_run_record.json"]
        assert out["summary_markdown_path"] is None
        assert out["artifact_paths"] == [str(root / "agentic_run_record.json")]


def test_archive_writer_summary_is_paper_archive_friendly() -> None:
    run_record = run_placeholder_agentic_cycle_record(
        {
            "overall_goal": "Summarize final decision.",
            "run_goal": "Write a paper-friendly record.",
            "stage": "wide_exploration",
            "run_id": "run_103",
        }
    )

    with _repo_local_tempdir() as root:
        out = write_agentic_run_record(run_record, root)
        summary = Path(out["summary_markdown_path"]).read_text(encoding="utf-8")

        assert "run_103" in summary
        assert "Summarize final decision." in summary
        assert "Write a paper-friendly record." in summary
        assert "wide_exploration" in summary
        assert "planner, run_manager, evaluator, orchestrator" in summary
        assert "Decision: continue" in summary
        assert "## Proposal Audit" in summary
        assert "- proposals: 1" in summary
        assert "- valid: 1" in summary
        assert "- invalid: 0" in summary
        assert "- warnings: 0" in summary
        assert "## Proposal Readiness" in summary
        assert "- status: all_valid" in summary
        assert "- can execute later: true" in summary
        assert "- reason: All validated tool proposals are ready for a future execution layer." in summary
        assert "## Tool Validation" in summary
        assert "crystal.csp_pack" in summary
        assert "valid" in summary


def test_archive_writer_summary_includes_invalid_tool_validation_details() -> None:
    run_record = run_placeholder_agentic_cycle_record(
        {
            "overall_goal": "Show validation failures.",
            "run_goal": "Render invalid proposal state.",
            "stage": "wide_exploration",
            "run_id": "run_103b",
        }
    )
    run_record["tool_validation_results"] = [
        {
            "schema_version": "agentic_csp.tool_validation.v1",
            "valid": False,
            "tool_name": "unknown.tool",
            "errors": ["Missing required argument: case_id"],
            "warnings": [],
        }
    ]
    run_record["tool_validation_summary"] = {
        "proposal_count": 1,
        "valid_count": 0,
        "invalid_count": 1,
        "warning_count": 0,
        "valid_tool_names": [],
        "invalid_tool_names": ["unknown.tool"],
    }
    run_record["proposal_readiness"] = {
        "schema_version": "agentic_csp.proposal_readiness.v1",
        "status": "has_invalid",
        "reason": "One or more validated tool proposals are invalid.",
        "can_execute_later": False,
    }

    with _repo_local_tempdir() as root:
        out = write_agentic_run_record(run_record, root)
        summary = Path(out["summary_markdown_path"]).read_text(encoding="utf-8")
        round_tripped = json.loads(Path(out["record_json_path"]).read_text(encoding="utf-8"))

        assert "## Proposal Audit" in summary
        assert "- proposals: 1" in summary
        assert "- valid: 0" in summary
        assert "- invalid: 1" in summary
        assert "- warnings: 0" in summary
        assert "## Proposal Readiness" in summary
        assert "- status: has_invalid" in summary
        assert "- can execute later: false" in summary
        assert "- reason: One or more validated tool proposals are invalid." in summary
        assert "## Tool Validation" in summary
        assert "unknown.tool" in summary
        assert "invalid" in summary
        assert "Missing required argument: case_id" in summary
        assert round_tripped == run_record


def test_archive_writer_creates_no_hidden_or_sqlite_files_and_runtime_stays_in_memory() -> None:
    with _repo_local_tempdir() as root:
        run_record = run_placeholder_agentic_cycle_record(
            {
                "overall_goal": "Keep runtime pure.",
                "run_goal": "Write only through the archive layer.",
                "stage": "wide_exploration",
                "run_id": "run_104",
            }
        )
        assert list(root.iterdir()) == []

        _ = write_agentic_run_record(run_record, root)
        names = sorted(path.name for path in root.iterdir())

        assert all(not name.startswith(".") for name in names)
        assert all(not name.endswith(".db") for name in names)
        assert all(not name.endswith(".sqlite") for name in names)


def test_archive_writer_writes_llm_trace_json_and_round_trips_exactly() -> None:
    trace = {
        "agent_name": "planner",
        "runtime_context": {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "gpt-oss:20b",
        },
        "system_prompt": "Return JSON only.",
        "user_payload": {"input_payload": {"overall_goal": "TiO2"}},
        "parsed_output": {
            "schema_version": "agentic_csp.run_plan.v1",
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
            "plan_as_text": "tool_hint: crystal.csp_pack",
        },
        "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
        "attempts": [
            {
                "attempt_number": 1,
                "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
                "validation_errors": [],
            }
        ],
        "validation_errors": [],
    }

    with _repo_local_tempdir() as root:
        out = write_agentic_llm_trace(trace, root, "planner")
        names = sorted(path.name for path in root.iterdir())

        assert names == ["agentic_llm_trace_planner.json"]
        assert out["schema_version"] == LLM_TRACE_WRITE_SCHEMA_VERSION
        assert out["agent_name"] == "planner"
        assert out["artifact_paths"] == [str(root / "agentic_llm_trace_planner.json")]
        round_tripped = json.loads(Path(out["trace_json_path"]).read_text(encoding="utf-8"))
        assert round_tripped == trace
        assert json.loads(json.dumps(out))["schema_version"] == LLM_TRACE_WRITE_SCHEMA_VERSION


def test_archive_writer_writes_llm_trace_markdown_with_redaction() -> None:
    trace = {
        "agent_name": "planner",
        "runtime_context": {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "gpt-oss:20b",
            "api_key": "ollama-secret",
        },
        "system_prompt": "Return JSON only.",
        "user_payload": {
            "input_payload": {"overall_goal": "TiO2"},
            "api_key": "super-secret-key",
        },
        "parsed_output": {
            "schema_version": "agentic_csp.run_plan.v1",
            "overall_goal": "TiO2",
        },
        "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
        "attempts": [
            {
                "attempt_number": 1,
                "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
                "validation_errors": [],
            }
        ],
        "validation_errors": [],
    }

    with _repo_local_tempdir() as root:
        out = write_agentic_llm_trace_markdown(trace, root, "planner")
        markdown_path = Path(out["markdown_path"])
        markdown = markdown_path.read_text(encoding="utf-8")
        names = sorted(path.name for path in root.iterdir())

        assert names == ["agentic_llm_trace_planner.md"]
        assert out["schema_version"] == LLM_TRACE_MARKDOWN_WRITE_SCHEMA_VERSION
        assert markdown_path.exists()
        assert "gpt-oss:20b" in markdown
        assert "http://127.0.0.1:11434/v1" in markdown
        assert "[REDACTED]" in markdown
        assert "super-secret-key" not in markdown
        assert "ollama-secret" not in markdown
        assert json.loads(json.dumps(out))["schema_version"] == LLM_TRACE_MARKDOWN_WRITE_SCHEMA_VERSION


def test_trace_redaction_replaces_api_key_like_values() -> None:
    redacted = redact_trace_for_display(
        {
            "runtime_context": {
                "base_url": "http://127.0.0.1:11434/v1",
                "api_key": "ollama-secret",
            },
            "user_payload": {
                "token": "abc123",
                "nested": {"authorization": "Bearer value"},
            },
        }
    )

    assert redacted["runtime_context"]["api_key"] == "[REDACTED]"
    assert redacted["user_payload"]["token"] == "[REDACTED]"
    assert redacted["user_payload"]["nested"]["authorization"] == "[REDACTED]"


def test_run_agent_and_archive_trace_calls_runtime_and_round_trips_trace() -> None:
    class _FakeRuntime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], str]] = []

        def run_agent(
            self,
            agent_name: str,
            input_payload,
            expected_schema_name: str,
        ):  # type: ignore[no-untyped-def]
            self.calls.append((agent_name, dict(input_payload), expected_schema_name))
            return {
                "agent_name": "planner",
                "runtime_context": {
                    "base_url": "http://127.0.0.1:11434/v1",
                    "model": "gpt-oss:20b",
                },
                "system_prompt": "Return JSON only.",
                "user_payload": {"input_payload": dict(input_payload)},
                "parsed_output": {
                    "schema_version": "agentic_csp.run_plan.v1",
                    "overall_goal": "TiO2",
                    "run_goal": "retrieve candidates",
                    "stage": "wide_exploration",
                    "plan_as_text": "tool_hint: crystal.csp_pack",
                },
                "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
                "attempts": [
                    {
                        "attempt_number": 1,
                        "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
                        "validation_errors": [],
                    }
                ],
                "validation_errors": [],
            }

    runtime = _FakeRuntime()
    input_payload = {
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
    }

    with _repo_local_tempdir() as root:
        out = run_agent_and_archive_trace(
            runtime,
            "planner",
            input_payload,
            "run_plan",
            root,
        )
        trace_json = json.loads((root / "agentic_llm_trace_planner.json").read_text(encoding="utf-8"))

        assert out["schema_version"] == AGENT_TRACE_ARCHIVE_RUN_SCHEMA_VERSION
        assert out["agent_name"] == "planner"
        assert out["parsed_output"]["schema_version"] == "agentic_csp.run_plan.v1"
        assert out["trace_write"]["schema_version"] == LLM_TRACE_WRITE_SCHEMA_VERSION
        assert runtime.calls == [("planner", input_payload, "run_plan")]
        assert trace_json["parsed_output"] == out["parsed_output"]
        assert trace_json["raw_output"] == "{\"schema_version\":\"agentic_csp.run_plan.v1\"}"


def test_archive_module_has_no_sqlite_or_pipeline_imports() -> None:
    source = Path(archive_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module.split(".")[0])

    assert "sqlite3" not in imported_modules
    assert "sqlalchemy" not in imported_modules
    assert "pipeline" not in imported_modules


def test_archive_writer_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    run_record = run_placeholder_agentic_cycle_record(
        {
            "overall_goal": "pipeline isolation",
            "run_goal": "pipeline isolation",
            "stage": "wide_exploration",
            "run_id": "run_105",
        }
    )
    with _repo_local_tempdir() as root:
        _ = write_agentic_run_record(run_record, root)
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
