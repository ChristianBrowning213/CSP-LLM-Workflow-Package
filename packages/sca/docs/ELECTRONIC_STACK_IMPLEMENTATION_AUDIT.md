# Electronic Stack Implementation Audit

Authoritative source: repository-root `eletronic_stack.md` (the filename differs from the
`eletronoc stack.md` spelling in the request). This audit records repository state before the
advanced-stack implementation. `PARTIAL` means useful implementation exists but the ticket's
contract or integration is incomplete.

| ticket | status_before | existing_files | gap | planned_action |
|---|---|---|---|---|
| T0.1 | PARTIAL | `artifacts/paper_full_sca_v1/input/PAPER_CANDIDATE_MANIFEST.csv` | Existing 31-case campaign is not the required paper-16 set; Li2FeO3 lives in a separate traceable paper run | Freeze a 16-row manifest referencing the original generated CIFs and intent sources |
| T0.2 | PARTIAL | `artifacts/paper_full_sca_v1/input/INPUT_HASH_MANIFEST.csv`, `initial/INITIAL_RESULTS.csv` | No paper-16 baseline in the required schema/location | Build CSV/JSON/Markdown baseline from immutable inputs and verify hashes |
| T1.1 | PARTIAL | `sca/backends.py`, `sca cli verify-backends` | Readiness lacks the required normalized states and file outputs | Extend readiness records and CLI CSV/JSON/Markdown output |
| T1.2 | PARTIAL | `sca/evaluators/chgnet.py`, `sca/evaluators/mlip.py`, registry, benchmark runner, prior campaign outputs | Required static schema/report campaign is not integrated for paper-16 | Reuse evaluators and add honest structured campaign writer |
| T1.3 | PARTIAL | `MlipEnsembleBenchmarkEvaluator`, prior `MLIP_ENSEMBLE_RESULTS.csv` | Existing evaluator averages incompatible raw model energies and exposes a stability flag | Replace with within-model rank consensus campaign analysis; never emit stability |
| T2.1 | PARTIAL | `sca/evaluators/chgnet_relax.py`, `scripts/run_paper_chgnet_relaxation.py`, prior real CHGNet campaign | Configuration/provenance and paper-16 integration incomplete | Add frozen configuration and campaign orchestration with structured unavailable results |
| T2.2 | PARTIAL | CHGNet evaluator writes separate CIFs; prior hashes exist | Raw/relaxed hash preservation is not enforced as a generic contract | Add hash verification and artifact separation tests |
| T2.3 | MISSING | Prior one-off `INITIAL_VS_RELAXED.csv` uses StructureMatcher distances | No reusable self-transition contract with lattice/angle/assignment diagnostics | Add generic periodic structure-transition analysis |
| T3.1 | REQUIRES_INTEGRATION | pre-DFT, geometry, symmetry, intent and family/topology evaluators | No reusable post-relax aggregate | Re-run the relevant SCA checks through a transition/retention evaluator |
| T3.2 | MISSING | Prior one-off post-relax script/report | No registered `relaxation_intent_retention` evaluator or required status semantics | Implement and register evaluator with documented policy |
| T4.1 | PARTIAL | Prior 31-case paper reports | No paper-16 summary with honest denominators | Add CSV/JSON/Markdown summary builder |
| T4.2 | PARTIAL | Prior paper figure scripts and PNGs | No reusable paper-16 figure generator or source-data contract | Add real-data-only PNG/PDF generator with insufficiency report |
| T5.1 | MISSING | None | No DFT calculation schema | Add versioned Pydantic DFT schemas |
| T5.2 | MISSING | None | No explicit RELAX/STATIC enum | Add calculation-type enum, excluding later calculation types |
| T5.3 | MISSING | None | No DFT result schema | Add result and execution schemas with structured failures |
| T6.1 | MISSING | Evaluator base patterns only | No generic DFT adapter | Add prepare/validate/parse/output-validation abstraction |
| T6.2 | NOT_EXECUTABLE_IN_CURRENT_ENVIRONMENT | No DFT executable/configuration found in repository audit | No adapter; no licensed executable confirmed | Implement a deterministic CASTEP adapter and frozen synthetic fixtures; report live execution blocked |
| T6.3 | MISSING | General artifact/provenance patterns | No reproducible prepared calculation directory | Write calculation, input/hash, engine inputs, environment, and settings fingerprint |
| T7.1 | MISSING | None | No Slurm renderer | Add typed Slurm configuration and deterministic renderer |
| T7.2 | MISSING | Existing Typer CLI conventions | No DFT CLI family | Add `sca dft prepare` |
| T7.3 | NOT_EXECUTABLE_IN_CURRENT_ENVIRONMENT | No local `sbatch` | Submission architecture absent | Add `submit`, exact execution records, and structured unavailable state |
| T7.4 | NOT_EXECUTABLE_IN_CURRENT_ENVIRONMENT | No local `squeue`/`sacct` | Status normalization absent | Add normalized status collection with injectable command runner |
| T7.5 | MISSING | CSV/JSONL writer patterns | No backend collection route | Add `collect` and result writers |
| T8.1 | MISSING | General evaluator errors | No DFT failure taxonomy | Add explicit failure enum and parser classification |
| T8.2 | MISSING | None | No retry provenance contract | Add optional parent/change/reason schema; never mutate settings silently |
| T9.1 | MISSING | Existing crystallographic evaluators and prior one-off post-relax script | No generated/MLIP/DFT transition analysis | Add reusable post-DFT validation built on structure transition and SCA checks |
| T9.2 | MISSING | None | No DFT relaxation status semantics | Add explicit status enum/evaluator and documentation |
| T10.1 | MISSING | ALIGNN predicted formation-energy evaluator only | No physical DFT reference-energy contract | Add elemental reference schema and formation-energy calculation |
| T10.2 | MISSING | Predicted-hull provenance checks are unrelated | No strict DFT energy compatibility guard | Add tri-state compatibility fingerprint comparison |
| T11.1 | PARTIAL | `benchmarks/assets/hull_reference_bundles.csv` is surrogate-oriented | No genuine DFT hull bundle schema | Add explicit DFT hull entry/bundle schema |
| T11.2 | MISSING | `PredictedHullBenchmarkEvaluator` exists for surrogate energies | No distinct compatible DFT phase diagram route | Add separate pymatgen DFT hull analysis |
| T11.3 | MISSING | Existing surrogate threshold reporting | No configurable descriptive DFT hull bands | Add stored thresholds while retaining raw E_hull |
| T12.1 | MISSING | Candidate sources exist | No paper-6 DFT campaign manifest | Derive paper-6 manifest from frozen paper-16 rows |
| T12.2 | NOT_EXECUTABLE_IN_CURRENT_ENVIRONMENT | No DFT executable or Slurm scheduler confirmed | Live smoke cannot run locally | Prepare campaign architecture/config; test end-to-end with frozen synthetic outputs |
| T12.3 | NOT_EXECUTABLE_IN_CURRENT_ENVIRONMENT | None | Expansion requires successful real six-case campaign | Leave explicitly blocked pending real Barkla results, not silently complete |
| T13.1 | MISSING | Modular benchmark runner/report writers | No unified advanced entrypoint or complete missing-layer representation | Add `analyse-crystal --level advanced` and machine/human reports |
| T13.2 | PARTIAL | Existing records preserve many dimensions | Some prior ranking code mixes evidence tiers | Add independent scientific-quality dimensions; no universal quality/stable boolean |
| T14 | MISSING | Prior MLIP figures only | No real-result-only advanced/DFT figure contract | Add source-data-first generator and honest unavailable report |
| T15 | MISSING | Existing unit/mocked optional-backend suite | Required DFT/transition/advanced tests absent | Add frozen synthetic fixtures and full contract tests; no live DFT/GPU |
| T16 | PARTIAL | README and evaluator/backend documentation | Required scientific distinctions and DFT workflow docs absent | Add five requested documents and update evaluator/README integration |

