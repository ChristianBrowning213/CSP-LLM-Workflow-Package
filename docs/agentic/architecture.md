# Agentic architecture for v0.2

## Status and scope

This document defines the design boundary for the optional v0.2 agentic layer.
It does not introduce an agent runtime or change the released scientific
workflow. The stable kernel remains:

```text
CSPWorkflowRequest + WorkflowConfig
    -> run_csp_workflow(...)
    -> WorkflowResult + referenced artifacts and provenance
```

The central architectural rule is:

> Agents may decide what scientific operation to request, but scientific
> operations themselves must execute through deterministic package APIs.

Anything achievable through the v0.1 deterministic API must remain achievable
without enabling the agentic layer. Agentic functionality is additive; no v0.1
public API may be removed or semantically changed.

## Responsibility boundary

The agentic layer may interpret a researcher goal, assemble an explicit plan,
select a named tool, evaluate structured outputs, and recommend a bounded next
action. It must not reproduce retrieval ranking, SPP mathematics, QLIP objective
construction, solver logic, or SCA validation mathematics.

Deterministic operations remain authoritative and are reached through stable
APIs such as `run_csp_workflow`, Crystal-DB `text_search`, packaged SPP and QLIP
APIs, and `llm_csp.validation`. An agent must not use unrestricted shell or
Python execution as the normal scientific interface.

```text
researcher goal
    -> Planner decision
    -> schema-defined tool request
    -> deterministic package API
    -> structured result and artifact references
    -> Evaluator decision
```

The LLM may select or query evidence. Crystal-DB provides attributable
structural evidence. Model-generated structures, citations, or literature
claims never substitute for retrieved evidence.

## Minimal roles

### Planner

Interprets researcher intent, preserves explicit constraints, selects required
stages, and emits a structured `AgentPlan`. It neither executes QLIP nor invents
scientific results.

### Run Manager

Validates tool arguments, executes approved deterministic adapters, tracks
artifacts, updates counters, and propagates subsystem failures unchanged. It is
ordinary deterministic application code, not an LLM persona.

### Evaluator

Reads `WorkflowResult`, validation results, and other structured evidence. It
determines request satisfaction using deterministic status and metric fields,
then emits either a terminal recommendation or one allowed structured repair.
An LLM may help explain or select among already legal actions, but is not the
scientific judge.

### Orchestrator

Owns state transitions, scheduling, approval gates, budgets, and termination.
It is a deterministic state machine. It never silently retries or edits a
scientific request.

No additional roles are justified for the first v0.2 milestone.

## Explicit state model

The proposed state is durable JSON, not conversational memory:

```python
AgentRunState(
    schema_version="llm_csp.agentic.state.v1",
    agent_run_id=...,
    user_goal=...,
    parsed_intent=...,
    plan=...,
    evidence=[EvidenceReference(...)],
    workflow_runs=[WorkflowRunReference(...)],
    current_candidate=...,
    evaluation=...,
    decisions=[DecisionRecord(...)],
    budgets=AgentBudgets(...),
    pending_approval=None,
    status=...,
)
```

`WorkflowRunReference` records the immutable deterministic run ID, result
location, result hash, status, and artifact references. `DecisionRecord`
contains a decision ID, input-state hash, concise rationale, selected tool,
validated arguments, result reference, next-state hash, timestamp, and approval
status. Concise rationale is retained for audit; private model chain-of-thought
is neither requested nor stored.

Structured deterministic output is scientific authority. Conversation context
may help interpret intent but cannot overwrite state, results, or provenance.
Long-term cross-run memory is out of scope for v0.2.

## Provenance chain

Each iteration appends records and never overwrites a prior deterministic run:

```text
decision D1 -> workflow run A -> validation A -> evaluation E1
            -> decision D2 -> workflow run B -> validation B
```

Every evaluation cites the result that supports it. Every repair cites the
failure and decision that caused it. Artifact paths are stored relative to the
configured run root where possible, with hashes for durable files.

## Bounds and termination

The first milestone defaults are deliberately small and configurable only
within an application policy:

- maximum workflow runs: 2 (initial run plus at most one approved retry)
- maximum repair attempts: 1
- maximum retrieval retries: 1
- maximum model-format retries per decision: 2
- maximum wall-clock budget: 3,600 seconds

The orchestrator checks all applicable counters before every transition. There
is no unbounded autonomous loop.

Terminal states are machine-readable:

- `SUCCESS`
- `BLOCKED`
- `NO_VALID_CANDIDATE`
- `SOLVER_INFEASIBLE`
- `INSUFFICIENT_EVIDENCE`
- `VALIDATION_FAILED`
- `BUDGET_EXHAUSTED`
- `USER_INPUT_REQUIRED`
- `SYSTEM_ERROR`

A prose conclusion is never the sole termination signal.

Subsystem failures including `missing_db`, `embedding_incompatible`,
`spp_incomplete`, `gurobi_unavailable`, `INFEASIBLE`, and
`backend_unavailable` remain structured. The agent may interpret them only
after the original code, stage, details, and provenance are recorded.

## Repair boundary

A repair is an explicit, schema-validated patch against the prior request or
configuration. Permitted proposals are limited to operations already supported
by public package APIs, for example selecting another configured scaffold,
choosing another retrieved evidence set, changing a supported SPP fitting mode,
or relaxing an optional constraint after the appropriate approval.

The agent may never alter SPP cutoffs, pair-scoring mathematics, solver-objective
implementation, validation thresholds, or other scientific algorithms ad hoc.
See `human_in_the_loop.md` for approval classes.

## Provider and memory boundaries

Planning integrations target a small provider-independent protocol, conceptually:

```python
class AgentModel(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...
```

Provider adapters translate this contract to a vendor API. Provider credentials,
retry behavior, and raw responses remain outside deterministic scientific
packages. The v0.1 workflow and every deterministic tool remain usable when no
model provider is configured.

Run state, scientific provenance, conversation context, and long-term memory are
separate concerns. v0.2 stores only explicit run state and provenance.

## Write and permission boundary

An agent may write only beneath a configured, resolved run/output root. Tool
adapters reject path traversal and do not modify package source, Git state,
external databases, source POT libraries, model configuration, or system
configuration. Scientific databases and POT libraries are read-only inputs.
Shell access is development-only and is not exposed through the agent tool
registry.

## Proposed package layout

```text
src/llm_csp/agentic/
|-- __init__.py
|-- models.py
|-- state.py
|-- planner.py
|-- run_manager.py
|-- evaluator.py
|-- orchestrator.py
|-- tools/
`-- schemas/
```

This ticket intentionally does not create this scaffold. Models and tool
contracts should be implemented only after their schemas are accepted.

## Testing strategy

Unit tests cover schema validation, state transitions, tool-selection parsing,
budget enforcement, approval gates, path boundaries, and every terminal state.
Integration tests use deterministic fake model responses with real v0.1 tool
adapters. The first agentic end-to-end test is a bounded fake-model plan/run/
evaluate cycle using a real packaged workflow fixture.

Default tests require no paid API, network call, production database, POT
library, or live LLM. Optional provider tests are separately marked. Scientific
success is asserted from solver status, validation metrics, and explicit request
satisfaction; model behavior is evaluated separately for planning, tool choice,
constraint preservation, and legal repair selection.
