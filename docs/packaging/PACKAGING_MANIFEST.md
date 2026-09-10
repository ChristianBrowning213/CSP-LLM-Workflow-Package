# Packaging migration manifest

This report inventories the current runtime boundary without copying or changing implementation. Evidence comes from imports/calls, package metadata, focused tests, Git history/status, and `Skill-Loop-CSP/docs/CANONICAL_CSP_WORKFLOW.md`. The CSV is the mechanical source of truth; classifications below summarize its rows.

## 1. Source repositories discovered

| Repository | Exact local path | Inspected revision / state | Role |
| --- | --- | --- | --- |
| Skill-Loop-CSP | `C:\Users\brown\Documents\GitHub\Skill-Loop-CSP` | branch `Agentic-Loop`, HEAD `b213066` | Current canonical composition/orchestration layer. |
| qlip | `C:\Users\brown\Documents\GitHub\qlip` | branch `QLIP-SPP-MCP-Esma`, HEAD `4087473`, dirty | Current QLIP solve/constraint/SPP runtime. |
| Crystal-DB | `C:\Users\brown\Documents\GitHub\Crystal-DB` | branch `mcp`, HEAD `e33d5cc`, clean | Current retrieval/database implementation. |
| SPP-Maker-QLIP | `C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP` | branch `SPP_MCP`, HEAD `3a2d557`, clean (status emitted inaccessible temp-directory warnings) | Current request-conditioned SPP build/score/package implementation. |
| Structured_Crystal_Analyser | `C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser` | branch `main`, HEAD `e5b2913`, clean | External post-generation validation package. |
| CSP_LLM_Orchestrator- | `C:\Users\brown\Documents\GitHub\CSP_LLM_Orchestrator-` | branch `main`, HEAD `b7f6c65`, dirty | Older generic MCP/plugin orchestrator, superseded for this distribution. |
| ipcsp-spp | `C:\Users\brown\Documents\GitHub\ipcsp-spp` | branch `main`, HEAD `ef9c5cc`, dirty | Historical monolithic IP-CSP/SPP ancestor. |

No similarly named forks, pytest temporary repositories, or unrelated repositories were inspected.

## 2. Functional entry points

### Crystal-DB retrieval

The canonical call is `crystal_db.retrieval.text_search(...)`. It accepts query text and an explicit SQLite path, embeds the query in the requested engine/model/version space, ranks compatible indexed rows, includes metadata/provenance, and can export policy-authorized CIFs. `crystal_db.csp_pack.run_csp_pack` adds chemistry-tiered evidence selection and a CSP-facing bundle. User-facing alternatives are `python -m crystal_db text-search|csp-pack` and MCP `python -m mcp_server.server` tools `crystal.text_search` / `crystal.csp_pack`.

Required state is a populated SQLite schema with matching text documents/embeddings and exportable CIF text. Tests named in `ENTRY_POINTS.md` exercise retrieval differentiation, backend readiness, CSP-pack selection/export, and MCP dispatch.

### SPP construction and scoring

Current construction is in SPP-Maker-QLIP. Standalone flow is `spp-maker fit` or `spp-maker run`; the canonical workflow calls `export_required_pair_spp_root`, then score collection/lambda recommendation/scaling. The core pipeline is CIF loading → periodic neighbor/pair histograms → statistical potential → QLIP-compatible `.POT` tree and manifest.

Standalone scoring is `spp-maker score` / `spp_maker.score.score_atoms`. Solver-parity scoring deliberately uses `Skill-Loop-CSP workflow.spp` with `qlip.interactions.spp.periodic_spp_sum`, ensuring the independent calculation uses the solver's periodic convention. The currently modified QLIP file corrects translated self-image multiplicity; it must be approved and frozen before migration.

### QLIP solving

The supported path is `qlip.core.validate.validate_request` → `qlip.core.solve.solve` (also exported as `qlip.solve`) → `Allocation`/Pyomo model → plugin constraints and objective → Gurobi → decoded ASE atoms/CIF → typed `SolveResult`. MCP exposes `qlip.validate_request` and `qlip.solve`; `python -m qlip` is the CLI.

Schemas live in `docs/mcp/MCP_SCHEMA.json`, currently loaded through a repository-relative path. Constraints/guidance are registered in `plugins.registry`. Ordered orbits flow through `Allocation`, validation, and `scaffolds.occupation`. Core tests cover strict requests, failure truthfulness, time-limit incumbents, objective contracts, registries, and CIF output.

### Crystallographic constraints and scaffolds

