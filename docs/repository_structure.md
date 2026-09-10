# Repository structure

Directory ownership is intentionally separated as follows:

```text
src/llm_csp/          high-level orchestration and public workflow
packages/crystal_db/  retrieval/database subsystem
packages/qlip/        CSP solver subsystem
configs/              user-facing and example configuration
examples/             minimal supported usage examples
tests/unit/           isolated package behaviour
tests/integration/    interactions between components
tests/e2e/            complete supported workflow tests
data/demo/            tiny distributable test/demo structures only
docs/                 supported user/developer documentation
scripts/              small supported maintenance/bootstrap scripts only
```

Experimental, paper-specific, audit, benchmark, migration, repair, and historical scripts or outputs do not belong in this repository. They remain in the research workspaces unless a later migration ticket identifies a component as required by a supported runtime workflow.

