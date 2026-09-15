# QLIP Migration Source Audit

## Scope and starting state

This audit freezes the QLIP source used by the later packaging migration. No
files were copied to the packaging repository during this work.

- Repository: `C:\Users\brown\Documents\GitHub\qlip`
- Branch: `QLIP-SPP-MCP-Esma`
- Starting commit: `40874730c8ac0d5b5cc86d045494af6f13b1281c`
- Starting tracked diff stat: 4 files changed, 73 insertions, 17 deletions

The initial `git status --short` was:

```text
 M data/base/provenance.json
 M src/qlip/interactions/spp.py
 M tests/test_spp_e2e_benchmark.py
 M tests/test_spp_periodic.py
 M tools/audit_spp_objective.py
?? docs/SPP_PERIODIC_SELF_IMAGE_CORRECTION.md
?? tests/test_spp_unordered_periodic.py
```

The changes were inspected before modification:

| Path | Purpose | Classification |
|---|---|---|
| `src/qlip/interactions/spp.py` | Adds the 0.5 diagonal periodic self-image multiplicity and applies it in scoring and objective coefficients. | Periodic SPP correction |
| `tests/test_spp_periodic.py` | Updates independent reference expectations and regression assertions to unordered self-image semantics. | Periodic SPP correction |
| `tests/test_spp_unordered_periodic.py` | Adds analytic self-image, off-diagonal, nonperiodic, cell-representation, and audit regressions. | Periodic SPP correction |
| `tests/test_spp_e2e_benchmark.py` | Updates the real-POT SrTiO3 objective expected after removing diagonal double counting. | Periodic SPP correction |
| `tools/audit_spp_objective.py` | Exposes per-image multiplicity and applies it in an independently enumerated objective breakdown. | Periodic SPP correction |
| `docs/SPP_PERIODIC_SELF_IMAGE_CORRECTION.md` | Records the defect, corrected convention, regression scope, and historical-result boundary. | Periodic SPP correction |
| `data/base/provenance.json` | Initially had no normalized content difference from `HEAD`; its index and filtered worktree hashes were identical. Full tests regenerate only `generated_at_utc`. | Unrelated generated state; excluded and restored |

## Periodic SPP interaction semantics

QLIP constructs one coefficient for each unordered site-index pair `i <= j`.
For each coefficient it enumerates integer lattice translations symmetrically
and includes every translated distance satisfying `0 < distance <= cutoff`.

- `i < j`: the atom pair is unordered at the site-pair level. Every qualifying
  image of `j` relative to `i` contributes at multiplicity 1. The translation
  enumeration is directed from the selected representative `i` to images of
  `j`, but it is not repeated as a separate `j, i` site pair.
- `i == j`, zero translation: excluded because its distance is zero.
- `i == j`, nonzero translation: included when within the cutoff. Symmetric
  translations `+T` and `-T` describe the same physical self-image bond from
  opposite directions, so each directed term has multiplicity 0.5. Together
  they contribute one unordered physical interaction.

Previously the diagonal terms used multiplicity 1 for both `+T` and `-T`.
That doubled periodic same-site/self-image energy. Off-diagonal interactions
were already counted under the intended convention and are unchanged.

`periodic_spp_sum()` centralizes this rule. `SPPCollection.score()` passes
explicit atom-identity information, and `SPPCollection.pair_cost_matrix()`
passes `i == j`, so standalone scoring and solver objective construction use
the same multiplicity. The public helper retains coordinate-based inference
only for callers that omit the explicit identity flag.

## Cutoff verification

The global scientific default remains `DEFAULT_SPP_CUTOFF = 11.0` angstrom.
The implementation uses an inclusive upper boundary (`distance <= cutoff`),
excludes only distances at or below `1e-12`, and enumerates translations to a
conservative image depth based on cell-vector lengths. Existing tests cover
the 11 angstrom boundary, multiple images, cubic and non-cubic orthorhombic
cells, and independent reference coefficient enumeration.

An additional independent constant-potential enumeration for a 5 angstrom
cubic cell at the canonical 11 angstrom cutoff found 32 directed nonzero
self-image translations, equivalent to 16 unordered pairs. QLIP returned
exactly 16.0.

## Independent semantic checks

Analytic checks used a constant potential and an enumeration that did not call
QLIP's periodic helper:

| Case | Directed images | Expected unordered total | QLIP total |
|---|---:|---:|---:|
| Unlike species at fractional separation `(0.5, 0, 0)`, 5 angstrom cell, 2.6 angstrom cutoff | 2 | 2.0 | 2.0 |
| One atom with periodic self-images, 5 angstrom cell, 5.1 angstrom cutoff | 6 | 3.0 | 3.0 |
| One atom with periodic self-images, 5 angstrom cell, 11 angstrom cutoff | 32 | 16.0 | 16.0 |

