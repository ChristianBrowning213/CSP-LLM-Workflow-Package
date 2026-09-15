# NASICON QLIP / Skill-Loop-CSP capability audit

Audit date: 2026-08-03  
Target: `Na3Zr2Si2PO12`  
Decision: **GO_AFTER_SMALL_EXTENSION**

## Scope and method

This audit inspected executable source and focused tests on the current branches:

- QLIP: `QLIP-SPP-MCP-Esma`
- Skill-Loop-CSP: `Agentic-Loop`
- Crystal-DB: `mcp`

The worktrees were already dirty. In particular, QLIP's production preflight, solve, validation, SPP, plugin-registry and related tests contained pre-existing changes. This audit did not overwrite them. `project_context.txt` was not inspected.

Read-only evidence commands included targeted `rg`, PowerShell `Get-Content`, `git status --short`, and a read-only SQLite query against `Crystal-DB/data/phase6_mp_10k.db`. The latter found zero exact `Na3Zr2Si2PO12` rows and zero rows containing all Na/Zr/Si/P/O elements. A Materials Project API key is available, but no acquisition was performed before this audit gate.

## Decision and blocking facts

`GO_AFTER_SMALL_EXTENSION` means the existing binary-allocation and periodic-SPP machinery is a plausible base for an ordered, fully occupied NASICON demonstration, but the current runtime does **not** solve a NASICON scaffold and must not be presented as doing so.

The minimum scientifically valid extension is:

1. represent the selected ordered conventional or primitive cell as explicit candidate sites;
2. add production QLIP constraints for per-site/per-orbit allowed species, fixed orbits, orbit closure, and full-cell composition;
3. expose those constraints in the QLIP schema and real validation/solve path;
4. make Skill-Loop-CSP submit that valid QLIP request and consume the returned CIF, rather than writing a predefined scaffold CIF;
5. add a NASICON topology validator and provenance-labelled specialist corpus metadata.

This is classified as a small, narrow extension rather than an architectural replacement because QLIP already constructs an arbitrary explicit periodic site set, binary species/site variables, exact integer species counts, exclusivity constraints, periodic all-image SPP coefficients, a Gurobi MIQP, and a real CIF from solved placements. The claim remains provisional until the 80-site-class focused smoke test measures build time, memory and solve time.

## A. QLIP audit

### Runtime representation

Production QLIP has no registered prototype or Wyckoff scaffold catalogue. `src/qlip/core/models.py` defines only `uniform_grid` and `explicit_fractional_sites`; `src/qlip/core/solve.py::_build_positions` implements those two modes. The apparent `SpaceGroupOrbits` import in `src/qlip/constraints/__init__.py` is a deliberate unavailable placeholder because `spacegroup_orbits.py` is not shipped. The experimental `SpaceGroup` implementation in `src/qlip/experimental/constraints/symmetry.py` is incomplete and is not registered in the production plugin registry.

Consequently:

- fixed-orbit solving is not operational in production QLIP;
- variable-orbit solving is not operational in production QLIP;
- Na, Zr, Si, P and O are accepted as ordinary ASE species, but their coordination roles and orbit membership have no native semantics;
- multiple inequivalent sites can be supplied as explicit coordinates, but QLIP presently permits every formula species on every candidate site unless another constraint forbids it;
- fractional occupancy and occupational disorder are unsupported because every decision variable is binary;
- candidate sites need not all be occupied (`sum_t x[t,i] <= 1`), while every atom in the supplied integer formula must be placed exactly once (`sum_i x[t,i] == count[t]`).

For a fully occupied ordered conventional cell, the formula passed to QLIP must contain the full-cell counts, for example four formula units as `Na12Zr8Si8P4O48`, not merely the reduced 20-atom formula. The output can then be checked against the reduced formula `Na3Zr2Si2PO12`.

### Stoichiometry, closure and periodic objective

`src/qlip/allocation.py::Allocation.encode` creates `x[species,site]` binary variables, exact per-species stoichiometry constraints, and at-most-one-species site exclusivity. There is no orbit variable, orbit multiplicity constraint, allowed-species mask, or fixed-site constraint. Orbit closure is therefore not enforced.

