# Branch Research Contract

## First Claim
Given a fixed composition and fixed objective/constraint contract, retrieval-conditioned SPP guidance helps QLIP reach better solver outcomes than baseline QLIP.

## Non-Claims
- No universal property optimization claim.
- No claim that the LLM directly solves CSP physics.
- No claim of superiority over all CSP methods.

## Primary Run Families
- `baseline_qlip`
- `qlip_fixed_spp`
- `qlip_retrieval_spp`
- `qlip_retrieval_spp_iter`
- `non_qlip_placeholder`

## Success Evidence Minimum
- Baseline and guided runs share the same fixed task contract.
- Run artifacts include retrieval IDs, corpus manifest, request/response logs, and verification outputs.
- Metrics are emitted with `metrics.result.v1` schema.
- Claim language distinguishes solver-objective gains from property verification.
