"""Minimal agentic runtime interfaces for future in-repo experiment loops."""

from .agents import (
    SCHEMA_VERSION,
    Agent,
    EvaluatorAgent,
    OrchestratorAgent,
    PlannerAgent,
    RunManagerAgent,
)
from .schemas import (
    AGENT_INPUT_SCHEMA_VERSION,
    RUN_RECORD_SCHEMA_VERSION,
    ORCHESTRATOR_DECISION_SCHEMA_VERSION,
    RUN_EVALUATION_SCHEMA_VERSION,
    RUN_MANAGER_LOG_SCHEMA_VERSION,
    RUN_PLAN_SCHEMA_VERSION,
    TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
    AgentInputEnvelope,
    AgenticRunRecord,
    OrchestratorDecision,
    RunEvaluation,
    RunManagerLog,
    RunPlan,
    ToolCallProposal,
    assert_json_serializable,
    to_json_dict,
)
from .runtime import (
    PROPOSAL_READINESS_SCHEMA_VERSION,
    RUNTIME_CYCLE_SCHEMA_VERSION,
    AgenticRuntime,
    build_run_record,
    classify_proposal_readiness,
    run_placeholder_agentic_cycle,
    run_placeholder_agentic_cycle_record,
    summarize_tool_validation_results,
)
from .archive import (
    AGENT_TRACE_ARCHIVE_RUN_SCHEMA_VERSION,
    ARCHIVE_WRITE_SCHEMA_VERSION,
    LLM_TRACE_WRITE_SCHEMA_VERSION,
    AgenticArchiveWriter,
    run_agent_and_archive_trace,
    write_agentic_llm_trace_markdown,
    write_agentic_llm_trace,
    write_agentic_run_record,
)
from .prompting import (
    PROMPT_FILE_BY_AGENT,
    load_agent_prompt,
    prompt_dir,
    prompt_path_for_agent,
    render_agent_prompt,
)
from .llm_runtime import (
    SCHEMA_NAME_BY_AGENT,
    SCHEMA_VERSION_BY_NAME,
    AgentLLMRuntime,
)
from .planner_runtime import (
    PLANNER_COMPILE_RUN_SCHEMA_VERSION,
    RUN_PLAN_REQUIRED_FIELDS,
    run_live_planner,
    run_live_planner_and_compile,
)
from .plan_compile import (
    PLAN_COMPILE_SCHEMA_VERSION,
    TOOL_PARSE_REPORT_SCHEMA_VERSION,
    build_tool_parse_report,
    compile_run_plan_to_tool_proposals,
)
from .execution_plan_adapter import (
    EXECUTABLE_PLAN_REPORT_SCHEMA_VERSION,
    EXECUTABLE_PLAN_SCHEMA_VERSION,
    build_executable_plan_from_compile_result,
    build_executable_plan_report,
)
from .tool_execution_adapters import (
    TOOL_EXECUTION_RESULT_SCHEMA_VERSION,
    get_default_tool_execution_adapters,
)
from .gated_executor import (
    EXECUTION_RUN_SCHEMA_VERSION,
    execute_executable_plan,
    resolve_step_placeholders,
)
from .execution_report import (
    EXECUTION_LOOP_REPORT_SCHEMA_VERSION,
    EXECUTION_LOOP_REPORT_WRITE_SCHEMA_VERSION,
    build_execution_loop_report,
    write_execution_loop_report,
)
from .sequence_diagram import build_demo_loop_mermaid_sequence
from .demo_bundle import (
    DEMO_SHOWCASE_BUNDLE_SCHEMA_VERSION,
    write_demo_showcase_bundle,
)
from .evaluator_runtime import (
    RUN_EVALUATION_REQUIRED_FIELDS,
    run_live_evaluator,
)
from .orchestrator_runtime import (
    ORCHESTRATOR_DECISION_REQUIRED_FIELDS,
    run_live_orchestrator,
)
from .chain_runtime import (
    FULL_LIVE_AGENT_CHAIN_ROUTE_MODE,
    PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION,
    run_live_proposal_review_chain,
)
from .chain_fixtures import (
    CHAIN_FIXTURE_SCHEMA_VERSION,
    C_LAYER_REPLAY_SCHEMA_VERSION,
    assert_chain_fixture_ready_for_c_layer,
    build_c_layer_replay_report,
    load_chain_fixture,
    replay_c_layer_from_fixture,
    write_chain_fixture,
)
from .execution_intent import (
    EXECUTION_INTENT_SCHEMA_VERSION,
    build_execution_intent,
)
from .execution_handoff import (
    DEFAULT_PREFLIGHT_REQUIREMENTS,
    EXECUTION_HANDOFF_SCHEMA_VERSION,
    build_execution_handoff,
)
from .executor_preflight import (
    EXECUTOR_PREFLIGHT_SCHEMA_VERSION,
    build_executor_preflight,
)
from .noop_executor import (
    NOOP_EXECUTION_REPORT_SCHEMA_VERSION,
    build_noop_execution_report,
)
from .failure_handling import (
    FAILURE_HANDLING_SCHEMA_VERSION,
    handle_inspection_failures,
)
from .manager_logging import (
    MANAGER_NOTES_SCHEMA_VERSION,
    MANAGER_REPLAY_ARTIFACTS_SCHEMA_VERSION,
    TOOL_CALL_LOG_ROW_SCHEMA_VERSION,
    build_manager_notes,
    build_tool_call_log_rows,
    write_manager_replay_artifacts,
)
from .partial_success import (
    CONTINUATION_SUMMARY_SCHEMA_VERSION,
    PARTIAL_SUCCESS_SCHEMA_VERSION,
    build_continuation_summary,
    build_partial_success_evaluation,
)
from .step_execution import (
    NOOP_STEP_EXECUTION_SCHEMA_VERSION,
    STEP_EXECUTION_PLAN_SCHEMA_VERSION,
    build_step_execution_plan,
    run_noop_step_execution,
)
from .result_inspection import (
    RESULT_INSPECTION_SCHEMA_VERSION,
    inspect_step_results,
)
from .run_manager_runtime import (
    RUN_MANAGER_LOG_REQUIRED_FIELDS,
    run_live_run_manager,
)
from .tools import (
    TOOL_VALIDATION_SCHEMA_VERSION,
    AgenticToolRegistry,
    ToolSpec,
    default_agentic_tool_registry,
)
from .trace_render import (
    LLM_TRACE_MARKDOWN_WRITE_SCHEMA_VERSION,
    redact_trace_for_display,
    render_agentic_llm_trace_markdown,
)

