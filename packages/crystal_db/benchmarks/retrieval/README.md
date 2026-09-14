# Retrieval Benchmark Cases

Each line is one JSON object with at least:
- `case_id` (string)
- `query` (string)
- `expected` (object)

`expected` supports:
- `must_contain_any` (list of strings)
- `family` (string)
- `elements_any` (list of strings)
- `structure_ids_any` (list of strings)

Optional Phase 6 gold fields:
- `expected_structure_ids` (list of strings)
- `expected_keywords` (list of strings)
- `expected_formula` (string)
- `expected_prototype` (string)
- `tags` (list of strings)
- `notes` (string)

Workflow:
1. Start from `tiny_fixture.jsonl` or `phase6_small.jsonl`.
2. Normalize deterministically with `cases-normalize`.
3. Add curated gold fields incrementally.
4. Use `calibrate-retrieval` + `gate-retrieval` in CI.

Determinism:
- Normalized files are sorted by `case_id`.
- Sampling uses SHA256-based deterministic ordering over `structure_id`.