Reusable framework code includes ordered-orbit validation/closure, required occupancy, allowed species/vacancy states, exact stoichiometric representability, proximity constraints, multi-scaffold attempts, top-k enumeration, and known-assignment exclusion. Current NASICON support uses `qlip.scaffolds.registry` plus `paper_diversity.smoke_preparation.task_orbits`; the latter is runtime despite its name and should be extracted/renamed.

Space-group detection is used to construct/validate scaffold records, but `experimental/constraints/symmetry.py` is not registered in the supported solve path. It remains `UNKNOWN`, not a claimed runtime constraint. Family scaffold code in `workflow/paper_scaffolds_library.py` is actually invoked at runtime and must be separated from benchmark-only v2 definitions.

### Validation

Validation is external SCA functionality, not an LLM-CSP reimplementation. The canonical adapter calls exactly:

1. `sca.pipelines.evaluate_one_cif(..., run_alignn=False)` for parsing, formula, geometry, symmetry, and base record creation.
2. `sca.evaluators.topology.family_topology_metrics(structure, policy)` for family topology via Pymatgen CrystalNN.

SCA should be a version-pinned dependency with this small stable interface. Its source, benchmarks, models, and datasets should not migrate. Optional CHGNet/ALIGNN/other ML validation remains post-generation only.

### Full request-to-crystal workflow

The selected API is `sok_llm_orchestrator.workflow.runner.run_csp_workflow`. The canonical document reports a 54-test gate and live BaTiO3, CsPbBr3, and Na3Zr2Si2PO12 smokes. The implementation performs normalization, corpus routing, Crystal-DB retrieval/CIF export, deterministic evidence selection, fresh request SPP and regulator fallback, strict QLIP formulation/solve, objective parity, CIF write/hash, SCA validation, and attempt/provenance manifests.

The current normalizer is a finite mapping of supported formulas/aliases rather than a general natural-language parser. That limitation must remain explicit; no broader public API should be claimed during migration.

## 3. Production dependency graph

```text
run_csp_workflow(request, WorkflowConfig)
├─ ProductionWorkflowStages.normalise
│  └─ finite supported task/alias map
├─ corpus_router.route_corpus
│  └─ specialist_corpora + data/corpora/registry.json
│     └─ external SQLite corpus path
├─ crystal_db.retrieval.text_search
│  ├─ db/readiness
│  ├─ embeddings → LM Studio endpoint + exact model/version
│  ├─ fingerprint/similarity/sequence canonicalization
│  └─ ranked metadata, provenance, exported CIFs
├─ workflow.evidence
│  └─ deterministic selected CIFs, required pair coverage, hashes
├─ ProductionWorkflowStages.fit_request_spp
│  ├─ spp_maker_qlip.required_pair_extraction
│  │  └─ spp_maker CIF → histogram/gr → phi → POT
│  ├─ spp_maker calibration/scale or common_contract
│  ├─ pot quality + hash/leakage audit
│  └─ external broad regulator POT tree
├─ ProductionWorkflowStages._scaffold / scaffold_ablation
│  ├─ prototype/family adapters, or
│  └─ qlip.scaffolds registry + external frozen NASICON CIF corpus
├─ qlip.core.solve
│  ├─ strict validate/preflight + base data + path authorization
│  ├─ Allocation/Pyomo + occupancy/proximity/plugin constraints
│  ├─ SPPCollection objective
│  ├─ Gurobi installation/license
│  └─ decode → ASE CIF → SolveResult
├─ workflow.spp.score_spp_components
│  └─ independent parity using QLIP periodic primitives
├─ external SCA evaluate_one_cif + family_topology_metrics
└─ trace, hashes, execution-attempt manifest, WorkflowResult
```

## 4. Migration candidates by subsystem

- **QLIP:** core models/chemistry/path/preflight/validate/solve, Allocation and grids, objective/SPP primitives, plugin registries, proximity and ordered-occupation constraints, scaffold framework, small base/radii data, CLI/MCP schemas, and focused tests.
- **Crystal-DB:** direct retrieval and CSP-pack modules, SQLite/readiness/embedding/fingerprint/similarity dependencies, schema/provenance support, minimal MCP/API surface, retrieval defaults, and focused retrieval/export tests.
- **SPP:** the standalone SPP-Maker core, required-pair/quality/package adapters, artifact contracts, optional MCP boundary, and deterministic build/score/handoff tests.
- **Scaffolds:** reusable family/prototype/cell adapters from Skill-Loop-CSP plus QLIP ordered-orbit and scaffold modules. Paper-named runtime logic must be extracted without bringing benchmark campaign code.
- **LLM-CSP:** canonical runner, evidence/routing, QLIP/SPP adapters, attempt/provenance writer, sanitized configuration schemas/examples, and batch wrapper.
- **Validation:** only an LLM-CSP adapter and pinned SCA dependency; no SCA source migration.

