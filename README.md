# LLM-CSP

LLM-CSP 0.1.0 is a deterministic, retrieval-guided crystal-structure
prediction workflow. It turns an explicit crystallographic request into
retrieved structural evidence, request-specific statistical pair-potential
(SPP) guidance, a QLIP mixed-integer CSP solve, a candidate structure, and
structured SCA validation with provenance.

~~~text
Request -> Crystal-DB -> SPP -> QLIP -> candidate CIF -> SCA validation
                                                        -> result + provenance
~~~

The major components are Crystal-DB retrieval, SPP preparation, QLIP
integer-programming CSP, the deterministic `llm_csp.workflow` coordinator, and
the optional SCA validation backend. The integrated repository installs the
`llm_csp`, `qlip`, and `crystal_db` namespaces with one command. Python 3.11 or
newer is required.

## Quick start

Clone this repository and, from its root, run:

~~~shell
python -m pip install .
llm-csp demo
~~~

The demo is an offline installation/workflow smoke test. It checks package import,
configuration, synthetic retrieval-fixture handling, SPP required-pair logic,
QLIP request construction, and the lazy validation adapter. No optimization is
run. No scientific POT library is bundled. The result is not a crystal
prediction. Install the supported SCA validation backend through:

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

Reproducibility requirements and exact source/dependency provenance are in
`docs/reproducibility.md`, `docs/packaging/RELEASE_DEPENDENCY_MATRIX.md`, and
`docs/packaging/SCA_VALIDATION_CONTRACT.md`.

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
