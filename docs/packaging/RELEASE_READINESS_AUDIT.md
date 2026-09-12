# First-release readiness audit

Audit date: 2026-09-12. Ticket 15 supersedes the historical Ticket 9 and
Ticket 14 audits.

## Release boundary

The public distributions contain the MIT-licensed integrated workflow,
Crystal-DB, SPP-Maker-derived software, and the separately attributed upstream
MIT QLIP code. SCA remains a separate MIT-licensed package and is pinned by the
optional `validation` extra; its implementation is not copied into llm-csp.
Scientific POT files and opaque chemistry tables remain outside the
distribution.

Production solving requires a compatible user-supplied POT root. Base installs
remain usable without SCA and report `backend_unavailable` when validation is
invoked. `pip install ".[validation]"` adds supported SCA 0.1.1 from commit
`3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af`. The public `llm-csp demo`
command is a non-solving, no-network installation smoke and explicitly reports
that it did not produce a scientific prediction.

## Licensing gate

Christian Browning confirmed that the identified Crystal-DB,
SPP-Maker-QLIP, and Skill-Loop-CSP code is his code and authorized MIT
distribution. The source/licensing commit pairs are:

| Repository | Scientific source | MIT licensing commit |
| --- | --- | --- |
| Crystal-DB | `e33d5cc55be01f800a7cf055cc1793d982deb5bc` | `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31` |
| SPP-Maker-QLIP | `3a2d557811973265f3373ec881cc8057a89789d2` | `82114cd05f0cb40149d13c20adeafe4c437a03ae` |
| Skill-Loop-CSP | `b2130661b4690623877e852dc03132506aa720dd` | `36f6280e47387643853ac0cfc510e20c5d595834` |
| SCA | `e5b291312151f34949a5e6ef0f43bebfeb752bc9` | `0382742a169507bcc356d60c73ae575063fc5af1` |

QLIP retains its own upstream MIT notice in `packages/qlip/LICENSE`. Christian
Browning confirmed ownership of the SCA code and authorized MIT distribution.
That authorization does not cover third-party models, weights, datasets, or
other external assets. SCA is `RESOLVED - MIT`; the licensing classification
for everything distributed is `LICENSING_RESOLVED`.

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
| llm-csp 0.1.0 | 103 | 212155 | `4a71446b3e1b39e2a66723b8014555bceff9ca1b3b0bf5052bf25e141f075dc1` |
| crystal-db 0.1.0 | 26 | 54059 | `b80e3fac312deccfd50e01bfdf4924c5c41f0dfd6c36d5a0e96803b3e204b3fe` |
| qlip 0.1.0 | 49 | 109533 | `83c86bacd6be9273d963c0ab54afc6adba42cfa97514b8f426164b3754e0b3cd` |
| SCA 0.1.1 wheel | 89 | 175305 | `f68e38fe376e0ce05197a3a0189f3ab2bf99019c4e6710a6f52f703419111cad` |
| SCA 0.1.1 sdist | 95 | 141226 | `eb2f239a5bdc32acf35cbeb78bff58da9e3db9790a0c539804d407c918373187` |

Archive inspection found no `.POT` file, legacy radii file, former generated
table JSON, model weight, benchmark/report dataset, cache, bytecode, Git
metadata, or entry over 1 MiB. The integrated wheel carries both the root MIT
license and QLIP's separate license; both standalone wheels carry their own
license. The SCA wheel and sdist carry SCA's MIT license and exclude repository
CIF fixtures, datasets, tests, models, reports, and paper artifacts.

## Installed-wheel gate

A clean virtual environment installed the root wheel non-editably, with
`PYTHONPATH` cleared and execution outside the checkout. `llm_csp`, `qlip`, and
`crystal_db` all resolved from that environment's `site-packages`; SCA was
absent, both validation imports worked, an invocation returned
`backend_unavailable`, and the public demo passed. Installing the same wheel's
`validation` extra fetched exact SCA commit
`3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af`; `sca` then also resolved from
that environment's `site-packages`. Synthetic NaCl general validation and
ROCKSALT topology matched direct SCA output exactly.

## Test gates

| Gate | Result |
| --- | --- |
| Unit | 123 passed |
| Integration | 37 passed, 5 skipped |
| Public no-external-assets E2E | 3 passed |
| Repository-wide | 163 passed, 5 skipped |
| Optional external scientific assets | 3 skipped when `LLM_CSP_EXTERNAL_POT_ROOT` was absent |
| Installed wheel | 163 passed, 5 skipped; import/path/parity audit and public CLI smoke passed |
| SCA upstream | 191 passed |
| Fresh clone | Core route: 159 passed, 6 skipped plus CLI smoke; validation route: 10 passed, 1 skipped with direct parity |

The optional external tests cover the retained scientific workflow boundary
when a lawful POT root is supplied. The historical validated SrTiO3 objective
`4.883033620558714` remains documentation-only provenance.

## Hygiene and failure behavior

The tracked-file audit scanned 223 files: no `.POT` remained and no file
exceeded 1 MiB. Scans found no private-key header, credential-bearing URL, or
assigned API-key/secret/password/token candidate.
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
- SCA through the validation extra when validation is required;
- separately installed third-party ML packages, weights, and datasets only
  when their optional SCA evaluators are explicitly selected.

## Recommendation

All included public code and assets have a resolved distribution basis. Real
scientific execution intentionally depends on external data and licensed
backends, so the evidence-based recommendation is:

`READY_WITH_DOCUMENTED_EXTERNAL_REQUIREMENTS`
