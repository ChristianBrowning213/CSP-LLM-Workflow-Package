# Crystal-DB Materials Project requests

Each section in a request file defines a separate local dataset. Copy or edit a
request file to define a new experimental dataset; do not change Crystal-DB's
scientific code to change dataset coverage.

The default request reproduces the query semantics recovered from
`Crystal-DB/grab_mp_bulk.py`: request `material_id` records in Materials Project
API order with `is_stable=true`, no chemical-system or element filter, stopping
after 10,000 downloaded structures. The source provides no explicit sort and no
API-version pin, so neither is asserted here.

Preview without network access:

```console
python scripts/crystal_db/grab_data.py --requests data/crystal_db/requests/default_mp_requests.txt --dry-run
```

For a live build, set `MP_API_KEY` and omit `--dry-run`. Acquisition resumes
from existing CIFs/manifests. The wrapper then calls the restored Crystal-DB
corpus builder for ingestion, CrystalCards, fingerprints, BGE-M3 text
embeddings, sequences, and retrieval smoke checks. Configure embeddings with
`CRYSTALDB_EMBED_BASE_URL`; the source model identity is
`text-embedding-bge-m3`.

Generated files are written below `data/crystal_db/runtime/` and are ignored by
Git. A future rerun may not recreate historical `phase6_mp_10k.db` byte-for-byte
because Materials Project records and API ordering can change. This process
recreates the recorded request and builds a valid source-faithful database; it
does not forge the historical snapshot.
