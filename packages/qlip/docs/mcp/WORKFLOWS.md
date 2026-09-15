# QLIP MCP Workflows

This guide describes a practical, repeatable conversational loop for solving QLIP requests.

## Conversation loop (5 steps)

1) Gather chemistry and design_space details (formula, lattice, site generation mode).
2) Call qlip.list_constraints and qlip.list_guidance to discover valid IDs and params.
3) Propose a SolveRequest (top-level, no wrapper) that matches the schemas.
4) Call qlip.validate_request and fix any schema or plugin errors.
5) Call qlip.solve and interpret the result status.

## If INFEASIBLE: how to relax

- Lower uniform grid density (fewer candidate sites).
- Broaden the lattice (increase a/b/c) to reduce crowding.
- Reduce the proximity.atomic_radii scale parameter (e.g., 1.0 -> 0.9).
- Remove or disable motif.linking constraints for early feasibility checks.
- Remove optional guidance or simplify guidance_mode to weighted_sum only.
- Reduce hard constraints count to isolate the first conflicting rule.

## If ERROR: deterministic debug steps

1) Verify Gurobi availability on the host.
2) Confirm SPP POT paths: set QLIP_SPP_POT_DIR or ensure defaults exist under src\qlip\interactions\SPP\SPP.
3) If paths are restricted, set QLIP_ALLOWED_PATH_ROOTS to include the POT root.
4) Set QLIP_TRACEBACK=1 to print a full stack trace on errors.
5) Set QLIP_DEBUG_SPP=1 to log the resolved POT root and filenames.
6) Re-run with the same SolveRequest and compare errors[] for deterministic reproduction.
