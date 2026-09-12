# QLIP

QLIP is the crystal structure prediction solver subsystem. It owns solver
behavior, constraints, guidance, schemas, request validation, periodic SPP
scoring, CIF generation, and solver-related scaffold primitives.

The migrated package is under `packages/qlip`. Its supported Python entry point
is `qlip.solve`; strict request validation is available from
`qlip.core.validate.validate_request`. See
`examples/qlip/solve_srtio3.py --pot-root PATH` for an external-asset solve and
`docs/packaging/QLIP_PACKAGING_NOTES.md` for scope and dependency details.
