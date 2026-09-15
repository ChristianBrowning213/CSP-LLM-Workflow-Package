# Optimization Runbook

Start:

```bash
sokllm optimize start --mode stub --query "TiO2 optimize high property x"
```

Structured task-spec start:

```bash
sokllm optimize start --mode stub --task-spec-file my_case.yaml
```

Check status:

```bash
sokllm optimize status --session-id <session_id>
```

Continue (including clarification answer):

```bash
sokllm optimize continue --session-id <session_id> --answer "composition TiO2, symmetry soft"
```

Show plan:

```bash
sokllm optimize show-plan --session-id <session_id>
```

Show best:

```bash
sokllm optimize show-best --session-id <session_id> --json
```

Common triage:

- If status is `PENDING_CLARIFICATION` or `WAITING_CLARIFICATION`, provide missing critical answers through `optimize continue --answer ...`.
- If budget exhausted, increase optimization budget config values.
- If invalid LLM action proposals occur, fallback behavior is automatically logged in session iteration records.
- For deterministic objective binding without NL parsing, use a JSON/YAML task spec file with
  `composition_target`, `qlip_objective`, and any symmetry or predictor fields you need.
