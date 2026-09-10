# Licence and attribution audit

This is an engineering inventory, not legal advice. Absence of a licence is not
permission to redistribute.

| Source repository | Observed licence at audited revision | Copied/migrated code? | Compatibility issue | Action needed |
| --- | --- | --- | --- | --- |
| qlip (a619ab379c62b5edefd6bb00076267e149f283ce) | MIT, copyright Vladimir V. Gusev | Yes | MIT is compatible if notice is preserved | Preserved in packages/qlip/LICENSE; retain upstream scientific attribution |
| Crystal-DB (e33d5cc55be01f800a7cf055cc1793d982deb5bc) | No licence file or project licence metadata observed | Yes | Redistribution permission is not established | Obtain/record licence and contributor approval |
| SPP-Maker-QLIP (3a2d557811973265f3373ec881cc8057a89789d2) | No licence file or project licence metadata observed | Yes | Redistribution permission is not established | Obtain/record licence and attribution |
| ipcsp-spp (ef9c5cc2924fae6ee35d0c5e526c132c17e1a014) | MIT, Leverhulme Research Centre for Functional Materials Design | Related SPP lineage; exact copied scope needs confirmation | MIT notice must follow any copied portions | Perform file-level provenance review and preserve applicable notice |
| Skill-Loop-CSP (b2130661b4690623877e852dc03132506aa720dd) | No licence file or project licence metadata observed | Workflow logic migrated | Redistribution permission is not established | Obtain/record licence and contributors |
| Structured Crystal Analyser (e5b291312151f34949a5e6ef0f43bebfeb752bc9) | No licence file or project licence metadata observed | No code bundled; installed as pinned external dependency | Installation/redistribution terms are unclear | Add an upstream licence before public release |
| CSP_LLM_Orchestrator- (b7f6c6555ce5d56c79d47d127fdf664021b30601) | MIT, generic 2026 copyright | No supported agentic subsystem migrated | No current bundled-code issue established | Retain provenance if future code is migrated |

The root MIT file covers work for which its named copyright holder can grant
rights; it cannot cure missing upstream permissions. Crystal-DB intentionally
has no licence assertion in package metadata pending resolution.

CITATION.cff identifies Christian Browning as package maintainer/author. Vladimir
V. Gusev is recorded in QLIP distribution metadata as the observed upstream
QLIP author. A complete scientific contributor list was not inferable from the
available source metadata and must be established before release. The release
is blocked on licensing and attribution.
