# Third-party notices

This file distinguishes upstream material from software covered by the root
Christian Browning MIT notice.

## QLIP

- Source: https://github.com/vlgusev/qlip
- Scientific revision: `a619ab379c62b5edefd6bb00076267e149f283ce`
- Licence: MIT
- Copyright: Copyright (c) 2025 Vladimir V. Gusev

The exact QLIP notice is retained at `packages/qlip/LICENSE` and included in
the standalone QLIP and integrated distributions. It is not replaced by the
root notice. QLIP's provenance resource records the Cordero, Pyykko, Meija, and
Shannon scientific citations used by its runtime-derived chemistry data.

## Authorized Christian Browning repositories

Christian Browning explicitly authorized distribution of the identified code
under MIT. Scientific and later licensing revisions remain separate:

| Project | Scientific revision | MIT licensing commit |
| --- | --- | --- |
| Crystal-DB | `e33d5cc55be01f800a7cf055cc1793d982deb5bc` | `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31` |
| SPP-Maker-QLIP | `3a2d557811973265f3373ec881cc8057a89789d2` | `82114cd05f0cb40149d13c20adeafe4c437a03ae` |
| Skill-Loop-CSP | `b2130661b4690623877e852dc03132506aa720dd` | `36f6280e47387643853ac0cfc510e20c5d595834` |

The SPP lineage audit found no copied code expression from the related
MIT-licensed `ipcsp-spp` repository at
`ef9c5cc2924fae6ee35d0c5e526c132c17e1a014`. That project's notice does not
replace SPP-Maker-QLIP's own licence or settle scientific-method attribution.

## Runtime chemistry sources

QLIP generates element, radii, and ionic-radii values in memory from pinned
ASE 3.27.0 (LGPL-2.1-or-later), mendeleev 1.1.0 (MIT), pymatgen 2026.5.4
(MIT), and SMACT 4.0.0 (MIT) installations. The compiled JSON tables are not
distributed. Dependency notices and scientific citations remain applicable.

## Excluded material

Structured Crystal Analyser revision
`e5b291312151f34949a5e6ef0f43bebfeb752bc9` has no established licence. No
SCA implementation, dependency, or installation extra is distributed; only a
generic lazy adapter remains. Users may configure a compatible validator only
where legally and technically appropriate.

The six unresolved SrTiO3 POT assets, legacy radii JSON, production databases,
CIF corpora, stored embeddings, broad POT libraries, model weights, and
benchmark artifacts are not included.
