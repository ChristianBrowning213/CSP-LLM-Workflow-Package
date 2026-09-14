# Recovery Status

Recovery baseline established.

| Subsystem | Status | Note |
|---|---|---|
| Skill-Loop-CSP | `NOT_RESTORED` | Source runtime has not been migrated. |
| Crystal-DB software | `RESTORED` | Complete scientific-revision package, CLI, MCP, schemas, tests and operational support code migrated in Ticket 24. |
| Crystal-DB operational assets | `BLOCKED_PROVENANCE` | Canonical `phase6_mp_10k.db` is hash-pinned and operationally verified, but all 10,000 records are Materials Project-derived and marked `allow_export=0`; no redistribution approval is recorded. |
| Crystal-DB | `BLOCKED_PROVENANCE` | Software is restored; the required operational snapshot cannot be included until a human clears redistribution. |
| SPP-Maker-QLIP software | `RESTORED` | Original `spp_maker`/`spp_maker_qlip`/`spp_maker_mcp` namespaces, CLI, MCP server, calibration/publishing/schemas restored in Ticket 26. |
| SPP-Maker-QLIP operational POT assets | `ASSET_DEFERRED` | 102,847 files inventoried (SHA-256, dedup) across `SPP-Maker-QLIP`/`Skill-Loop-CSP`/`QLIP`; zero bytes copied. Canonical broad-regulator library not yet materialized. |
| SPP-Maker-QLIP | `SOFTWARE_RESTORED_ASSETS_PENDING` | Software fully restored and source-vs-archive parity proven (byte-exact POT output, exact scores, identical QLIP packaging, identical failure behavior); production POT libraries deferred to a future ticket. |
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

## Ticket 26 verification

- Source revision `3a2d557811973265f3373ec881cc8057a89789d2` (scientific),
  `82114cd05f0cb40149d13c20adeafe4c437a03ae` (licensing) frozen via
  `git show`/`git ls-tree` only; source repository never modified.
- 114 tracked operational source files manifested with SHA-256; verbatim
  baseline (101 files, + 5 initially-omitted `scripts/*.py`, + 9 initially-
  omitted `QLIP_Outputs/` static files) independently re-hashed against the
  live source repository with zero drift.
- Restored source-suite (`packages/spp_maker_qlip/tests`): 111 passed, 18
  failed, 129 collected. Every failure individually diagnosed: 1 MCP
  schema-snapshot difference (environment/dependency drift — an extra
  `allow_fallback_precompiled` field emitted by the installed schema
  library versus the source-revision snapshot); 17 QLIP-handoff tests that
  require several distinct pre-published material systems (ABO3, CoAs2,
  ZnS, LiCoO2) which only ever existed as the original author's local,
  untracked generated state — never reachable from the frozen git
  revision, confirmed by inspecting the live source repository directly.
- Direct source-vs-archive parity (isolated frozen-revision checkout vs.
  restored archive, safe fixture CIFs only): fitting — required pairs
  match, manifest matches exactly (env-specific fields excluded), fitted
  POT file byte-for-byte identical; scoring — exact match; QLIP packaging —
  identical filenames, identical POT hashes, identical registry category
  structure; failure behavior — identical exit codes and exception classes
  across 5 deliberate invalid-input scenarios. Regulator-decision parity
  specifically: honestly reported blocked (no CLI verb exposes it; the
  harness is restricted to subprocess invocation to avoid fabricating an
  API) — not fabricated, not silently skipped.
- Existing `llm_csp.spp`/`llm_csp.workflow`/QLIP integration suite: 129
  passed, 3 skipped, 0 failed — zero regressions.
- Whole unified archive suite (incl. Crystal-DB): 346 passed, 6 skipped, 2
  failed — both failures pre-existing and unrelated to Ticket 26 (missing
  optional `robocrys` dependency; a version-pin mismatch on the externally
  vendored `sca` package, `0.1.0` installed vs. `0.1.1` expected).
- Resolved a pre-existing, repo-wide packaging defect (root
  `pyproject.toml`'s `license = "MIT"` was invalid under this
  environment's setuptools 70.2.0) as part of final installed-package
  verification — `pip install -e .` now succeeds. Found and worked around
  (without touching the base Python environment) two pre-existing,
  unrelated global editable installs (`SPP-Maker-QLIP`, `Skill-Loop-CSP`)
  that would otherwise silently shadow the restored archive's namespace
  packages.
- POT asset inventory: 102,847 files across `SPP-Maker-QLIP`/
  `Skill-Loop-CSP`/`QLIP`, 17,933 SHA-256 duplicate groups identified; zero
  bytes copied.
- No agent restoration started (Skill-Loop Planner/Run Manager/Evaluator/
  Orchestrator/LM Studio/Ollama runtimes/prompts all untouched).
- Crystal-DB status unchanged: `BLOCKED_PROVENANCE`.
- v0.1.0 tag verified unchanged: dereferences to
  `2dbf5e8852dc62c42d97385bc96ea90166d0fc74`.
