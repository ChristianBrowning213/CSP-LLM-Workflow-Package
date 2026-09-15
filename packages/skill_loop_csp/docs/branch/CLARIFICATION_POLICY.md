# Clarification Policy

The orchestrator classifies missing task information into:

- hard-required fields: trigger explicit follow-up prompt before solve planning;
- important-but-defaultable fields: may proceed with logged defaults;
- optional fields: no follow-up required for first pass.

All defaults are serialized in `task_spec.defaults_used` so decisions remain auditable.
