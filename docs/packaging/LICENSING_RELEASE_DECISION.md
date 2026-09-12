# Licensing release decision

Audit date: 2026-09-12. This records the Ticket 15 public-distribution boundary.

## Decision table

| Area | Included? | Basis | Decision |
| --- | ---: | --- | --- |
| Crystal-DB code/schemas/defaults | Yes | Christian Browning authorization; upstream MIT commit `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31` | `RESOLVED` |
| SPP-Maker-QLIP code/policy | Yes | Authorization; upstream MIT commit `82114cd05f0cb40149d13c20adeafe4c437a03ae`; lineage audit | `RESOLVED` |
| Skill-Loop-CSP workflow | Yes | Authorization; upstream MIT commit `36f6280e47387643853ac0cfc510e20c5d595834` | `RESOLVED` |
| QLIP | Yes | Independent upstream MIT; exact notice retained | `RESOLVED` |
| SCA 0.1.1 install dependency | Through optional validation extra | Christian Browning authorization; MIT commit `0382742a169507bcc356d60c73ae575063fc5af1`; artifact-safe package commit `3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af` | `RESOLVED` |
| Six SrTiO3 POT assets | No | Parameter provenance unresolved | `EXCLUDED_FROM_PUBLIC_RELEASE` |
| Element/radius/ionic-radius JSON tables | No | Values now generated from installed pinned dependencies | `DERIVED_AT_RUNTIME` |
| QLIP policy/provenance JSON | Yes | QLIP MIT and attribution metadata | `RESOLVED` |
| Legacy radii JSON | No | Unresolved origin and unused | `REMOVED` |

## Software versus scientific readiness

The no-network public smoke verifies imports, configuration objects, synthetic
retrieval-fixture handling, required-pair logic, QLIP request construction, and
the lazy validation boundary. It deliberately performs no optimization and
labels its output as not a scientific prediction.

Scientific solving remains available without algorithm changes when the user
provides a compatible POT root. The historical SrTiO3 objective
`4.883033620558714` is retained only as migration provenance; its blocked POTs
are not a runnable public fixture. Optional tests marked
`requires_external_scientific_assets` exercise the external-asset path when
`LLM_CSP_EXTERNAL_POT_ROOT` is supplied.

Production operation still requires user-controlled external data/services:
a Crystal-DB corpus/index with lawful CIFs, the matching embedding backend, a
compatible POT library (or lawfully fitted POTs), a Gurobi runtime/licence, and
SCA through the optional validation extra. Optional SCA ML systems and their
models/datasets remain external.

No licensing blocker remains among material actually included in the public
distribution.

LICENSING_RESOLVED

Because meaningful production/scientific operation depends on the documented
external systems and assets, the recommendation is:

READY_WITH_DOCUMENTED_EXTERNAL_REQUIREMENTS
