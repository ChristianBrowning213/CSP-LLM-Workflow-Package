# Release Readiness Audit

## Decision

Audit target: `c3aeda3702768e455b0264a7777652d7c2d63ebb`

- Commit-only status: `COMMIT_MISSING_REQUIRED_TRACKED_FILES`
- Release status: `BLOCKED_SOURCE_FIDELITY`
- Recommended next action: **fix tracked recovery omissions**

The target commit builds, preserves the recovered source, and passes substantial
source-level verification. It is not independently reproducible as an installed
release artifact. The wheel has a colliding `spp_maker_qlip` package layout that
omits required SPP modules, omits the Skill-Loop skill-card schema, and cannot run
the installed SPP MCP server or the installed SPP-to-QLIP pipeline. The sdist also
omits the tracked Crystal bootstrap specification and implementation. In addition,
the active Crystal and Skill-Loop defaults still assume historical or sibling data
paths instead of the supported bootstrap result.

This audit did not modify runtime code, source repositories, the recovery commit,
or release history. It did not push, merge, tag, or release anything.

## 1. Commit-only working-tree audit

The audit began on branch `recovery/source-fidelity` at the exact target commit.
The pre-existing working-tree changes were:

```text
 M .gitignore
?? .claude/
?? .grunt-smoke-test.txt
?? CLAUDE.md
?? docs/tickets/GRUNT_SMOKE_TEST.md
?? docs/tickets/swarm/
?? scripts/grunt-core.sh
?? scripts/grunt.sh
?? scripts/grunt.sh.pre-swarm
?? scripts/local-worker-runtime.sh
?? scripts/swarm.sh
```

There were no staged changes. The tracked `.gitignore` delta adds only
`.grunt-staging`; it is classified `UNRELATED_INFRASTRUCTURE_CHANGE`. The remaining
items are untracked local grunt/swarm infrastructure or related local support
files. None is imported, packaged, exercised, or required by the recovery runtime,
tests, packaging, or Crystal data bootstrap. They were excluded from the detached
clean-room checkout and left unchanged.

## 2. Clean-room method and environment

A detached worktree was created directly from the target commit, without copying
files from the working tree. All builds and primary audit runs used that worktree.
A fresh virtual environment was created inside it and the built wheel was installed
non-editably. Ordinary Python dependencies were obtained through normal package
installation; this is not an archive-fidelity defect.

Environment:

| Component | Version |
|---|---:|
| Python | 3.12.10 |
| pip | 25.0.1 |
| setuptools | 84.0.0 |
| wheel | 0.48.0 |

`pip check` passed. No sibling repository was added to `PYTHONPATH`. Direct imports
were repeated outside the repository working directory with the virtual
environment first on `PATH` and `PYTHONPATH` cleared.

## 3. Build artifacts and package contents

Both distributions built successfully from the detached commit:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `llm_csp-0.2.0.dev0+fidelity-py3-none-any.whl` | 1,264,317 | `ff788ec360780762cdcc8a244e16614e0129a9955866251b63df17f2e7e4a35b` |
| `llm_csp-0.2.0.dev0+fidelity.tar.gz` | 1,036,013 | `6549665ecac52779ac0d5892a0b5b760d3fc5d63f4728e54715a6e8e098e96b3` |

The wheel contains 526 entries. It includes:

- all nine intended built-in QLIP POT resources, with bytes matching the O-O
  source manifests;
- QLIP policies and packaged schema resources;
- SCA source/package content;
- all four Skill-Loop prompts;
- Crystal-DB software and MCP code;
- SPP-Maker software and the recovered MCP adapter.

The inspected wheel contains none of the prohibited/generated holdings:
`.git`, `QLIP_Outputs`, OMatG data, `phase6_mp_10k.db`, the canonical regulator
library, or repository `artifacts` directories.

Package-content failures:

1. Root package discovery combines two distributions that both own the
   `spp_maker_qlip` namespace: `packages/spp_maker_qlip/src` and
   `packages/skill_loop_csp/src`. Only the Skill-Loop compatibility module
   `spp_maker_qlip/qlip_package.py` reaches the wheel. Required source modules
   `__init__.py`, `corpus_quality.py`, `pot_quality.py`, and
   `required_pair_extraction.py` are omitted. Consequently importing
   `spp_maker_mcp.server` from the installed artifact fails with
   `ModuleNotFoundError: No module named 'spp_maker_qlip.required_pair_extraction'`.
