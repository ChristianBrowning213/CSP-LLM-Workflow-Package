# Ownership and authority confirmation record

Audit date: 2026-09-12.

## Authorization received

The project owner supplied this explicit authorization for Ticket 14:

> Christian Browning confirms that the identified Crystal-DB, SPP-Maker-QLIP and Skill-Loop-CSP code is his code and authorizes its distribution under the MIT licence.

This resolves the previously recorded human authority gate for those three
codebases. It does not extend to QLIP code owned by upstream authors, SCA,
third-party data, unresolved scientific POT assets, or third-party chemistry
datasets.

## Evidence and implementation

| Repository | Prior Git evidence | Authority | Approved licence | Scientific source commit | Licence-only commit |
| --- | --- | --- | --- | --- | --- |
| Crystal-DB | 16 commits; only Christian Browning identity observed | **YES** | MIT | `e33d5cc55be01f800a7cf055cc1793d982deb5bc` | `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31` |
| SPP-Maker-QLIP | 12 commits; only Christian Browning identity observed; no copied `ipcsp-spp` code expression found | **YES** | MIT | `3a2d557811973265f3373ec881cc8057a89789d2` | `82114cd05f0cb40149d13c20adeafe4c437a03ae` |
| Skill-Loop-CSP | 61 commits; only Christian Browning identity observed | **YES** | MIT | `b2130661b4690623877e852dc03132506aa720dd` | `36f6280e47387643853ac0cfc510e20c5d595834` |

Each upstream commit adds the standard MIT licence naming Christian Browning
and sets project metadata to MIT. No scientific implementation file changed.
The scientific revision remains separately recorded so the later licensing
commit is not misrepresented as the migration source.

AUTHORITY_CONFIRMED
