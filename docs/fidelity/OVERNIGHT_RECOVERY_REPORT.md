# Overnight recovery report — Tickets 27–32

## 1. Final commit

- Starting commit: `b917f5470f0254601bd213c8033bb02bd60deb4a`
- Ending commit: the recovery commit containing this report (resolve with
  `git rev-parse HEAD`)
- Branch: `recovery/source-fidelity`
- Remote synchronization: branch matched `origin/recovery/source-fidelity` at
  start; recovery commit is local and was not pushed.

## 2. Ticket status

- T27: `SPP_POT_ASSETS_BLOCKED_PROVENANCE`
- T28: `QLIP_SOFTWARE_RESTORED_ASSETS_BLOCKED`
- T29: `CRYSTAL_DB_BOOTSTRAP_READY`
- T30: `SCA_RESTORED`
- T31: `SKILL_LOOP_RUNTIME_RESTORED`
- T32: `SOURCE_FIDELITY_RESTORED_DATA_BOOTSTRAP_REQUIRED`

## 3. Restored systems

Crystal-DB software and MP bootstrap, SPP-Maker/SPP-Maker-QLIP, full tracked
QLIP software/resources, complete distributable SCA, and the original
Skill-Loop execution runtime are present under their original namespaces.
Canonical broad POT and Crystal database bytes remain outside the archive.

## 4. External requirements

- Gurobi and licence
- Materials Project API key for local Crystal dataset creation
- LM Studio BGE-M3 endpoint for Crystal text embeddings
- LM Studio or Ollama reasoning endpoint for optional live agents
- provenance-cleared canonical regulator POT root
- provenance-cleared specialist scaffold/corpus data when those workflows run
- optional CASTEP, Slurm, VESTA, SCA MLIP packages/weights, and Robocrys

## 5. Provenance blocks

- Historical `phase6_mp_10k.db` (Materials Project-derived, export disabled)
- `icsd_broad_regulator_v1` (external input lineage, no redistribution grant)
- MP-derived NASICON/specialist corpora
- historical paper outputs, benchmark dumps, figures, and untracked OMatG

## 6. Source tests

| Source suite | Passed | Failed | Skipped | Classification |
|---|---:|---:|---:|---|
| Crystal-DB | 175 | 0 | 1 | Skip: blocked historical database. |
| SPP-Maker-QLIP | 111 | 18 | 0 | Failures: untracked pre-published outputs and one dependency-generated schema snapshot difference; direct scientific parity passed. |
| QLIP | 254 | 6 | 0 | Failures: blocked specialist corpus, historical artifacts, and sibling-discovery assertions. |
| SCA | 185 | 6 | 0 | Failures: excluded external benchmark manifests/CSVs. |
| Skill-Loop-CSP | 1234 | 98 | 22 | Failures/skips: blocked databases/corpora, optional models, excluded paper/benchmark artifacts, and source sibling-layout assertions. All 1,354 tests remain represented. |
| Retained unified archive | 178 | 0 | 5 | Current root suite. |

No assertions were weakened to make a source suite green. Focused Skill-Loop
runtime-chain tests passed 54/54 and focused SPP regeneration/package tests
passed 18/18. Compile-all also exposed the authority revision's pre-existing,
unregistered experimental QLIP `symmetry.py` syntax defect; byte comparison
proved the archive did not introduce it.

## 7. Cross-system E2E

| Edge | Result |
|---|---|
| Skill-Loop → Crystal | Real server launch PASS; bounded DB reports missing BGE-M3 embedding space as designed. |
| Skill-Loop → SPP | Real MCP `spp.run_pipeline` PASS on two safe CIFs. |
| SPP → QLIP | Calibration and final QLIP bundle PASS. |
| Skill-Loop → QLIP | Real validate and solve PASS; SrTiO3 status `OPTIMAL`. |
| Skill-Loop → Crystal novelty | PASS using bounded MP database fingerprint index. |
| QLIP → SCA/validation | NaCl/general and topology parity PASS in retained suite. |

## 8. Model runtime

LM Studio configuration/discovery and Ollama configuration/native endpoint
support are restored. Both local services answered discovery/status endpoints.
The bounded LM Studio `/api/v1/chat` smoke timed out, so no live proposal chain
was accepted. No Ollama generation was launched. Model-free replay passed.

## 9. Materials Project bootstrap

Request specification recovered: yes. Bootstrap script ready: yes. Live MP
test: yes—one requested record retrieved, ingested, fingerprinted, sequenced,
and structurally queried with zero build errors. The full 10k request was not
started.

## 10. No-sibling-repo test

`PASS` for the active installed runtime. Wheel imports and real MCP module
launches resolve inside the unified package. Frozen historical campaign/test
references are recorded as non-runtime source evidence.

## 11. Scientific behavior

`NO_SCIENTIFIC_BEHAVIOR_CHANGE`.

Only packaging, resource inclusion, bootstrap orchestration, path relocation,
and documentation changed. Solver objectives, SPP mathematics, retrieval,
novelty, SCA metrics, crystallographic constraints, and agent scientific
policies were not changed.

## 12. Git safety

- `main` unchanged at `2dbf5e8852dc62c42d97385bc96ea90166d0fc74`.
- `v0.1.0` unchanged at its recorded target
  `2dbf5e8852dc62c42d97385bc96ea90166d0fc74`.
- All five original source repositories remain at their starting revisions;
  the only pre-existing source dirt is untracked Skill-Loop OMatG.
- No release, tag, push, publish, or merge was performed.
