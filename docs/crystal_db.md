# Crystal-DB

Crystal-DB provides the supported `crystal_db.retrieval.text_search`,
`crystal_db.csp_pack.run_csp_pack`, schema-validated API wrappers, and the
`crystal-db-mcp` entry point. Agent, novelty, corpus construction, calibration,
benchmark, report, and mixed source-CLI features are outside this package.

## External data contract

No database, corpus, stored embedding, or model is shipped. Pass an absolute
`db_path`, set `CRYSTAL_DB_PATH` (legacy alias `CRYSTALDB_PATH`), or configure
`CRYSTAL_DB_DATA_ROOT`. Relative database paths are resolved beneath that data
root. With no setting, the safe local default is
`<current-working-directory>/.crystal_db/crystal_phase0.db`.

The database must contain the Crystal-DB SQLite schema and populated
`structures`, `metadata`, `provenance`, `text_docs`, and `text_embeddings`
tables. Hybrid retrieval also requires compatible structure fingerprints.
Missing databases, empty corpora, absent indexes, and incompatible embedding
spaces return structured readiness errors; they are not presented as successful
empty searches.

## BGE-M3 / LM Studio compatibility

The production defaults are backend `lmstudio`, model
`text-embedding-bge-m3`, model-version/index label `lmstudio_v1`, and endpoint
`http://127.0.0.1:1234/v1` (override with `CRYSTALDB_EMBED_BASE_URL`).

Engine, model name, model-version label, text engine, and text view are index
identity fields and must match stored rows exactly. Vector dimension is supplied
by the live model and recorded per stored embedding; query and candidate vectors
must have the same dimension. The client does not L2-normalize LM Studio output.
Canonical `text_search` ranking uses cosine similarity (the legacy
structure-to-structure text helper uses Euclidean distance), so index and query
normalization policy must still be identical. Changing model weights,
dimensions, pooling, normalization, text view, or version label requires a new
index space; do not relabel an old index.

Importing the package never connects to LM Studio. A connection failure is
reported only when an LM Studio retrieval is requested. The deterministic
`hash` backend is for tests and development fixtures only and is never an
automatic replacement for the BGE-M3 production defaults.

## Policy and provenance

Every result carries stored provenance. CIF export checks `allow_export` and is
blocked by default when permission is false. `demo_export=True` is an explicit
override intended only for controlled synthetic/demo material. MCP additionally
requires `CRYSTALDB_POLICY_MODE=demo` before honoring that override; its default
mode is `safe`.

## MCP

Install `crystal-db[mcp]` and run `crystal-db-mcp`. Supported tools are
`crystal.text_search`, `crystal.csp_pack`, and `crystal.status`. Configuration
defaults are packaged; `CRYSTALDB_CONFIG` may point at an external JSON override.

See `examples/crystal_db/retrieval.py` for an installed-package call.
