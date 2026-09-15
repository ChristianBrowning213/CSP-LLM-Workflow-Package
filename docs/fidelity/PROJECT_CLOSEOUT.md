# Project Closeout — Source-Fidelity Recovery

## Final states

```text
COMMIT_SELF_CONTAINED
SOURCE_FIDELITY_RESTORED
READY_WITH_DOCUMENTED_EXTERNAL_REQUIREMENTS
PROJECT_COMPLETE
```

## Final commit

```text
5eeb6527c433a697b188b256a4c20d4fb41cb234
```

on branch `recovery/source-fidelity`, one commit ahead of the Ticket 34
remediation commit `9be55e904078d4ad33a595f142352f64b0cd5f85`. The extra
commit is a correction found during clean-room verification (see below),
not a new development phase.

## Artifact hashes

Built from a clean detached worktree at the final commit above (no
uncommitted supervisor files copied in):

- Wheel `llm_csp-0.2.0.dev0+fidelity-py3-none-any.whl`: SHA-256
  `34faa5925f6a8f91be04630730bef355a0c7378c86dff0a28a783cfb4a190564`
- Sdist `llm_csp-0.2.0.dev0+fidelity.tar.gz`: SHA-256
  `f4b17fb010de2b24d32f2f87cc6d799d06e39f82de179a9ffbc8539bc95cb150`

## Ticket 33 blockers — all fixed and independently re-verified

1. Incomplete SPP packaging (colliding `spp_maker_qlip` shim) — fixed.
2. Missing Skill-Loop schema (`schema.skillcard.v1.json`) — fixed.
3. Crystal bootstrap files missing from sdist — fixed.
4. Historical/sibling runtime path assumptions (`github_parent` corpus
   registry, `paper_final_v1.py` sibling dereference) — fixed.
5. Canonical regulator POT provenance boundary — honestly documented, not
   silently resolved (it cannot be, per the provenance-blocked
   classification).

Full evidence for each: `docs/fidelity/RECOVERY_STATUS.md` and
`docs/fidelity/RELEASE_READINESS_AUDIT.md`, "Ticket 34" sections.

## One correction made during clean-room verification

The `sca` console script crashed on a plain `pip install llm-csp`
(`ModuleNotFoundError: No module named 'typer'`) because `sca/cli.py`'s
unconditional imports (`pandas`, `typer`, `click`, `rich`) lived only in the
optional `validation` extra, not base dependencies. This was not one of
Ticket 33's five listed defects; it was found independently during Ticket
34's own mandatory CLI-verification gate. Fixed by moving exactly those
four packages to base `dependencies` (commit `5eeb6527`), delegated to a
bounded swarm worker, independently reviewed and re-verified (fresh build,
clean extras-free venv, all 7 console/MCP entry points working, `pip check`
clean) before being committed.

## Tests

- **Root suite** (`tests/`): 178 passed, 5 skipped — exact match to the
  pre-Ticket-34 reference, no regression.
- **Crystal-DB**: covered by the root suite (no separate package-level test
  directory exists).
- **SPP-Maker-QLIP** (`packages/spp_maker_qlip/tests`): 111 passed, 18
  failed — exact match to the Ticket 33 baseline. 17 failures require
  pre-published external material systems tied to the blocked regulator
  POT library; 1 is a known MCP schema-snapshot environment-drift nuance.
- **QLIP** (`packages/qlip/tests`): 242 passed, 13 failed — exact match to
  the Ticket 33 baseline. All 13 trace to the pre-existing, already-
  documented external `QLIP_SCAFFOLD_CORPUS_ROOT` data dependency.
- **SCA** (`tests/integration/validation/test_sca_adapter.py`): 4 passed, 0
  failed, including the family-topology test.
- **Skill-Loop-CSP** (`packages/skill_loop_csp/tests`, live-LLM tests
  marker-deselected): 1213 passed, 118 failed, 7 skipped, 16 deselected
  (1354 total items — identical total to the Ticket 33 baseline's
  1234+98+22=1354). The pass/fail split differs numerically from the
  documented baseline; every failure was individually categorized and
  traced to one of: untracked historical paper-run artifacts under
  `packages/skill_loop_csp/artifacts/...` (the same category Ticket 33
  already excluded), the missing optional `megnet` package, the missing
  bootstrapped Crystal database (requires a live Materials Project
  bootstrap), or a "repository root discovery" helper in legacy
  paper-reproduction tooling that only resolves correctly from a real dev
  checkout path (tripped in this session because of how this environment's
  editable install resolves `__file__`). None of the 118 failures were
  traced to the remediation commit's actual changes.
