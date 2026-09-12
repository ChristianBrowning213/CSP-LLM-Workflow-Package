# Ownership and authority confirmation record

Audit date: 2026-09-12.

This document identifies who must confirm licensing authority. Git authorship
is evidence of contribution, not legal ownership. The unauthenticated GitHub
contributors endpoint returned `404` for all three repositories, so no public
API contributor list was available; the complete locally reachable Git history
at each frozen revision is the contributor evidence used here.

## Contributor evidence summary

| Repository | Frozen history | Known Git identities | README/project metadata | Evidence classification | Institutional status |
| --- | --- | --- | --- | --- | --- |
| Crystal-DB | 16 commits, 2026-02-04 through 2026-09-05 | `ChristianBrowning213` with GitHub noreply and personal email forms | No author, contributor, copyright, licence, citation, or academic-reference statement found | `SOLE_AUTHORSHIP_LIKELY` | `INSTITUTIONAL_CONFIRMATION_REQUIRED` |
| SPP-Maker-QLIP | 12 commits, 2026-02-13 through 2026-08-27 | `ChristianBrowning213` with GitHub noreply and personal email forms | No author, contributor, copyright, licence, citation, or academic-reference statement found | `SOLE_AUTHORSHIP_LIKELY`; SPP code-expression comparison found no ipcsp copy/derivation | `INSTITUTIONAL_CONFIRMATION_REQUIRED` |
| Skill-Loop-CSP | 61 commits, 2026-03-05 through 2026-09-05 | `ChristianBrowning213` with GitHub noreply and personal email forms | No author, contributor, copyright, licence, or academic-reference statement found for the migrated workflow | `SOLE_AUTHORSHIP_LIKELY` | `INSTITUTIONAL_CONFIRMATION_REQUIRED` |

The two emails are associated with the same displayed Git identity; they are
not counted as two people. Commit counts are reported only to describe the
evidence and are not used to infer ownership.

## Crystal-DB

Repository: `https://github.com/ChristianBrowning213/Crystal-DB`

Relevant migrated code: the modules, MCP facade source, three schemas, and
retrieval defaults mapped into `packages/crystal_db/` by
`SOURCE_ATTRIBUTION_MATRIX.csv` and `CRYSTAL_DB_MIGRATION_FILESET.md`.

Known contributors: only the Christian Browning Git identity appears in the
reachable history and the relevant per-file logs.

Potential rights holder(s): Christian Browning; employer/University or other
institution if its policy applies. This is a contact set, not a legal finding.

Institutional question: research context may implicate employment, University,
sponsor, or project IP terms. No policy decision or waiver is present.

Authority confirmed: **NO**

Evidence: Git history and file logs support `SOLE_AUTHORSHIP_LIKELY`, but the
repository contains no human authority statement or institutional evidence.

Licence decision: **NONE**. No licence may be selected or added yet.

Smallest confirmation needed:

> I confirm that I authored or otherwise control the identified Crystal-DB
> files, have authority to license them for copied and modified public
> redistribution, that no additional contributor approval is required, and
> that any applicable institutional/employment IP requirements have been
> satisfied. I choose [LICENCE] and approve the stated attribution.

## SPP-Maker-QLIP

Repository: `https://github.com/ChristianBrowning213/SPP-Maker-QLIP`

Relevant migrated code: the 15 source areas mapped into `src/llm_csp/spp/` and
the covalent-rules example. `SPP_LINEAGE_AUDIT.md` classifies the code
expression as original to SPP-Maker relative to `ipcsp-spp`.

Known contributors: only the Christian Browning Git identity appears in the
reachable history and selected per-file logs.

Potential rights holder(s): Christian Browning; employer/University or sponsor
if applicable; any unrecorded contributor or upstream owner identified by
human review.

Institutional question: research context and the relationship to the wider SPP
research programme require confirmation. No institutional decision is present.

Authority confirmed: **NO**

Evidence: separate Git history, no shared commits/names/lines, and low token
similarity support `SOLE_AUTHORSHIP_LIKELY` for code expression, but do not
establish legal ownership or non-code method/data rights.

Licence decision: **NONE**. The `ipcsp-spp` MIT licence is not applied to this
separate repository.

Smallest confirmation needed:

> I confirm that I authored or otherwise control the identified SPP-Maker-QLIP
> files, have authority to license them for copied and modified public
> redistribution, have disclosed any upstream code lineage and contributors,
> and have satisfied applicable institutional/employment IP requirements. I
> choose [LICENCE] and approve the stated attribution.

## Skill-Loop-CSP

Repository: `https://github.com/ChristianBrowning213/Skill-Loop-CSP`

Relevant migrated code: deterministic contracts and policies adapted from
`workflow/runner.py` and `workflow/evidence.py` into `src/llm_csp/workflow/`,
`retrieval/`, `generation/`, and `schemas/`.

Known contributors: only the Christian Browning Git identity appears in the
reachable repository history and both relevant file histories. Both source
files first appear in commit `222b5b3a313c324f86c611a78f0514b449e4030c`.

Potential rights holder(s): Christian Browning; employer/University, sponsor,
or other institution if applicable.

Institutional question: the research workflow may have been created within
University/employment duties. No policy decision or permission is present.

Authority confirmed: **NO**

Evidence: Git history supports `SOLE_AUTHORSHIP_LIKELY`; it does not establish
ownership, institutional clearance, or authority to license adaptations.

Licence decision: **NONE**. AI assistance, if any, is not treated as an
additional human claimant, but it does not cure the human/institutional gate.

Smallest confirmation needed:

> I confirm that I authored or otherwise control the identified Skill-Loop-CSP
> workflow files, have authority to license copied and modified public
> redistribution of the adapted implementation, that no additional human
> contributor approval is required, and that applicable
> institutional/employment IP requirements have been satisfied. I choose
> [LICENCE] and approve the stated attribution.

## Human gate

All three repositories remain `REQUIRES_HUMAN_CONFIRMATION`. A valid record
must identify the confirmer, their authority, the files/revision covered, the
chosen licence, required attribution, date, and institutional decision where
applicable. Until then, no upstream licence commit or packaging status change
is authorized.
