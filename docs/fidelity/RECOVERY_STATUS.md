# Recovery Status

Recovery baseline established.

| Subsystem | Status | Note |
|---|---|---|
| Skill-Loop-CSP | `RESTORED` | Original `sok_llm_orchestrator` runtime, CLI, prompts, schemas and six-tool execution chain restored; real bundled MCP defaults verified. |
| Crystal-DB software | `RESTORED` | Complete scientific-revision package, CLI, MCP, schemas, tests and operational support code migrated in Ticket 24. |
| Crystal-DB operational assets | `BLOCKED_PROVENANCE` | Canonical `phase6_mp_10k.db` is hash-pinned and operationally verified, but all 10,000 records are Materials Project-derived and marked `allow_export=0`; no redistribution approval is recorded. |
| Crystal-DB | `SOFTWARE_RESTORED_DATA_BOOTSTRAP_REQUIRED` | Historical snapshot remains blocked; recovered MP request and source-faithful local bootstrap are ready and a one-record live build passed. |
| SPP-Maker-QLIP software | `RESTORED` | Original `spp_maker`/`spp_maker_qlip`/`spp_maker_mcp` namespaces, CLI, MCP server, calibration/publishing/schemas restored in Ticket 26. |
| SPP-Maker-QLIP operational POT assets | `BLOCKED_PROVENANCE` | Canonical 3,388-pair ICSD regulator identified and hash-frozen; no redistribution evidence, so zero canonical bytes copied. Nine QLIP built-ins and source fixtures restored. |
| SPP-Maker-QLIP | `SOFTWARE_RESTORED_ASSETS_PENDING` | Software fully restored and source-vs-archive parity proven (byte-exact POT output, exact scores, identical QLIP packaging, identical failure behavior); production POT libraries deferred to a future ticket. |
| QLIP | `SOFTWARE_RESTORED_ASSETS_BLOCKED` | Full source namespace, resources, CLI, six-tool MCP surface and tests restored; broad regulator/specialist corpus remain blocked. |
| SCA | `RESTORED` | Complete supported package and CLI bundled; no VCS fetch. Optional weights and external benchmark assets remain external. |
| Runtime assets | `PROVENANCE_BOUNDARY_ENFORCED` | Cleared tracked resources restored; MP database, canonical regulator, specialist corpora and optional models are not redistributed. |
| Invented v0.2 agent runtime | `ISOLATED` | Removed from active runtime; design retained only as history. |

Overall Ticket 32 status: `SOURCE_FIDELITY_RESTORED_DATA_BOOTSTRAP_REQUIRED`.

## Tickets 27–32

- T27: `SPP_POT_ASSETS_BLOCKED_PROVENANCE`
- T28: `QLIP_SOFTWARE_RESTORED_ASSETS_BLOCKED`
- T29: `CRYSTAL_DB_BOOTSTRAP_READY`
- T30: `SCA_RESTORED`
- T31: `SKILL_LOOP_RUNTIME_RESTORED`
- T32: `SOURCE_FIDELITY_RESTORED_DATA_BOOTSTRAP_REQUIRED`

See `OVERNIGHT_RECOVERY_REPORT.md` and `FINAL_SOURCE_PARITY.md` for current
test counts, edge verification, remaining externals, and Git safety evidence.

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

## Ticket 34 — final remediation and clean-room verification

Remediation commit: `9be55e904078d4ad33a595f142352f64b0cd5f85`.
Correction commit (one follow-up defect found during clean-room
verification, see below): `5eeb6527c433a697b188b256a4c20d4fb41cb234`.

All five Ticket 33 blockers fixed and independently re-verified from a
clean detached worktree at the correction commit:

| Ticket 33 blocker | Status | Evidence |
|---|---|---|
| Incomplete SPP packaging (colliding `spp_maker_qlip` shim) | `FIXED` | `packages.find` `where` reordered so `packages/spp_maker_qlip/src` resolves last/authoritative; installed `spp_maker_qlip.__file__` and `required_pair_extraction` submodule confirmed resolving from the full 5-module source package, not the 2-module Skill-Loop compatibility shim. |
| Missing Skill-Loop schema (`schema.skillcard.v1.json`) | `FIXED` | Added to `sok_llm_orchestrator` package-data; installed wheel copy SHA-256-identical to source. |
| Crystal bootstrap files missing from sdist | `FIXED` | `MANIFEST.in` added; sdist contains `data/crystal_db/requests/README.md`, `default_mp_requests.txt`, `scripts/crystal_db/grab_data.py`, `packages/crystal_db/grab_mp_bulk.py`, and `packages/crystal_db/scripts/*.py`. Dry-run bootstrap parses cleanly from an extracted sdist; live build without `MP_API_KEY` fails explicitly (exit 2, clear message, not a raw traceback). |
| Historical/sibling runtime path assumptions | `FIXED` | `github_parent` path_base removed entirely from `corpus_registry.json` (0 of 21 entries remain); `DEFAULT_REGISTRY` now resolves via the installed module's own `__file__`; `paper_final_v1.py`'s `../Crystal-DB/...` dereference replaced with a package-relative path. Installed-package import and corpus-registry load succeed with zero sibling-repository access. |
| Canonical regulator POT provenance boundary | `HONEST_BOUNDARY_DOCUMENTED` | README.md and `docs/external_assets.md` explicitly state the historical 3,388-pair regulator is not redistributed (provenance unresolved), distinct from the 9 bundled QLIP fixture POTs. `SKILL_LOOP_REGULATOR_SPP_ROOT` is wired into real code (`contracts/spp_regularisation.py`, `workflow/runner.py`, `config/workflow/default.json`), not just documented. |

