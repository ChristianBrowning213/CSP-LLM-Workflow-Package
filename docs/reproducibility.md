# Reproducibility

The canonical offline case is:

~~~shell
llm-csp demo --output ./runs
~~~

It fixes the SrTiO3 request and design space, deterministic retrieval fixture,
six bundled POT files, one solver thread, zero seed, 30-second limit, and unit
SPP regulator/outer weights. It uses real QLIP solving and invokes the
validation boundary. SCA is not part of the public installation metadata; with
no separately authorized compatible backend, candidate generation is retained
and validation is recorded as unavailable.

The run manifest records the workflow schema, complete request/configuration,
source workflow commit, package versions, validated SCA contract revision, retrieval
identity, required pairs, POT hashes, QLIP request and status, solver objective,
candidate CIF hash, independent SPP score, and validation result.

Production reproduction additionally requires pinning and preserving:

- the Crystal-DB file and its hash;
- text/index engine, view, model, model version, and embedding dimension;
- the embedding server/model build;
- every external POT file and its recorded hash;
- Gurobi version and licence/runtime environment;
- the exact separately authorized validation backend revision and any
  explicitly enabled optional model weights.

Scientific corpora, broad fitted-potential collections, embedding models,
production databases, and benchmark results are not bundled. The package does
not download them. The recorded SCA revision is compatibility provenance, not
an instruction or permission to install that unlicensed repository.
