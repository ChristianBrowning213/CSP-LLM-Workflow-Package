# Agentic source inventory

## Audited source

- Repository: `C:\Users\brown\Documents\GitHub\Skill-Loop-CSP`
- Branch: `Agentic-Loop`
- Commit inspected: `36f6280e47387643853ac0cfc510e20c5d595834`
- Existing working-tree state: untracked `benchmarks/external/OMatG/`
- Audit mode: read-only; the source repository was not modified

The branch is newer than the implementation previously referenced during the
deterministic workflow migration. The inventory therefore describes the
current branch rather than assuming an older Ticket 8 snapshot.

## Classification method

Every function and class in a listed file or file group inherits that row's
classification unless an exception is stated explicitly. The classifications
are `AGENT_REASONING`, `TOOL_ADAPTER`, `DETERMINISTIC_SCIENTIFIC_KERNEL`,
`EXPERIMENTAL_POLICY`, `BENCHMARK_ONLY`, and `HISTORICAL`.

`MIGRATE` means the design is suitable with minimal namespace/schema changes.
`ADAPT` means retain the pattern behind new v0.1-facing interfaces. `REWRITE`
means retain requirements or tests, not the implementation. `DISCARD` means the
code is not part of the production migration.

## Component inventory

| Source file(s) | Purpose and status | Dependencies | Scientific responsibility | Classification | Candidate destination | Decision |
|---|---|---|---|---|---|---|
| `agentic/schemas.py` | Dataclass envelopes for plans, proposals, logs, evaluations, decisions, and run records; working prototype | standard library | Carries claims but performs no science | `AGENT_REASONING` | `agentic/models.py`, `agentic/state.py` | ADAPT |
| `agentic/agents.py`, `agentic/runtime.py` | Four placeholder roles and an in-memory no-execution cycle | prototype schemas/registry | Placeholder only | `HISTORICAL` | none directly | DISCARD |
| `agentic/planner_runtime.py`, `plan_compile.py`, `prompting.py`, `prompts/*` | Schema-checked model planning with bounded format/compile retries | model runtime, prompt files, registry | Chooses proposed operations | `AGENT_REASONING` | `agentic/planner.py` | ADAPT |
| `agentic/llm_runtime.py`, `llm/client.py` | JSON-output runtime over an OpenAI-compatible chat endpoint | HTTP/JSON, configured model server | No scientific authority | `AGENT_REASONING` | provider-neutral `AgentModel` plus optional adapter | REWRITE |
| `agentic/run_manager_runtime.py` | Asks an LLM to produce a run-manager log | model runtime, archive | Describes execution rather than owning it | `AGENT_REASONING` | deterministic `agentic/run_manager.py` | REWRITE |
| `agentic/evaluator_runtime.py`, `orchestrator_runtime.py`, `chain_runtime.py` | Live proposal-review chain with schema validation and archived traces | model runtime, planner, no-op handoff | Model-driven evaluation/control prototype | `AGENT_REASONING` | evaluator suggestions plus deterministic state machine | REWRITE |
| `agentic/tools.py` | Six-name validation-only tool registry | schema helpers | Defines proposal surface only | `TOOL_ADAPTER` | `agentic/tools/contracts.py` | ADAPT |
| `agentic/execution_intent.py`, `execution_handoff.py`, `executor_preflight.py`, `execution_plan_adapter.py`, `gated_executor.py` | Validated execution handoff, preflight, placeholder resolution, and gated dispatch | tool registry/adapters, filesystem | Controls whether deterministic work may run | `TOOL_ADAPTER` | run manager and tool dispatcher | ADAPT |
| `agentic/tool_execution_adapters.py` | Large MCP adapter layer for Crystal-DB, SPP, QLIP, and novelty | legacy contracts, MCP subprocesses, local configuration | Mixes transport with formula, pair, POT, request, and recovery logic | `TOOL_ADAPTER`; embedded helper logic is `DETERMINISTIC_SCIENTIFIC_KERNEL` | new thin adapters calling packaged v0.1 APIs | REWRITE |
| `agentic/evaluator.py`, `result_inspection.py` | Reads run artifacts and derives success/failure, scores, and recovery hints | JSON/CIF parsing, artifact paths | Duplicates or supplements scientific interpretation | mixed `DETERMINISTIC_SCIENTIFIC_KERNEL` and `EXPERIMENTAL_POLICY` | consume `WorkflowResult` and validation models instead | REWRITE |
| `agentic/failure_handling.py`, `partial_success.py`, `qlip_recovery.py` | Maps failures to retries and rewrites some QLIP/SPP request data | inspection results, JSON artifacts | Experimental repair policy; some code changes guidance arguments | `EXPERIMENTAL_POLICY` | typed repair proposals with approval gates | REWRITE |
| `agentic/archive.py`, `manager_logging.py`, `execution_report.py`, `trace_render.py`, `sequence_diagram.py` | JSON/Markdown run records, traces, replay artifacts, and redaction | filesystem, schema helpers | Preserves provenance; no science | `TOOL_ADAPTER` | state store and provenance writer | ADAPT |
| `agentic/noop_executor.py`, `step_execution.py`, `chain_fixtures.py` | Safe no-op execution and deterministic fixture replay | schema helpers | None | `HISTORICAL` | test fixtures | MIGRATE |
| `agentic/demo_loop.py`, `demo_bundle.py`, `paper_smoke_suite.py`, `visualise_workflow_artifact.py` | Research demonstrations, paper smoke runs, bundles, and extensive visualization | local MCP stack, plotting/VESTA, research assets | Benchmark/report presentation | `BENCHMARK_ONLY` | optional future benchmark repository | DISCARD |
| `agentic/robocrys_adapter.py`, `robocrys_external_describe.py`, `robocrys_intent_validator.py`, `skills/robocrys_query_skill.py` | External description and rule/model intent-alignment prototype | robocrys, subprocesses, optional LLM | Experimental semantic validation | `EXPERIMENTAL_POLICY` | later evidence-evaluation proposal, if justified | DISCARD |
| `optimization/session_schema.py`, `session_store.py` | Durable session, history, best result, blocked state, and JSON persistence | JSON Schema, filesystem | State/provenance container | `AGENT_REASONING` | `agentic/state.py` and run-root store | ADAPT |
| `optimization/budget.py`, `stop_policy.py`, `stuck_detector.py`, `orchestrator/iteration_controller.py` | Explicit counters, wall-clock option, stop rules, stagnation, and deltas | settings, diagnostic records | Bounded control policy | `EXPERIMENTAL_POLICY` | deterministic orchestrator budgets | ADAPT |
| `optimization/action_schema.py`, `action_registry.py`, `action_compile.py`, `llm_action_selector.py`, `infeasibility_recovery.py` | Bounded research action library and recovery regimes | optimization configuration and LLM selector | Chooses scientific configuration changes | `EXPERIMENTAL_POLICY` | future reviewed repair-policy package | DISCARD for first milestone |
| `optimization/loop.py`, reporting/ablation/bandit modules, `bench/*`, `evals/*`, related scripts/tests | Full research optimization and benchmark machinery | research workflow, datasets, plotting, optional live LLM | Campaign-specific policies and evaluation | `BENCHMARK_ONLY` | later benchmark design only | DISCARD |
| `orchestrator/pipeline.py`, `workflow/*`, `contracts/*`, `verification/*`, `spp/*`, `qlip_mcp/*`, `crystaldb_mcp/*`, `spp_mcp/*` | Legacy deterministic retrieval/SPP/QLIP/verification implementations and MCP surfaces | scientific stack and sibling repositories | Performs scientific work now supplied by v0.1 packages | `DETERMINISTIC_SCIENTIFIC_KERNEL` | existing `llm_csp`, `crystal_db`, `qlip`, `sca` packages | DISCARD; do not duplicate |
| `safety/caps.py`, `safety/path_sandbox.py` | Limits and workspace path checks | filesystem | Execution safety only | `TOOL_ADAPTER` | run-manager permission layer | ADAPT |

## Conclusions

The useful migration material is architectural: typed records, bounded retries,
tool validation, execution gates, append-only archives, budget counters, and
fake-model tests. The current research implementation is tightly coupled to
legacy MCP tools and campaign-specific policies. It should not be copied as a
package wholesale.

In particular, formula parsing, required-pair derivation, POT selection, SPP
normalization, QLIP request construction, solver interpretation, novelty
calculation, CIF interpretation, and validation scoring remain in the released
deterministic packages. Agent code may only call those capabilities.

The untracked external OMatG directory was neither read as implementation input
nor modified. Existing benchmark code is classified for later evaluation work,
not migration in this ticket.
