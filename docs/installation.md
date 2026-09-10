# Installation

The repository currently contains three independently installable Python packages. From the repository root, install them in editable mode for development:

```shell
python -m pip install -e .
python -m pip install -e packages/crystal_db
python -m pip install -e packages/qlip
```

Crystal-DB's base retrieval package is standard-library only. Install
`packages/crystal_db[mcp,schema]` when FastMCP and full JSON Schema validation
are wanted. A compatible SQLite corpus/index and BGE-M3 embedding service remain
external; see `crystal_db.md`.

The root `llm-csp` package includes the supported `llm_csp.spp` build, export,
quality, and standalone-scoring APIs. Its direct dependencies are ASE, NumPy,
and PyYAML. The migrated QLIP package remains separately installable from
`packages/qlip`.

Broad POT libraries are external. Supply their root explicitly to
`export_required_pot_subset(..., source_pot_root=...)` or set
`SPP_SOURCE_POT_ROOT`; always supply a separate caller-owned output directory.
QLIP additionally requires its configured solver and, for production Gurobi
runs, a working Gurobi installation and license.

Validation uses Structured Crystal Analyser as an external optional backend:

```shell
python -m pip install ".[validation]"
```

The extra installs the exact validated SCA Git revision. Importing
`llm_csp.validation` does not import or require SCA; calls return a structured
`backend_unavailable` result when the backend cannot load. ALIGNN and CHGNet are
not installed by this extra and are not required for the supported default
validation path.

After installing all three monorepo packages and validation dependencies, run
the deterministic workflow through Python or the thin CLI:

```shell
llm-csp run --config request.json --output runs --json
```

Production configuration must supply a compatible Crystal-DB database/index,
matching embedding backend, and broad regulator POT root. The output directory
is mandatory; the workflow never defaults to a repository or installed-package
location.
