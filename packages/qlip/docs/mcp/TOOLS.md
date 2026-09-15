# QLIP MCP Tools

QLIP exposes 5 MCP tools for constraint discovery, request validation, and solving.
Call `qlip.shapes` first in any LM Studio session to learn the correct argument shapes.
LM Studio requires tool inputSchema.type == \"object\" and does not resolve refs, so tools/list returns simplified schemas. Strict validation happens at runtime inside validate_request.
All tool inputs are strict JSON (additionalProperties=false where specified).

## LM Studio Notes

- For list tools, prefer sending `{}` to avoid Form mode wrapper quirks.
- If Form mode injects `ids`/`tags_any` as `{}`, QLIP tolerates it, but when used they must be arrays.
- `include_params_schema` and `include_examples` should be booleans; string values like `"true"`/`"false"` (or `"1"`/`"0"`) are tolerated but discouraged.
- For validate/solve, prefer a top-level SolveRequest; the server unwraps `{request: ...}`, `{SolveRequest: ...}`, `{solve_request: ...}`, or `{payload: ...}` only when they are the sole key.

## Normalization (Conservative)

What is tolerated:
- list tools: `ids`/`tags_any` as `{}`, `""`, `null`, `{"ids":[...]}`/`{"tags_any":[...]}`, or a single string.
- shapes: `include_examples` as `"true"`/`"false"` or `"1"`/`"0"`.
- validate/solve: single-key wrapper objects like `{request: {...}}` or `{SolveRequest: {...}}`.

Scalar coercions (SolveRequest only):
- Booleans: `"true"`/`"false"` -> `true`/`false`
- Integers: digit strings -> int
- Numbers: float-like strings -> float
- Applied only to a small allowlist (solver limits, lattice dimensions, uniform_grid settings, artifacts flags, runtime limits).

Explicit non-behavior:
- Plugin params (`constraints[].params`, `guidance[].params`) are never coerced.
- Unknown keys are not dropped; schema validation remains strict.

## Runtime Objectives

`problem.objective` is optional. If omitted, QLIP keeps the legacy behavior and uses:
```json
{"type": "spp_energy"}
```

Supported live objective families:
- `spp_energy`: legacy SPP pair-energy minimization.
- `none`: zero objective, leaving feasibility constraints to define the solve.
- `density_packing`: native pair-distance packing proxy over live occupancy variables. The supported proxy is `pair_distance_packing`; set `direction` to `maximize` or `minimize`.
- `linear_property`: generic linear occupancy surrogate over `m.x[species, site]`; set `direction` and provide `property.terms`.
- `threshold_tradeoff`: hard bound on a linear property, with optional `spp_energy` or `none` base objective and optional weighted property tradeoff.

Density/packing example:
```json
{
  "type": "density_packing",
  "direction": "maximize",
  "proxy": "pair_distance_packing"
}
```

Linear property example:
```json
{
  "type": "linear_property",
  "direction": "minimize",
  "property": {
    "name": "property_x_estimate",
    "offset": 0.0,
    "terms": [
      {"species": "Sr", "site": 0, "coefficient": 1.0},
      {"site": 3, "coefficient": -0.2}
    ]
  }
}
```

Threshold tradeoff example:
```json
{
  "type": "threshold_tradeoff",
  "base_objective": "spp_energy",
  "property": {
    "name": "property_x_estimate",
    "terms": [
      {"species": "O", "coefficient": 0.5},
      {"species": "Ti", "site": 1, "coefficient": 2.0}
    ]
  },
  "threshold": {"sense": ">=", "value": 1.0},
  "tradeoff_direction": "maximize",
  "tradeoff_weight": 0.2
}
```

Do not combine non-`spp_energy` objective families with `guidance[].id = "objective.energy_spp"`; validation rejects that ambiguous mix.

## qlip.shapes

Purpose:
Return canonical args_schema + minimal example_args + pitfalls for QLIP tools.

