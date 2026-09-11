# Licensing remediation matrix

Audit date: 2026-09-11. No Git author identity is treated as legal ownership
confirmation. `SELF_CONTROLLED` is therefore not assigned without an explicit
statement from the rights holder.

| Component | Ownership path | Current blocker | Who can resolve it | Evidence needed | Public-release fallback |
| --- | --- | --- | --- | --- | --- |
| QLIP code | `UPSTREAM_CONTROLLED` | None for code: MIT notice is explicit and retained | QLIP rights holder for any future clarification | Existing MIT file at frozen revision is sufficient for copied code; preserve notice | Retain under upstream MIT notice |
| Crystal-DB | `INSTITUTIONAL_OR_SHARED` | `NO_EXPLICIT_LICENSE` on exact copied modules, schemas, and defaults | Confirmed rights holder(s), and institution/employer if applicable | Signed/written authority statement plus upstream licence commit or redistribution permission | Exclude Crystal-DB namespace and expose a future external retrieval interface; not implemented in this ticket |
| SPP-Maker-QLIP | `INSTITUTIONAL_OR_SHARED` | `NO_EXPLICIT_LICENSE`; relationship to `ipcsp-spp` not established | Confirmed SPP-Maker rights holder(s), institutional owner if applicable, and upstream lineage owners where derived | Ownership/contributor confirmation, lineage statement, upstream licence commit or written permission | Exclude SPP builder and accept user-supplied POT roots through a future independently specified interface; not implemented |
| Skill-Loop-CSP workflow | `INSTITUTIONAL_OR_SHARED` | `NO_EXPLICIT_LICENSE` for adapted workflow contracts/policy | Confirmed rights holder(s) and institution/employer if applicable | Written authority plus upstream licence commit or permission covering modified redistribution | Permission or a separately managed clean-room replacement is required; no rewrite is attempted here |
| Structured Crystal Analyser | `UPSTREAM_CONTROLLED` | `NO_EXPLICIT_LICENSE` for advertised Git installation | Confirmed SCA rights holder(s) | Explicit upstream licence/permission and confirmation that public installation/use is covered | `EXCLUDED_FROM_PUBLIC_RELEASE`: Git dependency and validation extra removed; lazy adapter retained |
| Six SrTiO3 POT files | `ASSET_PROVENANCE` | Generator inputs, data sources, and licensing authority not recorded | Person/group that generated or owns the files and any contributing-data rights holders | Generator/tool/version, input sources, creation record, ownership authority, and redistribution permission | Remove POTs and require a user POT root if permission is denied; not applied while confirmation is pending |
| QLIP base chemistry/radii tables | `ASSET_PROVENANCE` | Derived from ASE, mendeleev, pymatgen, and SMACT without a recorded rights analysis | QLIP resource maintainer plus project/institutional rights reviewer | Exact source versions/files, applicable software/data licences, transformation record, notice obligations, and parity evidence if regenerated | Replace with runtime/build derivation only in a separate task that proves byte/value parity; otherwise exclude affected QLIP functionality |
| Newly authored integration code | `INSTITUTIONAL_OR_SHARED` | Root notice exists, but employment/institutional ownership was not independently verified | Christian Browning and any employer/institution with applicable rights | Written confirmation of authority to publish under MIT | Withhold until authority is confirmed if institutional rights apply |

## Contributor evidence

At the audited scientific revisions, Git history shows only Christian Browning
identities for Crystal-DB, SPP-Maker-QLIP, Skill-Loop-CSP, and SCA. QLIP history
contains identities for Vladimir Gusev and Christian Browning, while its MIT
notice names Vladimir V. Gusev as copyright holder. SCA metadata uses the
generic label “Structured Crystal Analyser contributors.” These facts identify
people to contact; they do not establish sole ownership, employment IP status,
or authority to relicense.

Every unresolved case is therefore `REQUIRES_HUMAN_CONFIRMATION`.

## Permission and upstream-commit evidence

No private correspondence, signed permission, maintainer confirmation, or
institutional IP decision was supplied for this ticket. No permission request
was sent automatically.

An online `git ls-remote` recheck on 2026-09-11 found no new licence-confirming
revision on the relevant public branches. Crystal-DB `mcp` remained at
`e33d5cc55be01f800a7cf055cc1793d982deb5bc`, SPP-Maker-QLIP `SPP_MCP`
remained at `3a2d557811973265f3373ec881cc8057a89789d2`, and SCA `main`
remained at `e5b291312151f34949a5e6ef0f43bebfeb752bc9`. The remote
Skill-Loop-CSP branch tips did not provide a later licensing-confirmation
commit for the locally frozen scientific revision. Consequently:

