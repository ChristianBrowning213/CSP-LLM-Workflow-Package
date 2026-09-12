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
| Structured Crystal Analyser | `e5b291312151f34949a5e6ef0f43bebfeb752bc9` | `0382742a169507bcc356d60c73ae575063fc5af1` |

The SPP lineage audit found no copied code expression from the related
MIT-licensed `ipcsp-spp` repository at
`ef9c5cc2924fae6ee35d0c5e526c132c17e1a014`. That project's notice does not
replace SPP-Maker-QLIP's own licence or settle scientific-method attribution.

SCA is separately maintained and supported at package version 0.1.1, commit
`3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af`. The validation extra installs its
MIT-licensed software package. Repository benchmarks, paper/reference CIFs,
reports, datasets, generated outputs, and optional ML model assets are excluded
from SCA artifacts. ALIGNN, CHGNet, MatGL, MACE, SevenNet, their weights, and
their datasets retain their own independent terms.

## Runtime chemistry sources

QLIP generates element, radii, and ionic-radii values in memory from pinned
ASE 3.27.0 (LGPL-2.1-or-later), mendeleev 1.1.0 (MIT), pymatgen 2026.5.4
(MIT), and SMACT 4.0.0 (MIT) installations. The compiled JSON tables are not
distributed. Dependency notices and scientific citations remain applicable.

## Excluded material

The six unresolved SrTiO3 POT assets, legacy radii JSON, production databases,
CIF corpora, stored embeddings, broad POT libraries, model weights, and
benchmark artifacts are not included.
