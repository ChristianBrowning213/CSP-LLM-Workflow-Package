# QLIP Migration Fileset

## Source gate

- Source repository: `C:\Users\brown\Documents\GitHub\qlip`
- Required and verified source revision: `a619ab379c62b5edefd6bb00076267e149f283ce`
- Source status before migration: clean

All destinations are relative to `CSP-LLM-Workflow-Package`. Directory rows
mean every named file immediately listed beneath that directory, not an
unbounded repository copy.

## Core API

| Source | Destination |
|---|---|
| `src/qlip/__init__.py` | `packages/qlip/src/qlip/__init__.py` |
| `src/qlip/__main__.py` | `packages/qlip/src/qlip/__main__.py` |
| `src/qlip/allocation.py` | `packages/qlip/src/qlip/allocation.py` |
| `src/qlip/grids.py` | `packages/qlip/src/qlip/grids.py` |
| `src/qlip/motifs.py` | `packages/qlip/src/qlip/motifs.py` |

## Schemas

| Source | Destination |
|---|---|
| `docs/mcp/MCP_SCHEMA.json` | `packages/qlip/src/qlip/resources/schemas/MCP_SCHEMA.json` |
| `docs/mcp/MCP_TOOL_DEFS.json` | `packages/qlip/src/qlip/resources/schemas/MCP_TOOL_DEFS.json` |

`MCP_TOOL_DEFS.json` is a required transitive MCP resource omitted from the
Ticket 2 manifest: `qlip.mcp.server` reads it at import time alongside the
listed schema bundle.

## Validation

| Source | Destination |
|---|---|
| `src/qlip/core/chemistry.py` | `packages/qlip/src/qlip/core/chemistry.py` |
| `src/qlip/core/paths.py` | `packages/qlip/src/qlip/core/paths.py` |
| `src/qlip/core/preflight.py` | `packages/qlip/src/qlip/core/preflight.py` |
| `src/qlip/core/validate.py` | `packages/qlip/src/qlip/core/validate.py` |

## Solver/model construction

| Source | Destination |
|---|---|
| `src/qlip/core/__init__.py` | `packages/qlip/src/qlip/core/__init__.py` |
| `src/qlip/core/models.py` | `packages/qlip/src/qlip/core/models.py` |
| `src/qlip/core/objectives.py` | `packages/qlip/src/qlip/core/objectives.py` |
| `src/qlip/core/solve.py` | `packages/qlip/src/qlip/core/solve.py` |

## Constraints

| Source | Destination |
|---|---|
| `src/qlip/constraints/__init__.py` | `packages/qlip/src/qlip/constraints/__init__.py` |
| `src/qlip/constraints/proximity.py` | `packages/qlip/src/qlip/constraints/proximity.py` |
| `src/qlip/constraints/motif_linking.py` | `packages/qlip/src/qlip/constraints/motif_linking.py` |
| `src/qlip/constraints/radii.json` | `packages/qlip/src/qlip/resources/radii.json` |

## Guidance/objectives

| Source | Destination |
|---|---|
| `src/qlip/plugins/__init__.py` | `packages/qlip/src/qlip/plugins/__init__.py` |
| `src/qlip/plugins/base.py` | `packages/qlip/src/qlip/plugins/base.py` |
| `src/qlip/plugins/registry.py` | `packages/qlip/src/qlip/plugins/registry.py` |

## SPP interactions

| Source | Destination |
|---|---|
| `src/qlip/interactions/spp.py` | `packages/qlip/src/qlip/interactions/spp.py` |
| `src/qlip/interactions/spheres.py` | `packages/qlip/src/qlip/interactions/spheres.py` |

## Scaffolds / ordered occupation

| Source | Destination |
|---|---|
| `src/qlip/scaffolds/__init__.py` | `packages/qlip/src/qlip/scaffolds/__init__.py` |
| `src/qlip/scaffolds/schema.py` | `packages/qlip/src/qlip/scaffolds/schema.py` |
| `src/qlip/scaffolds/registry.py` | `packages/qlip/src/qlip/scaffolds/registry.py` |
| `src/qlip/scaffolds/occupation.py` | `packages/qlip/src/qlip/scaffolds/occupation.py` |
| `src/qlip/scaffolds/multi.py` | `packages/qlip/src/qlip/scaffolds/multi.py` |
| `src/qlip/scaffolds/topk.py` | `packages/qlip/src/qlip/scaffolds/topk.py` |
| `src/qlip/scaffolds/exclusion.py` | `packages/qlip/src/qlip/scaffolds/exclusion.py` |
| `src/qlip/paper_diversity/smoke_preparation.py` | `packages/qlip/src/qlip/scaffolds/nasicon.py` |

The paper-named source file is relocated as the runtime NASICON adapter listed
by Ticket 2. Its external corpus inputs are not bundled.

## CIF decode/export and visualization runtime helper

| Source | Destination |
|---|---|
| `src/qlip/visualization/__init__.py` | `packages/qlip/src/qlip/visualization/__init__.py` |
| `src/qlip/visualization/plot.py` | `packages/qlip/src/qlip/visualization/plot.py` |

These files are transitive runtime additions. Ticket 2 recorded the module as
absent, while the frozen source audit proved it is tracked and required by
`core.solve` for assignment extraction/CIF output.

