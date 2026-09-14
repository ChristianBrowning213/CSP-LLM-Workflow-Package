# Changelog

## Unreleased

- Development recovery branch. No v0.2 architecture is currently defined.

## 0.1.0

### Added

- Deterministic request-to-CIF workflow integrating Crystal-DB retrieval,
  request-specific SPP guidance, and QLIP integer-programming CSP.
- Structured workflow results, stage diagnostics, artifacts, and provenance.
- Public CLI for production runs and an offline installation/workflow smoke.

### Scientific safeguards

- Explicit finite design-space validation and required-pair POT coverage.
- Embedding model/version/dimension compatibility checks before ranking.
- No silent solver, retrieval, POT, validation, or scientific-data fallback.

### Packaging

- Integrated `llm-csp` distribution plus independently buildable Crystal-DB
  and QLIP distributions, all at version 0.1.0.
- Runtime chemistry tables regenerated deterministically from pinned sources.
- MIT licensing and retained upstream QLIP attribution.

### Validation

- Lazy `llm_csp.validation` adapter for general and family/topology validation.
- Optional `validation` extra pinned to MIT-licensed SCA 0.1.1.

### External requirements

- Production Crystal-DB corpus/index and compatible embedding backend.
- Lawfully sourced POT library, plus a Gurobi runtime and usable licence for
  scientific QLIP solving.
- External third-party ML packages, weights, and datasets for optional SCA ML
  evaluators.

### Known limitations

- No production crystal corpus or broad scientific POT library is bundled.
- Real QLIP runs require an explicit finite design space and Gurobi.
- Agentic orchestration and benchmark/paper campaign data are not included.
