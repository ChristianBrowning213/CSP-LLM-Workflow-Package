# SPP Corpus Policy

Corpus manifest schema: `spp.corpus_manifest.v1`.

Supported strategies:

- `top_k`
- `composition_tight`
- `family_biased`
- `property_biased` (requires explicit numeric metadata property key on retrieval rows)

Each corpus manifest records:

- source retrieval ID,
- selected structure IDs,
- weighting map,
- deterministic content hash.

For `property_biased`, selection fails fast if the requested property key is missing
from all retrieval metadata rows.
