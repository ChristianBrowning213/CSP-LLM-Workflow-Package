# Structured initial Planner

`Planner.plan(state=state, model=model)` converts one `AgentRunState` and one
provider-independent structured model response into a validated initial
`AgentPlan`. It proposes deterministic calls; it never executes tools, judges
scientific truth, creates candidates, or marks a run successful. Replanning,
the Run Manager, Evaluator, repair loop, and Orchestrator are out of scope.

## Input and tool boundary

The model receives the user goal, parsed intent, separately labelled hard
constraints, soft preferences and success criteria, current budget limits, and
a deterministic serialization of `TOOL_CONTRACTS`. The serialization includes
contract descriptions, input fields, side effects, approval policy, and
read-only status. There is no second handwritten tool list.

The only accepted names are `search_crystal_db`, `run_csp`,
`validate_candidate`, and `inspect_run`. Every proposed input is instantiated
through the corresponding Ticket 19 contract model before acceptance. Extra
fields—including arbitrary output roots—fail there. IDs are normalized by the
system, and the `run_csp` decision reference is system-owned.

## Validation and preservation

Output passes strict object parsing, closed-tool lookup, actual input-contract
validation, dependency existence/uniqueness/acyclicity/order checks, and
constraint preservation. The model must echo every typed constraint in its
original category. For a `run_csp` request, target formula, requested topology,
and keyed hard constraints are also checked against the actual workflow
request. Success criteria remain explicit for the future Evaluator. A protected
change may be marked with an approval category, but planning creates no
`APPROVED` record.

The normal generation plan starts with `run_csp`, because
`run_csp_workflow` already performs Crystal-DB retrieval and configured
validation. Adding a preliminary search solely because the search tool exists
would duplicate retrieval. Standalone `search_crystal_db` is appropriate when
retrieval is itself the requested result—for evidence inspection, readiness or
preflight—or when a later user decision will be based on retrieved evidence.
It is not forced into every plan.

## Failures, clarification, and state

Malformed and schema-invalid responses receive a provider-neutral correction
object and may use only the remaining `model_format_retries` budget (default
two, for at most three total attempts). Planning consumes no workflow,
retrieval, repair, or wall-clock counters. Each attempt records metadata and a
concise error, never chain-of-thought.

If information required by deterministic APIs is missing, the result is
`USER_INPUT_REQUIRED` with a question, missing field/category, and reason. It
contains no fake plan. `apply_planner_result` attaches a successful plan and a
concise Planner decision while retaining the active run status. For
clarification it sets `pending_user_action` and the Ticket 19
`USER_INPUT_REQUIRED` status. Neither path executes a scientific adapter.