The current SPP implementation does sum all translated periodic images within the configured cutoff. `src/qlip/interactions/spp.py::periodic_spp_sum` enumerates translations to an image depth derived from the cell and cutoff; `SPPCollection.pair_cost_matrix` compiles those sums for the MIQP. `tests/test_spp_periodic.py` contains focused boundary-image, multiple-image, self-image, non-cubic, cutoff and objective-parity tests. These source files already had user changes, so this audit records observed behavior without attributing authorship.

### Model-size estimate

For 80 explicit candidate sites and five species, the current unconstrained formulation creates:

- 400 binary allocation variables;
- 5 stoichiometry constraints;
- 80 site-exclusivity constraints;
- no explicit auxiliary variables before solver internal reformulation;
- 15 unordered species-pair matrices;
- 79,000 off-diagonal binary-product terms, plus as many as 400 same-site translated-self-image terms when enabled.

Each matrix coefficient itself sums a cell- and cutoff-dependent number of periodic images. Exact periodic pair-image term count, build time, memory and solve time cannot be claimed until the selected cell is instantiated and instrumented. The raw binary count is modest; coefficient construction and dense quadratic expression growth are the main risks.

### CIF fidelity

`src/qlip/core/solve.py::_build_cif_text` writes solved symbols and fractional coordinates with the declared ASE cell. It does not explicitly write the requested space-group/Wyckoff metadata. The generated CIF therefore preserves cell, species and coordinates, but symmetry metadata preservation is unsupported and must be restored or validated in the NASICON extension.

## B. Skill-Loop-CSP audit

### Scaffold selection and the runtime discrepancy

`src/sok_llm_orchestrator/contracts/qlip_builders_v2.py` maps a task's prototype/family through the fixed `SUPPORTED_PROTOTYPE_SCAFFOLDS` dictionary. NASICON is absent. `src/sok_llm_orchestrator/structures/prototype_scaffold.py` stores idealized scaffold definitions, expands symmetry-equivalent sites with pymatgen, and supports a formula allowlist for variable-orbit enumeration.

The important discrepancy is that these modes are not production QLIP modes. The builder itself labels scaffold support as metadata and “not a Wyckoff-orbit MILP enforcement module.” In the paper-specific runner, `src/sok_llm_orchestrator/experiments/paper_workflow.py::_run_row` calls `prototype_orbit_solution_from_request` and `write_prototype_scaffold_cif`; it does not call QLIP solve. Its SPP summary marks `missing_pairs` as empty without constructing row-specific POTs. Those artefacts are scaffold reconstruction/enumeration demonstrations, not end-to-end QLIP CSP solves.

The main orchestrator pipeline has a real retrieval → export staging → SPP MCP → package → QLIP validate/solve path and blocks on an empty export-ready CIF set. That path should be reused for NASICON after the request contract is extended.

### Corpus, pair coverage and requests

The paper runner selects database paths from CSV `source_db_scope`, while the general pipeline receives configured Crystal-DB connectivity and selects export-ready evidence. The specialist halide experiment is therefore a paper-runner convention, not a general corpus registry keyed by a stable corpus ID. A configurable corpus-ID-to-database mapping is required for NASICON; machine-specific paths must remain configuration only.

`src/spp_maker_qlip/qlip_package.py::required_pairs_from_formula` derives all unordered self and cross pairs. Its package checks block on missing required POT pairs. In contrast, `paper_workflow.py::_pairs_for_formula` derives only cross pairs and the runner does not audit actual POT coverage. The production SPP/QLIP path can combine task-specific POTs with an optional regularisation SPP directory and weight; QLIP supports strict complete mode and an explicitly labelled partial mode. The requested NASICON showcase must use strict complete coverage.

### Validation and artefacts

Current paper validation parses the CIF, compares reduced formula, analyzes symmetry with pymatgen, and screens contacts below 0.75 Å. Verification presets are a fixed dictionary in `src/sok_llm_orchestrator/verification/presets.py`; there is no topology-validator registry. Adding a NASICON validator and a named policy is a small extension.

