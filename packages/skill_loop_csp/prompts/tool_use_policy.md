# Tool Use Policy

- Enforce path sandboxing client-side for all read/write paths.
- Enforce caps client-side before and after SPP calls.
- Never send unknown top-level keys to QLIP solve requests.
- Write request/response logs with hashes for every tool call.
- Keep run IDs deterministic from canonicalized run inputs.
