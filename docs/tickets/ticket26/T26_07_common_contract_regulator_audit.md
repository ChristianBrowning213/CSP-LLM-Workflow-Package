# T26_07 — `common_contract` & Regulator Overlap Audit

## Owner

Claude (classification/architectural judgment) with a narrow Grunt documentation
pass once Claude has produced the classification.

## Depends on

T26_04, T26_05, T26_06 (package + tests + CLI + MCP all wired, so overlap
analysis is against a working restored system, not a partial one).

## Objective

Audit `spp_maker/common_contract.py`'s actual responsibilities
(request-specific SPP, regulator union, blend policy, coverage decisions,
pair selection) and classify the existing
`llm_csp.workflow.spp_policy` implementation against it as one of:

- `EXACT_SOURCE_ADAPTATION`
- `COMPATIBILITY_WRAPPER`
- `REDUNDANT_REIMPLEMENTATION`

This classification decision is explicitly reserved to Claude per Ticket 26
Part 15 ("Do not remove anything yet unless source restoration makes a
clearly duplicated implementation unnecessary and regression tests
establish replacement parity") — it is an architectural/parity judgement,
not bounded implementation, and must not be delegated to the grunt.

## Authoritative source

`spp_maker/common_contract.py` (248 lines, verbatim from T26_02 baseline).

## Archive files expected to change

- `src/llm_csp/workflow/spp_policy.py` — read-only for this subticket; no
  edits here (edits, if any, are deferred to T26_11, gated on parity proof).
- `docs/fidelity/SPP_MAKER_RESTORATION.md` — new `common_contract` section
  (grunt-authored transcription of Claude's findings, once Claude supplies
  them verbatim as subticket input).

## In-scope behavior (grunt sub-pass only)

Once Claude has written out the classification and responsibility mapping,
the grunt's only job is to format that content into the restoration doc's
`common_contract` section, matching the doc's existing style (see
`docs/fidelity/CRYSTAL_DB_RESTORATION.md` for precedent structure). No new
analysis, no new claims beyond what Claude supplies.

## Forbidden changes

- No code changes to `spp_policy.py` or `common_contract.py` in this
  subticket.
- The grunt must not add, remove, or reinterpret any classification — it
  transcribes Claude's exact findings.

## Implementation requirements

Claude performs the read-and-classify work directly (Read tool, not
delegated). Grunt is invoked only for the mechanical doc-formatting pass,
with Claude's findings pasted into the ticket verbatim as the source of
truth for that pass.

## Source-fidelity / parity requirements

Every claim in the resulting doc section must be traceable to specific line
ranges in `common_contract.py` and `spp_policy.py`, cited in the doc.

## Tests the grunt must run

N/A for the analysis; for the doc-formatting pass, none (documentation-only
change).

## Tests Claude must independently rerun

N/A — this is Claude's own analysis, self-verified by re-reading both files
side by side.

## Acceptance criteria

- [ ] `common_contract.py`'s actual responsibilities are documented exactly.
- [ ] `spp_policy.py` is classified as exactly one of the three categories,
      with justification citing line ranges.
- [ ] No code deleted or moved as a result of this subticket alone.
- [ ] Overlap is documented for later reference (Part 15).

## Expected outputs / artifacts

- `docs/fidelity/SPP_MAKER_RESTORATION.md` `common_contract` section.
- A written classification that gates T26_11's scope.
