# QLIP Packaging Notes

## Source revision

QLIP was migrated only from the clean source revision:

```text
a619ab379c62b5edefd6bb00076267e149f283ce
```

The source repository was clean before migration and remained read-only.

## Migrated capabilities

- `qlip.solve` and `qlip.core.solve.solve`
- strict `validate_request` request/schema/preflight validation
- Pyomo allocation and Gurobi solver dispatch
- objective contracts and registered constraint/guidance plugins
- proximity and motif-linking constraints
- periodic SPP loading, scoring, corrected unordered self-image counting, and
  solver/scorer coefficient parity
- CIF assignment decoding and export through the existing visualization helper
- ordered occupation, generic scaffold records/registry, multi/top-k/exclusion
  primitives, and the relocated NASICON task adapter
- direct CLI (`python -m qlip`)
- optional MCP boundary with packaged schemas/tool definitions
- small chemistry/base-data tables
- six canonical SrTiO3 POT files for offline regression/example use

## Packaging repairs

Repository-relative base-data, schema, tool-definition, and default POT paths
were replaced with a small `importlib.resources` boundary in
`qlip.resources`. The wheel declares its JSON and POT files as package data.
Default path authorization now permits the installed package resources and the
current working directory; callers can retain strict explicit roots through
`QLIP_ALLOWED_PATH_ROOTS`.

The package directly declares the dependencies imported or required by the
supported core runtime: ASE, Gurobi's Python binding, NumPy, Pymatgen, Pyomo,
and SciPy. MCP and Jsonschema are isolated in the optional `mcp` extra. Test
dependencies are in the `test` extra. Matplotlib remains optional because the
existing visualization module guards it and core CIF extraction does not use
it.

## Canonical packaged resources

Only these POT pairs are bundled:

```text
O-O  O-Sr  O-Ti  Sr-Sr  Sr-Ti  Ti-Ti
```

They are the complete pair set for the small SrTiO3 regression. Reverse-name
duplicates were omitted because pair lookup is canonical and verifies the six
files directly. Larger POT sets, regulator trees, and generated potentials are
external data dependencies supplied through request configuration or
`QLIP_SPP_POT_DIR`.

## Scientific parity

The identical 2x2x2 cubic SrTiO3 request was solved against both the frozen
source and an installed wheel from a temporary directory.

| Result | Frozen source | Installed package |
|---|---:|---:|
| Status | `OPTIMAL` | `OPTIMAL` |
| Objective | `4.883033620558714` | `4.883033620558714` |
| Periodic SPP score | `4.883033620558713` | `4.883033620558713` |
| Composition | `O3 Sr1 Ti1` | `O3 Sr1 Ti1` |
| Cell | `3.9, 3.9, 3.9, 90, 90, 90` | identical |
| Fractional placements | five deterministic sites | identical |

Both CIFs parsed successfully. The installed import, base data, schemas, and
POT paths all resolved beneath the temporary installation target; no resource
was loaded from `C:\Users\brown\Documents\GitHub\qlip`.

## Verification

- Migrated source-tree QLIP tests: `85 passed, 1 skipped, 6 warnings`
- Installed-wheel QLIP tests: `85 passed, 1 skipped, 6 warnings`
- Whole clean-repository tests using installed QLIP: `86 passed, 1 skipped, 6 warnings`
- Wheel smoke: imports, public solve identity, core/MCP schemas, six POTs,
  validation, solve, CIF parse, composition, and scorer parity all passed

The one skip is the NASICON integration requiring the deliberately external
hash-verified scaffold corpus. Warnings are inherited deprecations for removed
compatibility constraint exports and Jsonschema's `RefResolver`.

`python -m build` was attempted but the source environment does not contain
the `build` frontend. The permitted equivalent `pip wheel --no-deps
--no-build-isolation` succeeded and produced a 156,750-byte wheel with SHA-256
`db5f1850a68ce92145843313de6727e98dac0c7a36594415ae1c82bec4944023`.

## Explicitly not migrated

- historical `qlip.spp` runners and missing legacy dependencies
- experimental guidance and symmetry constraints
- paper-diversity campaign code beyond the named NASICON runtime adapter
- benchmark runners, generated artifacts, output directories, and audit CLI
- broad POT/regulator trees and reverse-name duplicate POT files
- the external NASICON CIF corpus
- Crystal-DB, SPP-Maker-QLIP, Skill-Loop-CSP orchestration, SCA, and their data

The frozen objective enumerator exists only under repository tests so the
approved scientific tests remain intact; it is not installed with QLIP.

## Remaining technical debt

- `core.solve` imports private `_extract_placements` from
  `visualization.plot`. The real module is packaged unchanged to minimize
  scientific risk, but assignment decoding should eventually move to a
  non-visual internal boundary.
- Real solving requires a working Gurobi installation and license, not merely
  the declared `gurobipy` distribution.
- Non-SrTiO3 chemistry requires an explicit compatible POT root. Large asset
  versioning, hashes, licensing, and distribution remain future work.
- Scaffold registry records require the external NASICON corpus through an
  explicit argument or `QLIP_SCAFFOLD_CORPUS_ROOT`. Sibling-repository fallback
  remains source-compatible technical debt and is not used by installed-wheel
  validation.
- Optional diagnostic and CLI output defaults still derive locations from the
  installed module layout. Callers should configure writable output paths.
- The MCP server retains deprecated `jsonschema.RefResolver` usage.
