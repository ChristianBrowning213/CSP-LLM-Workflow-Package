# Final source parity — Tickets 27–32

Overall: `SOURCE_FIDELITY_RESTORED_DATA_BOOTSTRAP_REQUIRED`.

| Subsystem / surface | State | Evidence |
|---|---|---|
| Crystal-DB code, CLI, MCP | `PATH_ONLY_DIFFERENCE` | Source code/package restored; non-editable wheel import and six MCP tools verified. |
| Historical Crystal database | `EXTERNAL_SERVICE_REQUIRED` | MP-derived snapshot cannot be redistributed. Recovered request and live one-record rebuild passed. |
| SPP-Maker code and output bytes | `EXACT` | Source parity and fixture regeneration/package tests passed. |
| Canonical ICSD regulator | `EXTERNAL_SERVICE_REQUIRED` | Hash-frozen, but redistribution provenance is absent. |
| QLIP software and six-tool MCP surface | `PATH_ONLY_DIFFERENCE` | Full tracked source restored; validate and Gurobi solve succeeded through real MCP. |
| QLIP specialist corpus | `EXTERNAL_SERVICE_REQUIRED` | MP-derived/untracked source data not copied. |
| QLIP experimental symmetry module | `KNOWN_SOURCE_DEFECT` | Authority revision contains the same `del[0]` syntax error; it is not in the registered production constraint path and was not altered. |
| SCA distributable package | `EXACT` | Scientific revision unchanged; licensing/package-only revision bundled. |
| SCA weights/benchmark datasets | `EXTERNAL_SERVICE_REQUIRED` | Optional upstream assets remain external. |
| Skill-Loop-CSP runtime | `PATH_ONLY_DIFFERENCE` | Exact runtime/prompts/schemas restored; MCP defaults rewired to bundled namespaces. |
| Frozen historical campaign references | `KNOWN_SOURCE_DEFECT` | Some source tests require excluded paper outputs or old sibling-layout fixtures; active runtime defaults do not. |

## Cross-system gate

- Skill-Loop → Crystal: real MCP launched. Status and `csp_pack` truthfully
  reported `missing_embedding_space` for the bounded MP database; novelty ran
  against its fingerprint index and returned a valid source response.
- Skill-Loop → SPP and SPP → QLIP: real `spp.run_pipeline` processed two safe
  CIFs, generated a byte-valid POT, calibrated it, and produced the final QLIP
  bundle.
- Skill-Loop → QLIP: real MCP validation returned valid; real Gurobi solve for
  the source SrTiO3 fixture returned `OPTIMAL` with objective
  `4.883033620558714`.
- QLIP → SCA/validation: retained NaCl and topology adapter parity tests passed.
- Model-free proposal/plan → manager → evaluator → orchestrator replay: 54
  selected source tests passed.

## No-sibling result

`PASS` for installed imports and the active Skill-Loop/MCP chain. A clean
non-editable wheel loaded `crystal_db`, `spp_maker`, `spp_maker_qlip`, `qlip`,
`sca`, and `sok_llm_orchestrator` from the wheel environment. Runtime MCP
defaults contain module commands only and no sibling cwd. Remaining sibling
text is confined to frozen historical campaign provenance/tests, not active
server selection or imports.

Scientific outcome: `NO_SCIENTIFIC_BEHAVIOR_CHANGE`.
