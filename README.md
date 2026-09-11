# LLM-CSP

LLM-CSP is a deterministic, retrieval-guided crystal-structure prediction
workflow. It turns an explicit scientific request into retrieved evidence,
statistical pair-potential (SPP) guidance, a QLIP mixed-integer solve, and
structured validation.

~~~text
request -> Crystal-DB -> SPP -> QLIP -> validation -> candidate + provenance
~~~

The integrated repository installs the separate llm_csp, qlip, and crystal_db
namespaces with one command. Python 3.11 or newer is required.

## Quick start

Clone this repository and, from its root, run:

~~~shell
python -m pip install .
llm-csp demo --output ./runs
~~~

The demo uses deterministic synthetic SrTiO3 retrieval evidence and six bundled
SrTiO3 POT files. It exercises the real workflow, QLIP/Gurobi solver, generated
CIF, and the validation boundary. It needs a working Gurobi runtime/licence but
no production database, embedding server, network, or broad POT corpus after
installation. SCA is not installed or advertised by this public package while
its upstream licence is unresolved. Without a separately authorized compatible
SCA installation, the candidate is preserved with validation reported as
unavailable and the CLI exits with backend-unavailable status `3`.

## Production requirements

- A compatible Crystal-DB SQLite/index and exportable CIF records.
- A matching BGE-M3 service, normally an LM Studio-compatible endpoint.
- A user-supplied broad regulator POT library covering every required pair.
- An explicit finite QLIP design space.
- Gurobi and a usable licence.
- A separately authorized compatible validation backend when validation is
  required; this repository does not install SCA.

Start from configs/examples/srtio3_production.json and run:

~~~shell
llm-csp run --config configs/examples/srtio3_production.json --output ./runs --json
~~~

Production corpora, embeddings, broad POT trees, model weights, and benchmark
outputs are not bundled and are not downloaded automatically.

## Status

This is the deterministic scientific workflow. It does not claim autonomous
materials discovery, agentic CSP, or experimental validation of novel
materials.

## Upstream software and attribution

QLIP-derived material retains its upstream MIT notice. Other migrated
components and bundled scientific resources still require explicit owner and
data-rights confirmation before public redistribution. See
`THIRD_PARTY_NOTICES.md`, `docs/packaging/SOURCE_ATTRIBUTION_MATRIX.csv`, and
`docs/packaging/LICENSING_RELEASE_DECISION.md` for the exact boundaries.

Release readiness remains `NOT_READY`; this repository must not be tagged or
published until those licensing blockers are resolved. The full packaging
assessment is in `docs/packaging/RELEASE_READINESS_AUDIT.md`.
