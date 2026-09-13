# Proposed agent tool contracts

## Common envelope

Agents receive only high-level tools. Every call uses a versioned envelope with
`tool_call_id`, `agent_run_id`, `decision_id`, and `arguments`. Every response
contains `schema_version`, `tool_call_id`, `status`, `result`, `artifacts`,
`provenance`, `warnings`, and `errors`.

`status` and each error code are preserved from the deterministic subsystem.
Adapters may add transport errors but may not replace `missing_db`,
`embedding_incompatible`, `spp_incomplete`, `gurobi_unavailable`, `INFEASIBLE`,
or `backend_unavailable` with generic prose.

All paths are resolved beneath a configured run root. Inputs refer to registered
artifact IDs or validated relative paths, never arbitrary model-provided system
paths.

## `search_crystal_db`

**Description:** Retrieve attributable crystallographic evidence using the
packaged Crystal-DB API. This is evidence retrieval, not structure invention.

**Input schema:**

```json
{
  "schema_version": "llm_csp.agentic.search_crystal_db.input.v1",
  "query": "non-empty string",
  "formula": "optional string",
  "k": "integer, 1..50",
  "retrieval": {
    "db_ref": "configured read-only database reference",
    "embed_engine": "configured supported engine",
    "model_name": "string",
    "model_version": "string",
    "text_engine": "string",
    "text_view": "string"
  }
}
```

**Output schema:** structured Crystal-DB status, ranked evidence records,
backend provenance, compatibility metadata, and an evidence-artifact reference.

**Failure states:** `missing_db`, `embedding_incompatible`, backend unavailable,
invalid request, and system I/O error.

**Side effects:** writes only the response/provenance JSON beneath the current
agent-run directory. The database and indexes remain read-only.

**Deterministic API:** Crystal-DB `text_search`/public facade.

## `run_csp`

**Description:** Execute one complete deterministic CSP workflow. This is the
preferred scientific tool instead of exposing individual SPP and QLIP steps.

**Input schema:**

```json
{
  "schema_version": "llm_csp.agentic.run_csp.input.v1",
  "request": "CSPWorkflowRequest-compatible object",
  "config": "WorkflowConfig-compatible object with registered resource refs",
  "parent_decision_id": "decision identifier"
}
```

The adapter supplies the authorized output root and run ID; a model cannot
choose an unrestricted path.

**Output schema:** the unmodified `WorkflowResult.to_dict()` value plus its
result hash and `WorkflowRunReference`.

**Failure states:** all structured workflow stage failures, including retrieval
errors, `spp_incomplete`, request-validation failure, `gurobi_unavailable`,
`INFEASIBLE`, validation failure, and system error.

**Side effects:** creates the normal deterministic run directory and artifacts
under the configured output root. It does not modify source resources.

**Deterministic API:** `llm_csp.workflow.run_csp_workflow`.

## `validate_candidate`

**Description:** Run supported SCA validation on a candidate already registered
to the current run.

**Input schema:**

```json
{
  "schema_version": "llm_csp.agentic.validate_candidate.input.v1",
  "candidate_ref": "registered candidate artifact ID",
  "target_formula": "optional non-empty string",
  "topology_family": "optional supported family"
}
```

**Output schema:** normalized general `ValidationResult`, optional
`TopologyValidationResult`, backend provenance, and source candidate hash.

**Failure states:** candidate missing, parse failure, `backend_unavailable`,
unsupported topology policy, and system error. A scientifically invalid
candidate is a successful tool invocation with a failing validation result.

**Side effects:** writes validation JSON beneath the current run only; the CIF
is read-only.

**Deterministic API:** `validate_cif` and `validate_family_topology`.

## `inspect_run`

**Description:** Load and summarize an existing deterministic result without
rerunning or reinterpreting scientific algorithms.

**Input schema:**

```json
{
  "schema_version": "llm_csp.agentic.inspect_run.input.v1",
  "workflow_run_id": "known run identifier",
  "include": ["stages", "artifacts", "provenance", "warnings", "errors"]
}
```

**Output schema:** referenced `WorkflowResult` fields, verified artifact
existence/hashes, and the immutable result reference.

**Failure states:** unknown run, corrupt manifest, hash mismatch, unauthorized
path, or system error.

**Side effects:** none beyond an optional inspection record beneath the agent
run root.

## `compare_candidates`

**Description:** Deterministically compare registered candidates using
structured fields rather than asking a model to compare raw CIF coordinates.
This tool is proposed for a later ticket and is not required by the first
plan/run/evaluate milestone.

**Input schema:**

```json
{
  "schema_version": "llm_csp.agentic.compare_candidates.input.v1",
  "candidate_refs": ["at least two registered candidate IDs"],
  "comparison_policy": "named, versioned deterministic policy"
}
```

**Output schema:** per-candidate QLIP status/objective, validation state,
topology metrics, provenance, explicit missing fields, and deterministic
ordering or `not_comparable`.

**Failure states:** unknown candidate, incompatible result schemas, insufficient
metrics, unknown policy, and artifact-integrity error.

**Side effects:** writes only a comparison record beneath the run root.

## Excluded surfaces

No agent tool exposes a shell, arbitrary Python, raw SQL, database mutation,
source POT mutation, Git operation, scientific-threshold editing, or direct
solver-objective construction. Lower-level SPP/QLIP APIs remain available to
ordinary Python callers but are not the default agent surface.
