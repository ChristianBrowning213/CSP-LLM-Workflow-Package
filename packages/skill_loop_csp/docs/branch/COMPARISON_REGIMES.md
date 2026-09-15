# Comparison Regimes

Stable run family IDs used across reports and benchmarks:

- `baseline_qlip`: QLIP request without SPP guidance.
- `qlip_fixed_spp`: QLIP with preselected fixed SPP package.
- `qlip_retrieval_spp`: QLIP with retrieval-conditioned SPP package.
- `qlip_retrieval_spp_iter`: retrieval-conditioned run with bounded delta iterations.
- `non_qlip_placeholder`: reserved non-QLIP comparator slot.

All family comparisons must hold fixed:

- composition target,
- objective/constraint contract,
- candidate cell regime.

Any deviation is recorded as a different run family.
