# Ticket 30 — SCA restoration

Status: `SCA_RESTORED`.

Revision comparison proved that supported revision
`3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af` differs from scientific lineage
`e5b291312151f34949a5e6ef0f43bebfeb752bc9` only in licensing and packaging.
The complete distributable `sca` package, CLI, configurations, examples, docs,
and tests were copied verbatim. The root package now installs it without a VCS
dependency. External model weights and source-audited benchmark/paper datasets
were not copied.

Source suite: 185 passed, 6 failed. Each failure opens an excluded external
benchmark CSV/manifest; the parsing, crystallographic metrics, CrystalNN,
schemas, reports, CLI, and optional backend hooks passed. The source inventory
and exclusion classification are in `evidence/SCA_SOURCE_MANIFEST.csv`.
