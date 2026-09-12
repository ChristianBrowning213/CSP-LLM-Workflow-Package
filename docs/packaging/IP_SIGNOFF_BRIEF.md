# LLM-CSP human IP sign-off brief

Decision packet prepared 2026-09-12. This is an evidence summary, not legal
advice or an approval record. No box below has been completed automatically.

## Reviewer checklist

- [x] Christian has authority to license Crystal-DB
- [x] Christian has authority to license SPP-Maker-QLIP
- [x] Christian has authority to license Skill-Loop-CSP
- [x] MIT is acceptable
- [x] University/institutional authority gate is satisfied by the supplied owner authorization
- [x] POT provenance decision reviewed
- [x] Chemistry/radii resource decision reviewed

## Release boundary

The proposed public software repository contains Crystal-DB retrieval, SPP
construction, QLIP integration, a deterministic LLM-CSP workflow, and a
validation adapter. QLIP is already covered by its retained upstream MIT
licence. The adapter does not bundle SCA source.

The proposed release does **not** contain the production Crystal-DB corpus,
restricted CIF collections, embedding models, the broad POT corpus, SCA source
code, agentic research code, or paper/benchmark artifacts. The six small
SrTiO3 demonstration POTs and bundled chemistry resources are reviewed
separately below and in the linked provenance records.

## Authorship evidence and present licence state

The complete locally reachable histories at the frozen source revisions were
used. Email variants with the same displayed identity are not counted as
different people.

| Repository | Git contributors observed | Commits | Other named authors found? | Third-party copied code found? | Current licence |
| --- | --- | ---: | --- | --- | --- |
| Crystal-DB | Christian Browning (`ChristianBrowning213`) | 16 | No | None identified in the migrated paths; this is not an originality warranty | None |
| SPP-Maker-QLIP | Christian Browning (`ChristianBrowning213`) | 12 | No | No copied/derived code expression identified in the comparison with `ipcsp-spp` | None |
| Skill-Loop-CSP | Christian Browning (`ChristianBrowning213`) | 61 | No | None identified in the migrated workflow paths; this is not an originality warranty | None |

Git evidence indicates sole authorship by Christian Browning, but this does
not itself establish legal ownership or authority to license
University/research software. The detailed evidence and limitations are in
`OWNERSHIP_CONFIRMATION.md` and `SPP_LINEAGE_AUDIT.md`.

## Decisions required from an authorized human

Please answer each question explicitly and identify the person making the
decision, their role/authority, the date, and any conditions:

1. Does Christian Browning have authority to open-source the code authored in
   Crystal-DB?
2. Does Christian Browning have authority to open-source the code authored in
   SPP-Maker-QLIP?
3. Does Christian Browning have authority to open-source the code authored in
   Skill-Loop-CSP?
4. Are there University of Liverpool, supervisor, sponsor, grant,
   collaboration, or employment IP terms that require additional approval?
5. If release is permitted, may these repositories be distributed under the
   MIT licence?

Ticket 14 supplied Christian Browning's explicit ownership and MIT
authorization and directed that it be used as the licensing authority for all
three repositories. The upstream licence-only commits are recorded in
`CODE_LICENSING_STATUS.md`.

## Proposed action after approval only

If, and only if, the required authority and MIT approval are recorded:

- Crystal-DB: add an MIT `LICENSE` upstream in a licence-only commit.
- SPP-Maker-QLIP: add an MIT `LICENSE` upstream in a licence-only commit.
- Skill-Loop-CSP: add an MIT `LICENSE` upstream in a licence-only commit.

The scientific source revisions will remain unchanged. Packaging records will
store two hashes for each repository: the unchanged scientific source commit
and the later licensing-confirmation commit. Required third-party notices and
asset restrictions remain separate conditions and are not overridden by an
MIT approval for project code.

## Approval wording

Combined one-line form:

> I confirm that Christian Browning has authority to distribute the identified Crystal-DB, SPP-Maker-QLIP, and Skill-Loop-CSP code under the MIT licence, subject to the third-party attribution and asset restrictions documented in the release audit.

If authority differs by repository, use one signed line per repository:

> I confirm that Christian Browning has authority to distribute the identified [REPOSITORY] code under the MIT licence, subject to the third-party attribution and asset restrictions documented in the release audit.

Neither form is approved merely by appearing here. The record must identify
the confirmer and their authority and must state whether institutional review
was required and satisfied.

## Asset decisions for the reviewer

`POT_PROVENANCE.md` classifies the six SrTiO3 files as
`POT_ASSETS_BLOCKED`; Ticket 14 applied the fallback by removing them,
requiring user-supplied POTs, and replacing the solving demo with a public
non-scientific software smoke.

`CHEMISTRY_RESOURCE_PROVENANCE.md` establishes byte-exact regeneration of the
three generated base tables from recorded upstream package versions. Those
tables are `CAN_DERIVE_AT_RUNTIME`; two QLIP policy files and the provenance
metadata are `REDISTRIBUTION_RESOLVED`. A separate unused legacy 13-value
`resources/radii.json` was removed. The three scientific base tables are now
derived lazily in memory with full parity coverage.

Current status is `CODE_LICENSING_RESOLVED` and
`READY_WITH_DOCUMENTED_EXTERNAL_REQUIREMENTS`.
