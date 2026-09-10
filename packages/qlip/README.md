# QLIP

QLIP is the solver subsystem for LLM-CSP. It exposes strict request validation,
Pyomo/Gurobi-backed solving, periodic SPP scoring, ordered occupation and
scaffold primitives, and CIF result generation.

The Python API is `qlip.solve`; `python -m qlip` provides the source-compatible
CLI. A working Gurobi installation and license are required for real solves.
The optional `mcp` extra installs the MCP server dependencies.