2. The wheel omits
   `sok_llm_orchestrator/skills/schema.skillcard.v1.json`. Installed
   `sokllm skills validate` exits 1 with `FileNotFoundError` for that resource.
3. The sdist omits
   `data/crystal_db/requests/default_mp_requests.txt`,
   `scripts/crystal_db/grab_data.py`, and
   `packages/spp_maker_qlip/src/spp_maker_qlip/required_pair_extraction.py`.
   Therefore it cannot reproduce either the documented Crystal bootstrap or the
   installed SPP package.
4. The root distribution does not publish the source Crystal console-script names
   `crystal-db` and `crystal-db-mcp`. A source-equivalent module CLI exists, but
   entry-point parity is incomplete.
5. The wheel includes 32 top-level `tests/` files from SCA. This is a packaging
   hygiene issue, but it is not independently a runtime blocker.

## 4. Namespace and sibling-repository verification

With the virtual environment isolated from source overlays, direct imports resolved
as follows (the prefix is the audit virtual environment's
`Lib/site-packages` directory):

| Namespace | Resolution |
|---|---|
| `crystal_db` | `site-packages/crystal_db/__init__.py` |
| `spp_maker` | `site-packages/spp_maker/__init__.py` |
| `spp_maker_qlip` | namespace at `site-packages/spp_maker_qlip` (`__file__` is `None`) |
| `qlip` | `site-packages/qlip/__init__.py` |
| `sca` | `site-packages/sca/__init__.py` |
| `sok_llm_orchestrator` | `site-packages/sok_llm_orchestrator/__init__.py` |
| `spp_maker_mcp` | `site-packages/spp_maker_mcp/__init__.py` |
| `crystaldb_mcp` | `site-packages/crystaldb_mcp/__init__.py` |
| `qlip_mcp` | `site-packages/qlip_mcp/__init__.py` |
| `spp_mcp` | `site-packages/spp_mcp/__init__.py` |

No direct import resolved to `Crystal-DB`, `SPP-Maker-QLIP`, `qlip`,
`Structured_Crystal_Analyser`, or `Skill-Loop-CSP` sibling repositories. The
namespace-only result for `spp_maker_qlip` is not contamination; it is evidence of
the wheel omission described above.

The `sokllm doctor` subprocess-origin report was also inspected, but its module
origin probe inherited paths from the development environment despite the outer
shell cleanup and was therefore not accepted as clean-room evidence. The direct
isolated imports above, `sys.path` inspection, artifact inventory, and installed
test behavior are the controlling evidence.

## 5. CLI verification

The following clean installed commands returned exit code 0 for `--help` or an
equivalent non-mutating module invocation:

```text
llm-csp --help
spp-maker --help
sca --help
sokllm --help
python -m crystal_db --help
python -m qlip --help
python -m qlip.scaffolds --help
```

The installed distribution exposes `llm-csp`, `spp-maker`, `spp-maker-mcp`, `sca`,
and `sokllm`. It does not expose `crystal-db` or `crystal-db-mcp`, although those
names exist in the recovered Crystal source project. The stdio
`spp-maker-mcp` command is not meaningfully exercised with `--help`; importing its
installed server fails because `required_pair_extraction.py` is absent. CLI parity
therefore fails.

## 6. MCP surface verification

The clean installed or clean source surfaces were enumerated without starting
persistent servers:

| Surface | Tools | Result |
|---|---|---|
| Crystal-DB | `crystal.text_search`, `crystal.agent`, `crystal.novelty_check`, `crystal.csp_pack`, `crystal.status`, `crystal.bench_retrieval` | exact names and schema parity with `crystal_db_mcp_surface.json` |
| QLIP | `qlip.list_constraints`, `qlip.list_guidance`, `qlip.shapes`, `qlip.validate_request`, `qlip.solve`, `qlip.debug_boundary_parse` | exact names and JSON-schema parity with `qlip_mcp_surface.json` |
| Skill-Loop | `crystal.csp_pack`, `crystal.novelty_check`, `qlip.solve`, `qlip.validate_request`, `spp.package_for_qlip`, `spp.run_pipeline` | exact registry names |
| SPP-Maker source | `spp.check_compat`, `spp.package_for_qlip`, `spp.publish_to_qlip_outputs`, `spp.run_pipeline` | exact source names; one generated schema snapshot differs by the recovered `allow_fallback_precompiled` property |
| SPP-Maker installed | unavailable | server import fails because a required packaged module is missing |

