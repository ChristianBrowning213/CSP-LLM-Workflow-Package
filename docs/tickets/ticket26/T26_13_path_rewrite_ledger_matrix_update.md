# T26_13 — Path-Rewrite Ledger & Source-to-Archive Matrix Update

## Owner

Grunt (local-grunt), transcribing Claude-supplied findings only.

## Depends on

T26_07 (common_contract classification), T26_12 (parity evidence). Should
run after all restoration subtickets (T26_03–T26_10) so the ledger is
complete in one pass.

## Objective

Produce the final `docs/fidelity/SPP_MAKER_RESTORATION.md` path-rewrite
table and update the SPP-Maker software rows in
`docs/fidelity/SOURCE_TO_ARCHIVE_MATRIX.csv`.

## Authoritative source

Every path-relocation change flagged with a `# repo-relocation` comment (or
equivalent note) across T26_03, T26_05, T26_06, T26_08, T26_09, plus
Claude's classification from T26_07 and parity evidence from T26_12.

## Archive files expected to change

- `docs/fidelity/SPP_MAKER_RESTORATION.md` — path-rewrite table:
  `source path behavior | archive path behavior | reason | parity test`.
- `docs/fidelity/SOURCE_TO_ARCHIVE_MATRIX.csv` — new/updated rows for every
  SPP-Maker source path, using status values
  `RESTORED | ALREADY_PARITY_VERIFIED | ASSET_DEFERRED |
  HISTORICAL_NON_RUNTIME`.

## In-scope behavior

Pure transcription/formatting of facts Claude supplies (or facts
mechanically extractable via grep for the relocation-comment marker) into
the required table/CSV formats, matching the existing
`SOURCE_TO_ARCHIVE_MATRIX.csv` column schema exactly (see current header
row).

## Forbidden changes

- No new classification invented by the grunt — every status value must
  come from a prior subticket's actual finding.
- No CSV column schema change.

## Implementation requirements

Grep every restored file for the relocation marker to build the path-
rewrite table mechanically; do not rely on memory of what changed.

## Source-fidelity / parity requirements

Every row must be traceable to an actual diff hunk from an earlier
subticket's GRUNT_PATCH.

## Tests the grunt must run

None (documentation-only).

## Tests Claude must independently rerun

- Cross-check every path-rewrite table row against the actual diff in the
  corresponding subticket's accepted patch.
- Confirm the CSV has no unexplained gap for any SPP-Maker source path from
  the T26_01 manifest (Part 52: "No unexplained software gaps").

## Acceptance criteria

- [ ] Every relocated path is documented with reason and parity test
      reference.
- [ ] Only location changes appear in the ledger (no behavior changes).
- [ ] `SOURCE_TO_ARCHIVE_MATRIX.csv` has a row for every SPP-Maker source
      path with an accurate status.
- [ ] No unexplained gap.

## Expected outputs / artifacts

- Completed `docs/fidelity/SPP_MAKER_RESTORATION.md`.
- Updated `docs/fidelity/SOURCE_TO_ARCHIVE_MATRIX.csv`.
