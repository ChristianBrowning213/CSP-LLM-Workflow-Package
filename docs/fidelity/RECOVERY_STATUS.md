# Recovery Status

Recovery baseline established.

| Subsystem | Status | Note |
|---|---|---|
| Skill-Loop-CSP | `NOT_RESTORED` | Source runtime has not been migrated. |
| Crystal-DB software | `RESTORED` | Complete scientific-revision package, CLI, MCP, schemas, tests and operational support code migrated in Ticket 24. |
| Crystal-DB production assets | `PENDING_TICKET_25` | Production database, CIF corpus, indexes and selected generated assets are inventoried but not copied. |
| SPP-Maker-QLIP | `PARTIAL` | Existing reduced `llm_csp.spp` implementation retained. |
| QLIP | `PARTIAL` | Existing reduced source-derived package retained. |
| SCA | `EXTERNAL` | Supported package remains a VCS dependency. |
| Runtime assets | `PARTIAL / EXTERNALIZED` | Provenance-cleared operational assets are not yet restored. |
| Invented v0.2 agent runtime | `ISOLATED` | Removed from active runtime; design retained only as history. |

This file records migration progress after the immutable Ticket 22 audit. No
Ticket 22 conclusion has been rewritten; later recovery progress is recorded
only in this status document.

## Baseline verification

- Deterministic/non-agentic archive suite: 173 passed, 5 skipped.
- Fidelity guard: included in the passing suite.
- Recovery wheel: built and installed as `0.2.0.dev0+fidelity`.
- Installed imports: `qlip`, `crystal_db`, `llm_csp.workflow`, `llm_csp.spp`
  and `llm_csp.validation` passed.
- Changed-file Ruff check: passed. The repository-wide Ruff run still reports
  48 pre-existing findings in retained v0.1-derived code/tests; they were not
  modified because this baseline ticket prohibits scientific/source changes.

## Ticket 24 verification

- Crystal-DB source suite in the unified archive: 175 passed, 1 skipped; the
  skipped test requires the deliberately deferred `phase6_mp_10k.db` snapshot.
- Direct source-revision/archive parity selection: 38 passed on each side.
- Clean, non-editable Crystal-DB wheel suite: 175 passed, 1 skipped.
- Whole unified archive suite: 344 passed, 7 skipped.
- Wheel imports, packaged schemas/policies, complete CLI help, MCP discovery,
  and the `crystal_db.mcp.server` compatibility alias passed.
