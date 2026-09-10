# Third-party notices

This file records third-party material present in, or explicitly interfaced by,
this repository. It is an attribution record, not a grant of rights for
components whose licensing is unresolved. The root `LICENSE` applies only to
material for which its copyright holder is entitled to grant that licence.

## QLIP

- Source: https://github.com/vlgusev/qlip
- Frozen revision: `a619ab379c62b5edefd6bb00076267e149f283ce`
- Observed licence: MIT
- Copyright notice: Copyright (c) 2025 Vladimir V. Gusev
- Derived areas: `packages/qlip/`, QLIP examples and QLIP-derived tests
- Required notice: the copyright and MIT permission notice must accompany
  copies or substantial portions.

The exact upstream licence is retained at `packages/qlip/LICENSE` and is
included in both the standalone QLIP distribution and integrated distribution.

The QLIP repository does not state a preferred scientific citation at the
frozen revision. Its bundled base-data provenance file records citations for
individual scientific radii and element-data sources; those citations are
scientific attribution and do not replace licence permission.

## Related SPP software and publication

`ipcsp-spp` (https://github.com/lrcfmd/ipcsp-spp), inspected at revision
`ef9c5cc2924fae6ee35d0c5e526c132c17e1a014`, is MIT-licensed to the
Leverhulme Research Centre for Functional Materials Design. Its metadata names
Vladimir Gusev as package author. Its README identifies the manuscript
“Quantum-ready Crystal Structure Prediction using Statistical Proxy
Potentials” as under review and provides no final DOI at that revision.

No packaged runtime file was found to be blob-identical to `ipcsp-spp`.
SPP-Maker-QLIP does not record whether or how its implementation derives from
that project, so this related licence and manuscript are not used to cure the
SPP-Maker-QLIP licensing gap. The lineage and appropriate scientific citation
require confirmation from the project owners.

## Components with no explicit licence at the frozen revision

The following projects are provenance disclosures, not permitted third-party
redistributions. Each exact revision was checked for `LICENSE`, `LICENCE`,
`COPYING`, `NOTICE`, package licence metadata, README licensing statements, and
source-file licence headers.

| Project | Frozen revision | Relationship | Status |
| --- | --- | --- | --- |
| Crystal-DB | `e33d5cc55be01f800a7cf055cc1793d982deb5bc` | code, schemas, and defaults copied/adapted into `packages/crystal_db/` | `NO_EXPLICIT_LICENSE`; redistribution blocked |
| SPP-Maker-QLIP | `3a2d557811973265f3373ec881cc8057a89789d2` | code and one policy example copied/adapted into `src/llm_csp/spp/` and `configs/examples/` | `NO_EXPLICIT_LICENSE`; redistribution blocked |
| Skill-Loop-CSP | `b2130661b4690623877e852dc03132506aa720dd` | workflow contracts and policy adapted into `src/llm_csp/{workflow,retrieval,generation,schemas}/` | `NO_EXPLICIT_LICENSE`; redistribution blocked |
| Structured Crystal Analyser | `e5b291312151f34949a5e6ef0f43bebfeb752bc9` | external Git dependency; implementation not copied | `NO_EXPLICIT_LICENSE`; advertised installation rights unresolved |

Public repository visibility is not treated as permission. See
`docs/packaging/LICENSING_RELEASE_DECISION.md` for the required owner actions.
