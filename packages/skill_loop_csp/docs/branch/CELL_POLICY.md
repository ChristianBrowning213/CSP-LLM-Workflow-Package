# Cell Policy

Policy version: `cell_policy.v1`

Representations tracked per structure:

- raw input cell,
- primitive cell,
- conventional cell,
- canonical comparison signature.

Stage usage:

- retrieval similarity: canonical comparison signature,
- SPP fitting corpus: normalized primitive form,
- baseline-vs-guided comparisons: canonical comparison signature only,
- human-readable reporting: conventional cell.

Equivalent-cell duplicate checks are signature-based under configured tolerances.
