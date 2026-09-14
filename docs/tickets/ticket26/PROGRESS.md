# Ticket 26 — Progress Record

Parent ticket: `docs/tickets/TICKET_26.md`
Baseline commit: `f6a4fab7aa11bdcc6b76e25ee3ed6202578bad76` on `recovery/source-fidelity`.
No commits made yet for Ticket 26 — all work below is uncommitted working-tree
state, per parent Ticket 26 Phase 5 (single commit deferred to T26_16).

| Subticket | Status | Files changed | Tests run by Qwen | Tests independently run by Claude | Source-parity evidence | Unresolved issues |
|---|---|---|---|---|---|---|
| T26_01 Source freeze & manifest | **ACCEPTED** | `docs/fidelity/evidence/SPP_MAKER_SOURCE_MANIFEST.csv` (new); `.grunt-staging/spp_maker_source/<rev>/**` (new, untracked) | N/A (Claude-owned) | Re-computed SHA-256 for 5 sampled files (`cli.py`, `common_contract.py`, both `qlip_package.py` copies, `spp_maker_mcp/server.py`) against fresh `git show`; source repo HEAD/status confirmed unchanged before/after | 114/114 manifested files; 5/5 sampled hashes matched exactly | None |
| T26_02 Package skeleton + verbatim baseline | **ACCEPTED** | `packages/spp_maker_qlip/**` (new, 101 files) | N/A (Claude-owned) | Full 101/101 file byte-for-byte re-diff against `git show <scientific-rev>:<path>` | 101/101 byte-identical; package intentionally not yet importable (root not wired) | None |
| T26_03 Packaging & namespace wiring | **ACCEPTED** (with documented pre-existing gap) | `pyproject.toml` (root): added `spp-maker`/`spp-maker-mcp` scripts, appended `packages/spp_maker_qlip/src` to `packages.find.where` | Grunt ran `pip install -e .` (with and without build isolation) — both failed | Reproduced the same `pip install -e .` failure on the **unmodified** root pyproject.toml (proves pre-existing, not caused by this change); confirmed sandbox has no network access (build isolation cannot fetch a newer setuptools); reviewed full GRUNT_PATCH — only the 3 intended lines changed in `pyproject.toml` (excluded a stray `install_err.txt` debug artifact from the patch, not applied); verified `import spp_maker, spp_maker_qlip, spp_maker_mcp` via PYTHONPATH, confirmed both console-script targets (`spp_maker.cli:main`, `spp_maker_mcp.server:main`) are callable, and ran `spp-maker --help` end-to-end (real subcommands: `fit, score, calibrate, run`) | Package resolves to `packages/spp_maker_qlip/src/...`; CLI executes for real | **User-acknowledged open gap**: `pip install -e .` cannot be verified in this sandbox because the *unmodified* root `pyproject.toml`'s `license = "MIT"` is invalid under the offline environment's setuptools 70.2.0 (needs `{text=...}`/`{file=...}`). Per explicit user decision, left untouched as out-of-Ticket-26-scope; carried forward as a blocker for T26_15's isolated-venv test. |
| T26_04_CORRECTION_01 Restore 5 missing scripts | **ACCEPTED** | `packages/spp_maker_qlip/scripts/{check_pot_compat,demo_property_conditioned_spp,diagnose_pair_extraction,publish_qlip_outputs,print_qlip_snippet}.py` (new, 5 files) | Swarm worker (slot A) ran hash comparison + `pytest --collect-only` (129 collected, no error) | Independently re-hashed all 5 files in the swarm worktree AND in the final applied copy against a **live `git show` from the source repo** (not just the staged copy) — 5/5 MATCH both times; confirmed patch touched only these 5 new files, nothing else; root-caused the original tooling failure (a prior local-grunt attempt failed because `.grunt-staging/` was gitignored, silently excluded from every worker's worktree snapshot — fixed by removing it from `.gitignore`, independently confirmed via `git check-ignore` before re-dispatching) | 5/5 byte-identical to `3a2d557811973265f3373ec881cc8057a89789d2` | None |
| T26_04 Source test-suite migration | **ACCEPTED** (with two fully-diagnosed, documented non-blocking gaps) | Test-suite path/fixture adaptation already present from initial migration; unblocked by T26_04_CORRECTION_01 | N/A (this row now covers Claude's own full-suite verification) | Ran the complete `packages/spp_maker_qlip/tests` suite twice independently, with `PYTHONPATH` including `packages/spp_maker_qlip` itself (needed for `scripts` to resolve as a top-level import) and with `cwd=packages/spp_maker_qlip` (matching the source repo's own invocation convention — one test uses a bare `Path("tests/fixtures/cifs")` literal that is CWD-relative, not `__file__`-relative): **108 passed, 21 failed, 129 collected.** Diagnosed every failure individually rather than accepting a raw count: (1) **1 MCP schema-snapshot failure** (`test_tool_schemas_snapshot_stable`) — the live-generated schema has one extra field (`allow_fallback_precompiled`) versus the committed snapshot; classified as **environment/dependency drift** (a newer installed library version emitting additional JSON-schema metadata for an `Optional`/`anyOf` field) — this matches, and is very likely literally, Ticket 26 Part 44's own documented baseline ("1 dependency-sensitive schema snapshot failure"). (2) **20 QLIP-handoff failures** (`test_qlip_package_pot_handoff.py` ×14, `test_unified_qlip_output.py` ×5, `test_qlip_outputs_assets.py::test_integration_md_exists_and_mentions_sppcollection` ×1) — traced to source: these tests read `QLIP_Outputs/SPP/latest.txt`, which at the frozen revision points to `SPP/runs/20260514_090416_CoAs2_safflorite_dmytro_fit_neighbors_calib_scaled_285e1305/` — a directory that **exists only as untracked local state on the original author's own machine** (confirmed via `git status --short` on the live source repo: empty for `QLIP_Outputs/`, i.e. not tracked at all) and is not reachable from the frozen git revision by any means. A byte-for-byte clean clone of the source repo at this revision would fail these exact same tests identically — this is not a fidelity gap in the restoration, it is the source test suite depending on non-committed generated fixture data, which Ticket 26 Part 36 itself classifies as "generated request-specific output... not archive assets." | Full independent test-suite reproduction (108/129, twice); every failure individually traced to source-level cause, not archive omission | **Two documented, non-blocking gaps carried forward** (not further corrected under T26_04, per scope discipline): (a) the MCP schema-drift failure — no action needed unless T26_06 finds a real cause; (b) the 20 QLIP-handoff tests need a **fresh, legitimately-generated** `QLIP_Outputs/SPP/runs/<run>/spp_root/**/*.POT` (produced by running the now-verified-working `spp-maker run` pipeline against safe fixture CIFs, e.g. `tests/fixtures/cifs/nacl.cif`/`sic.cif`) with `latest.txt` updated to point at it — flagged for T26_08/T26_12, which already plan exactly this kind of safe-fixture pipeline run; not performed here to avoid scope creep beyond "clear T26_04's collection blocker." A second real finding, also Claude's own T26_01/T26_02 scoping mistake but **not corrected here**: `QLIP_Outputs/{INTEGRATION.md,README.md,SPP/latest.txt,GUIDANCES/latest.txt,CONSTRAINTS/latest.txt,.gitkeep placeholders}` are genuinely tracked static source content (confirmed via `git ls-tree` at the scientific revision) that T26_01 wrongly excluded via a blanket `QLIP_Outputs/` exclusion — this static content (distinct from the untracked generated run data above) should be verbatim-restored as part of T26_08's QLIP_Outputs work. |
| T26_05 CLI entry-point restoration | **ACCEPTED** (no grunt needed — packaging already done by T26_03) | none beyond T26_03's `pyproject.toml` scripts entry | N/A | Enumerated actual subcommands via `grep add_parser` in `cli.py` (`fit`@1316, `score`@1488, `calibrate`@1554, `run`@1642 — no separate `quality`/`package`/`export`/`required-pair` verbs, contrary to Ticket 26's illustrative list); ran `spp-maker --help` and all 4 subcommand `--help` end-to-end via PYTHONPATH — real, non-invented arguments for every one | `cli.py` diff against T26_02 baseline: zero lines changed | None. Ticket 26 Part 22's example command list does not match this source revision's actual CLI; documented rather than invented. |
| T26_06 MCP server restoration | attempts 1+2 REJECTED; correction 2 **ACCEPTED** | Attempts 1-2 rejected (invalid JSON, then fabricated `*Arguments` class names / tarball path — see prior notes, preserved below). Correction 2 (pre-verified ground truth given to worker, not re-derived): `docs/fidelity/spp_maker_mcp_surface.json` — exactly the 4 real tools, real `*Request`/`*Result` class names, real repo path, `IDENTICAL` parity status. | Worker validated JSON parses | Independently re-parsed JSON, asserted all 4 names/classes/paths match ground truth programmatically (all passed); integrated into supervising repo; ran full `tests/mcp` suite: **6 passed, 1 failed** — the 1 failure is `test_tool_schemas_snapshot_stable`, exactly the pre-documented `allow_fallback_precompiled` environment/dependency-drift gap already diagnosed in T26_04's row, not a new regression | 4/4 tool names + class names + paths verified correct | None new. Same documented MCP schema-drift gap carried forward from T26_04. |
| T26_07 common_contract & regulator audit | **ACCEPTED** (Claude-only, no grunt — analysis pre-drafted, doc-formatted now) | `docs/fidelity/SPP_MAKER_RESTORATION.md` (new) | N/A | Split classification written with line-cited evidence from both `common_contract.py` and `spp_policy.py`; used directly to scope T26_11 (excludes `spp_policy.py` from delegation) | N/A (documentation task) | Redundant usable/fallback-criteria duplication flagged for later Skill-Loop restoration per Part 48, not resolved here |
| T26_08 QLIP handoff restoration | attempts 1+2 **FAILED (infra)** — retry queued solo | Attempt 1 (32K): 0-byte patch, context-exceeded. Attempt 2 (64K, concurrent w/ T26_09+T26_14_CORRECTION_01): partial untracked files only (`QLIP_Outputs/{CONSTRAINTS,GUIDANCES,SPP}/{...}` skeleton, no `qlip_package.py` changes, no fresh run generated), GRUNT_EXIT=1, log confirms `Context size has been exceeded` again — this time an aggregate-concurrency ceiling, not per-worker (model stayed loaded/healthy per `lms ps`). Neither attempt REJECTED (infra, not content). | | | | Retrying solo (no other heavy ticket concurrently) per the scheduling adjustment above. |
| T26_09 Calibration/publishing/corpus-prep/plotting | attempt 1 FAILED (infra) → retry (solo) **ACCEPTED** | Empty patch — worker found everything already correctly placed/wired from T26_02's verbatim baseline (confirms "relocation is free" pattern held for calibration.py/publish.py/etc. too, same as T26_03's finding for cli.py/server.py) | Worker ran the 11 required tests, claimed all passing | Independently reran all 11 required tests myself (`test_calibrate_outputs_explain_sign`, `test_calibration_stats_and_lambda`, `test_cli_calibrate_no_bandpass`, `test_cli_calibrate_smoke`, `test_cli_calibrate_supercell_method`, `test_publish_kinds`, `test_publish_qlip_outputs`, `test_demo_script_smoke`, `test_gr_phi_roundtrip`, `test_supercell_gr`, `test_supercell_support`): **14 passed** (11 files, some multi-test); confirmed no generated plot/report/corpus artifact was committed | No changes needed — already correct | None. Unblocks `T26_08_CORRECTION_02` (fresh-run generation), which depends on `publish.py` being verified working. |
| T26_10 Schema & configuration docs | attempt 1 **REJECTED (total fabrication)** — Claude rewrite **ACCEPTED** | Attempt 1 (agent `aea8db3a89b6b8618`) added a "Schemas" section listing 12 dataclasses (`BoundaryParams`, `CalibrationParams`, `CifParams`, `CovalentFilterParams`, `FitHistParams`, `FitPhiParams`, `MetaCsvParams`, `NeighborsParams`, `PotCompatParams`, `QlipOutputsPackagesParams`, `RunOrchestratorParams`) — **every single one is fabricated; none exist anywhere in the source.** Independently grepped `^class \|@dataclass` across all of `spp_maker`/`spp_maker_qlip`/`spp_maker_mcp` — zero matches for any claimed name; the real classes in those exact files are completely different (e.g. `calibration.py` really defines `CalibrationStats`/`LambdaRecommendation`, not `CalibrationParams`). Also left 2 stray scratch files (`SPP_MAKER_RESTORATION.md.backup`, `temp_doc.md`) uncommitted in its own worktree. REJECTED in full — nothing from this attempt applied. Given the severity (wholesale invention, not a partial defect) and that source-enumeration is squarely investigation work, Claude did the actual grep-based enumeration directly and wrote the replacement Schemas/Configuration sections from verified ground truth (44 real dataclasses + 12 Pydantic models + 6 MCP env vars + CLI path defaults, every entry cited by file:line). | Worker claimed it "examin[ed] actual source files through grep and AST analysis" — false, or the results were discarded/not used | Full independent `grep` re-verification of every claimed class name (0/12 found) and the real replacement content (all found exactly as cited) | N/A (documentation task) | None remaining — replacement content fully verified. |
| T26_11 llm_csp.spp compat wrapper | **ACCEPTED — zero modules approved for delegation** | None (no code change — this is the intended safe outcome when parity isn't established) | N/A | T26_12's parity evidence proves `spp_maker`/`spp_maker_qlip` (source) ≡ the restored archive package — it does NOT prove anything about the separate, older, already-reduced `llm_csp/spp/*.py` wrapper's own numerical behavior against either. Establishing THAT parity (comparing `llm_csp.spp.fit_hist` output against `spp_maker.fit_hist` output, module by module) was never performed and is a distinct, substantial investigation this ticket's gate requires before any delegation — "Do not start this subticket until Claude has reviewed T26_12's raw parity output and explicitly authorized which, if any, modules may delegate." Having reviewed it, it does not answer that question. | N/A | Per the ticket's own explicit allowance ("may be a subset, or none, of..."), the honest and conservative conclusion is **none** — no `llm_csp/spp/*.py` module is approved for delegation to restored source in this ticket. `spp_policy.py` was already excluded per T26_07. This preserves 100% of the existing, already-passing `llm_csp.spp` test suite unchanged and introduces zero risk. A future ticket could revisit this with a dedicated module-by-module `llm_csp.spp`-vs-`spp_maker` parity investigation if delegation is later desired. |
| T26_12 Parity test harness | attempt 1 **REJECTED (total fabrication)** — correction queued | Attempt 1 (agent `a64bcf69362f182b1`) produced 5 scripts, GRUNT_EXIT=0, "all imported without syntax errors" (import-only check, not execution). Independent review found **every one of the 5 scripts imports entirely fabricated Python APIs**: `spp_maker_qlip.fitting.fit_potential` and `spp_maker_qlip.scoring.score_potential` — neither `fitting.py` nor `scoring.py` exists anywhere in source or archive (confirmed by direct file listing of `spp_maker_qlip/`: only `corpus_quality.py`, `pot_quality.py`, `qlip_package.py`, `required_pair_extraction.py`, `__init__.py`). The "source" and "archive" invocation functions were also identical copy-pasted code — would never actually distinguish source from archive behavior even if the fake import worked. Also duplicated the fixture CIFs at the wrong location (unified repo root `tests/fixtures/cifs/` instead of the existing `packages/spp_maker_qlip/tests/fixtures/cifs/` — same mistake class as T26_08 attempt 3) and left a stray `test_parity_scripts.py` at the repo root. `SPP_PARITY_RESULTS.json` was correctly left as `{}` per the ticket's own design (grunt writes scripts, Claude runs them) — that part was honest. REJECTED in full, nothing applied. Root cause (3rd occurrence of the same failure class this session, after T26_06 and T26_10): asking a worker to "figure out the right internal API from the source" reliably produces plausible-but-fabricated results. Correction ticket `T26_12_CORRECTION_01_real_cli_invocation.md` written mandating subprocess-based CLI invocation only (the proven pattern from `test_run_orchestrator_smoke.py`), with exact verified CLI flag syntax supplied, explicitly forbidding any direct `spp_maker.*` Python import. | Worker claimed "all imported without syntax errors" — true but meaningless (import-only, not execution; the fabricated modules don't exist so even that "success" is suspect for anything beyond top-level `import os/sys/json`) | Read all 5 scripts in full; confirmed 0/5 use any real, existing API; confirmed the fixture-CIF duplication and stray file | N/A (harness-writing task; no real parity evidence produced yet) | **Correction attempt (agent `a06a8f19246758abf`)**: fixed the API-fabrication
problem (all 5 scripts now correctly use subprocess-based CLI invocation,
zero fabricated imports — genuine improvement), but its own dispatcher
caught 2 missing `import os` bugs and correctly refused to call it complete.
Claude's own deeper review found a second, more fundamental problem beyond
those 2 bugs: **none of the 5 scripts referenced the isolated source
checkout at all** (confirmed via `grep` — zero matches for
`spp-source-frozen` across all 5 files) — `parity_fitting.py` only ran
`fit` on the archive side twice (once per CIF) and compared NaCl's output
shape against SiC's, never actually comparing source vs. archive on the
same input. This is the 2nd complete rejection of T26_12's actual purpose
(1st: fabricated APIs; 2nd: correct APIs but no real comparison at all) —
per the two-failed-attempts rule, and given this is the single most
scientifically consequential piece of Ticket 26, Claude wrote all 5 scripts
directly rather than risk a 3rd cycle. **Claude-authored, ACCEPTED, real
results:**
- `parity_fitting.py`: ran `spp-maker fit` on both the isolated frozen
  source checkout and the archive against identical fixture CIFs —
  **required pairs match, manifest matches exactly** (after excluding one
  legitimately environment-specific field, `cif_dir`, which naturally
  differs since it embeds each side's own absolute path), **and the
  resulting `C-Si.POT` file is byte-for-byte identical** between source and
  archive.
- `parity_scoring.py`: fit then scored both CIFs on both sides via
  `spp-maker score --json` — **exact score match** (`0.0`/`0.0` for both
  structures on both sides; found and fixed a field-name assumption bug of
  my own along the way — real output uses `total`, not `score`, discovered
  by directly invoking the CLI and reading its actual JSON Lines output
  rather than guessing).
- `parity_qlip_packaging.py`: ran the full `run --publish_to` pipeline on
  both sides — **identical `Final_QLIP_output` filenames, identical POT
  hashes, identical `QLIP_Outputs` registry category names**
  (`CONSTRAINTS`/`GUIDANCES`/`PACKAGES`/`SPP`/`schema` on both sides).
- `parity_failure.py`: 5 deliberate invalid-argument scenarios (missing
  corpus, missing required arg, invalid fit method, missing/nonexistent
  `--spp_root`) — **identical exit codes and identical exception-class
  extraction on all 5**, run on both sides.
- `parity_regulator.py`: honestly reported **BLOCKED** — no `spp-maker` CLI
  verb exposes regulator union/fallback decisions at all (only
  `fit`/`score`/`calibrate`/`run` exist), and the harness is restricted to
  subprocess-CLI invocation (no direct Python imports, per the correction
  ticket's own anti-fabrication rule) — fabricating a fake entry point here
  would repeat the exact mistake this correction was meant to fix.

Every one of the above was independently reproduced by Claude directly
(not just reviewed) — these are first-hand results, not a worker's claims. |
| T26_13 Path-rewrite ledger & matrix update | **ACCEPTED (Claude-authored)** | `docs/fidelity/SOURCE_TO_ARCHIVE_MATRIX.csv` (114 rows appended, deterministic transform of the already-verified T26_01 manifest — not model enumeration, given the demonstrated fabrication risk on similar tasks this session); `docs/fidelity/SPP_MAKER_RESTORATION.md` path-rewrite table | N/A | Verified the transform script's classification logic against the manifest directly: 105 `RESTORED`, 9 `HISTORICAL_NON_RUNTIME`, 0 `NEEDS_REVIEW`/unclassified | 114/114 source paths accounted for, no gap | None. Given "relocation is free" held almost everywhere (zero code changes needed outside T26_03's packaging additions and the one legitimate `latest.txt` regeneration), the actual rewrite ledger is small — documented as such rather than padded. |
| T26_14 POT asset inventory & dedup audit | attempts 2-3 **REJECTED**; Claude rewrite **ACCEPTED**, real scan **RUNNING** | Attempt 2: 3 real bugs (duplicate-group data loss, wrong underscore-suffix pair convention, broken CWD-relative repo naming) — see full detail preserved from prior review. Correction attempt 1 (concurrent, infra-failed) claimed fixes but left the required duplicate-group test as a stub. Correction retry (solo, agent `acae8654c90a18846`): GRUNT_EXIT=0, all 3 targeted bugs genuinely fixed this time — BUT the worker fully rewrote the script and in doing so **dropped 6 of the 11 required CSV columns** (`source_path`→renamed `filepath`, `size` computation removed entirely, `library_role`/`runtime_required`/`generated_or_source`/`provenance`/`redistribution_status` all gone) and changed the CLI argument order — violating the correction ticket's own "do not change the CSV column schema" / "do not rewrite unrelated parts" constraints. REJECTED. This was the 2nd content-defect attempt on this exact script (1st: T26_14 attempt 2's 3 bugs; 2nd: this rewrite's schema regression) — per the two-failed-attempts rule, took over directly: rewrote `scripts/pot_asset_inventory.py` myself preserving all 3 correct bug fixes plus the full 11-column schema and original CLI usage. Self-tested against a synthetic 2-repo/5-file fixture (2 duplicate groups, hyphenated names, absolute paths) — all 3 bugs verified fixed, full schema present, confirmed strictly read-only. Ran the real scan against `SPP-Maker-QLIP`/`Skill-Loop-CSP`/`QLIP`
(background) — **ACCEPTED**: found 102,847 POT files, 17,933 duplicate
groups (close to Ticket 26's own prior estimate of ~102,397 combined —
sane, not a red flag). `docs/fidelity/SPP_POT_ASSET_MANIFEST.csv` written
(102,848 lines incl. header). Independently spot-checked 2 hashes with a
direct `sha256sum` against the live files — both matched exactly. Confirmed
source repository untouched (`git status`/`HEAD` unchanged) — zero bytes
copied, as required. Zero write/copy/delete calls in the script (confirmed
by code review). | N/A (Claude-owned fix + run) | Full independent code
review of both rejected attempts; synthetic self-test of Claude's rewrite
(all 3 bugs verified fixed); 2/2 spot-checked hashes matched the live scan
| N/A (inventory task) | **Still pending** (Part 35/36-37, Claude's own
determination, deferred until T26_10's config-surface enumeration reveals
the actual configured default regulator root): canonical regulator library
identification; request-specific vs. persistent-library POT distinction. |
| T26_15 Installed-package isolated-env test | **ACCEPTED (Claude-owned, per its own ticket definition)** | Root `pyproject.toml`: `license = "MIT"` → `license = { text = "MIT" }`, `license-files` removed (see resolution below) | N/A | **Resolved the T26_03-documented packaging blocker** now that the DAG reached final acceptance work, per explicit user instruction: the bare-string `license = "MIT"` (PEP 639 SPDX form) is not recognized by this environment's setuptools 70.2.0, which only accepts the older `{file=...}`/`{text=...}` table form; switching to `license = { text = "MIT" }` fixed that, but exposed a second, genuine schema conflict — this setuptools version's schema forbids combining `license-files` with the old table-form `license` (a real version-skew inconsistency in setuptools 70.2.0's own PEP 639 rollout, not something specific to this repo) — resolved by dropping the optional `license-files` field (the actual LICENSE files remain in the repo; this only affected auto-bundling metadata, not licensing itself). Verified `pip install -e . --no-build-isolation` succeeds cleanly with zero errors in an isolated venv (`--system-site-packages`, offline, no other option given the sandbox's lack of network access). **Found and worked around, without touching the base environment, a real environment hazard beyond the one already known from T26_03/T26_04**: this machine carries pre-existing, unrelated global editable installs for `SPP-Maker-QLIP` AND `Skill-Loop-CSP` (both true siblings, both containing their own `spp_maker_qlip` package) that silently shadow the restored archive's namespace packages once system-site-packages are inherited — worse than previously known, since `spp_maker_qlip.qlip_package` (1,369 lines of real business logic) resolved to **Skill-Loop-CSP's** copy, not the archive's, until corrected. Fixed via a venv-local-only `sitecustomize.py` (confirmed absent from the base Python's own site-packages both before and after) that strips known sibling-repo paths from `sys.path` at interpreter start — the base environment was never modified. Verified via direct import: `spp_maker`, `spp_maker_mcp`, and all 4 tested `spp_maker_qlip` submodules (`qlip_package`, `corpus_quality`, `pot_quality`, `required_pair_extraction`) all resolve exclusively to `packages/spp_maker_qlip/...` in the isolated venv — zero sibling-checkout contamination (Ticket 26 Part 46's explicit requirement). `spp-maker --help` and `llm-csp --help` both produced real, correct output; `spp-maker-mcp` (an MCP stdio server, `def main() -> None` — confirmed by reading source it takes no argv at all, no `--help` support by design) started and exited cleanly with no error, which is the correct, unmodified-source behavior for a client-less stdio server run non-interactively, not a defect. Temporary venv deleted after use. | Isolated-venv install + import + entry-point verification, all first-hand | Fixed a real, previously-undetected `spp_maker_qlip.qlip_package` cross-repo contamination risk; documented rather than silently worked around invisibly | None remaining for this ticket. The `license`/`license-files` fix benefits the entire unified archive's installability, not just SPP-Maker-QLIP. |
| T26_16 Full regression & final report | **ACCEPTED — SPP_MAKER_SOFTWARE_RESTORED** | `docs/fidelity/RECOVERY_STATUS.md` updated | N/A | Full battery run independently: restored SPP suite (111 passed/18 failed, all diagnosed), existing archive SPP/QLIP/workflow suite (129 passed/3 skipped/0 failed), Crystal-DB (174 passed/1 skipped/1 failed — pre-existing missing `robocrys`), whole archive (346 passed/6 skipped/2 failed — both pre-existing, unrelated). Confirmed: `spp_maker`/`spp_maker_qlip` namespaces restored; no scientific behavior changed (byte-exact POT parity is the strongest evidence); Crystal status unchanged (`BLOCKED_PROVENANCE`); v0.1.0 tag dereferences to `2dbf5e8852dc62c42d97385bc96ea90166d0fc74`, unchanged; no agent-runtime files touched; no POT-library restoration started (inventory only, zero bytes copied); current branch confirmed `recovery/source-fidelity` throughout, `main` never touched. | Every Ticket 26 acceptance-criterion checkbox individually verified, not inferred from subticket counts | None blocking final acceptance. |

## Dependency DAG (reconstructed after T26_04 acceptance)

```
T26_01 ─┬─> T26_02 ─> T26_03 ─┬─> T26_05 (done)
        │                     ├─> T26_06 ──────────┐
        │                     └─> T26_04 ──┬────────┼─> T26_08 ─┬─> T26_10 ─> T26_12 ─┬─> T26_11 ─> T26_15 ─> T26_16
        │                                  └────────┼─> T26_09 ─┘                     └─> T26_13 (also needs T26_07)
        └─> T26_14 (independent side-branch, no dependency on the restoration chain)
T26_07 (Claude-only, done) ─> T26_08, T26_13
```

T26_06, T26_08, T26_09, T26_14 are mutually file-disjoint (confirmed by
comparing each ticket's "Archive files expected to change" section) and are
scheduled as the first rolling-swarm wave.

## Active swarm agent-ID map (to avoid cross-ticket mixups)

| Agent ID | Ticket |
|---|---|
| `ac80f3e377c93b7ed` | T26_06_CORRECTION_02 — **finished, ACCEPTED, integrated** |
| `a5f279b949d948161` | T26_14_CORRECTION_01 — RUNNING |
| `a6a61f7a1fdc5dccc` | T26_08 retry — RUNNING |
| `ab7e68c5aa9c96e52` | T26_09 attempt 1 — failed (infra), retry queued solo |
| `ae218494e6bac7780` | T26_08 retry attempt 3 — REJECTED (real content defects, not infra — see T26_08 row) |
| `aea8db3a89b6b8618` | T26_10 attempt 1 — REJECTED (total fabrication), Claude took over |
| `a64bcf69362f182b1` | T26_12 attempt 1 — REJECTED (total fabrication) |
| `a06a8f19246758abf` | T26_12_CORRECTION_01 — RUNNING (only active worker; nothing else is
genuinely READY right now since T26_11/T26_13/T26_15/T26_16 all
transitively depend on T26_12) |

T26_08 attempt 3 succeeded at the infra level (GRUNT_EXIT=0) but was
REJECTED on independent review: files created at both the unified repo
root `QLIP_Outputs/` (wrong — must not exist there) and the correct
`packages/spp_maker_qlip/QLIP_Outputs/`; an invented `PACKAGES/` directory
not present in source; and fabricated 6-byte placeholder content in every
`latest.txt` instead of real verbatim bytes (source: `CONSTRAINTS/latest.txt`
is empty, `GUIDANCES/latest.txt`/`SPP/latest.txt` are non-trivial real
pointer strings — none of which were preserved). Root cause: T26_01 never
staged `QLIP_Outputs/` verbatim content, so the worker had nothing real to
copy from. Fixed the same way as T26_04_CORRECTION_01: staged the exact
verbatim bytes (Claude, source investigation) into `.grunt-staging/`, then
split T26_08's remaining work into two precisely-scoped corrections:
`T26_08_CORRECTION_01` (pure verbatim copy of 9 static files, explicitly
forbidding repo-root pollution and the invented `PACKAGES/` dir) and
`T26_08_CORRECTION_02` (fresh-run generation via `spp-maker run
--publish_to`, deferred — investigation revealed `--publish_to` writes
`latest.txt` automatically via `publish.py`'s registry code, which is
T26_09's responsibility to verify; sequencing CORRECTION_02 after T26_09's
acceptance rather than running it against unverified `publish.py`).

**T26_08_CORRECTION_01 ACCEPTED** (agent `a720e05b5a73cd573`): 6/9 files
byte-correct on the worker's own attempt; the dispatcher's own independent
review (unusually thorough) correctly caught 3 `.gitkeep` placeholder files
under `runs/` subdirectories written via a PowerShell `echo` fallback as
6-byte UTF-16LE+CRLF instead of the true 1-byte LF source content —
independently re-verified byte-for-byte myself and confirmed the same 3
mismatches. Since this was the 2nd failed attempt specifically on
QLIP_Outputs static-content restoration (1st: T26_08 attempt 3's fabricated
content), took over this narrow, trivial residual fix directly per the
two-failed-attempts escalation rule (3 empty 1-byte placeholder files,
zero interpretive content) rather than spending a 3rd swarm cycle on it.
All 9 files now verified MATCH against the **live source repo** (not just
staging); confirmed no repo-root `QLIP_Outputs/` and no `PACKAGES/`
directory anywhere. Integrated into the supervising repo.

Launching T26_09 retry solo next (agent `a54a012a0354b8afb`) — **ACCEPTED**,
see T26_09 row.

Ran 2 concurrently (narrower-scoped than the earlier failed batch,
deliberately not 3): `T26_08_CORRECTION_02` (agent `a5b6eaed516b422be`,
fresh-run generation) and `T26_14_CORRECTION_01` retry (agent
`acae8654c90a18846`).

**T26_08_CORRECTION_02 ACCEPTED**: ran the exact proven CLI invocation
(`spp-maker run ... --publish_to QLIP_Outputs`) — confirmed genuinely real,
unmodified-software output (not fabricated): a real timestamped run dir,
real `manifest.json`, a real `C-Si.POT`. Also corrected an earlier
misjudgment of my own: `QLIP_Outputs/PACKAGES/` is **not** invented —
`publish.py`'s own `kind_to_dir()` maps `"package" -> "PACKAGES"`,
confirmed by reading the source directly; T26_08 attempt 3 was wrong to
fabricate its content by hand, but the *location* was always legitimate.
Found and fixed a real infrastructure bug while integrating: `.gitignore`'s
blanket `runs/` pattern (for unrelated generated-output dirs) was silently
swallowing `QLIP_Outputs/*/runs/` too — this is why CORRECTION_01's
`.gitkeep` files under `runs/` never appeared in that patch, and why this
patch was missing the actual generated run content. Added a scoped
negation (`!packages/spp_maker_qlip/QLIP_Outputs/*/runs/` + `/**`) so this
content will actually be trackable at T26_16's final commit — verified via
`git check-ignore` before and after. Manually copied the worker's real
generated output into the supervising repo (the patch itself under-
captured it due to the gitignore bug) and reran the 20-test set directly
against the supervising repo: **17 failed, 14 passed** — identical to the
worker's own worktree result, confirming correct integration. Of the 20
originally-failing tests: 3 now pass (the ones needing only *some* real POT
file); 17 remain failing because they test cross-run *selection logic*
requiring several distinct pre-published material systems (ABO3, CoAs2,
ZnS, LiCoO2 — visible in the test names) that only ever existed as the
original author's local generated history, never committed to git — the
same structural limitation identified in T26_04's original review, not a
defect in this restoration. Ticket's own acceptance bar ("as many as
genuinely resolvable") is met. **T26_08 is now fully resolved.**

Model infra note: `grunt-qwen-coder` (qwen3-coder-30b) confirmed actually
loaded at `CONTEXT=65536` via `lms ps` (not just config) before launching
this wave. Prior "Context size has been exceeded" failures on T26_06
(duplicate attempt), T26_08 (attempt 1), and T26_14 (attempt 1) were on the
stale 32768-context instance.

**New evidence after the 64K wave (T26_08 retry, T26_09, T26_14_CORRECTION_01
all launched concurrently):** all three failed with the identical
`Context size has been exceeded` server error mid-run. `lms ps` immediately
after showed the model still loaded and IDLE at `CONTEXT=65536` — it did not
crash or unload, so this is a per-request/aggregate capacity ceiling, not a
dead model. T26_06_CORRECTION_02 (a small, quick ticket) succeeded cleanly
while briefly overlapping with 2 heavy tickets; the two genuinely *heavy*
tickets (T26_08, T26_09 — large file reads, many tool-call rounds) failed
specifically when run concurrently *with each other*. Conclusion: this is an
aggregate/concurrent KV-cache capacity limit across simultaneously heavy
conversations, not a per-worker context deficiency — raising context further
would not fix this and could worsen it (more memory reserved per slot, less
room for real concurrency). Per instruction, none of these three failures are
classified REJECTED and none count toward the two-failed-attempt escalation
rule. **Scheduling adjustment (Claude's own infra decision, not a ticket
content change):** heavy tickets (T26_08, T26_09) will be retried one at a
time rather than concurrently; only light/quick tickets will be paired
alongside a heavy one going forward.

## Notes

- Scientific revision confirmed resolvable in source repo:
  `3a2d557811973265f3373ec881cc8057a89789d2`.
- Licensing revision confirmed as source repo's current `HEAD`:
  `82114cd05f0cb40149d13c20adeafe4c437a03ae`.
- Source repository untouched throughout (read-only `git show`/`ls-tree`
  only).
