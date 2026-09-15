# Backend Interface

`backends/base.py` defines a stable placeholder interface for non-QLIP solvers.

Contract:

- `validate(request) -> BackendResult`
- `solve(request) -> BackendResult`

Benchmark artifacts include `backend_name` so future second backends can share the same report surface.
