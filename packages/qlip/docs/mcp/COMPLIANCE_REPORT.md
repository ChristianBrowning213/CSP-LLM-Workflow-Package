# MCP Compliance Report (qlip-mcp)

Summary: FAIL

## Tool surface checks

Tool | Implemented? | Name exact? | Input schema exact? | Output schema exact? | Notes
---|---|---|---|---|---
qlip.list_constraints | Yes | Yes | No | No | Tool signature only; no schema registration/validation against `docs/mcp/MCP_TOOL_DEFS.json`.
qlip.list_guidance | Yes | Yes | No | No | Same issue as above.
qlip.validate_request | Yes | Yes | No | No | Accepts args but does not validate against tool schema.
qlip.solve | Yes | Yes | No | No | No explicit schema enforcement; relies on function signature.

## Schema checks (SolveRequest/SolveResult)

- SolveRequest validation: PASS. `src/qlip/core/validate.py` uses `jsonschema.Draft202012Validator` with `docs/mcp/MCP_SCHEMA.json`, rejects unsupported guidance modes, and validates the live objective families exposed by the runtime contract.
- SolveResult conformance: FAIL. `src/qlip/core/models.py` uses `dataclasses.asdict()` in `SolveResult.to_dict`, which serializes `SolveError.details=None` as `"details": null`. The schema requires `details` to be an object when present (no `null`). This violates `docs/mcp/MCP_SCHEMA.json` for most error cases.

## Plugin system checks

- Registered plugins only: PASS. `src/qlip/plugins/registry.py` uses static registries, and `validate_request` enforces IDs + per-plugin params schemas.
- No arbitrary code: PASS. There is no dynamic import or class loading from requests.
- Note: `src/qlip/core/solve.py` still skips unknown plugins if called directly without validation; however `solve()` always calls `validate_request(strict=True)` first.

## Gurobi-only checks

- PASS. `src/qlip/allocation.py` rejects non-`gurobi` solvers. `src/qlip/core/solve.py` uses `SolverFactory("gurobi")` only.
- `rg -n "highs|glpk|cbc|scip|cplex|solver=" src/qlip -S` shows no fallback solvers in the core path.

## Path safety checks

Field | Location | Handling | Issue
---|---|---|---
`context.pot_root` | `src/qlip/core/solve.py`, `src/qlip/core/validate.py` | `Path(...).expanduser().resolve()` in solve; raw `Path(...)` in validate | No restriction to safe roots; accepts arbitrary paths. No explicit guardrails for MCP server.
`context.motif_root` | `src/qlip/core/validate.py` | `Path(...)` used; existence check only | No normalization to safe roots; accepts arbitrary paths.
`constraints[].params.motif_dir` | `src/qlip/plugins/registry.py`, `src/qlip/core/solve.py` | Passed through to `Allocation.enable_motifs()` | No normalization or safety checks; arbitrary path allowed.
`artifacts.vesta_path` | `src/qlip/core/models.py` only | Not used in core or MCP | Path handling not implemented; no guardrails documented in code.
Output paths | `src/qlip/core/solve.py` | CIF returned as text | OK for MCP. (CLI writes `viz/structure.cif`, but that is outside MCP.)

The architecture doc calls for “No arbitrary file paths unless explicitly whitelisted,” but the current implementation does not enforce a whitelist or safe-root checks.

## Required fixes (prioritized, minimal diffs)

1) Enforce tool schemas in `src/qlip/mcp/server.py` (either register schemas with the MCP SDK or validate inputs/outputs against `docs/mcp/MCP_TOOL_DEFS.json` / `docs/mcp/MCP_SCHEMA.json`).
2) Fix SolveResult error serialization so `details` is omitted when `None` (avoid `null`), or ensure it is always an object.
3) Add path safety guardrails for `pot_root`, `motif_root`, and `motif_dir` (normalize, restrict to safe roots, or explicitly document local-only trust assumptions in code paths).

## Fix plan

1) `src/qlip/mcp/server.py`: load `docs/mcp/MCP_TOOL_DEFS.json` and validate tool inputs/outputs with `jsonschema.Draft202012Validator`.
2) `src/qlip/core/models.py` and/or `src/qlip/core/solve.py`: serialize `SolveResult` via `SolveError.to_dict()` to avoid `details: null`.
3) `src/qlip/core/solve.py` + `src/qlip/core/validate.py` + `src/qlip/plugins/registry.py`: enforce safe-root checks for path inputs or document explicit local-only trust policy.
