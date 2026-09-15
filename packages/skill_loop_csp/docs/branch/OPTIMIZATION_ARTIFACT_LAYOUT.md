# Optimization Artifact Layout

Optimization sessions are stored under:

- `.sokllm_workspace/optimization/sessions/<session_id>/session.json`
- `.sokllm_workspace/optimization/sessions/<session_id>/iterations/<idx>.json`

Session records include links to underlying run/paired artifacts (`run_reference` fields) so each optimization iteration is replayable against existing pipeline manifests.

