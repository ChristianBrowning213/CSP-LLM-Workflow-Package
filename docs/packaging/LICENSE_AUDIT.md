# Licence and attribution audit

Audit date: 2026-09-12. This is an engineering inventory, not legal advice.

## Included software

| Component | Scientific source revision | Licensing evidence | Decision |
| --- | --- | --- | --- |
| QLIP | `a619ab379c62b5edefd6bb00076267e149f283ce` | Upstream MIT commit `f4bdb60ce36565954d9bfa5f6226979053fe70e9`; exact notice retained at `packages/qlip/LICENSE` | `RESOLVED` |
| Crystal-DB | `e33d5cc55be01f800a7cf055cc1793d982deb5bc` | Christian Browning authorization plus licence-only commit `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31` | `RESOLVED` |
| SPP-Maker-QLIP | `3a2d557811973265f3373ec881cc8057a89789d2` | Christian Browning authorization, independent-expression lineage audit, and licence-only commit `82114cd05f0cb40149d13c20adeafe4c437a03ae` | `RESOLVED` |
| Skill-Loop-CSP | `b2130661b4690623877e852dc03132506aa720dd` | Christian Browning authorization plus licence-only commit `36f6280e47387643853ac0cfc510e20c5d595834` | `RESOLVED` |
| SCA | `e5b291312151f34949a5e6ef0f43bebfeb752bc9` | Christian Browning authorization plus MIT commit `0382742a169507bcc356d60c73ae575063fc5af1`; package 0.1.1 at `3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af` | `RESOLVED` |

Authorization recorded for this ticket:

> Christian Browning confirms that the identified Crystal-DB, SPP-Maker-QLIP and Skill-Loop-CSP code is his code and authorizes its distribution under the MIT licence.

Ticket 15 separately records:

> Christian Browning confirms that the SCA code is his code and authorizes its distribution under the MIT licence.

The later licence commits do not alter the separately recorded scientific
source revisions. QLIP remains under its upstream owner's separate notice; the
Christian Browning authorization is not applied to QLIP. SCA remains a
separately maintained dependency; its implementation is not copied here. Its
wheel/sdist exclude repository benchmarks, reports, datasets, model assets,
tests, caches, and paper artifacts. ALIGNN, CHGNet, MatGL, MACE, SevenNet and
their weights/data remain external optional systems.

## Excluded software and assets

The six SrTiO3 POT files with unresolved parameter provenance were removed.
Their hashes and evidence remain in `POT_PROVENANCE.md`. The legacy
`qlip/resources/radii.json` was also removed after confirming no supported path
read it.

The former `elements.json`, `radii.json`, and `ionic_radii.json` compilations
are no longer included. `qlip.data.generated` derives every value lazily in
memory from pinned ASE, mendeleev, pymatgen, and SMACT installations. Full-table
regression hashes prove parity with the former tables. Resolved QLIP policy and
provenance JSON remain included.

No production CIF corpus, SQLite database, stored embeddings, broad POT
library, model weights, SCA implementation, or benchmark output is bundled.

## Included notices

The root MIT licence covers Christian Browning's authorized software. QLIP's
original MIT notice remains separately installed and identified in
`THIRD_PARTY_NOTICES.md`. Runtime dependency licences and scientific citations
remain applicable to their installed packages/data APIs.

No unresolved licensing blocker remains among files included in the public
distribution.

LICENSING_RESOLVED
