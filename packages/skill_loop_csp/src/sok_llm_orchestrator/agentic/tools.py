from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

TOOL_VALIDATION_SCHEMA_VERSION = "agentic_csp.tool_validation.v1"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    required_arguments: list[str]
    optional_arguments: list[str]
    expected_result_keys: list[str]
    archive_notes: str

    def to_dict(self) -> dict[str, Any]:
        return to_json_dict(self)


class AgenticToolRegistry:
    """Registry of agent-proposable tool contracts with validation only."""

    def __init__(self, tools: list[ToolSpec]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def list_tools(self) -> list[dict[str, Any]]:
        return [self._tools[name].to_dict() for name in sorted(self._tools)]

    def get_tool(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            msg = f"Unknown tool: {name}"
            raise KeyError(msg) from exc

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def validate_tool_call_proposal(self, proposal: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(proposal, Mapping):
            msg = "proposal must be a mapping"
            raise TypeError(msg)

        tool_name_value = proposal.get("tool_name")
        tool_name = tool_name_value if isinstance(tool_name_value, str) else ""
        errors: list[str] = []
        warnings: list[str] = []

        if not tool_name:
            errors.append("tool_name is required.")
        elif not self.has_tool(tool_name):
            errors.append(f"Unknown tool name: {tool_name}")
        else:
            tool = self.get_tool(tool_name)
            arguments = proposal.get("arguments")
            if not isinstance(arguments, Mapping):
                errors.append("arguments must be a mapping.")
            else:
                for required_argument in tool.required_arguments:
                    if required_argument not in arguments:
                        errors.append(
                            f"Missing required argument for {tool_name}: {required_argument}"
                        )
                allowed_arguments = set(tool.required_arguments) | set(tool.optional_arguments)
                for argument_name in arguments:
                    if str(argument_name) not in allowed_arguments:
                        warnings.append(
                            f"Unexpected argument for {tool_name}: {argument_name}"
                        )

        result = {
            "schema_version": TOOL_VALIDATION_SCHEMA_VERSION,
            "valid": not errors,
            "tool_name": tool_name,
            "errors": errors,
            "warnings": warnings,
        }
        assert_json_serializable(result)
        return result


def default_agentic_tool_registry() -> AgenticToolRegistry:
    return AgenticToolRegistry(
        tools=[
            ToolSpec(
                name="crystal.csp_pack",
                description="Propose a future crystal CSP candidate-pack step without executing it.",
                required_arguments=["case_id", "objective_family"],
                optional_arguments=["notes"],
                expected_result_keys=["proposal_ref", "candidate_count", "artifact_refs"],
                archive_notes="Store proposal-time CSP pack metadata as plain JSON artifacts.",
            ),
            ToolSpec(
                name="spp.run_pipeline",
                description="Propose a future SPP pipeline step over a pending corpus reference.",
                required_arguments=["case_id", "corpus_ref"],
                optional_arguments=["notes"],
                expected_result_keys=["proposal_ref", "spp_run_summary", "artifact_refs"],
                archive_notes="Record proposal-time SPP pipeline metadata and pending refs in JSON.",
            ),
            ToolSpec(
                name="spp.package_for_qlip",
                description="Propose a future packaging step from SPP outputs into a QLIP request bundle.",
                required_arguments=["case_id", "spp_package_ref"],
                optional_arguments=["notes"],
                expected_result_keys=["proposal_ref", "request_bundle_ref", "artifact_refs"],
                archive_notes="Archive proposal-time package metadata and pending refs as plain files.",
            ),
            ToolSpec(
                name="qlip.validate_request",
                description="Propose a future QLIP request validation step using a pending request ref.",
                required_arguments=["case_id", "request_ref"],
                optional_arguments=["notes"],
                expected_result_keys=["proposal_ref", "validation_summary", "artifact_refs"],
                archive_notes="Persist proposal-time validation metadata as JSON or Markdown only.",
            ),
            ToolSpec(
                name="qlip.solve",
                description="Propose a future QLIP solve step from a pending validated request ref.",
                required_arguments=["case_id", "validated_request_ref"],
                optional_arguments=["notes"],
                expected_result_keys=["proposal_ref", "solve_summary", "artifact_refs"],
                archive_notes="Capture proposal-time solve metadata as archive-ready JSON only.",
            ),
            ToolSpec(
                name="crystal.novelty_check",
                description="Propose a future novelty-check step against prior crystal results.",
                required_arguments=["case_id"],
                optional_arguments=["notes"],
                expected_result_keys=["proposal_ref", "novelty_summary", "artifact_refs"],
                archive_notes="Save proposal-time novelty-check metadata as plain JSON for later reports.",
            ),
        ]
    )


__all__ = [
    "TOOL_VALIDATION_SCHEMA_VERSION",
    "ToolSpec",
    "AgenticToolRegistry",
    "default_agentic_tool_registry",
]
