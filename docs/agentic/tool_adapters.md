# Deterministic agent tool adapters

Ticket 20 implements the execution layer behind the four closed Ticket 19
contracts. Adapters validate typed arguments, call one existing deterministic
public API, and normalize its structured result. They contain no model client,
planning, evaluation, scheduling, retry loop, or scientific algorithm.

## Adapter boundaries

| Tool | Underlying deterministic API | Writes | Produced references |
|---|---|---|---|
| `search_crystal_db` | `crystal_db.retrieval.text_search` | None from the adapter; database and indexes are treated as configured read-only resources | None |
| `run_csp` | `llm_csp.workflow.run_csp_workflow` | One generated `workflow_runs/<workflow-run-id>/` beneath the agent run root | Workflow manifest, candidate CIF when produced, validation result when produced |
| `validate_candidate` | `llm_csp.validation.validate_cif` and optionally `validate_family_topology` | None | None; returns the typed validation payload |
| `inspect_run` | Registered `WorkflowResult` JSON manifest | None | Reuses registered manifest/candidate references |

`ToolExecutionContext` carries the resolved run root, registered workflow and
retrieval configurations, known workflow runs, and known artifacts. It has no
global mutable state, shell, Git handle, database mutation handle, model client,
or unrestricted filesystem capability. Simple callable injection supports
deterministic tests while production defaults remain the APIs listed above.

## Execution and provenance

`execute_tool` verifies the closed contract, validates arguments, enforces the
write policy, applies legal `ToolCall` transitions, invokes exactly one adapter,
and returns a terminal call plus `ToolResult`. Each result records:

- tool and versioned input/output schemas;
- validated input payload;
- UTC start and finish timestamps and elapsed seconds;
- original subsystem/result status;
- relative, SHA-256-addressed artifact references;
- underlying deterministic API identity.

`run_csp` requires an already approved tool-call state because it creates a new
workflow run. The other three tools are read-only and can execute from
`PROPOSED`. Current inputs do not express repair patches, so exact patch-bound
approval gates first become active with the Run Manager/repair work in Tickets
22 and 23; the adapter does not manufacture an artificial approval path.

Budget impact is metadata only: retrieval reports one retrieval call, workflow
execution reports one workflow run, and validation/inspection report no
workflow-run consumption. Adapters do not own or mutate a global budget.

## Status and retry classification

Scientific and subsystem status is never reduced to a generic Boolean.
Workflow results retain workflow, retrieval, SPP, solver, validation, and
topology statuses independently. In particular `OPTIMAL`, `FEASIBLE`,
`FEASIBLE_TIME_LIMIT`, `INFEASIBLE`, `spp_incomplete`, and
`gurobi_unavailable` remain distinguishable. `INFEASIBLE` is a completed
deterministic scientific invocation, not a transport retry.

Known non-automatic-retry states include `missing_db`,
`embedding_incompatible`, `no_exportable_cifs`, `backend_unavailable`,
`INFEASIBLE`, `gurobi_unavailable`, `candidate_missing`, `parse_failure`,
`unsupported_policy`, `unknown_run`, `missing_manifest`, `corrupt_manifest`,
and `hash_mismatch`. Only explicitly transient retrieval/time-out and manifest
I/O states carry `retryable=true`; Ticket 20 implements no retry loop.

Expected missing-resource, backend, candidate, and manifest failures become a
typed `ToolError` containing code, message, subsystem status, safe details, and
retryability. Contract violations and unexpected return types continue to
raise, so programming defects are not disguised as successful tool results.

## Tool-specific notes

`search_crystal_db` disables export and preserves ranked IDs, scores, metadata,
provenance, backend readiness, and export-policy readiness. Crystal-DB does not
currently expose a formula-filter parameter on `text_search`, so a non-null
formula filter is rejected rather than silently translated into different
retrieval semantics.

`run_csp` ignores the registered configuration's original output path and
replaces it with the confined agent workflow root and preallocated run ID. It
requires the returned manifest and verifies every referenced artifact remains
beneath the run root before hashing it. It delegates the incomplete-SPP stop
entirely to `run_csp_workflow` and exposes the resulting absence of a solver
stage.

`validate_candidate` accepts only an exact artifact reference registered in the
context. Topology validation runs only when a family is requested and general
parsing succeeded. Missing SCA remains the public validation boundary's
`backend_unavailable` result; the adapter never imports or installs SCA.

`inspect_run` accepts only a registered workflow-run ID, checks the manifest
path and optional hash, and selects from a closed set of actual result sections.
It never reruns, validates, repairs, or rewrites the inspected run.
