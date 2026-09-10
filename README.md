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
python -m pip install ".[validation]"
llm-csp demo --output ./runs
~~~

The demo uses deterministic synthetic SrTiO3 retrieval evidence and six bundled
SrTiO3 POT files. It exercises the real workflow, QLIP/Gurobi solver, generated
CIF, and SCA validation. It needs a working Gurobi runtime/licence but no
production database, embedding server, network, or broad POT corpus after
installation.

## Production requirements

- A compatible Crystal-DB SQLite/index and exportable CIF records.
- A matching BGE-M3 service, normally an LM Studio-compatible endpoint.
- A user-supplied broad regulator POT library covering every required pair.
- An explicit finite QLIP design space.
- Gurobi and a usable licence.
- The pinned SCA dependency when validation is enabled.

Start from configs/examples/srtio3_production.json and run:

~~~shell
llm-csp run --config configs/examples/srtio3_production.json --output ./runs --json
~~~

Production corpora, embeddings, broad POT trees, model weights, and benchmark
outputs are not bundled and are not downloaded automatically.

## Status

This is the deterministic scientific workflow. It does not claim autonomous
materials discovery, agentic CSP, or experimental validation of novel
materials. Release readiness and unresolved upstream licensing are documented
in docs/packaging/RELEASE_READINESS_AUDIT.md.
