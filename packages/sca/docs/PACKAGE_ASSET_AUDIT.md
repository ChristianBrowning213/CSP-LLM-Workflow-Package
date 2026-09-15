# SCA package asset audit

Audit date: 2026-09-12.

This audit separates Christian Browning's MIT-licensed SCA software from
repository research material and optional third-party systems. `MANIFEST.in`
constrains both wheel and source distribution to the package source and
essential package metadata.

| Repository material | Classification | Distribution decision |
| --- | --- | --- |
| `sca/**/*.py` authored package source | `INCLUDE_RESOLVED` | Included under MIT |
| `LICENSE`, `README.md`, `pyproject.toml`, `MANIFEST.in` | `INCLUDE_RESOLVED` | Included |
| Small authored/synthetic CIF and JSON fixtures under `tests/fixtures/` | `TEST_ONLY_RESOLVED` | Kept in the repository for tests; excluded from wheel and sdist |
| Benchmark datasets and replicas under `benchmarks/` | `EXTERNAL` | Excluded from wheel and sdist; MIT software licensing makes no data-rights claim |
| Paper/reference CIF collections under `benchmarks/paper_targets/` | `REMOVE_FROM_DISTRIBUTION` | Excluded from wheel and sdist |
| Comparator data under `data/` | `EXTERNAL` | Excluded from wheel and sdist |
| Generated reports and cached outputs under `reports/` | `REMOVE_FROM_DISTRIBUTION` | Excluded from wheel and sdist |
| Paper/experiment scripts under `scripts/` | `REMOVE_FROM_DISTRIBUTION` | Excluded from wheel and sdist |
| Repository context/ticket exports | `REMOVE_FROM_DISTRIBUTION` | Excluded from wheel and sdist |
| ALIGNN, CHGNet, MatGL, MACE and SevenNet packages, weights and datasets | `EXTERNAL` | Not bundled; available only through explicit optional extras where declared |

No model or weight file is package data. Base SCA dependencies contain no
ALIGNN, CHGNet, MatGL, MACE or SevenNet requirement. The public LLM-CSP
validation contract uses `evaluate_one_cif` and `family_topology_metrics`
without enabling those optional backends.