The standalone `tools/audit_spp_objective.py` was also run on the bundled
SrTiO3 CIF and bundled POT tree at 11 angstrom. It enumerated 1,346 explicit
SPP terms: 400 directed diagonal terms (200 unordered equivalents) and 946
full-weight off-diagonal terms. Its total was `4.883033620558706`; direct
`SPPCollection.score()` returned `4.883033620558714`, a difference of
`-7.99e-15`.

## Solver/scorer parity and end-to-end result

The canonical bundled-grid SrTiO3 test ran with the local Gurobi installation.
The solve was `OPTIMAL`, the returned CIF parsed, the composition was exactly
`O3 Sr1 Ti1`, all occupied sites were valid and unique, and the periodic score
was finite. The solver objective and standalone scorer agreed within the
test's `1e-9` tolerance at `4.883033620558714`. The optimized structure also
scored below the deterministic bad assignment.

The old expected objective, `10.675031383326704`, included the doubled
diagonal self-image contribution. Historical results were not rewritten and
must be compared using their source revision and counting convention.

## Visualization import diagnosis

The reported missing-module chain could not be reproduced at the starting
commit. `src/qlip/visualization/plot.py` is tracked at `HEAD` and contains the
real `_extract_placements()` implementation used by `qlip.core.solve` to
decode solver assignments when producing CIF text. It is not a placeholder.

A freshly built wheel contained both `qlip/visualization/__init__.py` and
`qlip/visualization/plot.py`. The module guards its optional Matplotlib and
`scipy.spatial.ConvexHull` imports, while assignment extraction itself needs
neither. Fresh-process imports of `qlip.core.solve` and the public solver API
therefore succeeded. No visualization code change was justified; duplicating
the helper or adding a fake module would have increased risk.

The private cross-layer import is still architectural coupling worth revisiting
during packaging, but it is not an absent-module defect in this revision.

## API import verification

The following succeeded in a new Python process using the repository virtual
environment:

```python
import qlip
from qlip.core.validate import validate_request
from qlip.core.solve import solve
from qlip.interactions.spp import periodic_spp_sum
from qlip import solve as public_solve
```

`qlip.solve` remains the supported top-level solver interface identified by
the migration manifest. No documented/actual API discrepancy was found for
this surface.

## Regression results

Focused minimum command:

```text
.venv\Scripts\python.exe -m pytest -q tests/test_spp_periodic.py tests/test_spp_unordered_periodic.py tests/test_spp_e2e_benchmark.py
37 passed, 0 failed, 0 skipped, 4 warnings
```

Expanded SPP/public-surface command selected all 15 test files found by
searching for `SPPCollection`, `periodic_spp`, `energy_spp`, or
`spp_objective`:

```text
90 passed, 0 failed, 0 skipped, 6 warnings
```

The first full-suite run exposed two pre-existing MCP output-schema failures:
the runtime emitted `missing_pairs_use_regulator_fallback` but
`MCP_TOOL_DEFS.json` had `additionalProperties: false` without declaring that
existing boolean. The smallest contract repair added that one property. Its
focused regression result was 9 passed, and the final broad run was:

```text
.venv\Scripts\python.exe -m pytest -q
260 passed, 0 failed, 0 skipped, 37 warnings
```

Warnings are existing deprecation warnings from compatibility constraint
exports, `jsonschema.RefResolver`, and spglib; none represents a test failure.

## Provenance decision

`data/base/provenance.json` does not record SPP implementation semantics or
POT provenance for this correction. At capture time its normalized worktree
blob exactly matched `HEAD`, despite appearing modified due to worktree/index
metadata and mixed line endings. The full test suite later regenerated only
`generated_at_utc`; that test side effect was restored. The file is excluded
from the migration-source commit. Scientific change provenance is instead in
the dedicated correction document and this audit.

## Deferred packaging issues

- `src/qlip/interactions/spp.py`, which is in `MIGRATE_RUNTIME`, directly
  imports `scipy.interpolate.interp1d`. SciPy is installed transitively in the
  current environment (version 1.17.0 via ASE/pymatgen/SMACT) but is not a
  direct dependency in `pyproject.toml`, `requirements.txt`, or wheel metadata.
  Declare it directly in Ticket 4 as instructed.
- `src/qlip/mcp/server.py` resolves `docs/mcp/MCP_SCHEMA.json` and
  `docs/mcp/MCP_TOOL_DEFS.json` relative to a repository root. Neither schema
  file is present in the current wheel. Ticket 4 must move/package resources
  and load them using package-resource APIs.
- The built wheel contains zero bundled `.POT` files even though core solve
  defaults to `src/qlip/interactions/SPP/SPP`. Ticket 4 must package the POT
  resource tree or establish an explicit external asset contract.
- The visualization module is packaged, but core solve imports a private
  assignment-extraction helper from it. Preserve the real helper during
  migration or relocate it deliberately; do not replace it with plotting
  stubs.

## Freeze decision

The periodic correction is scientifically consistent with unordered
self-image counting, its objective/scorer parity is directly demonstrated,
the canonical solve succeeds, required imports work, and the full local suite
passes. The validated files are suitable for one migration-source commit.
The exact final commit hash is recorded in the ticket completion report after
the commit is created.
