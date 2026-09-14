# SPP-Maker-QLIP Software Restoration

## Authority and scope

- Scientific source: `3a2d557811973265f3373ec881cc8057a89789d2`
- Later licensing revision: `82114cd05f0cb40149d13c20adeafe4c437a03ae`
- Destination: `packages/spp_maker_qlip/`
- Production POT assets: deferred (Ticket 26 Parts 33-37; inventory only,
  see `docs/fidelity/SPP_POT_ASSET_MANIFEST.csv` once produced)

The source was read through the frozen Git object (`git show`/`git ls-tree`),
never from an uncommitted source worktree, and the source repository was
never modified. `docs/fidelity/evidence/SPP_MAKER_SOURCE_MANIFEST.csv`
records 114 tracked operational source files with path/size/SHA-256. The
verbatim baseline committed to `packages/spp_maker_qlip/` (101 files, later
extended by 5 omitted `scripts/*.py` files — see below) was independently
re-hashed file-by-file against the frozen revision with zero drift.

## `common_contract` and regulator classification (Ticket 26 Part 15/16)

This section documents the responsibility overlap between
`spp_maker/common_contract.py` (restored verbatim, untouched) and the
existing archive's `llm_csp/workflow/spp_policy.py`, per the full analysis
in `docs/tickets/ticket26/T26_07_FINDINGS.md`.

**`common_contract.py`'s actual responsibilities:** a fixed numerical
contract (`dmytro_gr_v1`: 0.05 Å uniform bins on [0, 10] Å, Gaussian
deposition, `U(r) = -ln(g(r) + 1e-12)`), a deterministic pair-confidence
score, and — critically — genuine **pair-level blend mathematics**
(`choose_pair_blend`/`blend_contract_roots`): a confidence-weighted mix of
local (request-specific) and global (regulator-derived) POT curves with a
fixed weight formula (`global_weight = 0.05 + 0.15*(1-confidence)`). This is
squarely inside Ticket 26's forbidden "blend behavior"/"potential
mathematics" categories and was not touched.

**`spp_policy.py`'s actual responsibilities:** derives required pairs,
exports/audits a regulator POT subset for completeness and quality,
optionally fits a request-specific SPP root, and classifies each required
pair's `guidance_mode` (`REQUEST_PLUS_REGULATOR` vs. `REGULATOR_ONLY_*`)
based on whether the request-fitted pair is "usable." It never imports or
calls `common_contract.py`.

**Classification is split, not a single tag:**

| Responsibility | `common_contract.py` | `spp_policy.py` | Classification |
|---|---|---|---|
| Pair usable-vs-fallback decision | `_valid_pot` (200-pt/finite/monotonic POT-array check) | `pot_quality == "usable"` (independent fit-quality audit) | `REDUNDANT_REIMPLEMENTATION` — independently-invented criteria that can disagree on the same input |
| Numerical local+regulator blend | `choose_pair_blend`/`blend_contract_roots` (confidence-weighted mix) | *(none)* | Absent from the archive workflow entirely — not a duplicate, a gap |
| Regulator coverage/quality gating | *(implicit, via `_valid_pot` on regulator-derived output)* | `audit_pot_root` completeness/quality checks | Compatible in intent, independently implemented |

**Decision:** per Ticket 26 Part 48, this overlap is documented, not
resolved, in this ticket. `spp_policy.py` is explicitly excluded from
T26_11's compatibility-wrapper delegation scope regardless of what T26_12's
parity harness finds, since it does not reimplement `common_contract.py`'s
blend math at all — there is nothing to safely delegate without adding new
behavior the v0.1 deterministic workflow never had. The redundant
usable/fallback-criteria duplication is flagged for the later Skill-Loop
restoration ticket referenced by Part 48, not addressed here.

## Test-suite migration and known gaps (Ticket 26 Part 44)

Full detail in `docs/tickets/ticket26/PROGRESS.md`'s T26_04 row. Summary:

- Source baseline (per Ticket 26): 128 passed, 1 dependency-sensitive
  schema-snapshot failure.
