# Crystal-DB packaging notes

## Authoritative source

- repository: `C:\Users\brown\Documents\GitHub\Crystal-DB`
- branch: `mcp`
- commit: `e33d5cc55be01f800a7cf055cc1793d982deb5bc`
- status at start and end: clean

The source repository was read only throughout Ticket 5. The exact selection is
in `CRYSTAL_DB_MIGRATION_FILESET.md`.

## Packaged and external boundaries

The wheel contains SQLite schema/access code, canonical text retrieval,
similarity/fingerprint helpers, embedding client, readiness checks, CSP-pack CIF
export, provenance/run logging, three JSON response schemas, safe retrieval
defaults, and the narrowed API/MCP facade.

It contains no production SQLite database, CIF corpus, Robocrys corpus, stored
embedding or vector index, model/checkpoint, bulk download, experiment output,
or benchmark/paper machinery. Robocrys is used when building source corpora, not
for online retrieval, and therefore is not a core dependency. Corpus
redistribution depends on each upstream source's terms; this software package
does not grant or imply permission to redistribute restricted crystal data.

## Data-root and resource repairs

Database resolution order is explicit argument, `CRYSTAL_DB_PATH` or legacy
`CRYSTALDB_PATH`, then `CRYSTAL_DB_DATA_ROOT/crystal_phase0.db`. Relative paths
are resolved beneath `CRYSTAL_DB_DATA_ROOT`; if unset, the data root is
`<cwd>/.crystal_db`. No sibling repository is searched. The current runtime uses
one SQLite file; no separate embeddings directory is fabricated because text
and vector rows are stored in that database.

Schemas and MCP defaults are wheel package data. MCP external config paths are
explicit or relative to the current working directory/config file, never to a
repository checkout.

## Embedding/index contract

The canonical space is:

- backend/provider: LM Studio's OpenAI-compatible HTTP service (`lmstudio`)
- default base URL: `http://127.0.0.1:1234/v1`
- request: `POST /embeddings`, JSON `{"model": <model>, "input": [<text>, ...]}`,
  optional bearer key (default development value `lm-studio`)
- model identifier: `text-embedding-bge-m3`
- stored model-version identity: `lmstudio_v1`
- vector dimension: not hard-coded for LM Studio; taken from the response and
  recorded in `text_embeddings.dim` (64 is only the hash-test default)
- normalization: the client does not normalize response vectors; canonical
  `text_search` calculates cosine similarity directly

`text_engine`, `text_view`, embedding engine, model, and model-version are all
part of index selection. Candidate vector lengths must match the query vector;
unusable spaces fail with diagnostics rather than falling back. Model weights,
dimension, preprocessing/chunk pooling, or normalization changes require a
separately labeled and rebuilt index. Hash embeddings remain available only for
deterministic development/tests and are not a production fallback.

Importing `crystal_db` makes no HTTP request. Backend errors occur on retrieval
and identify the LM Studio endpoint configuration.

## Dependencies

The core runtime uses the Python standard library, including `sqlite3` and
`urllib`. `jsonschema` is an optional stricter schema validator; a local minimum
validator remains available. `mcp` is optional because the server includes a
minimal JSON-RPC stdio fallback. Test dependencies are declared separately.

## Verification record

- focused package source: 18 passed
- deterministic frozen-source/package parity: identical status, ordering, IDs,
  cosine scores, provenance/policy signature, and export decisions on synthetic
  data
- wheel: `crystal_db-0.1.0-py3-none-any.whl`, installed into an isolated venv
- isolated import:
  `C:\Users\brown\AppData\Local\Temp\crystal-wheel-final-6da396af63134ee89c9e29f159dd1285\venv\Lib\site-packages\crystal_db\__init__.py`
- installed-wheel focused tests: 18 passed from outside the repository tree
- whole repository after local package installation: 104 passed, 1 skipped
- real external index, read-only readiness check: ready, 10,000 structures,
  9,992 compatible Robocrys/BGE-M3 embeddings; file size/mtime unchanged

The optional real-index top-k comparison was not run: the canonical retrieval
connection opens SQLite in read/write/create mode and changes PRAGMA state, so it
cannot honestly be called read-only. The deterministic parity probe is the
authoritative ranking comparison. The real-index check used readiness queries
only and verified unchanged file metadata.

## Remaining issues

- Production use still requires the external compatible SQLite index and a
  reachable compatible BGE-M3 service.
- LM Studio dimension is response-defined; deployments must retain the exact
  index-build model/configuration metadata outside the wheel.
- The source demo CIF redistribution status remains unresolved and those files
  stay excluded.
- Agent, novelty, benchmark, corpus construction, mixed CLI, and the live
  real-index parity smoke remain deliberately deferred.
