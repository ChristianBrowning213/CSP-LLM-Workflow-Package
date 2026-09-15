# Optimization Action Library

The optimization orchestrator selects from registered, validated actions only.

Current actions:

- `baseline_control`
- `guided_hybrid_balanced`
- `guided_property_push`
- `retrieval_text_explore`
- `retrieval_fingerprint_probe`
- `cell_policy_probe`

Each action explicitly binds:

- retrieval policy
- SPP corpus strategy
- SPP calibration mode
- QLIP guidance mode
- cell-candidate selection policy

The LLM cannot bypass this registry. Invalid action proposals are rejected and fallback to policy-ranked legal actions.

