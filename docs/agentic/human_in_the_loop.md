# Human-in-the-loop policy

Agentic execution distinguishes automatic safe retries, suggestions, and
approval-required changes. A decision record captures the category and the
researcher's response before any gated action executes.

## Automatic safe retry

The orchestrator may perform these within the configured counters without a new
approval:

- correct model-output formatting without changing semantic arguments;
- repeat a read-only retrieval call after an explicitly transient transport
  failure;
- re-read a run manifest or artifact after a transient I/O failure;
- execute the initially approved plan exactly once;
- stop when a deterministic terminal state or budget is reached.

An automatic retry must preserve the request, constraints, scientific
configuration, evidence query, and resource identities. It appends a decision
record rather than replacing the failed attempt.

## Agent suggestion

The agent may propose, but not silently execute:

- use another retrieved evidence set;
- select another already allowed scaffold;
- choose another packaged SPP fitting mode;
- change a soft optional constraint;
- make a small search-space expansion within a researcher-approved bound;
- invoke deterministic candidate comparison;
- perform the single repair allowed by the first milestone.

Each suggestion is a structured patch with the prior value, proposed value,
supporting result reference, expected effect, and approval class.

## Human approval required

Explicit researcher approval is required before:

- dropping or weakening a user-requested hard constraint;
- changing target composition or stoichiometry;
- switching topology family or requested space group semantics;
- substantially expanding the design or retrieval search space;
- accepting a merely feasible candidate when optimality was required;
- disabling validation or accepting a failed/unknown validation result;
- changing scientific resource identity, POT/SPP source, database, embedding
  model/version, or solver configuration beyond preapproved choices;
- increasing workflow, repair, retrieval, wall-clock, or cost budgets;
- sending data to a newly selected external model/provider;
- overwriting or deleting an existing scientific artifact.

Approval binds to the exact structured patch and expires if its arguments
change.

## Never agent-authorized

Neither a model suggestion nor ordinary researcher approval through the agent
loop may edit package source, Git state, external databases, source POT
libraries, system configuration, SPP/scoring mathematics, QLIP objective code,
or SCA thresholds. Such changes are software/scientific-development work and
must occur through a separate reviewed release process.

## Approval outcomes

- approved: execute the exact validated patch if budget remains;
- rejected: preserve the rejection and choose another legal action or stop;
- unavailable/ambiguous: transition to `USER_INPUT_REQUIRED`;
- request outside the tool surface: transition to `BLOCKED` with the unsupported
  action recorded.
