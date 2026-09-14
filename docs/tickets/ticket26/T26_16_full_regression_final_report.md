# T26_16 — Full Regression, Recovery Docs & Final Ticket-26 Report

## Owner

Claude. Not delegated: final acceptance, cross-ticket regression judgment,
and the go/no-go call on `SPP_MAKER_SOFTWARE_RESTORED` vs.
`SPP_MAKER_SOFTWARE_GAPS_REMAIN` are explicitly reserved to the supervising
engineer.

## Depends on

All prior T26_* subtickets.

## Objective

Run the complete regression battery required by Ticket 26 Part 54, update
`docs/fidelity/RECOVERY_STATUS.md`, and produce the full 27-section
completion report the parent ticket requires — checking every original
acceptance criterion individually rather than inferring success from
subticket pass counts.

## Authoritative source

Ticket 26 itself (`docs/tickets/TICKET_26.md`), re-read in full at this
final step, plus every accepted subticket's evidence.

## Archive files expected to change

- `docs/fidelity/RECOVERY_STATUS.md` — SPP-Maker-QLIP row updated to
  `SOFTWARE: RESTORED` / `ASSETS: PENDING` (not "fully restored").
- No other files change in this subticket beyond documentation.

## In-scope behavior

Run, in a clean shell, in this order:
1. `packages/spp_maker_qlip/tests` (restored source suite)
2. T26_12 parity harness scripts (direct, not from cached JSON)
3. `tests/unit/spp`, `tests/integration/spp` (existing archive suite)
4. `tests/unit/qlip`, `tests/integration/qlip` (QLIP integration)
5. Crystal-DB tests not requiring the blocked DB
6. Validation tests, deterministic workflow tests, fidelity guards
7. The whole archive suite

## Forbidden changes

- No "fixing" a failing test to force a green result.
- No marking the ticket restored while any Part 26 acceptance-criterion
  checkbox is unverified.

## Implementation requirements

Check each of Ticket 26's ~28 acceptance-criteria checkboxes individually
against actual evidence gathered in T26_01–T26_15, not against subticket
ACCEPTED/REJECTED status alone.

## Source-fidelity / parity requirements

Confirm explicitly, with evidence:
- `spp_maker` namespace restored
- `spp_maker_qlip` namespace restored
- No scientific behavior changed (`NO_SCIENTIFIC_BEHAVIOR_CHANGE`)
- Production POT assets inventoried, not blindly restored
- `CRYSTAL_DB_BLOCKED_PROVENANCE` status unchanged
- v0.1 integrity (`2dbf5e8852dc62c42d97385bc96ea90166d0fc74`) unchanged
- No agent restoration started (Part 56 list untouched)
- No POT-library restoration started

## Tests the grunt must run

N/A — no grunt invocation.

## Tests Claude must independently rerun

The entire Phase 7 battery listed above, freshly, in this subticket.

## Acceptance criteria

- [ ] Every Ticket 26 acceptance-criterion checkbox individually verified.
- [ ] Full regression battery run with results recorded.
- [ ] `RECOVERY_STATUS.md` updated accurately (not overstated).
- [ ] Final status is exactly one of `SPP_MAKER_SOFTWARE_RESTORED` or
      `SPP_MAKER_SOFTWARE_GAPS_REMAIN`, decided on evidence.
- [ ] If and only if fully restored: commit on `recovery/source-fidelity`
      and push to `origin/recovery/source-fidelity` — no merge/tag/release.
- [ ] If gaps remain: report `SPP_MAKER_SOFTWARE_GAPS_REMAIN` honestly, no
      commit/push of a false-positive status.

## Expected outputs / artifacts

- Updated `docs/fidelity/RECOVERY_STATUS.md`.
- The complete 27-section Ticket 26 completion report delivered to the
  user.
- A single commit (only if genuinely passing) on `recovery/source-fidelity`.
