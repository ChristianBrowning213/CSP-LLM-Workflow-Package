# SPP packaging notes

## Source revision

- repository: `C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP`
- branch: `SPP_MCP`
- commit: `3a2d557811973265f3373ec881cc8057a89789d2`
- source status at migration start: clean

Git emitted permission warnings for ignored `.codex_pytest_tmp` and
`.tmp_pytest` directories while reporting the worktree clean. The source was not
modified. See `SPP_MIGRATION_FILESET.md` for the exact selection.

## Packaged functionality

`llm_csp.spp` owns CIF loading, periodic pair-distance collection, histogram and
phi construction, QLIP-compatible POT writing/loading, compatibility and quality
checks, standalone scoring, and two explicit export paths:

- `export_required_pair_spp_root`: the frozen source algorithm, which fits new
  POTs from a CIF directory for a target formula and explicit output root
- `export_required_pot_subset`: a packaging adapter that copies the required
  unchanged POT files from an explicit library into a canonical run root

Both output locations are caller supplied. No code writes into site-packages or
searches sibling repositories.

## Pair semantics

The source builder parses unique element symbols from the target formula, not a
union of every incidental species in retrieved CIFs. For `n` target elements it
requires all `n(n+1)/2` unordered self/cross pairs. `A,B,C` therefore requires
`A-A, A-B, A-C, B-B, B-C, C-C`. Symbols are title-cased, duplicate species are
removed, pair members are sorted case-insensitively, and the final labels are
sorted case-insensitively.

Multiple CIFs contribute a deterministic union of distance evidence to those
formula-required histograms. CIF filenames are loaded in sorted order; a pair is
fitted once regardless of how many files contain it. The builder reports pairs
with no periodic evidence in `missing_pairs`, writes per-pair diagnostics, and
returns `ok=False`; it never fabricates a potential.

## POT naming and external libraries

Canonical layout is `<A>-<B>/<A>-<B>.POT`, using the same unordered label as
above. The frozen published-root resolver checks canonical naming first and then
the reverse name. The packaging adapter preserves that preference: when both
exist, the canonical file wins; a reverse-only source is accepted but exported
under the canonical name. Only one output file is written per required pair.
SHA-256 values prove that numerical POT contents are unchanged.

The broad regulator POT collection remains external. Pass `source_pot_root` or
set `SPP_SOURCE_POT_ROOT`. A valid root contains QLIP-readable `.POT` files in
canonical or recognized reverse/flat layouts. The adapter does not search old
`QLIP_Outputs`, artifact directories, or developer paths.

Incomplete library coverage produces `status="incomplete"`, `complete=false`,
and a sorted `missing_pairs` array in both the return value and `manifest.json`.
Available files may be exported as a truthful partial root, but it cannot be
mistaken for complete coverage from its manifest.

## Regulator responsibility

The canonical `export_required_pair_spp_root` performs fresh target-formula
fitting only. Published-root discovery existed in the source QLIP package
compiler. Broad target/regulator union and fallback blending live in separate
`common_contract` or Skill-Loop orchestration paths and are deliberately not
moved into this generic library.

## Scoring semantics and QLIP boundary

`score_atoms` builds a unique undirected atom-pair list using ASE minimum-image
distances. Its default cutoff is 4 Å, or callers may provide a cutoff or k-nearest
mode. It canonicalizes pair lookup, optionally applies the source band-pass
weight, and sums contributions without normalization. Missing and out-of-range
behavior comes from the loaded `SPPModel` policies (defaults: global-maximum
missing-pair penalty and maximum out-of-range penalty).

This validator is not numerically interchangeable with QLIP's solver scorer.
QLIP remains authoritative: `periodic_spp_sum` explicitly enumerates periodic
images through the unchanged 11 Å cutoff, including translated self-images.
Ticket 6 does not modify it. For the exact bundled SrTiO3 files, the exported
subset is accepted by packaged QLIP and retains objective
`4.883033620558714` and periodic score `4.883033620558713`.

## Dependencies and assets

The root package directly declares ASE, NumPy, and PyYAML. PyYAML is needed only
when YAML covalent-exclusion rules are loaded, but it is declared rather than
being left as an undeclared dynamic dependency. No Pydantic, plotting, notebook,
benchmark, MCP, or paper dependency is pulled in by this selected API.

The historical QLIP SrTiO3 six-POT set was a QLIP test/example resource. Ticket
14 removed it from the public tree because parameter provenance remained
unresolved. No
broad POT library, generated statistical potential, production CIF corpus, or
SPP benchmark artifact was added.

## Verification

- Focused source-tree SPP gate: 14 passed.
- Isolated installed-wheel SPP gate: 14 passed. Imports resolved from
  `Lib/site-packages/llm_csp/spp/__init__.py` and
  `Lib/site-packages/qlip/__init__.py`, outside both source trees.
- Repository-wide gate: 118 passed and 1 skipped.
- The synthetic NaCl source/package parity probe matched required, fitted, and
  missing pairs, pair statistics, exported POT SHA-256 values, and standalone
  score diagnostics exactly.
- Historically, the exact six SrTiO3 POTs were exported and accepted by installed
  QLIP; its optimal objective and independent periodic score agreed to floating
  precision (`4.883033620558714` versus `4.883033620558713`).

## Remaining issues

- Production chemistries beyond the bundled SrTiO3 example require an external
  licensed/compatible POT library or freshly fitted evidence.
- Later orchestration must refuse incomplete subset manifests before invoking
  QLIP; this library truthfully reports but does not own workflow decisions.
- Published `QLIP_Outputs` registry selection, broad regulator union/blending,
  calibration campaigns, CLI, and MCP remain deferred.
- External POT and CIF redistribution remains subject to their original terms;
  the software package makes no additional licensing claim.
