# First-release readiness audit

Audit date: 2026-09-12. Ticket 14 supersedes the historical Ticket 9 audit.

## Release boundary

The public distributions contain the MIT-licensed integrated workflow,
Crystal-DB, SPP-Maker-derived software, and the separately attributed upstream
MIT QLIP code. SCA implementation code, scientific POT files, and opaque
chemistry tables are outside the distribution.

Production solving requires a compatible user-supplied POT root. SCA remains
an optional, separately authorized validator backend and is not an install
dependency or extra. The public `llm-csp demo` command is a non-solving,
no-network installation smoke and explicitly reports that it did not produce a
scientific prediction.

## Licensing gate

Christian Browning confirmed that the identified Crystal-DB,
SPP-Maker-QLIP, and Skill-Loop-CSP code is his code and authorized MIT
distribution. The source/licensing commit pairs are:

| Repository | Scientific source | MIT licensing commit |
| --- | --- | --- |
| Crystal-DB | `e33d5cc55be01f800a7cf055cc1793d982deb5bc` | `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31` |
| SPP-Maker-QLIP | `3a2d557811973265f3373ec881cc8057a89789d2` | `82114cd05f0cb40149d13c20adeafe4c437a03ae` |
| Skill-Loop-CSP | `b2130661b4690623877e852dc03132506aa720dd` | `36f6280e47387643853ac0cfc510e20c5d595834` |

QLIP retains its own upstream MIT notice in `packages/qlip/LICENSE`. SCA is
`EXCLUDED_FROM_PUBLIC_RELEASE`. The licensing audit classification for every
file actually included is `LICENSING_RESOLVED`.

## Assets and deterministic chemistry

The six SrTiO3 POTs and the legacy `resources/radii.json` are removed. QLIP
requires an explicit request/configuration POT root and fails clearly when it
is absent. The former `base/elements.json`, `base/radii.json`, and
`base/ionic_radii.json` files are derived lazily in memory from exact declared
dependency versions, without network access or filesystem writes.

Complete-table regression hashes match the former Windows JSON serialization:

| Generated table | Records/rows | Former canonical SHA-256 |
| --- | ---: | --- |
| elements | 118 elements | `1456486184a1854330bfaf99afee734c41a0f47b0f7a0dff2a22268738c9f75d` |
| radii | 118 elements | `fab9add217a03f460f75e5f8d4bc673cbe8a3e5e5ed7afcc9f048e5c087f9a6f` |
| ionic radii | 486 selected ionic rows | `acb6af1a4f67c6246c4db1689ee533a1c9d31efea00ab50535730fa4acd42a07` |

The resolved `radius_policy.json`, `pair_distance_policy.json`, and
`provenance.json` remain packaged.

## Wheel audit

Built with `python -m build --wheel` in isolated build environments. Artifacts
were written outside the repository.

| Distribution | Entries | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| llm-csp 0.1.0 | 103 | 211954 | `94b41415e9993e56e154a00c6c1a180bf2a9cf1cc49c34c8587fc32267994db3` |
| crystal-db 0.1.0 | 26 | 54059 | `f43ac533f238fe55b9b603f575910cadb3863b2e520b047c4d8030c7a5cb0b4b` |
| qlip 0.1.0 | 49 | 109533 | `884f89565ed985a259e113dec28b3f86dc84266eea212dd10639229e7404f207` |

Archive inspection found no `.POT` file, legacy radii file, former generated
table JSON, or `__pycache__` entry. The integrated wheel carries both the root
MIT license and QLIP's separate license; both standalone wheels carry their
own license.

## Installed-wheel gate

A clean virtual environment installed the root wheel non-editably, with
`PYTHONPATH` cleared and execution outside the checkout. `llm_csp`, `qlip`, and
`crystal_db` all resolved from that environment's `site-packages`. The public
demo passed with configuration, retrieval fixture, required-pair, QLIP request,
and lazy validation-adapter checks. It required no database, embedding service,
POT, Gurobi license, validator, or network. Runtime chemistry generation in the
installed wheel reproduced all three hashes above, and missing bundled POTs
failed explicitly.

## Test gates

| Gate | Result |
| --- | --- |
| Unit | 123 passed |
| Integration | 37 passed, 5 skipped |
| Public no-external-assets E2E | 3 passed |
| Repository-wide | 163 passed, 5 skipped |
| Optional external scientific assets | 3 skipped when `LLM_CSP_EXTERNAL_POT_ROOT` was absent |
| Installed wheel | import/resource/parity audit and public CLI smoke passed |
| Fresh clone | Non-editable install and CLI smoke passed; 159 passed, 6 skipped without SCA or external POTs |

The optional external tests cover the retained scientific workflow boundary
when a lawful POT root is supplied. The historical validated SrTiO3 objective
`4.883033620558714` remains documentation-only provenance.

## Hygiene and failure behavior

The tracked-plus-new-file audit scanned 233 files: no `.POT` remained, no file
exceeded 1 MiB (largest 53,120 bytes), and scans found no private-key header,
credential-bearing URL, or assigned API-key/secret/password/token candidate.
Generated build directories containing stale assets were removed before wheel
and installed-package tests.

Configuration validation, unavailable backend handling, absent database,
missing/invalid POT coverage, and validation-backend absence remain covered by
the passing automated suite. No fallback scientific solver or silent POT
default was added.

## External production requirements

A production user supplies, as applicable:

- a Crystal-DB corpus/index and compatible embedding backend;
- a compatible POT library, or POTs fitted/generated from evidence they are
  entitled to use;
- a Gurobi runtime and license;
- a separately authorized compatible validator backend, if desired.

## Recommendation

All included public code and assets have a resolved distribution basis. Real
scientific execution intentionally depends on external data and licensed
backends, so the evidence-based recommendation is:

`READY_WITH_DOCUMENTED_EXTERNAL_REQUIREMENTS`