One new defect was found during clean-room verification (not one of
Ticket 33's five) and fixed under the correction workflow: the `sca`
console script crashed with `ModuleNotFoundError: No module named 'typer'`
on a plain `pip install llm-csp`, because `sca/cli.py`'s unconditional
imports (`pandas`, `typer`, `click`, `rich`) lived only in the optional
`[validation]` extra. Fixed by moving exactly those four packages to base
`dependencies` in `pyproject.toml` (commit `5eeb6527`). Verified from a
fresh clean-commit build: all 7 console/MCP entry points
(`llm-csp`, `crystal-db`, `crystal-db-mcp`, `spp-maker`, `spp-maker-mcp`,
`sca`, `sokllm`) now work with no extras installed, and `pip check` stays
clean.

Test regression check (all runs at commit `5eeb6527` or the equivalent dev
checkout, compared against Ticket 33's documented baselines):

- Root suite (`tests/`): **178 passed, 5 skipped** — exact match, no
  regression.
- QLIP package suite (`packages/qlip/tests`, scoped to its own directory):
  **242 passed, 13 failed** — exact match to the Ticket 33 baseline; all 13
  failures trace to the same pre-existing, already-documented external
  `QLIP_SCAFFOLD_CORPUS_ROOT` data dependency (`SHOULD_BE_ARCHIVED` /
  `PROVENANCE_BLOCKED`-adjacent, not redistributed).
- SPP-Maker-QLIP package suite: **111 passed, 18 failed** — exact match to
  the Ticket 33 baseline; 17 require pre-published external material
  systems tied to the blocked regulator POT library, 1 is the known MCP
  schema-snapshot environment-drift nuance.
- SCA (`tests/integration/validation/test_sca_adapter.py`): **4 passed, 0
  failed**, including the family-topology test.
- Skill-Loop-CSP package suite (`packages/skill_loop_csp/tests`, live-LLM
  tests marker-deselected): **1213 passed, 118 failed, 7 skipped, 16
  deselected** (1354 total items — exact total-item match to the Ticket 33
  baseline of 1234+98+22=1354, but the pass/fail split differs numerically
  from the documented 1234/98/22). Investigated: the 118 failures are not
  attributable to the remediation commit. They decompose into (a) ~39
  failures from a "repository root discovery" helper in legacy
  paper-reproduction tooling that only works when running from a real dev
  checkout path, tripped here because this session's Python environment has
  an editable install whose `__file__` resolves through a site-packages
  stub; (b) the large majority are `FileNotFoundError` for untracked,
  gitignored historical paper-run artifacts under
  `packages/skill_loop_csp/artifacts/...` — the same
  "excluded external datasets/models/historical outputs" category Ticket 33
  already documented; (c) missing optional `megnet` package (documented
  `OPTIONAL_FEATURE`); (d) missing bootstrapped Crystal database (requires
  the Materials Project bootstrap, an already-documented external
  requirement). No failure signature outside these four known categories
  was found.
- Skill-Loop model-free fixture/replay path: **10 passed, 0 failed**
  (`test_agentic_chain_runtime_stub.py` + `test_agentic_c_layer_replay_e2e.py`),
  concretely exercising Planner (`planner_result`), Run Manager
  (`run_manager_log`), Orchestrator (`orchestrator_decision`), Evaluator
  evidence, and an ordered tool-execution step sequence (`c_steps`).
- Skill-Loop bundled-MCP-modules wiring test
  (`test_skill_loop_defaults_launch_bundled_mcp_modules`): **passed**.
- MCP tool-surface parity (installed server registrations vs. recorded
  snapshots): Crystal-DB 6/6 exact, SPP-Maker 4/4 exact, QLIP 6/6 exact —
  zero missing, zero invented, zero drift.
- Real clean E2E: the source SrTiO3 SPP→QLIP→Gurobi fixture
  (`tests/integration/spp/test_srtio3_qlip.py`, real
  `pyo.SolverFactory("gurobi")`, not mocked) is part of the passing root
  178.

Final wheel/sdist inclusion audit (built from the clean detached worktree
at `5eeb6527`): no historical Crystal databases, no blocked regulator
libraries beyond the 9 allowed QLIP fixture POTs, no benchmark outputs, no
local runs, no grunt/swarm infrastructure, no developer caches in the
wheel; all required Crystal bootstrap files and the Skill-Loop schema
present in wheel/sdist as applicable.

Overall Ticket 34 status: `SOURCE_FIDELITY_RESTORED`,
`READY_WITH_DOCUMENTED_EXTERNAL_REQUIREMENTS`. See `PROJECT_CLOSEOUT.md`
for the full final report.