- **Skill-Loop model-free fixture/replay path**: 10 passed, 0 failed,
  concretely exercising Planner, Run Manager, Orchestrator, Evaluator
  evidence, and an ordered tool-execution step sequence.

## Clean-room end-to-end results

- **SPP → QLIP → Gurobi**: the source SrTiO3 fixture
  (`tests/integration/spp/test_srtio3_qlip.py`) uses a real
  `pyo.SolverFactory("gurobi")` (not mocked) and is part of the passing
  root 178; the canonical objective value `4.883033620558714` was
  previously confirmed exact in Ticket 26/33 and the source computation
  path is unchanged by Ticket 34.
- **Crystal bootstrap**: from an extracted sdist, dry-run parses to
  well-formed JSON (`api_key_present: false`); live build without
  `MP_API_KEY` fails explicitly with exit code 2 and a clear message, not
  an unhandled traceback.
- **SCA**: 4/4 fixture/topology tests pass
  (`tests/integration/validation/test_sca_adapter.py`).
- **Skill-Loop replay**: 10/10 model-free fixture/replay tests pass,
  exercising the full agentic chain (Planner/Run Manager/Orchestrator/
  Evaluator/tool execution) without a live LLM.
- **MCP surfaces**: Crystal-DB (6/6), SPP-Maker (4/4), and QLIP (6/6) tool
  registrations match their recorded snapshots exactly; Skill-Loop's
  bundled-MCP-modules wiring test passes.
- **CLI surfaces**: all 7 console/MCP entry points
  (`llm-csp`, `crystal-db`, `crystal-db-mcp`, `spp-maker`, `spp-maker-mcp`,
  `sca`, `sokllm`) work from a clean install with no extras.

## External requirements (final, definitive list)

Required for normal configured operation:

- Gurobi, with a usable licence.
- An LM Studio-compatible BGE-M3 embedding endpoint (Crystal-DB
  retrieval / data bootstrap).

Required only for an Ollama-backed reasoning configuration:

- Ollama. (Model-free replay requires neither LM Studio nor Ollama.)

Required to build a Crystal dataset:

- A Materials Project API key.

Required only for historical regulator-dependent production workflows:

- An approved canonical regulator POT library, supplied via
  `SKILL_LOOP_REGULATOR_SPP_ROOT` or the existing explicit workflow
  configuration field. Not redistributed; redistribution provenance is
  unresolved. The 9 bundled QLIP POT fixtures are limited fixtures, not a
  substitute.

Optional scientific integrations:

- CASTEP, Slurm, VESTA, SCA optional MLIP models/weights, `megnet`.

## Remaining provenance boundary

The historical canonical regulator POT library (3,388-pair) remains a
`REQUIRED_PROVENANCE_BLOCKED_ASSET`: not redistributed because its
redistribution provenance is unresolved. This is the sole reason release
status is `READY_WITH_DOCUMENTED_EXTERNAL_REQUIREMENTS` rather than
`READY_FOR_RELEASE_CANDIDATE`. Software fidelity is complete and separate
from this historical data-availability boundary:

- The source-faithful software that consumes the regulator library is
  fully included and restored.
- The library itself is not copied, fabricated, or silently substituted.
- Workflows that require it must supply an approved root through the
  existing configuration mechanism.
- Workflows that generate/fit their own POTs from evidence the user is
  entitled to use, including the safe fixture pipeline, remain fully
  available and were exercised end-to-end above.

## Original repositories and v0.1

- The five original source repositories (Crystal-DB, SPP-Maker-QLIP, qlip,
  Structured_Crystal_Analyser, Skill-Loop-CSP) were not touched this
  session — no commands were run against them, only prior audits (Ticket
  33) inspected their HEADs.
- `v0.1.0` unchanged: dereferences to `2dbf5e8852dc62c42d97385bc96ea90166d0fc74`
  (unchanged from Ticket 33's verification; not re-touched this session).

## Git

- Final commit: `5eeb6527c433a697b188b256a4c20d4fb41cb234` on
  `recovery/source-fidelity`.
- Not merged to `main`.
- Not yet pushed — push requires explicit user confirmation (see the
  session's final report).

## Project conclusion

```text
PROJECT_COMPLETE
```

Every Ticket 34 acceptance requirement is genuinely satisfied: all five
Ticket 33 blockers are fixed and independently re-verified from a clean
detached worktree; one additional defect found during verification was
fixed and independently re-verified under the same correction workflow;
there is no test regression attributable to the remediation; and the only
remaining limitation is the explicitly documented, provenance-blocked
historical regulator asset. Future work on this archive is ordinary
feature/research work, not another recovery-project phase.
