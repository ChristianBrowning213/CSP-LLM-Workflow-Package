# Recovery Status

Recovery baseline established.

| Subsystem | Status | Note |
|---|---|---|
| Skill-Loop-CSP | `NOT_RESTORED` | Source runtime has not been migrated. |
| Crystal-DB software | `RESTORED` | Complete scientific-revision package, CLI, MCP, schemas, tests and operational support code migrated in Ticket 24. |
| Crystal-DB operational assets | `BLOCKED_PROVENANCE` | Canonical `phase6_mp_10k.db` is hash-pinned and operationally verified, but all 10,000 records are Materials Project-derived and marked `allow_export=0`; no redistribution approval is recorded. |
| Crystal-DB | `BLOCKED_PROVENANCE` | Software is restored; the required operational snapshot cannot be included until a human clears redistribution. |
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

## Ticket 25 asset audit

- Canonical database: `phase6_mp_10k.db`, 881,799,168 bytes, SHA-256
  `572448fbcb7716d315246f24dd427064715fd56839d0b4450cc6a8231a0e5dc0`.
- Read-only inventory: 20 candidate databases, all passing SQLite integrity
  and foreign-key checks.
- Real-data source/archive probes on temporary copies: exact text retrieval,
  CSP-pack, novelty and readiness results.
- Required database status: `REQUIRED_BUT_PROVENANCE_BLOCKED`.
- Runtime asset bytes copied: zero.
