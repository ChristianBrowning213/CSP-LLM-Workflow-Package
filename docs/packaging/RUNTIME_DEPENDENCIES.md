# Runtime dependency summary

This is an observed dependency inventory, not a request to update any `pyproject.toml` yet. Version constraints must be resolved during migration against the approved source revisions.

## Python dependencies

| Dependency | Required by | Evidence / boundary |
| --- | --- | --- |
| `numpy` | SPP, QLIP, cell/scaffold code | Direct imports throughout SPP fitting/scoring, QLIP solve/interactions, and dynamic-cell formulation. |
| `scipy` | QLIP SPP | `qlip.interactions.spp` imports `scipy.interpolate.interp1d`; it is missing from QLIP's current `pyproject.toml`. |
| `ase` | SPP and QLIP | CIF loading, atom containers, chemistry formula parsing, and CIF emission. |
| `pymatgen` | orchestration, QLIP scaffolds, SCA | Composition/Structure, symmetry, StructureMatcher, CifWriter, and CrystalNN topology. |
| `pyomo` | QLIP and dynamic cell | IP model, constraints, objectives, and Gurobi solver bridge. |
| `gurobipy` | QLIP | Declared solver binding; a working installation/license is separately required. |
| `jsonschema` | QLIP MCP, Crystal-DB schemas, older orchestration contracts | Request/result validation. Crystal-DB imports it lazily. |
| `pydantic` | SPP MCP, QLIP MCP/data contracts, SCA | Tool contracts and SCA result models. |
| `mcp` | QLIP/SPP/Crystal-DB MCP surfaces | Optional if the final monorepo composes Python APIs directly; required to retain current MCP entry points. |
| `PyYAML` | workflow configuration and optional SPP covalent-rule YAML | SPP loads YAML dynamically but does not currently declare PyYAML. |
| `orjson`, `pydantic-settings`, `python-dotenv`, `mendeleev`, `smact` | QLIP declared environment | Present in QLIP metadata; exact necessity for the minimum core must be confirmed in the QLIP migration ticket. |
| `pandas`, `rich`, `tqdm`, `typer` | external SCA package | Declared SCA base dependencies; canonical direct APIs primarily exercise Pydantic/Pymatgen paths. |

No scientific dependency should be copied blindly from these source metadata files. QLIP currently pins several exact versions while the other repositories use broader ranges.

## External runtime dependencies

- **Gurobi installation and valid license.** The production solve path constructs `pyomo.SolverFactory("gurobi")`; package importability alone is insufficient.
- **SQLite database backend.** Python's `sqlite3` is sufficient as an engine, but a populated and schema-compatible Crystal-DB database/index is external data.
- **LM Studio/OpenAI-compatible embeddings endpoint.** The canonical configuration selects `lmstudio`, `text-embedding-bge-m3`, and `lmstudio_v1`, defaulting to `http://127.0.0.1:1234/v1`. Hash embeddings exist for local/demo paths but are not equivalent to the canonical indexed embedding space.
- **Structured Crystal Analyser (`sca`).** The adapter was validated against
  scientific commit `e5b2913` and licensed package 0.1.1 commit `3ede1ee`, exposing
  `sca.pipelines.evaluate_one_cif` and
  `sca.evaluators.topology.family_topology_metrics`. SCA is not copied into this
  monorepo, is imported lazily by `llm_csp.validation`, and is installed through
  the root `validation` extra.

## Optional dependencies

- MCP server/runtime packages are optional if only direct Python APIs ship; they are required to preserve the current tool surfaces.
- SCA's ALIGNN, CHGNet, MatGL/M3GNet, MACE, and SevenNet extras are post-generation evaluation features. The canonical workflow passes `run_alignn=False`; these must not influence candidate selection.
- RoboCrystallographer is needed to build the canonical `robocrys` text corpus, not to query an already populated compatible index. Its version remains part of data provenance.
- PyYAML is needed only for YAML-form covalent filtering in SPP-Maker; CSV rules avoid it.
- Crystal-DB novelty/agent/reporting APIs and QLIP top-k/reference-exclusion APIs are not required by every minimal solve but are supported-adjacent candidates.

## Data/model dependencies

| Asset | Current expectation | Packaging decision |
| --- | --- | --- |
| Crystal-DB SQLite corpora | General 10k and specialist family/NASICON databases referenced by `data/corpora/registry.json` | Never commit. Define configurable roots, schema/version checks, legal provenance, and hashes. |
| Text documents and embeddings | Must match text engine/view plus embedding engine/model/version exactly | External indexed data; no silent model-space fallback. |
| Request-conditioned SPP/POT tree | Generated from the selected CIF evidence for each attempt | Runtime artifact under a configured run root; never package as source. |
| Broad regulator SPP tree | Current canonical docs describe a frozen 3,388-pair ICSD regulator | External, versioned scientific asset with manifest/hash; path currently defaults under QLIP data or `SKILL_LOOP_REGULATOR_SPP_ROOT`. |
| QLIP base JSON data | `data/base/{elements,ionic_radii,pair_distance_policy,provenance,radii,radius_policy}.json` | Small runtime package data after provenance review. |
| Atomic radii | `src/qlip/constraints/radii.json` plus configurable base-data registry | Small runtime package data. |
| NASICON scaffold corpus | Frozen CIF corpus plus retained manifest expected by `qlip.scaffolds.registry` | External scientific data; replace paper-artifact path assumptions with a versioned configured asset interface. |
| Demo CIF fixtures | Crystal-DB and package tests contain tiny CIFs | Copy only after legal/source provenance is confirmed. |
| Optional ML checkpoints | ALIGNN/CHGNet/MatGL/MACE/SevenNet | Managed by external SCA extras; never vendor checkpoints here. |

## Observed configuration and environment variables

- Legacy component repositories: `CRYSTAL_DB_ROOT`, `SPP_MAKER_ROOT`, `QLIP_ROOT`, `SCA_ROOT`.
- Packaged SPP: `SPP_SOURCE_POT_ROOT` selects an external broad POT library
  when `source_pot_root` is not passed directly. Outputs are always explicit
  caller-owned paths and have no environment-variable default.
- Crystal-DB: `CRYSTAL_DB_DATA_ROOT` is the portable external-data root;
  `CRYSTALDB_PATH` / `CRYSTAL_DB_PATH` select a database directly.
  `CRYSTALDB_CONFIG`, `CRYSTALDB_POLICY_MODE`, `CRYSTALDB_EMBED_BASE_URL`,
  `CRYSTALDB_EMBED_API_KEY`, and timeout/batch/retry/chunking variables configure
  the optional MCP and LM Studio boundaries.
- QLIP: `QLIP_ALLOWED_PATH_ROOTS`, `QLIP_BASE_DATA_DIR`, `QLIP_SOLVER`, `QLIP_SPP_POT_DIR`, `QLIP_SPP_REGULARISATION_DIR` / US-spelling alias, `QLIP_SCAFFOLD_CORPUS_ROOT`, and optional diagnostic-output variables.
- Canonical workflow: `SKILL_LOOP_REGULATOR_SPP_ROOT` is documented by the workflow configuration.