```text
Crystal-DB licensing-confirmation commit: none
SPP-Maker-QLIP licensing-confirmation commit: none
Skill-Loop-CSP licensing-confirmation commit: none
SCA licensing-confirmation commit: none
```

The scientific source revisions remain unchanged. Any future licence-only
commit must be recorded separately rather than substituted for those scientific
revisions.

## Current component decisions

| Component | Decision | Evidence |
| --- | --- | --- |
| QLIP | `RESOLVED` | Explicit upstream MIT licence retained |
| Crystal-DB | `BLOCKED` | Exact copied material; no explicit licence or permission |
| SPP-Maker-QLIP | `BLOCKED` | Exact/adapted material; no explicit licence or established lineage permission |
| Skill-Loop-CSP | `BLOCKED` | Adapted workflow material; no explicit licence or permission |
| SCA | `EXCLUDED_FROM_PUBLIC_RELEASE` | No code bundled; Git dependency and public validation extra removed |
| SrTiO3 POT files | `BLOCKED` | Still bundled pending owner/data confirmation; removal fallback documented |
| Chemistry/radii resources | `BLOCKED` | Still bundled pending data-rights review; parity-preserving derivation is future work |

## Bundled POT identity

These are the exact bundled files reviewed. Hashes are SHA-256.

| Pair | Bytes | SHA-256 |
| --- | ---: | --- |
| O-O | 18543 | `45d0b5d18b7ebcf4ec5b34b37f510be6f4d7b39dfc5379ac8442d18820bab6eb` |
| O-Sr | 18553 | `1082622447502233a736b148ef191dc33122195223a6370ce00776324acc34f7` |
| O-Ti | 18535 | `f0bfa99dc765c7a2f3c632113c588a4516d253f78e18f12806d9c9c304a4556a` |
| Sr-Sr | 18521 | `f5492b8f04dd406b740d53e3406a2e05b99ef09575e6f0fc88c9ee1d489398a6` |
| Sr-Ti | 18523 | `574d60742a956d3ba0dfe789c4e83dfd4c839174278e992a748516bce00b1388` |
| Ti-Ti | 18525 | `57cf57d594f16ee75deb1113be0b0d612d1b11a45e89f79e7543546263af7c5a` |

Git evidence identifies only the QLIP introducing commit `6aed49d` and its
committer identity. It does not identify the generator, input dataset, or
licensing authority, so no inference is made about who generated the assets.

## Chemistry/radii resource inventory

| File | Classification | SHA-256 |
| --- | --- | --- |
| `elements.json` | Generated/transformed element table from named package APIs | `1456486184a1854330bfaf99afee734c41a0f47b0f7a0dff2a22268738c9f75d` |
| `ionic_radii.json` | Generated/transformed ionic-radii table from named package APIs | `acb6af1a4f67c6246c4db1689ee533a1c9d31efea00ab50535730fa4acd42a07` |
| `radii.json` | Generated/transformed atomic/covalent/van-der-Waals radii table | `fab9add217a03f460f75e5f8d4bc673cbe8a3e5e5ed7afcc9f048e5c087f9a6f` |
| `pair_distance_policy.json` | QLIP-authored policy/configuration, not identified as copied scientific data | `bac724476cee9412c314967a7fb88ca421cb3fefec86c30cc16e48dd4f393bc5` |
| `radius_policy.json` | QLIP-authored policy/configuration, not identified as copied scientific data | `d88c7157ff73e499592222034543b75011dbe6103b78ef24e9c3786fb9d0807f` |
| `provenance.json` | Generated provenance metadata | `67c90ea77afcc26052a84a2c68cd46c0b531b6b8a0c7bb1f864b92c56e22843f` |

The generated tables cite ASE 3.27.0, mendeleev 1.1.0, pymatgen 2026.5.4,
and SMACT 4.0.0. The available provenance records transformations and
scientific citations but not the exact upstream data-file licences or a
redistribution analysis; the three data-bearing tables remain blocked.

The current integrated repository remains outside the public-release boundary.
Only the newly authored material (subject to ownership authority), QLIP code
under its retained MIT notice, and the generic validation adapter can presently
be identified as potentially publishable components. They have not been split
into a separate distribution in this ticket.
