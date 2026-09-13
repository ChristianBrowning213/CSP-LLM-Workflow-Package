# Agentic state model v1

Ticket 19 implements the provider-free, immutable substrate for later v0.2
components. It defines data and validation only: no planner reasoning, tool
execution, evaluation algorithm, or orchestration loop is present.

## State structure

`AgentRunState` is the authoritative durable record. It contains the researcher
goal and parsed intent, an `AgentPlan`, immutable workflow-run and artifact
references, append-only decisions and tool calls, the current candidate,
optional evaluation, budgets, approvals, run status, and any pending user
action. Frozen dataclasses and immutable nested mappings prevent incidental
in-place mutation; explicit append and transition helpers return replacement
objects.

Plans contain only the closed tool names `search_crystal_db`, `run_csp`,
`validate_candidate`, and `inspect_run`. A plan step records structured inputs,
dependencies, an optional approval category, and its own status. It cannot hold
shell, Python, SQL, or Git operations.

Parsed constraints use distinct `HARD_CONSTRAINT`, `SOFT_PREFERENCE`, and
`SUCCESS_CRITERION` kinds. Evaluation and repair records are schemas only.
Repair types are closed to operations expressible through the documented
workflow boundary.

## Status and transitions

Run status is `PENDING` or `RUNNING`, or one of these terminal values:
`SUCCESS`, `BLOCKED`, `NO_VALID_CANDIDATE`, `SOLVER_INFEASIBLE`,
`INSUFFICIENT_EVIDENCE`, `VALIDATION_FAILED`, `BUDGET_EXHAUSTED`,
`USER_INPUT_REQUIRED`, and `SYSTEM_ERROR`. `is_terminal` is the single
authoritative terminal-state test.

Plan-step, tool-call, approval, and run transitions are centralized. Terminal
step/call/approval states cannot return to an active state. A terminal agent
run cannot accept new planned execution; continuing work requires a new run.

## Budgets

`AgentBudgets` pairs immutable limits and usage. Defaults are two workflow
runs, one repair attempt, one retrieval retry, two model-format retries, and
3,600 elapsed seconds. `remaining`, `exhausted`, `can_consume`, and `consume`
are deterministic. `consume` raises `BudgetExceededError` instead of exceeding
a limit.

## Approvals

Approval categories cover hard-constraint removal, composition and topology
changes, search expansion, non-optimal acceptance, validation bypass,
scientific-resource changes, and budget increases. Approval binds to an exact
`request_ref` and structured patch. Only `USER` can approve or reject; no
automatic approval exists. Cancellation remains an explicit terminal outcome.

The narrow automatic-action enum permits only model-format retry, read of an
existing run, retrieval retry, and execution of an already approved step,
subject to the relevant budget and future orchestrator checks.

## Decision provenance and references

`DecisionRecord` stores actor, action, validated tool arguments, input/result
references, UTC timestamp, and a concise audit rationale capped at 500
characters. It has no private-reasoning or chain-of-thought field.

`ArtifactReference` uses a stable ID, kind, traversal-free relative path,
producing workflow-run ID, and optional SHA-256. `WriteScope` resolves these
paths beneath one configured run root and rejects POSIX paths, Windows drives,
UNC paths, and `..` traversal. `WorkflowRunReference` retains the deterministic
run ID and subsystem status plus result and optional candidate references.

## Serialization and invariants

The state schema identifier is `llm_csp.agentic.state.v1` (numeric version 1).
All state records serialize to ordinary JSON data and parse with strict unknown-
field rejection. Sorted-key JSON provides deterministic output; the canonical
fixture is `tests/fixtures/agentic/canonical_agent_state.v1.json`.

Construction checks currently enforce unique record IDs, produced-candidate
references, evaluation-to-run references, workflow-run budget accounting,
decision-to-tool-call result references, tool-call-to-artifact/workflow-run result
references, valid approved request references, no pending required approval at
`SUCCESS`, and no active execution in a terminal run.

Ticket 20 adds explicit replacement helpers for completed tool-call records and
the current candidate. Its `apply_execution_to_state` helper appends a produced
workflow reference (thereby consuming the existing immutable workflow budget),
replaces the known tool call with its legally transitioned terminal record, and
sets a produced candidate without interpreting whether it satisfies the goal.
`ToolError` now also carries the original subsystem status and a conservative
retryability flag.
