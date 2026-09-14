# Crystal-DB

This directory contains the source-faithful Crystal-DB software surface from
scientific revision `e33d5cc55be01f800a7cf055cc1793d982deb5bc`.

The original namespace and module CLI are preserved:

```console
python -m crystal_db --help
python -m mcp_server.server
```

Installed convenience entry points are `crystal-db` and `crystal-db-mcp`.
The latter exposes the six original MCP tools. `crystal_db.mcp.server` remains
as a compatibility alias to the authoritative `mcp_server.server` module.

Production databases, CIF corpora and generated indexes are deliberately not
included by Ticket 24. They are inventoried in
`docs/fidelity/CRYSTAL_DB_ASSET_MANIFEST.csv` for Ticket 25. In a unified
checkout the default data location is `data/crystal_db/`; explicit
`CRYSTAL_DB_PATH` and legacy `CRYSTALDB_PATH` continue to take precedence.
