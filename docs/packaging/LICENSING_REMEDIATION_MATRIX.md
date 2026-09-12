# Licensing remediation matrix

Audit date: 2026-09-12.

| Component | Authority/licence evidence | Remediation applied | Current decision |
| --- | --- | --- | --- |
| QLIP code | Independent upstream MIT notice at scientific revision | Retain `packages/qlip/LICENSE` and separate attribution | `RESOLVED` |
| Crystal-DB | Christian Browning authorization | Upstream MIT licence-only commit `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31`; scientific revision remains `e33d5cc55be01f800a7cf055cc1793d982deb5bc` | `RESOLVED` |
| SPP-Maker-QLIP | Christian Browning authorization; no copied `ipcsp-spp` expression found | Upstream MIT licence-only commit `82114cd05f0cb40149d13c20adeafe4c437a03ae`; scientific revision remains `3a2d557811973265f3373ec881cc8057a89789d2` | `RESOLVED` |
| Skill-Loop-CSP | Christian Browning authorization | Upstream MIT licence-only commit `36f6280e47387643853ac0cfc510e20c5d595834`; scientific revision remains `b2130661b4690623877e852dc03132506aa720dd` | `RESOLVED` |
| Structured Crystal Analyser | Christian Browning owner authorization | MIT licence commit `0382742a169507bcc356d60c73ae575063fc5af1`; independently versioned 0.1.1 package commit `3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af`; validation extra restored | `RESOLVED` |
| Six SrTiO3 POT files | Hard-coded parameter provenance unresolved | Removed; user-supplied compatible POT root required | `EXCLUDED_FROM_PUBLIC_RELEASE` |
| Generated chemistry tables | Upstream package versions and citations known; compiled-table redistribution avoided | Generate lazily in memory from pinned dependencies; full-table parity test | `DERIVED_AT_RUNTIME` |
| QLIP policy/provenance resources | QLIP-authored under retained MIT | Retained | `RESOLVED` |
| Legacy radii JSON | Origin unresolved; no supported runtime reader | Removed | `REMOVED` |

## Authorization scope

The supplied statement authorizes only the identified Crystal-DB,
SPP-Maker-QLIP, and Skill-Loop-CSP code under MIT. Ticket 15 separately
authorizes SCA code. Neither authorization covers QLIP, third-party data, POT
parameters, chemistry datasets, or optional ML packages, weights, and data.
Each is handled independently above.

## Removed POT identity

| Pair | SHA-256 |
| --- | --- |
| O-O | `45d0b5d18b7ebcf4ec5b34b37f510be6f4d7b39dfc5379ac8442d18820bab6eb` |
| O-Sr | `1082622447502233a736b148ef191dc33122195223a6370ce00776324acc34f7` |
| O-Ti | `f0bfa99dc765c7a2f3c632113c588a4516d253f78e18f12806d9c9c304a4556a` |
| Sr-Sr | `f5492b8f04dd406b740d53e3406a2e05b99ef09575e6f0fc88c9ee1d489398a6` |
| Sr-Ti | `574d60742a956d3ba0dfe789c4e83dfd4c839174278e992a748516bce00b1388` |
| Ti-Ti | `57cf57d594f16ee75deb1113be0b0d612d1b11a45e89f79e7543546263af7c5a` |

The public package fails explicitly when an SPP objective has no `pot_root` or
`QLIP_SPP_POT_DIR`. Test-generated POTs are newly authored, clearly labelled
non-scientific fixtures, and are not package data.