## 5. External dependencies

The definitive split is in `RUNTIME_DEPENDENCIES.md`. Highest-impact dependencies are Gurobi/license, populated Crystal-DB SQLite/index data, the exact LM Studio embedding space, the broad regulator POT tree, the NASICON scaffold corpus, and external SCA. None belongs in Git as generated scientific data.

## 6. Duplicate/superseded implementations

| Concept | CURRENT | SUPERSEDED / BENCHMARK-SPECIFIC | Evidence |
| --- | --- | --- | --- |
| Full workflow | `workflow.runner.run_csp_workflow` | `orchestrator.pipeline.run_csp_pipeline`, `system_entrypoint.run_system_text`, `experiments.paper_workflow`, `paper_final_v1/v2`; old `CSP_LLM_Orchestrator-` | Canonical workflow document names one supported API and explicitly labels paper workflow historical. |
| SPP builder | Standalone `SPP-Maker-QLIP/src/spp_maker` and `spp_maker_qlip` | Embedded Skill-Loop `src/spp_maker_qlip/qlip_package.py` and `src/spp_mcp` shim | Canonical runner imports standalone package; copies differ. |
| Periodic SPP score | `qlip/interactions/spp.py` | `qlip/src/qlip/spp/*` runners | Legacy runners import four absent local modules; canonical parity imports `interactions.spp`. |
| Solver | `qlip.core.solve` SolveRequest API | `ipcsp2` interactive monolith | Current canonical runner imports QLIP core; ipcsp-spp is older upstream/reproduction code. |
| Objective/guidance | `qlip.core.objectives` + `plugins.registry` | `qlip.experimental.guidance` | Core solve imports the former; experimental package is outside active call chain. |
| Scaffold framework | QLIP ordered occupation/registry plus current Skill-Loop family/prototype adapters | `paper_scaffolds_library_v2` benchmark campaigns; experimental symmetry constraint | Current runner imports v1 library; v2 and experimental symmetry are not on that path. |

## 7. Hidden coupling / packaging risks

1. **Dirty scientific QLIP source.** `interactions/spp.py`, related periodic tests, and `data/base/provenance.json` differ from HEAD; one new periodic test is untracked. Migration must wait for an approved commit/revision and regression gate.
2. **Broken QLIP import boundary.** `qlip.core.solve` imports `qlip.visualization.plot`, which is absent. Other legacy `qlip.spp` modules import absent `qlip.spp.guidance`, `qlip.spp.io`, `qlip.tasks`, and `qlip.analysis`. Core migration needs a baseline import/test gate without inventing replacements.
3. **Sibling repositories on `sys.path`.** CSV workflow loads four absolute component roots from `.env`; the new monorepo must use installed packages and a narrow SCA dependency.
4. **Hard-coded/generated corpus paths.** The corpus registry points into sibling `Crystal-DB/data` and `Crystal-DB/artifacts/Paper_scaffolds_september`. It cannot ship verbatim.
5. **Scientific assets outside packages.** Broad regulator and NASICON registry expect QLIP data/generated paper-diversity manifests. Define stable asset IDs, roots, hashes, and compatibility checks.
6. **Embedding-space lockstep.** Canonical retrieval requires stored Robocrys text and BGE-M3 LM Studio embeddings with matching version metadata. A hash embedding fallback changes behavior and must not be silent.
7. **Repository-relative schemas.** QLIP MCP loads `docs/mcp/MCP_SCHEMA.json` by walking to repository root; package it as resource data.
8. **Mixed public modules.** Skill-Loop and Crystal-DB CLIs/API modules eagerly combine production, benchmark, paper, and developer functions. Do not copy them wholesale.
9. **Undeclared dependencies.** QLIP uses SciPy without declaring it; SPP-Maker dynamically uses PyYAML for YAML rules. Skill-Loop's canonical imports exceed its declared dependency list.
10. **Output locations and environment mutation.** QLIP defaults diagnostics under its repository, while the workflow temporarily mutates `QLIP_ALLOWED_PATH_ROOTS`; destination APIs need explicit, concurrency-safe configuration.
11. **Data licensing.** Materials Project-derived databases, ICSD-derived regulator data, and even demo CIFs need separate redistribution review.

## 8. Unknown items requiring later resolution

