# Licence and attribution audit

Audit date: 2026-09-10. This is an engineering inventory, not legal advice.
Absence of a licence is not permission to redistribute. Each upstream tree was
examined at the exact frozen revision, without changing its checkout.

## Authoritative repository evidence

| Project and revision | Files/statements inspected | Copyright or author evidence | Result |
| --- | --- | --- | --- |
| [QLIP](https://github.com/vlgusev/qlip/tree/a619ab379c62b5edefd6bb00076267e149f283ce) `a619ab379c62b5edefd6bb00076267e149f283ce` | Root `LICENSE`; `pyproject.toml`; README; source headers | `LICENSE` is MIT and says Copyright (c) 2025 Vladimir V. Gusev; pyproject points to that file. No source-file headers or preferred citation were found. | Modified redistribution is permitted if the copyright and permission notice accompany copies/substantial portions. Root MIT is compatible; exact notice is retained. |
| [Crystal-DB](https://github.com/ChristianBrowning213/Crystal-DB/tree/e33d5cc55be01f800a7cf055cc1793d982deb5bc) `e33d5cc55be01f800a7cf055cc1793d982deb5bc` | Complete tree names; `pyproject.toml`; available READMEs; source headers | No `LICENSE`, `LICENCE`, `COPYING`, `NOTICE`, project licence metadata, README licence statement, copyright header, or author metadata found. Git history contains Christian Browning identities but does not by itself prove authorship or licensing authority. | `NO_EXPLICIT_LICENSE`; copied modules, schemas, and defaults block release. |
| [SPP-Maker-QLIP](https://github.com/ChristianBrowning213/SPP-Maker-QLIP/tree/3a2d557811973265f3373ec881cc8057a89789d2) `3a2d557811973265f3373ec881cc8057a89789d2` | Complete tree names; `pyproject.toml`; README; source/rule headers | No licence file, metadata, statement, or source header found. Git history contains Christian Browning identities but does not resolve rights or earlier method/code lineage. | `NO_EXPLICIT_LICENSE`; exact/adapted SPP code and the covalent-rules example block release. |
| [Skill-Loop-CSP](https://github.com/ChristianBrowning213/Skill-Loop-CSP/tree/b2130661b4690623877e852dc03132506aa720dd) `b2130661b4690623877e852dc03132506aa720dd` | Complete tree names; `pyproject.toml`; repository documentation; source headers | No licence file, metadata, README statement, or source header found. Git history contains Christian Browning identities; employment, institutional ownership, and contributor scope are not established. | `NO_EXPLICIT_LICENSE`; adapted workflow contracts/policy block release. |
| [Structured Crystal Analyser](https://github.com/ChristianBrowning213/Structured_Crystal_Analyser/tree/e5b291312151f34949a5e6ef0f43bebfeb752bc9) `e5b291312151f34949a5e6ef0f43bebfeb752bc9` | Complete tree names; `pyproject.toml`; README; source headers | No licence file, metadata, README statement, or source header found. Pyproject names only “Structured Crystal Analyser contributors.” | `NO_EXPLICIT_LICENSE`; no implementation is copied. Ticket 11 removed the Git dependency/validation extra from public metadata and retains only the lazy adapter. |
| [ipcsp-spp](https://github.com/lrcfmd/ipcsp-spp/tree/ef9c5cc2924fae6ee35d0c5e526c132c17e1a014) `ef9c5cc2924fae6ee35d0c5e526c132c17e1a014` | Root `LICENSE`; `setup.py`; README | MIT, Copyright (c) 2026 Leverhulme Research Centre for Functional Materials Design. Setup metadata names Vladimir Gusev. README names an under-review manuscript without final DOI. | Permissive for that repository with notice, but no packaged runtime blob matches it and SPP-Maker lineage is not documented. It cannot supply the missing SPP-Maker licence. |

The exact checks included conventional licence filenames (`LICENSE`,
`LICENSE.txt`, `LICENCE`, `COPYING`, and `NOTICE`), package metadata, README
statements, and `Copyright`, SPDX, MIT, or GPL-style source headers. No hidden
file-level licence was found for the four `NO_EXPLICIT_LICENSE` repositories.

## File-level result

`SOURCE_ATTRIBUTION_MATRIX.csv` maps the installed code, resources, examples,
and migrated test families. Git blob comparison established, among other
matches:

- substantial QLIP runtime code, all six POTs, base JSON, schemas, examples,
  and its licence are exact copies;
- eleven Crystal-DB modules, all three schemas, and retrieval defaults are exact
  copies;
- SPP `io_cif.py`, `neighbors.py`, `weights.py`, and `compat.py` are exact
  source blobs; other SPP modules are import/path adaptations;
- workflow/retrieval/generation/schema code is an adaptation of Skill-Loop-CSP,
  not a verbatim tree copy;
- SCA is called through a new lazy adapter and no SCA implementation is copied.

None of the inspected upstream Python or data files contained a licence header
that the migration stripped. No speculative headers were added.

## Bundled asset evidence

| Asset | Evidence | Licensing conclusion |
| --- | --- | --- |
| Six SrTiO3 POTs | Byte-identical to QLIP paths at the frozen revision; introduced together by QLIP commit `6aed49d` under a Christian Browning Git identity; files contain model parameters but no generator/input provenance | QLIP root MIT notice is retained, but authority/provenance for the scientific assets requires confirmation; bundled-asset blocker |
| Base chemistry/radii JSON | Byte-identical to QLIP `data/base`; `provenance.json` records generator, versions, field sources, and literature citations for ASE, mendeleev, pymatgen, and SMACT | Scientific provenance is useful but upstream data/package licensing was not recorded; derived-compilation redistribution requires review; blocker |
| QLIP radii policy and MCP schemas | Exact QLIP repository content under its root MIT licence | Permitted with retained QLIP notice |
| Crystal-DB schemas/defaults | Exact Crystal-DB repository content | Blocked with the unlicensed source repository |
| Covalent-rules example | Exact SPP-Maker-QLIP content | Blocked with the unlicensed source repository |
| Synthetic demo structures/configuration | Generated at runtime or newly written in this repository; no external CIF is shipped | Covered by root MIT to the extent the named holder owns it |

No production CIF corpus, SQLite database, stored embedding, broad POT corpus,
model weight, or benchmark data is bundled.

## Root MIT and attribution

The root MIT licence remains appropriate only for newly authored material for
which Christian Browning has authority to grant rights. It does not cure absent
rights in copied or adapted material. QLIP's separate MIT notice is preserved
at `packages/qlip/LICENSE` and identified in `THIRD_PARTY_NOTICES.md`.

`CITATION.cff` was reviewed and deliberately not expanded beyond Christian
Browning. The root repository evidence supports that maintainer/software-author
statement, but does not establish complete scientific authorship. Its
project-wide `license: MIT` field was removed while integrated rights remain
unresolved. Upstream dependency contributors are not automatically authors of
this integration. QLIP's established copyright attribution is handled in its
licence and notice. No complete preferred scientific citation was stated by
QLIP, SPP-Maker-QLIP, or SCA at the frozen revisions. The related `ipcsp-spp`
paper was still under review and lacked a final DOI.

The release decision and smallest required owner actions are recorded in
`LICENSING_RELEASE_DECISION.md`; Ticket 11's component paths and unsent request
templates are in `LICENSING_REMEDIATION_MATRIX.md` and
`permission_requests/`.

Ticket 11 isolated SCA by removing its Git dependency and public validation
extra. No other blocker received permission evidence or an upstream licensing
commit, so no other component is marked resolved or excluded.

LICENSING_BLOCKED