When to call:
At the start of any LM Studio session (or when a tool call fails due to shape mismatch).

Input:
JSON object with optional fields:
- tool: optional tool name filter
- include_examples: boolean (default false)

Minimal examples:
```json
{}
```

```json
{"tool":"qlip.solve","include_examples":true}
```

Sample output (shortened):
```json
{
  "tools": [
    {
      "name": "qlip.solve",
      "description": "Run QLIP optimization ...",
      "args_schema": {"type":"object","required":["version","problem","constraints","guidance","solver"]},
      "example_args": {"version":"1.0","problem":{...},"constraints":[],"guidance":[],"solver":{"name":"gurobi"}},
      "notes": ["Preferred call shape is top-level SolveRequest; the server unwraps {request:...}, {SolveRequest:...}, {solve_request:...}, or {payload:...} when they are the only key."]
    }
  ]
}
```

## qlip.list_constraints

Purpose:
Return the catalog of registered constraint plugins and their params_schema.

When to call:
At the start of a session, before forming constraints[].

Input:
JSON object with optional filters:
- ids: array of constraint IDs to include
- tags_any: array of tags; returns entries matching any tag
- include_params_schema: boolean (default true)

Output:
Object with items[] of plugin_catalog_entry.

Minimal example:
```json
{}
```

Common errors & fixes:
- Extra fields rejected: remove unknown keys.
- Unknown ids: call qlip.list_constraints without filters to discover valid IDs.

## qlip.list_guidance

Purpose:
Return the catalog of registered guidance plugins and their params_schema.

When to call:
At the start of a session, before forming guidance[].

Input:
JSON object with optional filters:
- ids: array of guidance IDs to include
- tags_any: array of tags; returns entries matching any tag
- include_params_schema: boolean (default true)

Output:
Object with items[] of plugin_catalog_entry.

Minimal example:
```json
{}
```

Common errors & fixes:
- Extra fields rejected: remove unknown keys.
- Unknown ids: call qlip.list_guidance without filters to discover valid IDs.

## qlip.validate_request

Purpose:
Validate a SolveRequest against the JSON schema and installed plugins without solving.

When to call:
After any change to chemistry, design_space, constraints, guidance, or solver settings.

Input:
A SolveRequest object at the top level (do NOT wrap in {"request": ...}).

Output:
A ValidationReport with valid, errors[], warnings[], and optional normalized_request.

Minimal example (SrTiO3, density=4):
```json
{
  "version": "1.0",
  "problem": {
    "chemistry": {"formula": "SrTiO3"},
    "design_space": {
      "template": {
        "lattice": {
          "a": 3.9,
          "b": 3.9,
          "c": 3.9,
          "alpha": 90.0,
          "beta": 90.0,
          "gamma": 90.0,
          "units": "angstrom"
        }
      },
      "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}}
    }
  },
  "constraints": [
    {"id": "proximity.atomic_radii", "params": {"scale": 1.0}}
  ],
  "guidance": [],
  "solver": {"name": "gurobi"}
}
```

Common errors & fixes:
- Wrapped input: legacy {"request": ...} is accepted but deprecated; prefer top-level SolveRequest.
- Missing required fields: ensure version, problem, constraints, guidance, solver are present.
- Invalid constraint/guidance IDs: call list_constraints/list_guidance first.

## qlip.solve

Purpose:
Run QLIP optimization with the selected constraints and guidance.

When to call:
After validate_request returns valid=true.

Input:
A SolveRequest object at the top level (do NOT wrap in {"request": ...}).

Output:
Object with run_id and result (SolveResult). Status is OPTIMAL, FEASIBLE, INFEASIBLE, or ERROR.

Minimal example:
Use the same SolveRequest as qlip.validate_request.

Common errors & fixes:
- INFEASIBLE: relax constraints or reduce grid density.
- ERROR: confirm Gurobi is available and SPP POTs are accessible.
- Wrong solver: solver.name must be "gurobi".