The main workflow records retrieval, staged CIFs, SPP runs/packages, QLIP requests/responses, verification and novelty artefacts. The visualisation code supports VESTA-backed structure renders and workflow panels, but no existing code constructs chemically differentiated ZrO6/SiO4/PO4 polyhedra or a sodium-channel network. Paper-quality NASICON rendering therefore requires an extension or a reproducible VESTA scene configuration.

No general three-element limit was found in the production formula-pair derivation or QLIP binary allocation. Prototype-family allowlists and hard-coded paper query schemas are the practical limitations, not elemental cardinality.

## C. Crystal-DB audit

### Acquisition and ingestion

The repository provides:

- `python -m crystal_db ingest-folder` for policy-controlled local CIF ingestion;
- `scripts/build_crystaldb_corpus.py` for Materials Project, local-CIF and combined-view corpora;
- `scripts/build_paper_result_datasets_from_mp.py` as an older paper-target acquisition route.

The reusable builder loads an MP key without printing it, queries `mp_api.client.MPRester`, writes CIFs and a JSONL manifest, ingests with explicit policy, and can build CrystalCards, fingerprints, text documents/LM Studio embeddings and sequence representations. It explicitly avoids silent hash-embedding fallback when LM Studio embeddings are requested.

### Schema and retrieval

Core tables store CIF text, formula/reduced formula, element CSV, space group, source/source ID, retrieval timestamp and policy flags. The reusable corpus manifest additionally records chemical system, family label/source, CIF SHA-256, stability fields and query provenance.

There is no canonical `topology_tier`, `family_assignment_method`, `source_version`, exact-target exclusion, near-duplicate exclusion, or topology-label table/column. The existing `family_label` is manifest-level and is not preserved by `ingest_folder` in the SQLite metadata schema. These fields require a narrow schema/manifest extension before the requested frozen corpora are defensible.

Production representations are:

- baseline CrystalCard and composition/symmetry fingerprint;
- generated structure text, including RoboCrys-compatible text surfaces;
- LM Studio `text-embedding-bge-m3` embeddings;
- canonical CIF sequence plus sequence embedding;
- structural, text and hybrid retrieval.

Retrieval supports text search, formula filtering, element/chemical-system filtering, structural fingerprint similarity and hybrid reranking. It can use family keywords in text/hints, but it has no exact prototype/topology field query today. CIF export is policy-gated in retrieval and CSP-pack code.

### Local corpus evidence

A read-only query of `data/phase6_mp_10k.db` found:

- exact target rows: 0;
- rows containing Na/Zr/Si/P/O: 0;
- rows containing Na/Zr/P/O: 0.

No local CIF, JSON, JSONL or CSV under the inspected Crystal-DB data/artifact roots contained the exact target formula or a NASICON label. A lawful Materials Project API acquisition route and API key are available, so reference/corpus selection is not blocked operationally, but the target's ordering and occupancy must be inspected after download.

## Documentation/runtime discrepancies

1. Skill-Loop-CSP experiment CSVs call modes `prototype_orbit_qlip` and `prototype_orbit_variable_spp_qlip`, but production QLIP accepts only `uniform_grid` and `explicit_fractional_sites`.
2. The paper workflow calls its output a QLIP solution while directly writing a predefined/enumerated scaffold CIF without calling QLIP solve.
3. The paper workflow records SPP pairs and an empty missing-pair list without building or checking row-specific POT coverage.
4. The reusable Crystal-DB builder can label a family in its manifest, but the production SQLite schema does not preserve specialist topology tiers or assignment evidence.

## Phase 1 conclusion

**GO_AFTER_SMALL_EXTENSION**

Proceed only after the real QLIP request and solve path supports ordered orbit/site restrictions and after the selected reference is shown to be fully occupied and integer-stoichiometric. Until then:

- QLIP NASICON support is untested;
- fixed- and variable-orbit NASICON solving are unsupported;
- topology recovery, stability, novelty and experimental realizability must not be claimed;
- emitting a reference-derived scaffold CIF would be reconstruction, not the requested CSP demonstration.