## Reuse decisions

- Keep `BenchmarkRecord` / `BenchmarkEvaluatorResult`, evaluator registry, manifest runner, and
  existing crystallographic evaluators as the integration foundation.
- Keep CHGNet, MatGL/M3GNet, MACE, SevenNet and ALIGNN adapters; improve their orchestration and
  readiness reporting rather than reimplementing the models.
- Keep `predicted_hull` explicitly surrogate-only. Genuine compatible DFT hull analysis is a
  separate `sca.dft.analysis.hull` route.
- Treat prior real CHGNet outputs as provenance-bearing historical results, not as fabricated new
  paper-16 results. A new campaign may reuse values only when input hash and configuration match.

## Final ticket disposition

The authoritative final status ledger is
`artifacts/electronic_stack/IMPLEMENTATION_PROGRESS.md`. All implementation tickets are complete
except runtime/data outcomes that cannot be manufactured:

- T12.2 is `BLOCKED_ENVIRONMENT`: the six inputs are prepared and synthetic traversal is tested,
  but no CASTEP/VASP or Slurm executable exists locally.
- T12.3 is `BLOCKED_ENVIRONMENT`: expansion must wait for a reviewed real six-case campaign.
- T14 is `BLOCKED_MISSING_DATA` only for the optional DFT paper figure; the real-result MLIP figure
  is complete. There are no real DFT values to plot.
- Real paper formation energies and E_hull remain `BLOCKED_MISSING_DATA` at runtime because no
  compatible competing-phase/elemental CASTEP reference bundle exists. Their implementations and
  compatibility tests are complete.