There are no invented or missing source tool names. Release-artifact MCP parity
still fails because the installed SPP surface is unusable. The SPP schema snapshot
difference is retained as an evidence-backed dependency/source snapshot issue.

## 7. Source-derived test results

Each recovered suite was run separately from the detached commit. Where a suite
requires its own source root, only roots inside the unified checkout were used.

| Suite | Result | Classification |
|---|---:|---|
| Crystal-DB | 175 passed, 1 skipped | skip is the documented historical-database boundary |
| SPP-Maker-QLIP | 111 passed, 18 failed | 17 require excluded pre-published QLIP outputs/material systems; 1 is the recovered MCP schema-snapshot difference |
| QLIP | collection failure in the multi-scaffold test; remaining tests: 242 passed, 13 failed | missing excluded scaffold/corpus or historical artifacts and sibling-discovery assumptions |
| SCA | 185 passed, 6 failed | excluded benchmark CSV/manifests |
| Skill-Loop-CSP | 1,234 passed, 98 failed, 22 skipped | excluded external datasets/models/historical outputs and sibling-layout assertions |
| unified compatibility tests, source tree | 178 passed, 5 skipped | matches the recovery reference |
| unified compatibility tests, installed wheel | 177 passed, 1 failed, 5 skipped | failure detects namespace-only `spp_maker_qlip`, caused by wheel collision |

These failures are not collapsed into one total because they describe different
boundaries. The missing historical fixtures explain much of the source-suite
delta, but they do not explain or excuse the installed-artifact package failures.

The QLIP clean result intentionally differs from a previous recovery run of
254 passed and 6 failed: that earlier run supplied an external scaffold corpus.
The clean-room audit did not.

## 8. Root regression

The root suite from the clean source checkout produced the exact reference result:

```text
178 passed, 5 skipped
```

The same suite against only the installed wheel produced:

```text
177 passed, 1 failed, 5 skipped
```

The failure is `test_original_public_namespaces_import`; the installed
`spp_maker_qlip` package is a namespace with no `__file__`, which is the artifact
collision described above.

## 9. SPP to QLIP to Gurobi smoke

The recovered source-overlay smoke using the safe CIF fixture passed its real
pipeline test:

```text
test_run_pipeline_creates_spp_outputs_and_unified_qlip_package: 1 passed
```

It generates real POT content and a QLIP package through the restored source.
However, the required clean installed-wheel flow cannot begin: importing the SPP
MCP server fails due to the omitted `spp_maker_qlip.required_pair_extraction`
module. Consequently the installed sequence cannot demonstrate package generation,
request acceptance, Gurobi execution, or a candidate/result. The release-level
SPP -> QLIP -> Gurobi smoke is **FAIL**, even though the source components retain
their proven behavior.

## 10. SCA validation smoke

The SCA adapter resolved from the clean installed unified package. Its focused
candidate/fixture validation smoke produced:

```text
4 passed
```

Result: **PASS**.

## 11. Crystal bootstrap and request-file architecture

The tracked request specification parses and validates in the source checkout:

| Field | Value |
|---|---|
| Request file | `data/crystal_db/requests/default_mp_requests.txt` |
| Format | INI, parsed by `ConfigParser` |
| SHA-256 | `7aff0ac0dda18d6f8ef0bdce0b011210f0551b2b1c6aa95f863f6fbf46a94f2a` |
| Bootstrap command | `python scripts/crystal_db/grab_data.py --requests data/crystal_db/requests/default_mp_requests.txt --runtime-root data/crystal_db/runtime` |
| Default database output | `data/crystal_db/runtime/phase6_mp_stable_10k/phase6_mp_stable_10k.db` |

The request describes the 10,000 stable-material-ID dataset and operational chunk
and rate settings outside Python code. A future experiment can copy/edit the
request and build a separate database without a code change. The dry path passed.
With the key explicitly removed, the live path exited 2 with:

```text
ERROR: set MP_API_KEY for a live Materials Project build
```

and created no runtime output. A key was available in the audit environment, but
no live record was fetched because the bounded live check is optional and the
dry/missing-key paths supplied the required evidence. The 10k dataset was not
downloaded.

