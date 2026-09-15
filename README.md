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
integer-programming CSP, SCA validation, the deterministic `llm_csp.workflow`
coordinator, and the original Skill-Loop-CSP agent runtime. The integrated
repository installs their original namespaces with one command. Python 3.11 or
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

Required for normal configured operation:

- a compatible Crystal-DB SQLite/index with exportable CIF records and the
  matching BGE-M3 service, normally an LM Studio-compatible endpoint;
- an explicit finite QLIP design space; and
- Gurobi with a usable licence.

Ollama is required only when an Ollama-backed reasoning configuration is
selected. Model-free replay does not require LM Studio or Ollama. Building a
new Crystal dataset requires a Materials Project API key and the matching
embedding service. CASTEP, Slurm, VESTA, and SCA MLIP models/weights are
optional scientific integrations.

The historical canonical regulator POT library is not redistributed because
its redistribution provenance is unresolved. The source-faithful software that
consumes it is included. Historical regulator-dependent production workflows
must supply an approved root through `SKILL_LOOP_REGULATOR_SPP_ROOT` (or the
existing explicit workflow configuration field). Source-supported workflows
that fit or use their own lawfully obtained POTs, including the safe fixture
pipeline, remain available. The nine bundled QLIP POTs are limited fixtures and
are not a substitute for the historical 3,388-pair regulator.

Start from configs/examples/srtio3_production.json and run:

~~~shell
llm-csp run --config configs/examples/srtio3_production.json --output ./runs --json
~~~

Production corpora, embeddings, broad POT trees, model weights, and benchmark
outputs are not bundled and are not downloaded automatically.

## Unified source-runtime setup

1. Install the repository with `python -m pip install -e ".[validation]"`.
2. Configure Gurobi using its standard licence mechanism.
3. Copy `.env.example` to `.env` and configure the independent Crystal
   embedding and Skill-Loop reasoning endpoints.
4. Set `MP_API_KEY`, preview the recovered dataset request, and build a local
   Crystal-DB:

   ```console
   python scripts/crystal_db/grab_data.py --requests data/crystal_db/requests/default_mp_requests.txt --dry-run
   python scripts/crystal_db/grab_data.py --requests data/crystal_db/requests/default_mp_requests.txt
   ```

5. Point `CRYSTAL_DB_DATA_ROOT` at `data/crystal_db/runtime` (or
   `CRYSTAL_DB_PATH` directly at the generated database), set
   `SKILL_LOOP_REGULATOR_SPP_ROOT` when running a regulator-dependent workflow,
   run the subsystem tests/readiness checks, then use the
   original `sokllm` CLI. `sokllm --help`, `sca --help`, `spp-maker --help`,
   and `llm-csp --help` expose the preserved source commands.

The default Skill-Loop MCP processes are the bundled
`crystal_db.mcp.server`, `spp_maker_mcp.server`, and `qlip.mcp.server`; no
sibling checkout is required. LM Studio and Ollama are optional for
model-free fixture replay. CASTEP, Slurm, VESTA, and SCA MLIP models remain
optional source-supported externals.

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
