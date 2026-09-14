# T26_07 — Claude's common_contract / regulator classification findings

(Prepared ahead of T26_07's formal execution slot, since the analysis does
not depend on T26_04-06 being wired — only on T26_02's verbatim baseline,
which already exists. This file is the exact, verbatim input the T26_07
grunt documentation-transcription pass must use; it must not add or
reinterpret anything beyond what is written here.)

## `spp_maker/common_contract.py` — actual responsibilities

File: `packages/spp_maker_qlip/src/spp_maker/common_contract.py` (248 lines,
verbatim, unmodified from T26_02 baseline).

- Defines a fixed numerical contract ("`dmytro_gr_v1`"): 0.05 Å uniform
  bins on [0, 10] Å, Gaussian deposition (`sigma=0.1`, 3-sigma truncation),
  transform `U(r) = -ln(g(r) + 1e-12)` (lines 1-59).
- `pair_confidence()` (159-165): deterministic confidence score from
  `sqrt(min(structures/20,1) * min(log1p(observations)/log1p(20000),1))`.
- `choose_pair_blend()` (168-181): **genuine scientific blend math** —
  given local/global validity, computes `global_weight = 0.05 + 0.15*(1-confidence)`
  when both are valid, else falls back to local-only or global-only. This is
  the literal "blend behavior" and "potential mathematics" Ticket 26's
  header forbids modifying.
- `_valid_pot()` (184-189): validity = POT array has exactly 200 points,
  all finite, strictly increasing `r`.
- `blend_contract_roots()` (192-248): orchestrates the above per required
  pair, writes blended `.POT` files and a `manifest.json` with per-pair
  blend metadata (mode, weights, confidence).
- `build_local_supercell_artifact()` / `rebuild_global_pair_from_rdf()`
  (83-156): construct the two input artifacts (local request-fit, global
  regulator-derived) that `blend_contract_roots` then blends.

## `llm_csp/workflow/spp_policy.py` — actual responsibilities

File: `src/llm_csp/workflow/spp_policy.py` (158 lines, existing archive
code, read-only for this audit).

- `prepare_spp_guidance()` (27-158): given a formula + evidence + config,
  derives required pairs (`derive_required_pairs`), exports a regulator POT
  subset and checks its completeness/quality (`audit_pot_root`), optionally
  fits a request-specific SPP root from evidence CIFs
  (`export_required_pair_spp_root`), and for each required pair decides
  `guidance_mode` ∈ {`REQUEST_PLUS_REGULATOR`, `REGULATOR_ONLY_*`} based on
  whether the request-fitted pair's `pot_quality == "usable"` (107-115,
  118-138).
- Returns `request_coefficient` / `regulator_coefficient` /
  `outer_objective_scale` **as passed-through config values** (153-157) —
  it never applies them to blend a POT curve.
- **Never imports or calls anything from `common_contract.py`.**

## Classification (Ticket 26 Part 15)

This is a split finding, not a single tag, because the two files operate at
different responsibility layers with only partial, non-code-sharing
overlap:

1. **Pair usable-vs-fallback decision** (does this pair have good enough
   local/request data, or must it fall back to the regulator?): classified
   `REDUNDANT_REIMPLEMENTATION`. `spp_policy.py`'s criterion
   (`pot_quality == "usable"` from a fit-quality audit) and
   `common_contract.py`'s criterion (`_valid_pot`: exact 200-point,
   finite, strictly-increasing-`r` POT) are **independently invented and
   can disagree** on the same input — a genuine duplicate-logic risk, not
   merely two names for the same check.
2. **Numerical pair-level blend** (`choose_pair_blend` /
   `blend_contract_roots`'s confidence-weighted mixing of local+regulator
   POT curves): **no counterpart exists in `llm_csp.workflow` at all.**
   This is an absence, not a duplicate — the current v0.1 deterministic
   workflow does not blend POT curves the way `common_contract.py` does;
   it only decides a mode label and passes coefficient config through.

## Regulator behavior (Ticket 26 Part 16)

Per Part 16, source behavior wins wherever it conflicts with the reduced
archive's assumptions. No conflict was found in this audit:
`spp_policy.py`'s regulator-root/coverage/fallback handling
(`config.regulator_root`, completeness check, quality audit) is a
plausible, non-contradictory adaptation of the same requirements
`common_contract.py`'s `rebuild_global_pair_from_rdf` serves upstream of —
they are compatible in intent, just implemented independently as noted
above.

## Decision for T26_11 (Part 15's "do not remove... unless replacement
parity is established")

- Do **not** delegate or modify `spp_policy.py` in T26_11. Its SPP-relevant
  behavior must remain unchanged per Ticket 26 Part 48, and the overlap
  identified here is documented for later Skill-Loop restoration, not
  resolved now.
- T26_11 may still delegate the lower-level `llm_csp/spp/*.py` modules
  (`io_cif`, `neighbors`, `fit_hist`, `fit_phi`, `pot_io`, `score`,
  `required_pairs`, `quality`, `covalent_filter`, `weights`, `export`,
  `model`, `library`, `corpus_quality`, `compat`) if and only if T26_12
  proves parity for each — this finding does not touch those modules.

## Overlap table (for `docs/fidelity/SPP_MAKER_RESTORATION.md` common_contract section)

| Responsibility | `common_contract.py` | `spp_policy.py` | Classification |
|---|---|---|---|
| Pair usable-vs-fallback decision | `_valid_pot` (200-pt/finite/monotonic check) | `pot_quality == "usable"` (fit-audit check) | `REDUNDANT_REIMPLEMENTATION` (independently-criteria'd) |
| Numerical local+regulator blend | `choose_pair_blend` / `blend_contract_roots` (confidence-weighted mix) | *(none)* | Absent in archive — not a duplicate |
| Regulator coverage/quality gating | *(implicit, via `_valid_pot` on `rebuild_global_pair_from_rdf` output)* | `audit_pot_root` completeness/quality checks | Compatible in intent, independently implemented |