This architecture is sound in the source checkout, but it is not distributable
from the current sdist because both the request file and bootstrap script are
omitted.

## 12. Canonical regulator POT conclusion

### A. Are the excluded canonical regulator POTs required for the default restored workflow?

`YES`

They are required by the canonical/default Skill-Loop production workflow. The
small root offline demonstration can use the nine bundled fixture POTs, but that
does not replace the canonical production regulator.

### B. Which workflows require them?

- `WorkflowConfig.regulator_id`, whose default is `icsd_broad_regulator_v1`;
- `ProductionWorkflowStages._regulator_root`;
- the default configuration in
  `packages/skill_loop_csp/config/workflow/default.json`;
- canonical `run_csp_workflow`, experiment-table, and experiment-CSV runs that use
  request-plus-regulator or regulator-only guidance;
- common-contract fallback for required pairs not supplied by request-specific
  evidence; and
- the recovered paper benchmark paths that expect the historical broad regulator.

The root is selected explicitly in configuration or via
`SKILL_LOOP_REGULATOR_SPP_ROOT`.

### C. What happens when they are absent?

The source-faithful behavior is explicit failure, not scientific substitution.
Depending on entry point, this is:

```text
FileNotFoundError: regulator SPP root unavailable: <resolved path>
```

or a `WorkflowStageError` with code `GUIDANCE_PAIR_UNSUPPORTED` when required
pairs have no usable regulator data. The common-contract helper raises
`RegulatorSPPConfigurationError` directing the operator to set
`SKILL_LOOP_REGULATOR_SPP_ROOT`.

### D. Can they be regenerated?

Yes, but only from provenance-cleared source structures or regulator RDF inputs.
The restored `spp-maker run` / `spp.run_pipeline` path can generate and package
pair POTs from such structures. A common-contract pair can also be rebuilt from an
external regulator RDF with
`spp_maker.common_contract.rebuild_global_pair_from_rdf`.

Reconstructing the full canonical 3,388-pair bytes requires the original
ICSD-derived structures/RDF corpus and its permission/provenance record. The known
external source tree is untracked and no redistribution grant is present in the
recovery commit. No substitute scientific assets were generated.

Final classification: `REQUIRED_PROVENANCE_BLOCKED_ASSET`.

## 13. External dependency truth table

| Dependency | Classification | Release meaning |
|---|---|---|
| Gurobi | `REQUIRED_DEFAULT` | required by the default QLIP solve path |
| LM Studio | `REQUIRED_FOR_DATA_BOOTSTRAP` | BGE-M3 embeddings for Crystal bootstrap; also used by default semantic retrieval |
| Ollama | `OPTIONAL_FEATURE` | optional model/provider path |
| Materials Project API | `REQUIRED_FOR_DATA_BOOTSTRAP` | required to construct the supported Crystal dataset |
| canonical regulator POTs | `PROVENANCE_BLOCKED` | also required by the canonical/default production workflow; cannot be redistributed from current evidence |
| optional SCA MLIP models | `OPTIONAL_FEATURE` | only needed for the corresponding MLIP validation paths |
| CASTEP | `OPTIONAL_FEATURE` | optional external simulation integration |
| Slurm | `OPTIONAL_FEATURE` | optional cluster execution integration |
| VESTA | `OPTIONAL_FEATURE` | optional visualization integration |

The regulator conclusion means the release cannot truthfully state that Crystal
bootstrap is its only setup-time scientific-data dependency.

## 14. Historical Crystal database dependency

Result: **FAIL**.

The source bootstrap writes:

```text
data/crystal_db/runtime/phase6_mp_stable_10k/phase6_mp_stable_10k.db
```

but the active Crystal MCP default in
`packages/crystal_db/src/mcp_server/server.py` resolves to the historical archive
path `data/crystal_db/phase6_mp_10k.db`. An operator can override it with
`CRYSTALDB_PATH` or `CRYSTAL_DB_PATH`, but the commit contains no tracked default
configuration that automatically selects the bootstrap-built database. Normal
installed runtime is therefore not wired to the documented supported build path.

Historical/audit references to `phase6_mp_10k.db` are acceptable; this active
runtime default is not.

## 15. Hidden developer and sibling paths

Result: **FAIL**.