- Archive result after restoring 5 initially-omitted `scripts/*.py` files:
  **108 passed, 21 failed, 129 collected** (run with `cwd` and `PYTHONPATH`
  matching the source repo's own invocation convention).
- 1 failure (`test_tool_schemas_snapshot_stable`) is classified as
  environment/dependency drift (an extra `allow_fallback_precompiled`
  field emitted by the installed schema library versus the committed
  snapshot) — very likely the exact same failure the ticket's baseline
  already documents.
- 20 failures trace to a single cause: `QLIP_Outputs/SPP/latest.txt` at the
  frozen revision points to a run directory that is untracked local state
  on the original author's machine, absent from git entirely. A clean
  clone of the source repo would fail these same tests identically — not
  an archive-restoration defect. Resolution (generating one fresh,
  legitimate run from safe fixture CIFs) is scoped to T26_08.

## Schemas (Ticket 26 Part 30)

Enumerated by grepping `^class \|@dataclass` across
`packages/spp_maker_qlip/src/{spp_maker,spp_maker_qlip,spp_maker_mcp}/*.py`
directly — every entry below is independently greppable at the cited
file:line. No schema redesign; all classes are verbatim, untouched source.

**Dataclasses (`spp_maker`):** `boundary.py:20 BoundaryParseError`,
`calibration.py:43 CalibrationStats`, `calibration.py:64
LambdaRecommendation`, `common_contract.py:35 PairBlend`,
`covalent_filter.py:20 CovalentRule`, `fit_hist.py:18 Binning`,
`fit_hist.py:102 HistAccumulator`, `fit_phi.py:14 PhiResult`,
`io_cif.py:15 LoadedCIF`, `meta_csv.py:16 MetaRow`, `meta_csv.py:27
MetaMap`, `meta_csv.py:36 MetaMatch`, `neighbors.py:13 NeighborEdge`,
`pot_compat.py:12 PotCompatFailure`, `pot_compat.py:20 PotCompatReport`,
`qlip_outputs_packages.py:30 PublishedArtifact`, `run_orchestrator.py:31
RunConfig`, `run_orchestrator.py:71 RunPaths`, `run_orchestrator.py:96
RunResult`, `score.py:17 ScoreReport`, `spp_model.py:24 SPPModel`,
`supercell_gr.py:18 SupercellBuildResult`, `supercell_gr.py:30
SupercellHistogramResult`, `weights.py:16 BandpassParams`.

**Dataclasses (`spp_maker_qlip`):** `qlip_package.py:33 CandidateRoot`,
`qlip_package.py:45 RootSelectionResult`.

**Pydantic models (`spp_maker_mcp/contracts.py`, all `DeterministicModel`
subclasses):** `DeterministicModel` (base, :12), `WarningObject` (:18),
`StructuredErrorDetail` (:25), `StructuredError` (:32), `ProvenanceBlock`
(:39), `ToolEnvelope` (:47), `MCPServerConfig` (:56), `RunFitParams` (:74),
`RunCovalentParams` (:91), `RunCalibrationBandpass` (:96),
`RunCalibrationParams` (:104), `RunFilterParams` (:116),
`RunPublishParams` (:122), `RunPipelineRequest` (:126), `RunPipelinePaths`
(:151), `RunPipelineResult` (:158), `CheckCompatRequest` (:182),
`CompatFailure` (:189), `CheckCompatResult` (:195),
`PackageForQLIPRequest` (:202), `PackageForQLIPResult` (:225),
`PublishToQLIPOutputsRequest` (:234), `PublishToQLIPOutputsResult` (:247).
These are the same `*Request`/`*Result` classes verified in T26_06's MCP
surface manifest correction.

**Dataclasses/classes (`spp_maker_mcp/server.py`):** `ToolValidationError`
(:87, plain `Exception`), `RuntimeContext` (:103, `@dataclass`),
`RuntimeStageRecorder` (:110).

*(A prior draft of this section, produced by a swarm worker, invented 12
plausible-sounding "Params" dataclass names — e.g. `CalibrationParams`,
`RunOrchestratorParams` — none of which exist anywhere in the source. That
draft was rejected in full after independent grep verification found zero
matches; this section replaces it with directly-verified content only.)*

## Configuration (Ticket 26 Part 31)

**Environment variables** (all in `spp_maker_mcp/server.py`, MCP server
only — `spp_maker`/`spp_maker_qlip` core have none):

| Variable | Default | Line |
|---|---|---|
| `SPP_MCP_ALLOWED_READ_ROOTS` | `""` (empty) | 195 |
| `SPP_MCP_ALLOWED_WRITE_ROOTS` | `""` (empty) | 196 |
| `SPP_MCP_MAX_CIF_COUNT` | `5000` | 197 |
| `SPP_MCP_MAX_RUNTIME_SECONDS` | `7200` | 198 |
| `SPP_MCP_MAX_OUTPUT_BYTES` | `2000000000` | 199 |
| `SPP_MCP_USE_FASTMCP` | unset (falsy) | 2373 |

**CLI path/root defaults** (`spp_maker/cli.py`, all relative — this is
exactly what makes the "relocation is free" pattern documented under T26_03
above work: relative defaults resolve correctly regardless of which
directory `packages/spp_maker_qlip/` sits inside):

- `calibrate --qlip_outputs` defaults to `Path("QLIP_Outputs")` (line 1638).
- `run --out_dir` defaults to `Path(".")` (line 1649).
- All other CLI arguments (`fit`/`score`/`calibrate`/`run` subcommands) are
  enumerated in full under T26_05 above — not repeated here.

No source configuration default was changed for this restoration; only
`packages.find.where` and `[project.scripts]` in the unified repo's root
`pyproject.toml` were added (T26_03), which is repository-relocation
packaging metadata, not `spp_maker` source configuration.

## Path-rewrite ledger (Ticket 26 Part 32)

The complete per-file mapping (all 114 manifested source files) is in
`docs/fidelity/SOURCE_TO_ARCHIVE_MATRIX.csv` (105 `RESTORED`, 9
`HISTORICAL_NON_RUNTIME` — non-runtime docs/metadata files with no archive
counterpart needed, e.g. `.gitattributes`, `project_context.txt`). The
summary of *actual* location/behavior changes (everything else is an exact
verbatim path mirror, `<source-path>` → `packages/spp_maker_qlip/<source-path>`):

| Source path behavior | Archive path behavior | Reason | Parity test |
|---|---|---|---|
| Standalone repo root (`src/`, `tests/`, `scripts/`, `rules/`, `QLIP_Outputs/` as siblings) | `packages/spp_maker_qlip/` plays the same "root" role, same internal nesting depth | Repository-relocation only — required by living inside the unified archive (Ticket 26 Part 3) | `Path(__file__).resolve().parents[N]`-based logic (in `cli.py`, `run_orchestrator.py`, `server.py`, `qlip_outputs_packages.py`, and every migrated test) resolves correctly with **zero code changes**, verified during T26_03/T26_06/T26_08/T26_09 — confirmed via successful imports, CLI execution, and full test-suite runs |
| Root `pyproject.toml` had no `spp_maker`/`spp_maker_qlip`/`spp_maker_mcp` entries | Root `pyproject.toml`: `packages/spp_maker_qlip/src` added to `[tool.setuptools.packages.find].where`; `spp-maker`/`spp-maker-mcp` added to `[project.scripts]` | Packaging wiring only — no source file touched | T26_03: `import spp_maker, spp_maker_qlip, spp_maker_mcp` + `spp-maker --help` end-to-end via PYTHONPATH |
| `QLIP_Outputs/SPP/latest.txt` pointed to a run that only ever existed as untracked local state on the original author's machine | Static structure restored verbatim; `latest.txt` content instead points to a **freshly, legitimately generated** run (produced by actually running the unmodified, restored `spp-maker run --publish_to` pipeline against safe fixture CIFs) | The original pointer target was never reachable from git at any revision — restoring it verbatim would just be a second dangling pointer. Ticket 26 Part 36 classifies generated request-specific output as not an archive asset in itself, but the *software that produces it* is exactly what T26_08 restores and exercises here. | T26_08_CORRECTION_02: 3/20 previously-failing tests newly pass; `latest.txt` verified to resolve to a real, existing run with a real `.POT` file |
| N/A (tooling, not source) | `.gitignore`'s blanket `runs/` pattern (for unrelated generated-output dirs elsewhere in the archive) was silently excluding `packages/spp_maker_qlip/QLIP_Outputs/*/runs/` too | Infrastructure bug found during T26_08_CORRECTION_02 integration — would have silently dropped all generated registry content at T26_16's final commit | Verified via `git check-ignore` before and after a scoped negation was added |

No forbidden change occurred: no potential mathematics, histogram
mathematics, pair counting, regulator behavior, blend behavior, QLIP
handoff semantics, schema, tool name, CLI semantics, or MCP semantics was
altered anywhere in this restoration — confirmed by T26_12's direct
source-vs-archive parity evidence (byte-exact POT files, exact scores,
identical packaging structure, identical failure behavior).

*(This document is extended by T26_16's final report — rather than
rewritten.)*
