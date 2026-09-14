# SPP Pair Extraction Audit

## Current Pair Selection Behaviour

SPP has two fitting paths that decide which pairs become exported POT files.

The default `neighbors` path builds a unit-cell minimum-image distance matrix and then exports only pairs that appear in `build_neighbor_edges`. With the default cutoff mode, edges are selected by `r_cut` (default `4.0` in the CLI; the diagnostic uses an explicit `6.0` to expose NaCl). The histogram accumulator creates pair rows only when an accepted edge is seen, and `export_spp_root` writes one POT file for each pair row in the resulting `PhiResult`.

The `supercell_gr` path builds an explicit supercell and accumulates unit-to-supercell distances up to `r_max`. That path can see periodic same-element image distances because it enumerates repeated images and skips only zero self distances.

Publishing and compatibility checks do not add missing pairs. They copy/check the exported root and its `manifest.json`.

## Why Self-Pairs May Not Become POT Files

For the existing minimal `nacl.cif` fixture, ASE loads one Na and one Cl site. The default neighbor/contact extraction operates on unique unit-cell site pairs. It can select the Na-Cl unit-cell edge when the cutoff is large enough, but it does not enumerate Na images around Na or Cl images around Cl. Therefore Na-Na and Cl-Cl periodic image distances can exist geometrically while still not appearing in the neighbor histogram, `PhiResult.pairs`, manifest, or exported POT tree.

Bandpass weighting can reduce weights for selected distances, but it is not the root cause of the missing self-pair files. The pair row must first exist in the extractor's accepted edges. Likewise, publishing and POT compatibility do not filter these pairs out; they only operate on files already exported.

## Bug Or Policy Mismatch

This is primarily a policy mismatch.

QLIP compatibility currently expects the complete unordered pair universe for the requested formula, including self-pairs. The default SPP `neighbors` extractor exports only observed/contact/selected pairs from the configured extraction policy. For a sparse/minimal CIF representation, periodic same-element image pairs are real but are not selected by that policy.

There is still a potential bug-shaped risk: a user may reasonably assume "periodic structure" means same-element periodic images are part of pair extraction. The current code is internally consistent, but the contract between SPP-generated roots and QLIP-required all-pair roots is stricter than the extractor's observed-pair output.

## Recommended Next Implementation

Recommended path: **A with a small C-style fallback design note**.

A. Make SPP generate all required pair POTs for a requested formula when producing QLIP-solve-compatible packages. The generation path should receive `required_pairs`/`formula`, compute periodic pair distributions for every required pair where geometry supports it, and fail clearly when a pair cannot be estimated.

B. Making QLIP accept observed-pair SPPs would require an explicit missing-pair policy in QLIP. That is useful for statistical guidance mode, but it weakens the current solve-compatible contract unless the missing-pair behavior is first-class and visible.

C. A hybrid can be useful later: generate observed periodic distributions where possible, and use an explicit neutral/radius-only fallback for missing self-pairs. That fallback must be labelled as estimated, not silently treated as fitted data.

For the current compatibility issue, the safest implementation is to keep QLIP compatibility strict and add an SPP all-required-pair generation mode for fresh formula-targeted packages.