The scan found many absolute developer paths in copied historical scripts. Those
files are non-production evidence and are not alone a blocker. It also found active
assumptions:

- `sok_llm_orchestrator.retrieval.specialist_corpora.DEFAULT_REGISTRY` resolves
  through a repository-relative `data/corpora/registry.json` location not included
  in the wheel;
- the active Skill-Loop corpus registry uses `path_base: github_parent`, including
  a default general corpus at
  `Crystal-DB/data/phase6_mp_10k.db` and other sibling-repository paths;
- active Crystal MCP configuration defaults to the historical database path; and
- `packages/skill_loop_csp/src/.../workflow/paper_final_v1.py` retains a frozen
  `../Crystal-DB/artifacts...` sibling assumption.

The first two make a normal installed Skill-Loop workflow depend on resources or
layout that the distribution does not supply. These are genuine release defects,
not merely allowed historical documentation.

## 16. Prompt and schema integrity

The source-tree manifest comparison covered 48 Skill-Loop prompt/schema rows:
zero were missing and zero differed. The four prompt hashes exactly match
`SKILL_LOOP_PROMPT_HASHES.txt`:

| Prompt | SHA-256 prefix |
|---|---|
| evaluator | `779e...` |
| orchestrator | `0fa...` |
| planner | `565...` |
| run manager | `a420...` |

Source migration integrity therefore passes. Distribution integrity fails because
the wheel omits `schema.skillcard.v1.json`, as recorded in section 3.

## 17. Scientific invariant checks

The focused QLIP periodic and end-to-end source tests produced:

```text
37 passed
```

They verify:

- distinct-site multiplicity is `1.0`;
- nonzero self-translation multiplicity is `0.5`;
- zero self-translation is excluded;
- the 11 angstrom cutoff is inclusive; and
- the canonical SrTiO3 fixture objective is
  `4.883033620558714`.

Result: **PASS** for the recovered source implementation.

## 18. Original source-repository integrity

The five source repositories were inspected and not modified:

| Repository | HEAD | Status |
|---|---|---|
| Crystal-DB | `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31` | clean |
| SPP-Maker-QLIP | `82114cd05f0cb40149d13c20adeafe4c437a03ae` | clean; status emitted only permission warnings for local pytest-temp paths |
| qlip | `a619ab379c62b5edefd6bb00076267e149f283ce` | clean |
| Structured_Crystal_Analyser | `3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af` | clean |
| Skill-Loop-CSP | `36f6280e47387643853ac0cfc510e20c5d595834` | pre-existing untracked `benchmarks/external/OMatG/` only |

## 19. Historical release integrity

Both required lineage checks are unchanged:

```text
main:          2dbf5e8852dc62c42d97385bc96ea90166d0fc74
peeled v0.1.0: 2dbf5e8852dc62c42d97385bc96ea90166d0fc74
```

The peeled release commit, not the annotated tag-object SHA, was used.

## 20. Follow-up defects and final recommendation

The target commit is `COMMIT_MISSING_REQUIRED_TRACKED_FILES`. The evidence-backed
tracked omissions/changes required before release-candidate review are:

1. correct root package discovery/metadata so the complete source
   `spp_maker_qlip` package is present and the compatibility shim does not replace
   it;
2. package `sok_llm_orchestrator/skills/schema.skillcard.v1.json`;
3. include the Crystal bootstrap request and script in the sdist (and any intended
   release interface needed to make them usable from a source distribution);
4. wire Crystal's supported runtime default to the bootstrap-built database rather
   than `data/crystal_db/phase6_mp_10k.db`;
5. package or explicitly configure the active Skill-Loop corpus registry so an
   installed workflow does not depend on `github_parent` sibling repositories;
6. restore the intended Crystal console entry points or document and manifest an
   intentional source-equivalent replacement; and
7. update the recovered SPP MCP schema snapshot or dependency pin so source schema
   parity is deterministic.

The canonical regulator remains a separate
`REQUIRED_PROVENANCE_BLOCKED_ASSET`. It must stay explicit in release requirements;
it cannot be repaired by silently generating or bundling a substitute.

Final release status is `BLOCKED_SOURCE_FIDELITY`. The next action is:

```text
fix tracked recovery omissions
```

Do not push the recovery branch or create a release candidate until a follow-up
implementation commit fixes the artifact/runtime omissions and a new clean-room
audit passes.
