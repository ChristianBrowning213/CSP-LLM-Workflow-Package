# QLIP MCP Example Requests

These examples are generated from the authoritative JSON Schemas in `docs/mcp`.

## Generate examples

```powershell
python tools\mcp_generate_examples.py
```

The generator writes four JSON payloads under `examples/mcp/` and prints an
`OK: 0 schema errors` line for each.

## Use in MCP Inspector

1. Start the MCP server as usual.
2. In MCP Inspector, select the tool (`qlip.validate_request` or `qlip.solve`).
3. Paste the entire JSON file content into the tool input.

## Key schema requirements

- `version` must be exactly `"1.0"`.
- `solver` is required and must use the Gurobi solver.
- `problem.chemistry.formula` is required (no `composition` field).
- `problem.design_space.template.lattice` is required.
- `problem.design_space.sites.mode` must be `uniform_grid` or `explicit_fractional_sites`.
- `problem.objective` defaults to `{"type":"spp_energy"}` when omitted.
- Supported live objective families are `spp_energy`, `none`, `density_packing`, `linear_property`, and `threshold_tradeoff`.

## Objective examples

Legacy SPP energy:
```json
{"type": "spp_energy"}
```

Density/packing proxy:
```json
{"type": "density_packing", "direction": "maximize", "proxy": "pair_distance_packing"}
```

Linear property proxy:
```json
{
  "type": "linear_property",
  "direction": "minimize",
  "property": {
    "name": "property_x_estimate",
    "terms": [
      {"species": "Sr", "site": 0, "coefficient": 1.0},
      {"site": 3, "coefficient": -0.2}
    ]
  }
}
```

Threshold tradeoff:
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
