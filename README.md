# LLM-CSP

LLM-CSP provides a retrieval-guided, solver-backed workflow that converts
structured crystallographic requests into evidence-conditioned CSP runs with
explicit provenance and validation.

High-level architecture:

```text
Researcher intent
→ Crystal-DB retrieval
→ evidence / statistical guidance
→ QLIP crystal structure prediction
→ validation
→ generated structure + provenance
```

The supported deterministic API is:

```python
from llm_csp.workflow import run_csp_workflow
```

This is a scientific workflow kernel, not autonomous materials discovery or an
agentic orchestrator. Full production retrieval requires an external compatible
Crystal-DB index and matching embedding backend; broad POT libraries, Gurobi,
and SCA retain their documented external boundaries. See `docs/workflow.md`.
