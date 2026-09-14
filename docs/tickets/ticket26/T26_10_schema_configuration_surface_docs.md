# T26_10 — Schema & Configuration Surface Documentation

## Owner

Grunt (local-grunt), Claude-reviewed.

## Depends on

T26_09.

## Objective

Inventory every schema (JSON Schema, dataclass, Pydantic model, manifest
structure) and every configuration surface (env vars, config files,
defaults, CLI args, POT/corpus/QLIP-output/calibration roots, MCP settings)
actually present in the restored source, and document them.

## Authoritative source

All of `packages/spp_maker_qlip/src/**` as restored through T26_09.

## Archive files expected to change

- `docs/fidelity/SPP_MAKER_RESTORATION.md` — new "Schemas" and
  "Configuration" sections.

## In-scope behavior

- Mechanical enumeration: grep for `pydantic.BaseModel`/`@dataclass`/
  `json.load`/`jsonschema`/`os.environ`/`argparse.add_argument` across the
  restored package, and list each finding with its file:line, current
  default, and whether the archive value matches source exactly.

## Forbidden changes

- No schema redesign.
- No changing any default value found during this audit — document only.

## Implementation requirements

Enumeration must be produced by grepping/AST-walking the actual restored
source, not written from the ticket text's example list.

## Source-fidelity / parity requirements

Every schema/config entry in the doc must be traceable to a specific
file:line in the restored package.

## Tests the grunt must run

None (documentation-only; no runtime behavior change).

## Tests Claude must independently rerun

- Independently grep the same patterns and cross-check completeness against
  the produced doc (no missing schema/config item, no invented one).

## Acceptance criteria

- [ ] Every operational schema is inventoried with exact structure.
- [ ] Every configuration surface (env var/file/default/CLI arg/root path)
      is inventoried with source vs. archive value noted.
- [ ] No schema redesign occurred.

## Expected outputs / artifacts

- `docs/fidelity/SPP_MAKER_RESTORATION.md` Schemas + Configuration sections
  for the Ticket 26 completion report (§13, §14).