__all__ = [
    "SCHEMA_VERSION",
    "Agent",
    "PlannerAgent",
    "RunManagerAgent",
    "EvaluatorAgent",
    "OrchestratorAgent",
    "AGENT_INPUT_SCHEMA_VERSION",
    "RUN_PLAN_SCHEMA_VERSION",
    "TOOL_CALL_PROPOSAL_SCHEMA_VERSION",
    "RUN_MANAGER_LOG_SCHEMA_VERSION",
    "RUN_EVALUATION_SCHEMA_VERSION",
    "ORCHESTRATOR_DECISION_SCHEMA_VERSION",
    "RUN_RECORD_SCHEMA_VERSION",
    "AgentInputEnvelope",
    "AgenticRunRecord",
    "RunPlan",
    "ToolCallProposal",
    "RunManagerLog",
    "RunEvaluation",
    "OrchestratorDecision",
    "to_json_dict",
    "assert_json_serializable",
    "PROPOSAL_READINESS_SCHEMA_VERSION",
    "RUNTIME_CYCLE_SCHEMA_VERSION",
    "AgenticRuntime",
    "build_run_record",
    "classify_proposal_readiness",
    "run_placeholder_agentic_cycle",
    "run_placeholder_agentic_cycle_record",
    "summarize_tool_validation_results",
    "AGENT_TRACE_ARCHIVE_RUN_SCHEMA_VERSION",
    "ARCHIVE_WRITE_SCHEMA_VERSION",
    "LLM_TRACE_WRITE_SCHEMA_VERSION",
    "LLM_TRACE_MARKDOWN_WRITE_SCHEMA_VERSION",
    "AgenticArchiveWriter",
    "run_agent_and_archive_trace",
    "write_agentic_llm_trace_markdown",
    "write_agentic_llm_trace",
    "write_agentic_run_record",
    "PROMPT_FILE_BY_AGENT",
    "prompt_dir",
    "prompt_path_for_agent",
    "load_agent_prompt",
    "render_agent_prompt",
    "SCHEMA_NAME_BY_AGENT",
    "SCHEMA_VERSION_BY_NAME",
    "AgentLLMRuntime",
    "PLANNER_COMPILE_RUN_SCHEMA_VERSION",
    "PLAN_COMPILE_SCHEMA_VERSION",
    "TOOL_PARSE_REPORT_SCHEMA_VERSION",
    "RUN_PLAN_REQUIRED_FIELDS",
    "compile_run_plan_to_tool_proposals",
    "build_tool_parse_report",
    "EXECUTABLE_PLAN_SCHEMA_VERSION",
    "EXECUTABLE_PLAN_REPORT_SCHEMA_VERSION",
    "build_executable_plan_from_compile_result",
    "build_executable_plan_report",
    "TOOL_EXECUTION_RESULT_SCHEMA_VERSION",
    "get_default_tool_execution_adapters",
    "EXECUTION_RUN_SCHEMA_VERSION",
    "execute_executable_plan",
    "resolve_step_placeholders",
    "EXECUTION_LOOP_REPORT_SCHEMA_VERSION",
    "EXECUTION_LOOP_REPORT_WRITE_SCHEMA_VERSION",
    "build_execution_loop_report",
    "write_execution_loop_report",
    "build_demo_loop_mermaid_sequence",
    "DEMO_SHOWCASE_BUNDLE_SCHEMA_VERSION",
    "write_demo_showcase_bundle",
    "run_live_planner",
    "run_live_planner_and_compile",
    "RUN_EVALUATION_REQUIRED_FIELDS",
    "run_live_evaluator",
    "ORCHESTRATOR_DECISION_REQUIRED_FIELDS",
    "run_live_orchestrator",
    "FULL_LIVE_AGENT_CHAIN_ROUTE_MODE",
    "PROPOSAL_REVIEW_CHAIN_SCHEMA_VERSION",
    "run_live_proposal_review_chain",
    "CHAIN_FIXTURE_SCHEMA_VERSION",
    "C_LAYER_REPLAY_SCHEMA_VERSION",
    "assert_chain_fixture_ready_for_c_layer",
    "build_c_layer_replay_report",
    "write_chain_fixture",
    "load_chain_fixture",
    "replay_c_layer_from_fixture",
    "EXECUTION_INTENT_SCHEMA_VERSION",
    "build_execution_intent",
    "EXECUTION_HANDOFF_SCHEMA_VERSION",
    "DEFAULT_PREFLIGHT_REQUIREMENTS",
    "build_execution_handoff",
    "EXECUTOR_PREFLIGHT_SCHEMA_VERSION",
    "build_executor_preflight",
    "NOOP_EXECUTION_REPORT_SCHEMA_VERSION",
    "build_noop_execution_report",
    "FAILURE_HANDLING_SCHEMA_VERSION",
    "handle_inspection_failures",
    "MANAGER_NOTES_SCHEMA_VERSION",
    "TOOL_CALL_LOG_ROW_SCHEMA_VERSION",
    "MANAGER_REPLAY_ARTIFACTS_SCHEMA_VERSION",
    "build_manager_notes",
    "build_tool_call_log_rows",
    "write_manager_replay_artifacts",
    "PARTIAL_SUCCESS_SCHEMA_VERSION",
    "CONTINUATION_SUMMARY_SCHEMA_VERSION",
    "build_partial_success_evaluation",
    "build_continuation_summary",
    "STEP_EXECUTION_PLAN_SCHEMA_VERSION",
    "NOOP_STEP_EXECUTION_SCHEMA_VERSION",
    "build_step_execution_plan",
    "run_noop_step_execution",
    "RESULT_INSPECTION_SCHEMA_VERSION",
    "inspect_step_results",
    "RUN_MANAGER_LOG_REQUIRED_FIELDS",
    "run_live_run_manager",
    "TOOL_VALIDATION_SCHEMA_VERSION",
    "ToolSpec",
    "AgenticToolRegistry",
    "default_agentic_tool_registry",
    "redact_trace_for_display",
    "render_agentic_llm_trace_markdown",
]
