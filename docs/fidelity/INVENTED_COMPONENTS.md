# Invented Components

## Finding

The current `develop` archive contains an archive-native v0.2 agent layer that was created in Tickets 18–21. It is useful new work, but it is not a preservation of the frozen Skill-Loop-CSP agentic system and must not be presented as such.

| Archive component | Classification | Source comparison | Disposition |
|---|---|---|---|
| `agentic/models.py`: `AgentPlan`, `PlanStep`, `ParsedIntent`, decision/tool/evaluation records and enums | `NEW_NOT_IN_SOURCE` | Same domain, new schemas; incompatible with the seven source record types | `REPLACE_WITH_SOURCE_IMPLEMENTATION` or retain only as a labelled compatibility layer. |
| `agentic/state.py`: `AgentRunState`, identifiers and `WriteScope` | `NEW_NOT_IN_SOURCE` | Same state concept, new implementation | `REPLACE_WITH_SOURCE_IMPLEMENTATION`. |
| `agentic/budgets.py`: `AgentBudgets`, limits/usage/resources | `NEW_NOT_IN_SOURCE` | Same budget concept, new implementation | `REVIEW`; it cannot substitute for source run limits. |
| `agentic/approvals.py`: `ApprovalRequest` and transitions | `NEW_NOT_IN_SOURCE` | Completely new approval abstraction | `REVIEW`. |
| `agentic/termination.py`: statuses and transitions | `NEW_NOT_IN_SOURCE` | Same lifecycle concept, new state machine | `REPLACE_WITH_SOURCE_IMPLEMENTATION`. |
| `agentic/contracts.py`: four inputs and `ToolContract` | `NEW_NOT_IN_SOURCE` | Replaces six original tool specs with four generic tools | `REMOVE` from fidelity claims. |
| `agentic/model/base.py`: `AgentModel`, metadata and structured response | `NEW_NOT_IN_SOURCE` | New provider-independent interface replaces concrete source runtime | `REVIEW` after source restoration. |
| `agentic/model/fake.py` and fixtures | `NEW_NOT_IN_SOURCE` | Test double/fixtures, not a source runtime provider | `KEEP_AS_COMPATIBILITY_WRAPPER` only for archive-native tests. |
| `agentic/planner.py`: `Planner` and planner records | `NEW_NOT_IN_SOURCE` | New implementation; not source planner prompt/runtime/compiler | `REPLACE_WITH_SOURCE_IMPLEMENTATION`. |
| `agentic/tools/search_crystal_db.py` | `NEW_NOT_IN_SOURCE` | Generic replacement for `crystal.csp_pack`/Crystal tools | `REMOVE` or compatibility-wrapper only. |
| `agentic/tools/run_csp.py` | `NEW_NOT_IN_SOURCE` | Generic workflow wrapper replaces the source's staged tool chain | `REMOVE` or compatibility-wrapper only. |
| `agentic/tools/validate_candidate.py` | `NEW_NOT_IN_SOURCE` | Generic wrapper around validation, not an original registered agent tool | `REVIEW`. |
| `agentic/tools/inspect_run.py` | `NEW_NOT_IN_SOURCE` | Completely new registered tool concept | `REVIEW`. |
| `agentic/tools/base.py`, `registry.py`, `_utils.py` | `NEW_NOT_IN_SOURCE` | New adapter registry/execution contract | `REPLACE_WITH_SOURCE_IMPLEMENTATION`. |

## Exact source agent boundary that is absent

The frozen source contains `sok_llm_orchestrator.agentic` modules for agents, chain runtime, evaluator/runtime, execution intent/preflight, failure handling, gated execution, LLM runtime, manager logging, orchestration, plan compilation, planner runtime, QLIP recovery, result inspection, run-manager runtime, schemas, step execution, tool execution adapters, tool registry, trace rendering, and package-owned prompts.

Its default tool registry is exactly:

1. `crystal.csp_pack`
2. `spp.run_pipeline`
3. `spp.package_for_qlip`
4. `qlip.validate_request`
5. `qlip.solve`
6. `crystal.novelty_check`

The model boundary calls an OpenAI-compatible `/chat/completions` endpoint, discovers local LM Studio/Ollama models, retries, removes Markdown fences, extracts JSON objects, validates required fields/types, and sends correction prompts. These behaviors and the package-owned prompt texts are part of fidelity.

## Release rule

Archive-native components may remain as explicitly experimental work, but they cannot close a source-fidelity row and cannot substitute for restoring the original namespace and operational call graph. No evidence found suggests malicious or inappropriate invention; the problem is attribution and compatibility, not code quality.
