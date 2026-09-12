# Reproducibility

The public no-external-assets software smoke is:

~~~shell
llm-csp demo --output ./runs
~~~

It deterministically checks configuration, a newly authored synthetic
retrieval fixture, required-pair derivation, QLIP request construction, and the
lazy validation boundary. It performs no solve and is explicitly not a
scientific prediction.

The historical migration regression used a fixed SrTiO3 request/design space,
six now-excluded POT assets, one solver thread, seed zero, a 30-second limit,
and unit SPP weights. Its validated objective was `4.883033620558714`. This is
retained only as provenance; it is not a runnable bundled release test.

An authorized scientific reproduction must preserve:

- the Crystal-DB corpus/CIFs and their hashes and redistribution authority;
- text/index engine, model identity/version, dimension, and embedding backend;
- every external POT file and its hash;
- Gurobi version and licence/runtime environment;
- the explicit design space and solver controls; and
- any separately authorized compatible validation backend and model weights.

Set `LLM_CSP_EXTERNAL_POT_ROOT` to a lawful compatible SrTiO3 POT root to run
tests marked `requires_external_scientific_assets`. The repository supplies no
scientific POTs, corpus, embeddings, production database, model weights, or
benchmark results and downloads none of them.

The element, radii, and ionic-radii tables are generated lazily in memory from
the exact dependency versions recorded in QLIP provenance. Full-table hashes
guard equality with the former canonical values.
