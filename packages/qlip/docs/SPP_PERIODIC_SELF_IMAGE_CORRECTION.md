# SPP Periodic Self-Image Counting Correction

## Scope

This correction changes only the multiplicity of periodic same-species
self-image interactions. It does not change POT data, SPP construction,
interpolation, cutoffs, missing-pair policy, regularisation weights, retrieval,
cell selection, grids, or solver policy.

## Defect

QLIP enumerates periodic translations symmetrically, so every nonzero lattice
translation `T` has a corresponding `-T`. Off-diagonal atom pairs are consumed
once under an unordered `i < j` convention. Diagonal terms previously summed
both `+T` and `-T` at full weight, double-counting the same physical periodic
self-image pair relative to that convention.

Standalone scoring and solver objective construction shared the biased
coefficient calculation. Their numerical agreement therefore did not detect
the defect.

## Correction

For diagonal `i == j`, nonzero periodic translations retain the existing full
symmetric enumeration but receive multiplicity `0.5`. Thus `+T` and `-T`
together contribute one unordered pair. Off-diagonal terms retain multiplicity
`1.0` and are unchanged.

The shared rule is implemented by `periodic_pair_multiplicity()` and applied by
`periodic_spp_sum()`. `SPPCollection.score()` and
`SPPCollection.pair_cost_matrix()` both use that path. The objective audit uses
the same multiplicity helper and reports the per-image weight explicitly.

## Regression coverage

Focused tests cover an analytic one-atom self-image count, unchanged
off-diagonal and nonperiodic behavior, primitive/conventional/supercell
score-per-atom invariance, periodic cutoff behavior, solver/scorer coefficient
agreement, audit totals, and existing missing-pair behavior. The real bundled
SPP solve remains subject to the repository's established Gurobi availability
gate.

## Historical provenance

Historical generated candidates and recorded objectives were not regenerated
or overwritten. They remain products of the old objective semantics:

- Old: `periodic_same_species_self_image_counting = doubled`
- New: `periodic_same_species_self_image_counting = unordered / corrected`

When comparing results across this correction, record the source revision and
do not treat historical objective values as if they used corrected counting.
