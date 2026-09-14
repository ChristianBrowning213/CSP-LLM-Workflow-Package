# Recovery Status

Recovery baseline established.

| Subsystem | Status | Note |
|---|---|---|
| Skill-Loop-CSP | `NOT_RESTORED` | Source runtime has not been migrated. |
| Crystal-DB | `PARTIAL` | Existing reduced source-derived package retained. |
| SPP-Maker-QLIP | `PARTIAL` | Existing reduced `llm_csp.spp` implementation retained. |
| QLIP | `PARTIAL` | Existing reduced source-derived package retained. |
| SCA | `EXTERNAL` | Supported package remains a VCS dependency. |
| Runtime assets | `PARTIAL / EXTERNALIZED` | Provenance-cleared operational assets are not yet restored. |
| Invented v0.2 agent runtime | `ISOLATED` | Removed from active runtime; design retained only as history. |

This file records migration progress after the immutable Ticket 22 audit. No
source subsystem was restored by the recovery-baseline ticket.

## Baseline verification

- Deterministic/non-agentic archive suite: 173 passed, 5 skipped.
- Fidelity guard: included in the passing suite.
- Recovery wheel: built and installed as `0.2.0.dev0+fidelity`.
- Installed imports: `qlip`, `crystal_db`, `llm_csp.workflow`, `llm_csp.spp`
  and `llm_csp.validation` passed.
- Changed-file Ruff check: passed. The repository-wide Ruff run still reports
  48 pre-existing findings in retained v0.1-derived code/tests; they were not
  modified because this baseline ticket prohibits scientific/source changes.