- Which exact QLIP worktree revision (including or excluding the current self-image correction and untracked test) is scientifically approved.
- How the missing `qlip.visualization.plot` import is satisfied in the known-working environment; no matching tracked module exists in the inspected QLIP tree.
- Whether the MCP surfaces must ship in the first public release or direct Python APIs are sufficient. The implementations are classified as candidates, but MCP dependencies can be optional.
- Whether `experimental/constraints/symmetry.py` is intended to become a supported hard constraint. It is currently neither registered nor on the canonical path.
- Which current corpus IDs/assets are legally redistributable, downloadable, or user-supplied, and what stable artifact registry will replace research paths.
- Whether Crystal-DB's broad `api.py` surface (agent, novelty, benchmarks) is part of the first supported distribution; the canonical workflow needs direct `text_search`, not all eager imports.
- Whether all family scaffolds currently reached through `paper_scaffolds_library.py` are supported product capabilities or only the subset in the canonical smoke matrix.
- The release/version contract for external SCA's two imported APIs.

## 9. Recommended migration order

The dependency graph supports the following batches. No batch is executed here.

### Batch 1 — QLIP core

Freeze the approved QLIP revision, repair/resolve its import boundary in the source project, then migrate request validation, core solve/model, plugins, constraints, SPP primitive, small package data, and focused tests. Every later solve path depends on this contract.

### Batch 2 — Crystal-DB retrieval

Migrate the minimal direct retrieval/CSP-pack boundary and tests, with external DB/index configuration and no corpus data.

#### Ticket 5 resolution

The Batch 2 runtime was migrated from frozen Crystal-DB commit `e33d5cc` into
`packages/crystal_db`. The exact pre-copy selection and exclusions are recorded
in `CRYSTAL_DB_MIGRATION_FILESET.md`. Existing CSV classifications remain the
historical inventory; the migrated package narrows the mixed API/MCP rows to
text search, CSP-pack, and backend status. External SQLite/index data is resolved
through `CRYSTAL_DB_DATA_ROOT`, `CRYSTAL_DB_PATH`, or `CRYSTALDB_PATH`, and no
source fixture CIF was copied because redistribution provenance was unresolved.

### Batch 3 — SPP

Migrate standalone SPP-Maker build/score/quality/package modules and tests. Bind its output contract to the migrated QLIP SPP loader.

#### Ticket 6 resolution

The supported SPP builder/scorer was migrated from frozen SPP-Maker commit
`3a2d557` into `llm_csp.spp`; the exact split is recorded in
`SPP_MIGRATION_FILESET.md`. Fresh formula-required fitting preserves the source
algorithm. A small packaging adapter exports byte-identical canonical subsets
from an explicit `SPP_SOURCE_POT_ROOT`, with hashes and truthful missing-pair
status. Broad regulator assets, registry/orchestration code, CLI/MCP, calibration
campaigns, and generated artifacts remain excluded. Packaged QLIP consumed the
six exported SrTiO3 POTs without changing its 11 Å scorer or objective.

### Batch 4 — scaffold/constraint framework

Migrate generic ordered occupation, proximity, top-k/multi/exclusion, then extract current family/prototype/NASICON adapters from paper-named locations. Externalize scaffold corpora.

### Batch 5 — validation integration

Add a narrow adapter and version-pinned optional/required SCA dependency for the two canonical APIs. Keep ML extras post-generation and optional.

#### Ticket 7 resolution

`llm_csp.validation` now lazily wraps the external frozen SCA interfaces
`sca.pipelines.evaluate_one_cif` and
`sca.evaluators.topology.family_topology_metrics`. SCA remains
`DEPENDENCY_EXTERNAL`; the optional root extra points to commit `e5b2913`, and
the adapter preserves exact scientific records/metrics while normalizing
backend absence, parse failure, evaluation failure, and unsupported topology
policy. ALIGNN remains opt-in and CHGNet is outside the selected call graph.

### Batch 6 — high-level LLM-CSP workflow

Migrate canonical routing/evidence/runner/provenance and batch wrapper after package APIs exist. Replace sibling paths and finite research configuration with explicit supported configuration while preserving the finite supported-task claim.

#### Ticket 8 resolution

The deterministic `run_csp_workflow` contract is now packaged with explicit
request/config/result models, normalized Crystal-DB outcomes, packaged SPP and
complete-regulator decisions, QLIP request validation/solve, SCA-backed
validation, portable run manifests, and a thin JSON CLI. The source finite task
normalizer was replaced by required resolved formula/design-space input rather
than claiming general language understanding. Agentic, paper, benchmark,
calibration/common-contract research campaigns, and external scientific assets
remain excluded.

### Batch 7 — demo assets/examples

After legal review, add tiny CIF/config examples and end-to-end smoke tests. Do not include scientific corpora, fitted POT trees, checkpoints, or run artifacts.
