# Provider-independent model boundary

Ticket 21 introduces `AgentModel.generate_structured(...)`, a deliberately
small protocol. A caller supplies package-owned task instructions, a JSON-safe
input object, and the expected output type. The response contains untrusted
structured output plus `ModelMetadata`: provider, model identifier, adapter
version, optional request ID, and a UTC timestamp. This operational metadata is
kept separate from Crystal-DB evidence and scientific workflow provenance. It
contains no credentials.

The core interface has no provider-specific parameters and installs no model
SDK. `FakeAgentModel` is the default backend for tests. It returns a fixed value
or sequence, can return malformed values, and can raise any configured typed
`AgentModelError`, without network, keys, a GPU, local models, or filesystem
writes.

The error taxonomy distinguishes `MODEL_UNAVAILABLE`, `MODEL_REQUEST_FAILED`,
`MODEL_OUTPUT_INVALID`, `MODEL_OUTPUT_SCHEMA_MISMATCH`, and
`MODEL_FORMAT_RETRY_EXHAUSTED`. Only malformed or schema-invalid output is
eligible for the Planner's bounded format correction. Authentication,
availability, policy, and ordinary provider/runtime failures are not retried.

Core code never parses Markdown, extracts JSON from prose, requests hidden
reasoning, or passes package source, database content, POT files, or Python
objects to the model. Provider adapters remain a later-ticket concern.
