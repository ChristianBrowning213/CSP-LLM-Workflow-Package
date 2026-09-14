# Source-Fidelity Recovery Rules

The original source repositories and their tested runtime behaviour are
authoritative.

The unified repository may:

- relocate files;
- change imports;
- change paths;
- change package metadata;
- change configuration lookup;
- add compatibility shims;
- add tests proving parity.

The unified repository may not:

- redesign runtime architecture;
- replace existing schemas with new schemas;
- replace source tools with simplified tools;
- alter scientific mathematics;
- alter source control flow without demonstrated necessity;
- silently drop source capabilities.

If original code can be migrated, migrate it.

If original public interfaces exist, preserve them.

If a change is required only because repositories are being combined, the
smallest behaviour-preserving change is preferred.

## Evidence and change control

Every recovery change must cite a frozen source revision from
`SOURCE_SYSTEMS.json`, identify its source path and interface, and carry tests
that demonstrate parity. Audit classifications remain historical findings;
later progress is recorded separately in `RECOVERY_STATUS.md`.
