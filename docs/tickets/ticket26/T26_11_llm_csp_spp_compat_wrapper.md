# T26_11 — `llm_csp.spp` Compatibility Wrapper Update

## Owner

Grunt (local-grunt), gated by Claude sign-off.

## Depends on

T26_12 (parity harness results). **Do not start this subticket until Claude
has reviewed T26_12's raw parity output and explicitly authorized which, if
any, `llm_csp.spp` modules may delegate to restored source.**

## Objective

Where — and only where — Claude has proven parity between the reduced
`src/llm_csp/spp/` implementation and the restored `spp_maker`/
`spp_maker_qlip` source, update the reduced wrapper to delegate to the
restored implementation, without removing any public API the v0.1
deterministic workflow depends on.

## Authoritative source

Claude's parity sign-off notes from T26_12, naming exactly which modules
are approved for delegation (may be a subset, or none, of
`src/llm_csp/spp/{compat,corpus_quality,covalent_filter,export,fit_hist,
fit_phi,io_cif,library,model,neighbors,pot_io,quality,required_pairs,
score,weights}.py`).

**`src/llm_csp/workflow/spp_policy.py` is explicitly OUT OF SCOPE for this
subticket**, per T26_07's finding: it does not reimplement
`common_contract.py`'s numerical blend (`choose_pair_blend`/
`blend_contract_roots`) at all — it makes an independently-criteria'd
usable/fallback decision per pair and never calls into `common_contract`.
Ticket 26 Part 48 requires this overlap to be documented, not resolved,
during this ticket ("do not move it during this ticket unless needed for
exact parity... Document the overlap for later Skill-Loop restoration").
Do not delegate `spp_policy.py` here regardless of what T26_12 finds.

## Archive files expected to change

Only the specific files Claude has named as parity-approved. Anything not
named is out of scope for this subticket — leave it untouched.

## In-scope behavior

For each approved module, replace its internal implementation with a thin
delegation to the restored `spp_maker`/`spp_maker_qlip` equivalent,
preserving the existing public function/class signatures exactly (so
existing callers in `llm_csp.workflow` are unaffected).

## Forbidden changes

- Deleting any public API currently used by `llm_csp.workflow` or its
  tests.
- Delegating any module Claude did not explicitly approve.
- Any signature change.

## Implementation requirements

One module at a time; run the full existing `tests/unit/spp`,
`tests/integration/spp`, `tests/unit/workflow/test_spp_policy.py` suite
after each module's change before moving to the next.

## Source-fidelity / parity requirements

Behavior of the wrapped module must be identical pre/post change — this is
exactly what the T26_12 parity proof exists to establish before this
subticket is allowed to touch anything.

## Tests the grunt must run

- `tests/unit/spp/**`, `tests/integration/spp/**` (existing archive tests)
- `tests/unit/workflow/test_spp_policy.py`
- `tests/unit/qlip/**`, `tests/integration/qlip/test_spp_e2e.py`

## Tests Claude must independently rerun

- Full listed suite, plus a manual before/after comparison on at least one
  real workflow run to confirm output is unchanged.

## Acceptance criteria

- [ ] Only Claude-approved modules were touched.
- [ ] All existing `llm_csp.spp`, workflow, and QLIP integration tests
      remain green — zero regressions.
- [ ] No public API removed.
- [ ] Delegation is provably behavior-preserving (matches T26_12 parity
      evidence).

## Expected outputs / artifacts

- Updated `src/llm_csp/spp/*.py` (approved subset only).
- Regression-test evidence for the Ticket 26 completion report (§22
  existing archive tests).