## MCP boundary

| Source | Destination |
|---|---|
| `src/qlip/mcp/__init__.py` | `packages/qlip/src/qlip/mcp/__init__.py` |
| `src/qlip/mcp/boundary.py` | `packages/qlip/src/qlip/mcp/boundary.py` |
| `src/qlip/mcp/normalize.py` | `packages/qlip/src/qlip/mcp/normalize.py` |
| `src/qlip/mcp/server.py` | `packages/qlip/src/qlip/mcp/server.py` |

MCP dependencies remain an optional package extra; direct Python solve and
validation imports do not require MCP.

## Resources

| Source | Destination |
|---|---|
| `data/base/elements.json` | `packages/qlip/src/qlip/resources/base/elements.json` |
| `data/base/ionic_radii.json` | `packages/qlip/src/qlip/resources/base/ionic_radii.json` |
| `data/base/pair_distance_policy.json` | `packages/qlip/src/qlip/resources/base/pair_distance_policy.json` |
| `data/base/provenance.json` | `packages/qlip/src/qlip/resources/base/provenance.json` |
| `data/base/radii.json` | `packages/qlip/src/qlip/resources/base/radii.json` |
| `data/base/radius_policy.json` | `packages/qlip/src/qlip/resources/base/radius_policy.json` |
| `src/qlip/interactions/SPP/SPP/O-O/O-O.POT` | `packages/qlip/src/qlip/resources/spp/O-O/O-O.POT` |
| `src/qlip/interactions/SPP/SPP/O-Sr/O-Sr.POT` | `packages/qlip/src/qlip/resources/spp/O-Sr/O-Sr.POT` |
| `src/qlip/interactions/SPP/SPP/O-Ti/O-Ti.POT` | `packages/qlip/src/qlip/resources/spp/O-Ti/O-Ti.POT` |
| `src/qlip/interactions/SPP/SPP/Sr-Sr/Sr-Sr.POT` | `packages/qlip/src/qlip/resources/spp/Sr-Sr/Sr-Sr.POT` |
| `src/qlip/interactions/SPP/SPP/Sr-Ti/Sr-Ti.POT` | `packages/qlip/src/qlip/resources/spp/Sr-Ti/Sr-Ti.POT` |
| `src/qlip/interactions/SPP/SPP/Ti-Ti/Ti-Ti.POT` | `packages/qlip/src/qlip/resources/spp/Ti-Ti/Ti-Ti.POT` |

The six canonical pair files are the minimal complete SrTiO3 set. Reverse-name
duplicates and every noncanonical regulator/corpus tree remain excluded.
Package marker files under `qlip/resources/` are new packaging infrastructure.

## Tests

| Source | Destination |
|---|---|
| `tests/test_validate_request.py` | `tests/unit/qlip/test_validate.py` |
| `tests/test_runtime_objective_contract.py` | `tests/unit/qlip/test_objectives.py` |
| `tests/test_registry_catalog.py` | `tests/unit/qlip/test_plugins.py` |
| `tests/test_ordered_orbits.py` | `tests/unit/qlip/test_ordered_orbits.py` |
| `tests/test_generalized_ordered_occupation.py` | `tests/unit/qlip/test_occupation.py` |
| `tests/test_spp_periodic.py` | `tests/unit/qlip/test_spp_periodic.py` |
| `tests/test_spp_unordered_periodic.py` | `tests/unit/qlip/test_spp_unordered_periodic.py` |
| `tests/test_solve_smoke.py` | `tests/integration/qlip/test_solve.py` |
| `tests/test_solve_success_returns_non_placeholder_cif.py` | `tests/integration/qlip/test_cif_output.py` |
| `tests/test_solve_time_limit_incumbent_handling.py` | `tests/integration/qlip/test_time_limit.py` |
| `tests/test_nasicon_ordered_orbit_runner.py` | `tests/integration/qlip/test_nasicon.py` |
| `tests/test_spp_e2e_benchmark.py` | `tests/integration/qlip/test_spp_e2e.py` |
| `tests/helpers/solve_test_support.py` | `tests/qlip_support/solve_test_support.py` |
| `tools/audit_spp_objective.py` | `tests/qlip_support/audit_spp_objective.py` |

The unordered and end-to-end tests became approved migration tests in Ticket
3. The two helper modules are direct test-only dependencies missed by the
file-level manifest. The audit CLI is not shipped; only its frozen enumerator
is retained under tests so approved scientific assertions are not weakened.

## Examples

| Source | Destination |
|---|---|
| `examples/mcp/README.md` | `examples/qlip/mcp/README.md` |
| `examples/mcp/*.json` | `examples/qlip/mcp/*.json` |
| New packaged-resource smoke | `examples/qlip/solve_srtio3.py` |

## Deliberately excluded

- `src/qlip/spp/` historical runners and their missing-module dependencies
- `src/qlip/experimental/`
- general `src/qlip/paper_diversity/` tooling beyond the named adapter
- broad/reverse-duplicate POT and regulator trees
- `tools/` as installed runtime or CLI surface
- benchmark scripts, generated artifacts, output directories, datasets, and
  the external NASICON scaffold corpus
- Crystal-DB, SPP-Maker-QLIP, Skill-Loop-CSP, SCA, and workflow implementation
