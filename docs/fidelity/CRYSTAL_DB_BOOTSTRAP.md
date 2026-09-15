# Ticket 29 — Materials Project bootstrap

Status: `CRYSTAL_DB_BOOTSTRAP_READY`.

The original request semantics were recovered from `grab_mp_bulk.py` and its
documented invocation: Materials Project summary search with only
`material_id`, `is_stable=true`, no `chemsys` or `elements` filter, source/API
return order, 200-record chunks, and a 10,000-CIF stop. Source evidence does
not identify an API version or deterministic sort.

`data/crystal_db/requests/default_mp_requests.txt` records that request.
`scripts/crystal_db/grab_data.py` deterministically parses it, delegates
acquisition to the restored downloader, then delegates ingestion and indexing
to the restored corpus builder. It supports source resume behavior and an
offline `--dry-run`; no second database or embedding implementation exists.
The generated source manifests, dataset card, indexing summary, and bootstrap
manifest record request hash/version, retrieval times, material IDs, CIF
hashes, database counts, and BGE-M3 identity/dimensions where available.

The environment contained `MP_API_KEY` during recovery, but the full 10k build
was not launched. Historical bytes are not reproducible because Materials
Project data and API ordering can change.
