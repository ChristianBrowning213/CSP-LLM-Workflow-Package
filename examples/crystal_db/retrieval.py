"""Query an externally configured Crystal-DB from an installed package."""

import json
import os

from crystal_db import retrieve_text


# Set CRYSTAL_DB_PATH to a compatible external SQLite index before running.
result = retrieve_text(
    os.environ.get("CRYSTAL_DB_PATH"),
    "oxide perovskite with corner-sharing octahedra",
    k=5,
    embed_engine="lmstudio",
    model="text-embedding-bge-m3",
    model_version="lmstudio_v1",
)
print(json.dumps(result, indent=2))
