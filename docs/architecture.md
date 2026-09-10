# Architecture

LLM-CSP is organized as a monorepo with three logical Python packages:

- `llm_csp` provides high-level deterministic orchestration and the supported public workflow.
- `crystal_db` will provide crystal structure storage, metadata, provenance, and retrieval capabilities.
- `qlip` will provide constraint-based crystal structure prediction capabilities.
- `llm_csp.spp` converts retrieved CIF evidence into formula-required
  QLIP-compatible POT roots, or selects an exact canonical subset from an
  explicitly configured external POT library. It reports incomplete pair
  coverage rather than fabricating missing potentials.
- `llm_csp.validation` is the stable, lazy adapter between generated CIFs and
  the external Structured Crystal Analyser package. It normalizes general and
  family-topology results without copying or reimplementing SCA science.

The intended workflow is researcher intent → Crystal-DB retrieval → evidence and statistical guidance → QLIP prediction → validation → generated structure and provenance.

`llm_csp.workflow.run_csp_workflow` coordinates those installed boundaries. It
owns explicit request policy, stage ordering, failure propagation, regulator
selection, QLIP request assembly, and compact run manifests. Similarity,
statistical-potential fitting, MILP science, and validation metrics remain in
their component packages. Agentic orchestration is outside this layer.
