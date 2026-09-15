# Dynamic search-cell contract

Version: `retrieval_feasible_cell_v1`

This contract replaces the single global volume-per-atom box only for a new,
separately frozen campaign. It does not alter `paper_final_v1`.

## Inputs and leakage controls

The inputs are the literal target composition and the same ordered CIF cohort
already selected for request-SPP fitting. No second retrieval is issued. Each
valid CIF contributes `cell volume / atom count` in A^3/atom. The policy excludes:

- any CIF with the exact reduced target composition;
- any caller-declared target or reference CIF SHA-256;
- repeated CIF SHA-256 values after their first ranked occurrence;
- missing, hash-mismatched, unparsable, empty, nonpositive-volume, or
  nonfinite-volume structures.

At least five valid observations are required. Their median is `v_retrieval`,
and `V_prior = N_target * v_retrieval`. If fewer than five survive, the status is
`RETRIEVAL_VOLUME_INSUFFICIENT` and the explicit fallback is the frozen
`mp_stable_10k_v1` global median, 17.986899303180298 A^3/atom. The shape remains
cubic; retrieval does not infer lattice ratios in this version.

## Exact hard-feasibility model

For each proposed edge, the policy builds the same 4x4x4 QLIP uniform grid and
uses QLIP `Allocation.encode()` with the real
`proximity.atomic_radii(scale=1.0, allow_self_overlap=false)` plugin. Exact
stoichiometry, one species-or-vacancy state per site, and exact vacancy count
are therefore shared with the scientific QLIP solve. The SPP objective is
deactivated and replaced by zero. Each check uses Gurobi with a 60 s limit,
zero MIP gap, and one thread. An undecided check is an explicit failure.

## Deterministic search

The retrieval-prior edge is tested first. If it is infeasible, the edge expands
by 1.10 until feasibility, with a hard maximum of 2.0 times the prior. If it is
already feasible, the audit brackets downward by the reciprocal factor to
measure the geometry threshold, with a fixed 0.5 A lower bound. Once an
infeasible/feasible bracket exists, binary search continues to a 0.001 A edge
tolerance.

The selected cell is:

`a_search = max(a_prior, a_geom_upper_bound) * 1.01`

`V_search = a_search^3`

The 1.01 factor is a fixed edge safety margin applied identically to every
target. Grid density remains 4 (64 candidate positions). There is no
per-material tuning and no use of final QLIP success or SPP energy.

## Statuses

- `RETRIEVAL_VOLUME_USABLE`
- `RETRIEVAL_VOLUME_INSUFFICIENT`
- `GLOBAL_VOLUME_FALLBACK`
- `GEOMETRY_FEASIBLE_AT_PRIOR`
- `GEOMETRY_EXPANDED_TO_FEASIBLE`
- `GEOMETRY_NOT_FEASIBLE_WITHIN_BOUND`

All contributing and excluded retrieval records, every feasibility check, the
final cell, and the policy constants must be persisted per task.
