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

The demo is a no-network software installation smoke. It checks package import,
configuration, synthetic retrieval-fixture handling, SPP required-pair logic,
QLIP request construction, and the lazy validation adapter. It does not solve,
does not require Gurobi or POT assets, and labels its output as not a scientific
prediction. Install the supported SCA validation backend separately through:

~~~shell
python -m pip install ".[validation]"
~~~

## Production requirements

- A compatible Crystal-DB SQLite/index and exportable CIF records.
- A matching BGE-M3 service, normally an LM Studio-compatible endpoint.
- A compatible user-supplied regulator POT library covering every required
  pair, or POTs fitted from evidence the user is entitled to use.
- An explicit finite QLIP design space.
- Gurobi and a usable licence.
- SCA 0.1.1 through the `validation` extra when supported validation is
  required. Optional ML models and their assets remain separate SCA extras.

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

QLIP-derived material retains its upstream MIT notice. Crystal-DB,
SPP-Maker-QLIP, Skill-Loop-CSP, and SCA are distributed under MIT with Christian
Browning's explicit authorization. Blocked scientific resources are excluded. See
`THIRD_PARTY_NOTICES.md`, `docs/packaging/SOURCE_ATTRIBUTION_MATRIX.csv`, and
`docs/packaging/LICENSING_RELEASE_DECISION.md` for the exact boundaries.

Release recommendation: `READY_WITH_DOCUMENTED_EXTERNAL_REQUIREMENTS`. No tag
or public release is created by this work. The full assessment is in
`docs/packaging/RELEASE_READINESS_AUDIT.md`.
