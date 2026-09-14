# T26_14 — POT Asset Inventory & Dedup Audit

## Owner

Grunt writes the inventory script only; Claude runs it against the external
repositories and interprets results. NOT delegated for execution: the
target directories (`SPP-Maker-QLIP`, `Skill-Loop-CSP`, `QLIP`) sit outside
any grunt worktree, and at the ticket's own stated scale (~102,000 files
combined) this is a long-running scan Claude must supervise directly rather
than trust to an unattended grunt run.

## Depends on

T26_01 (can run in parallel with T26_02–T26_13; independent of the
restoration work itself).

## Objective

Inventory (never copy) all POT assets across the three repositories,
determine SHA-256-based overlap, and identify which POTs the SPP source at
the scientific revision actually expects — without restoring any of them
(explicitly deferred by Ticket 26 and forbidden from starting: "Do not
begin POT-library restoration").

## Authoritative source

- `SPP-Maker-QLIP` (~27,041 POTs per ticket's prior audit)
- `Skill-Loop-CSP` (~55,870 POTs)
- `QLIP` (~19,486 POTs)

## Archive files expected to change

- `docs/fidelity/SPP_POT_ASSET_MANIFEST.csv` (new) — columns exactly:
  `source_repository,source_path,pair,size,sha256,library_role,
  runtime_required,generated_or_source,provenance,redistribution_status,
  duplicate_group`.

## In-scope behavior (grunt's scope: script only)

Write a script (Python, using `hashlib.sha256`, streamed reads) that:
- walks a given root directory,
- finds `*.POT` files,
- extracts the pair name from filename convention,
- computes size and SHA-256,
- accepts multiple roots and assigns a `duplicate_group` id to any set of
  files sharing a SHA-256 across roots.

The script must not write, move, copy, or delete any POT file — read-only
by construction (open in `"rb"` mode only; no `shutil.copy`/`os.remove`
calls).

## Forbidden changes

- No copying, symlinking, or hardlinking of any POT file in this subticket
  (Part 34 explicitly defers materialization to a later ticket).
- No modification to any of the three source repositories.

## Implementation requirements

Claude reviews the script for read-only safety **before** running it
against real directories. Given the file count, Claude runs it as a
background task and samples intermediate output rather than blocking on
full completion inline.

## Source-fidelity / parity requirements

N/A (inventory only; no restored code to compare).

## Tests the grunt must run

- Script self-test against a small synthetic fixture directory (a handful
  of dummy `.POT` files) to prove correctness before Claude runs it for
  real.

## Tests Claude must independently rerun

- Code-review the script for any write/delete call before execution.
- Spot-check a sample of the resulting manifest's SHA-256 values against a
  manual `sha256sum` on a handful of real files.
- Independently determine the canonical broad-regulator library (Part 35)
  by tracing actual source configuration/runtime use — this determination
  is Claude's, not inferable from the manifest alone.

## Acceptance criteria

- [ ] `SPP_POT_ASSET_MANIFEST.csv` inventories all three repositories'
      POT holdings with the required columns.
- [ ] Zero bytes copied; zero files modified in any source repository.
- [ ] SHA-256-based duplicate groups identified.
- [ ] Canonical regulator library identified and justified (Part 35),
      by Claude.
- [ ] Request-specific vs. persistent-library POTs distinguished
      (Parts 36–37).

## Expected outputs / artifacts

- `docs/fidelity/SPP_POT_ASSET_MANIFEST.csv`
- POT asset inventory section for the Ticket 26 completion report (§16).
