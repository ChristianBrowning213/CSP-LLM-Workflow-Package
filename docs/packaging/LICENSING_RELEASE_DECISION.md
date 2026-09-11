# Licensing release decision

Audit date: 2026-09-10. This is an engineering provenance assessment, not
legal advice. It examines the exact frozen Git objects recorded by the
migration tickets and does not infer permission from public availability.

| Component | Copied code? | Explicit licence? | Redistribution permitted? | Attribution resolved? | Release blocker? |
| --- | ---: | ---: | ---: | ---: | ---: |
| Newly authored LLM-CSP packaging/adapter code | No upstream copy identified | Yes, root MIT | Yes, if the named holder has authority to license it | Package maintainer named; employment/institutional ownership not independently established | Requires owner/institution confirmation, but no conflicting repository evidence found |
| QLIP | Yes, including substantial exact copies | Yes, MIT | Yes, subject to retaining the MIT notice | Copyright notice resolved; complete scientific/software author list not stated upstream | No for licence notice; contributor/citation confirmation remains advisable |
| Crystal-DB | Yes, including exact modules and schemas | No | No permission established | No | **Yes** |
| SPP-Maker-QLIP | Yes, exact and adapted modules | No | No permission established | No; relationship to `ipcsp-spp` also unstated | **Yes** |
| Skill-Loop-CSP workflow | Adapted rather than copied verbatim | No | No permission established for derivative redistribution | No | **Yes** |
| Structured Crystal Analyser (SCA) | No implementation copied | No | Not established | Generic contributor label only | No after Ticket 11 exclusion: Git dependency/validation extra removed from public metadata |
| Six bundled SrTiO3 POT files | Yes, exact QLIP assets | QLIP root MIT; no asset-specific terms | Repository licence indicates permission, but underlying parameter/generation provenance is not documented sufficiently for a confident asset release | No | **Yes**, pending asset-origin confirmation |
| Bundled QLIP base chemistry/radii resources | Yes, exact generated tables | QLIP root MIT; source-package/data terms not recorded | Not confidently established for the derived compilation | Scientific citations exist; rights provenance does not | **Yes**, pending data-rights review or replacement |
| QLIP MCP schemas and radii policy | Yes | MIT | Yes with QLIP notice | Yes to available evidence | No |
| Crystal-DB JSON schemas/defaults | Yes | No | No permission established | No | **Yes** |
| Synthetic demo structures and new configuration examples | No external structure files bundled | Root MIT | Yes, subject to ownership authority | Yes to available repository evidence | No |

## Code licensing blockers

1. Crystal-DB contains byte-identical source modules and schemas but has no
   licence evidence at its frozen revision.
2. SPP-Maker-QLIP contains the implementation from which the packaged SPP
   subsystem was copied/adapted, but has no licence evidence. An MIT licence in
   the related `ipcsp-spp` repository does not automatically license this
   separate repository or establish its file lineage.
3. Skill-Loop-CSP has no licence evidence for the adapted workflow contracts
   and policy.

SCA remains unlicensed, but Ticket 11 isolated that issue by removing the Git
dependency and validation extra from public installation metadata. The lazy
adapter does not copy SCA and reports `backend_unavailable` when no separately
authorized compatible backend is present.

## Asset and data blockers

1. The six POT files are exact QLIP repository assets. The QLIP MIT notice is
   preserved, but the files contain no generator/input provenance and their
   introducing commit message only says `needed spps`. Confirm that the QLIP
   licence holder has authority to license the parameterized files and record
   their scientific source/generation method.
2. QLIP base tables record generation packages, versions, and literature
   citations, but do not record the upstream package/data licences or a rights
   conclusion for redistribution of the extracted compilation.
3. Crystal-DB schemas/defaults and the SPP covalent-rules example inherit the
   missing-licence blockers of their repositories.
4. No production database, CIF corpus, stored embeddings, model weights, or
   broad POT corpus is bundled. Rights for those user-supplied assets therefore
   do not automatically block the software repository, though users remain
   responsible for them.

## Root licence decision

MIT remains a suitable permissive licence for newly authored repository
material if Christian Browning has authority to grant it. It does not
relicense migrated material. The current root package metadata must not be
treated as resolving unlicensed components; before publication it must match
the licences/permissions eventually established for the integrated contents.
The unmodified QLIP MIT text remains at `packages/qlip/LICENSE`.

No speculative licence file or copyright header was added for an unlicensed
project. The frozen source files contained no headers requiring restoration.

## Attribution and citation decision

`CITATION.cff` continues to identify Christian Browning as author of this
software repository, consistent with the root notice and repository evidence.
Its project-wide `license: MIT` field was removed because that statement would
overstate the unresolved integrated licence coverage. It was not expanded with
upstream project authors because the audited metadata does not establish
complete author lists, and upstream dependency contributors are not
automatically authors of this integration. QLIP's copyright notice is
preserved in its licence and `THIRD_PARTY_NOTICES.md`.

The related `ipcsp-spp` README names an under-review manuscript but supplies no
final DOI or complete publication citation. QLIP, SPP-Maker-QLIP, and SCA state
no preferred scientific citation in the inspected root metadata. Publication
citations should be added only after the project owners confirm the intended
papers and bibliographic records. Scientific citation remains separate from
software licence permission.

## Smallest required human actions

1. The owner(s), employer, or institution with authority must add explicit
   licences at the frozen revisions (or provide written permission covering
   this redistribution) for Crystal-DB, SPP-Maker-QLIP, and Skill-Loop-CSP.
2. The SCA rights holder must add an explicit licence/permission before an SCA
   installer or advertised dependency can be restored; it is currently
   excluded from the public release contract.
3. The QLIP/SPP asset owner must document the source and licensing authority
   for the six POTs.
4. Review ASE, mendeleev, pymatgen, and SMACT source/data terms for the bundled
   derived base tables; then record the conclusion or replace the tables with
   clearly licensed/generated release assets.
5. Confirm employment/institutional ownership and the complete software and
   scientific contributor/citation record. Update `CITATION.cff` only from that
   evidence.

## Final classification

The exact copied and adapted components cannot currently be released under the
root MIT notice because explicit upstream permission is absent. Documentation
cannot substitute for that permission.

Ticket 11 removed SCA from public installation metadata. Crystal-DB,
SPP-Maker-QLIP, Skill-Loop-CSP, the bundled POT files, and the derived
chemistry/radii tables remain blocked; none has been relabelled as resolved or
excluded without evidence. See `LICENSING_REMEDIATION_MATRIX.md` for exact
statuses, hashes, fallbacks, and request templates.

LICENSING_BLOCKED

## Updated Ticket 9 recommendation

NOT_READY
