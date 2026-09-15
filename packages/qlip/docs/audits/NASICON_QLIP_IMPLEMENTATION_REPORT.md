# NASICON QLIP implementation report

## Scope and decision

Decision: **GO_AFTER_SMALL_EXTENSION**.

QLIP did not previously expose executable scaffold or orbit-closure machinery. Its production site modes were `uniform_grid` and `explicit_fractional_sites`; allocation used one binary `x[species, site]`, exact species counts, and at-most-one species per candidate site. The change adds generic `ordered_orbits` to explicit sites. It is not NASICON-specific and does not emit a stored reference CIF.

The selected first target is the fully ordered 40-site C2 representation of Na6Zr4Si4P2O24 (two Na3Zr2Si2PO12 formula units) from Materials Project record `mp-1221148`. Na, Zr, and O orbits are fixed. Four tetrahedral-centre orbits allow Si/P; exact stoichiometry and orbit multiplicities leave three feasible symmetry-closed assignments.

## Implementation

- `docs/mcp/MCP_SCHEMA.json`: adds validated `ordered_orbits` records with orbit ID, non-overlapping site indices, allowed formula species, and required-occupancy semantics.
- `src/qlip/core/validate.py`: rejects duplicate orbit IDs, unknown species, overlapping sites, and out-of-domain indices.
- `src/qlip/allocation.py`: enforces a common species assignment across every site in an ordered orbit, excludes disallowed species, and optionally requires full occupancy.
- `src/qlip/core/solve.py`: transfers orbit data into the allocation model and records separate model-build and solver timings.
- `src/qlip/core/models.py`: exposes the optional orbit records in the Python request model.
- `scripts/run_nasicon_qlip_smoke.py`: builds the request from the frozen cell/orbit table, enumerates all feasible Si/P assignments, runs QLIP, independently rescores the output, and records hashes and structural checks.
- `tests/test_ordered_orbits.py`: focused schema, semantic-validation, and closure-constraint tests.

## Standalone smoke evidence

Command:

```powershell
$env:QLIP_ALLOWED_PATH_ROOTS='C:\Users\brown\Documents\GitHub\qlip;C:\Users\brown\Documents\GitHub\Skill-Loop-CSP'
.\.venv\Scripts\python.exe scripts\run_nasicon_qlip_smoke.py --reference-cif C:\Users\brown\Documents\GitHub\Skill-Loop-CSP\data\nasicon\reference\reference.cif --orbit-table C:\Users\brown\Documents\GitHub\Skill-Loop-CSP\data\nasicon\reference\orbit_table.csv --pot-root C:\Users\brown\Documents\GitHub\Skill-Loop-CSP\artifacts\nasicon_spp\full\spp_root --out-dir artifacts\nasicon_qlip_smoke
```

Observed result:

| Metric | Value |
|---|---:|
| candidate sites | 40 |
| species | 5 |
| binary variables | 200 |
| auxiliary variables | 0 |
| constraints | 259 |
| physical periodic pair-image terms in solved structure | 8,153 |
| cutoff | 11.0 Å |
| model build | 15,483 ms |
| Gurobi solve | 108 ms |
| total reported time | 15,634 ms |
| status | OPTIMAL |
| objective | 6775.94560329246 |
| output rescore | 6775.945603292451 |
| parity absolute error | 9.09e-12 |
| output reduced formula | Na3Zr2Si2PO12 |
| duplicate occupied coordinates | 0 |

The three feasible objectives were 6775.945603292457 (P on reference `p_1_2c`), 6890.892143744105 (P on both singleton orbits), and 6916.294769903814 (P on `si_3_2c`). Pair coefficients therefore affect a real discrete choice. The solution CIF SHA-256 is `d946cfd2ee4edfa46624e32db414ea04dc20173f4b0cbbd6fb02ba2db43cbf8d`; the frozen reference SHA-256 is `5f1b7b14e6c1abf3a209c8d9557948ac67282de47283f4af2ee409e23ca228b8`, so the emitted file is not a byte copy.

## CIF and claim boundaries

The emitted CIF preserves the selected cell and solved species coordinates and parses to the correct formula. ASE's generic writer does not preserve the input C2 space-group metadata in the CIF text; symmetry must be reanalysed from coordinates. This limitation existed before the extension.

This run is best described as **scaffold-constrained discrete occupational optimization**, not unconstrained crystal structure prediction: cell and candidate coordinates are fixed from the ordered reference scaffold, while the Si/P orbit allocation is optimized. The SPP is a statistical proxy; no thermodynamic stability, novelty, ionic conductivity, experimental realizability, or synthesis claim follows.

The full-corpus POT files cover all 15 pairs and pass file compatibility, but the SPP-Maker-QLIP cap-fraction quality gate classifies several sparse curves as `unusable`/diagnostic-only. That limitation is retained in downstream reports and prevents a calibrated energy interpretation.
