# Optimization Method

This tranche adds a conversational optimization loop on top of the existing CSP branch.

Flow:

1. Chemist request intake.
2. Critical clarification gating.
3. Structured optimization plan generation.
4. Iterative legal action selection (bandit + LLM arbitration).
5. Action compilation into retrieval/SPP/QLIP/cell policies.
6. Underlying paired execution.
7. Reward update and best-so-far promotion.
8. Stop or mid-loop clarification when blocked/stagnating.

Scientific boundary:

- Primary objective is QLIP objective improvement under fixed composition/objective contract.
- Property fields are treated as backend estimates unless separately validated.
- No claim is made that the system performs autonomous physics discovery.

Phase 1 property/objective catalog:

- See `docs/branch/PHASE1_PROPERTY_OBJECTIVE_STACK.md` for the canonical Phase 1 table. The current implemented subset is the full eight-entry Phase 1 stack.
- For benchmark strictness, use `--strict-phase1 true` on benchmark/experiment commands.
- Downstream QLIP requests now preserve the expanded runtime objective families through `qlip_request.objective`:
  `spp_energy`, `none`, `density_packing`, `linear_property`, and `threshold_tradeoff`.
- `density_packing` is a pair-distance packing/contact proxy, not physical mass density.
- `linear_property` is native occupancy-linear scoring only; external property predictors are Phase 2.
- `threshold_tradeoff` separates the hard linear-property bound from the optional weighted property term and optional `spp_energy`/`none` base.

Phase 2 external predictors:

- See `docs/branch/PHASE2_EXTERNAL_PROPERTY_PREDICTORS.md` for the external predictor registry and request rules.
- External predictors are reported under `external_phase2`; they are not native QLIP objectives.
- The initial implemented backend is `phase2.external.pymatgen_composition_descriptor`, a raw exploratory formula descriptor adapter with explicit provenance and no benchmark-approval claim.
