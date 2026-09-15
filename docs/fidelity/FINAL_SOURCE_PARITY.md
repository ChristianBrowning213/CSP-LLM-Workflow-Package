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

## Ticket 34 — final remediation parity

Overall: `SOURCE_FIDELITY_RESTORED` /
`READY_WITH_DOCUMENTED_EXTERNAL_REQUIREMENTS`.

Remediation commit `9be55e904078d4ad33a595f142352f64b0cd5f85` plus one
correction commit `5eeb6527c433a697b188b256a4c20d4fb41cb234` (unconditional
`sca` CLI imports moved from the optional `validation` extra to base
dependencies — a genuine defect found during clean-room verification, not
one of Ticket 33's five, fixed under the correction workflow and
independently re-verified).

| Subsystem / surface | State | Evidence |
|---|---|---|
| SPP-Maker-QLIP package namespace | `EXACT` (was `PATH_ONLY_DIFFERENCE` / colliding) | Installed `spp_maker_qlip` resolves to the full 5-module source package (incl. `required_pair_extraction`), not the 2-module Skill-Loop compatibility shim. |
| Skill-Loop skill-card schema | `EXACT` | `schema.skillcard.v1.json` present in the installed wheel, SHA-256-identical to source. |
| Crystal bootstrap sdist reconstructibility | `EXACT` | Extracted-sdist dry-run parses; live build without `MP_API_KEY` fails explicitly (exit 2). |
| Skill-Loop corpus registry sibling dependency | `EXACT` (was `RUNTIME_SIBLING_DEPENDENCY`) | Zero `github_parent` entries remain (0 of 21); registry resolves from the installed package's own location or explicit config; imports/registry-load succeed with no sibling repositories present. |
| Canonical ICSD regulator | `EXTERNAL_SERVICE_REQUIRED` (unchanged) | Still hash-frozen, still not redistributed; boundary now explicitly documented in README/`external_assets.md` and wired through `SKILL_LOOP_REGULATOR_SPP_ROOT`. |
| `sca` console script | `EXACT` (new defect found + fixed) | Was broken (`ModuleNotFoundError: typer`) on a plain install; fixed by moving `pandas`/`typer`/`click`/`rich` to base dependencies; now works from a clean, extras-free install. |
| MCP tool surfaces (Crystal-DB, SPP-Maker, QLIP) | `EXACT` | Installed server tool registrations diffed byte-for-name against `docs/fidelity/*_mcp_surface.json`; zero drift, zero missing, zero invented across 16 tools. |
| Skill-Loop bundled MCP wiring | `EXACT` | `test_skill_loop_defaults_launch_bundled_mcp_modules` passed against the installed package. |
| Root regression suite | `EXACT` | 178 passed, 5 skipped — identical to the pre-Ticket-34 reference. |
| QLIP / SPP-Maker-QLIP subsystem suites | `EXACT` | 242p/13f and 111p/18f respectively — identical counts to the Ticket 33 baseline; all failures trace to the same already-documented external scaffold-corpus/regulator-POT gaps. |
| Skill-Loop-CSP subsystem suite | `PATH_ONLY_DIFFERENCE` (numeric split differs, total item count identical) | 1213p/118f/7s/16 deselected vs. documented 1234p/98f/22s (1354 total either way). All 118 failures traced to known external-artifact/optional-dependency categories or a test-environment path-resolution quirk, not to the remediation; none newly introduced by source changes. |

Scientific outcome: `NO_SCIENTIFIC_BEHAVIOR_CHANGE` (unchanged from
Tickets 27-32; Ticket 34 was packaging/path remediation only, per its own
"do not add functionality, do not redesign anything" constraint).
