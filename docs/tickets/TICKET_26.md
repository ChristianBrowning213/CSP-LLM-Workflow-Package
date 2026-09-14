# Ticket 26 — Restore the Complete SPP-Maker-QLIP Software Surface

## Objective

Restore the original SPP-Maker-QLIP software system into the unified archive.

This is a source-fidelity migration.

The authority is the original repository:

```text
C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP
```

Scientific source revision:

```text
3a2d557811973265f3373ec881cc8057a89789d2
```

Licensing revision:

```text
82114cd05f0cb40149d13c20adeafe4c437a03ae
```

The archive currently contains only a reduced subset under:

```text
src/llm_csp/spp/
```

That reduced subset may remain where useful for compatibility, but the original software namespaces and interfaces must be restored.

Do not redesign the SPP system.

---

# Baseline

Recovery branch:

```text
recovery/source-fidelity
```

Starting commit:

```text
f6a4fab7aa11bdcc6b76e25ee3ed6202578bad76
```

Current status:

```text
SPP-Maker-QLIP: PARTIAL
```

Expected final software status:

```text
SPP_MAKER_SOFTWARE_RESTORED
```

This ticket does not restore the large POT holdings yet.

---

# Critical rule

If the selected source revision contains working functionality, migrate the implementation rather than recreating it.

Allowed changes:

```text
repository-relative path changes
imports
package metadata
resource lookup
configuration lookup
compatibility aliases
```

Forbidden changes:

```text
potential mathematics
histogram mathematics
pair counting
regulator behavior
blend behavior
QLIP handoff semantics
schemas
tool names
CLI semantics
MCP semantics
```

---

# Part 1 — Freeze the authoritative source tree

Inspect exactly:

```text
3a2d557811973265f3373ec881cc8057a89789d2
```

Record:

```bash
git rev-parse HEAD
git status --short
```

Do not modify the source repository.

Generate:

```text
docs/fidelity/evidence/SPP_MAKER_SOURCE_MANIFEST.csv
```

containing all tracked operational source.

---

# Part 2 — Restore original namespaces

Preserve the actual source namespaces:

```python
import spp_maker
import spp_maker_qlip
```

Do not require existing users to migrate to:

```python
llm_csp.spp
```

The existing `llm_csp.spp` package may later delegate to or wrap the restored source implementation.

Original namespaces are authoritative.

---

# Part 3 — Determine archive location

Prefer an independent package layout such as:

```text
packages/spp_maker_qlip/
```

containing the source-faithful distributions/namespaces.

Example only:

```text
packages/spp_maker_qlip/
├── pyproject.toml
└── src/
    ├── spp_maker/
    └── spp_maker_qlip/
```

Use the source packaging structure where possible.

Do not flatten the original packages into `llm_csp.spp`.

---

# Part 4 — Restore core CIF input

Restore exact source behavior for:

```text
CIF loading
directory traversal
structure parsing
ordering
error handling
```

Preserve source ASE/pymatgen behavior exactly where applicable.

---

# Part 5 — Restore periodic neighbor processing

Restore original:

```text
neighbor generation
periodic-image handling
minimum-image behavior
cutoffs
pair identities
```

No mathematical changes.

The earlier QLIP periodic self-image correction belongs to QLIP objective semantics and must not cause unrelated SPP-Maker changes.

---

# Part 6 — Restore histogram construction

Restore source implementations for:

```text
distance histograms
pair bins
normalization
pair keys
sampling
```

Preserve exact defaults.

No re-fitting of source behavior around the reduced archive implementation.

---

# Part 7 — Restore potential fitting

Restore:

```text
fit_phi
weights
statistical-potential creation
normalization
smoothing
quality logic
```

using source implementation.

Same inputs must produce source-equivalent output.

---

# Part 8 — Restore POT I/O

Preserve original:

```text
POT parser
POT writer
directory conventions
pair naming
reverse-pair behavior
metadata
```

Do not replace source formats with a new manifest.

Compatibility manifests may exist additionally.

---

# Part 9 — Restore SPP model/scoring

Restore:

```text
in-memory SPP model
standalone scoring
periodic scoring behavior
score aggregation
```

Use source semantics.

Test source vs archive on identical fixture structures and POT files.

---

# Part 10 — Restore required-pair extraction

Restore the authoritative:

```text
formula → required species pairs
```

logic from:

```text
spp_maker_qlip
```

Preserve:

```text
unordered-pair semantics
same-species pairs
canonical naming
coverage diagnostics
```

---

# Part 11 — Restore corpus quality

Restore original corpus-quality diagnostics.

Include exact source behavior for:

```text
coverage
pair counts
data sufficiency
warnings
failure thresholds
```

Do not substitute newer archive-specific readiness models.

---

# Part 12 — Restore POT quality

Restore original generated-POT quality gates and diagnostics.

Preserve exact thresholds/defaults.

---

# Part 13 — Restore covalent filter

Restore:

```text
covalent rules
policy loading
filter behavior
configuration
```

Use the source rule file(s), not only the reduced example currently in `configs/examples`.

---

# Part 14 — Restore `common_contract`

The previous reduced migration explicitly omitted this.

Restore the source implementation if it participates in the operational workflow.

Audit exact responsibilities including:

```text
request-specific SPP
regulator union
blend policy
coverage decisions
pair selection
```

Do not reimplement these decisions in `llm_csp.workflow`.

---

# Part 15 — Determine ownership overlap with current workflow

Compare original:

```text
common_contract
qlip_package
run pipeline
```

with current:

```text
llm_csp.workflow.spp_policy
llm_csp.spp
```

Classify current code as:

```text
EXACT_SOURCE_ADAPTATION
COMPATIBILITY_WRAPPER
REDUNDANT_REIMPLEMENTATION
```

Do not remove anything yet unless source restoration makes a clearly duplicated implementation unnecessary and regression tests establish replacement parity.

Document all overlap.

---

# Part 16 — Restore regulator handling

Restore source regulator behavior exactly.

Audit:

```text
regulator POT root
required regulator pairs
fallback behavior
request + regulator composition
missing regulator handling
```

Do not preserve the reduced archive's external-root semantics if they differ from source.

Source behavior wins.

---

# Part 17 — Restore broad POT-library interface

Restore the software that locates and handles the original POT libraries.

Do not copy the large POT libraries yet.

The software must support the original:

```text
directory structure
lookup
coverage
reverse naming
selection
packaging
provenance
```

Asset restoration comes later.

---

# Part 18 — Restore `qlip_package`

The earlier packaging explicitly migrated only selected behavior from:

```text
src/spp_maker_qlip/qlip_package.py
```

Restore the complete operational module.

This includes, where present:

```text
QLIP_Outputs registry
Final_QLIP_output layout
POT package creation
QLIP handoff metadata
request packaging
result/output organization
```

Preserve source filenames and directory layout.

---

# Part 19 — Restore `QLIP_Outputs`

If the source uses:

```text
QLIP_Outputs
```

as an actual runtime registry/location, restore it.

Do not replace it with the v0.1 run-root abstraction.

Only alter the filesystem base required for unified-repository relocation.

---

# Part 20 — Restore `Final_QLIP_output`

Restore the source output layout and associated helper functions.

Preserve:

```text
names
directory structure
manifest semantics
POT locations
generated QLIP request locations
```

This is required for source workflow compatibility.

---

# Part 21 — Restore run pipeline

Restore the actual source high-level SPP pipeline.

Inventory the source command/function responsible for:

```text
input CIF corpus
→ fit/build potentials
→ quality checks
→ regulator handling
→ output package
```

Preserve stage order and error behavior.

---

# Part 22 — Restore original CLI

Audit and restore every source CLI command.

At minimum determine whether source exposes commands equivalent to:

```text
fit
run
score
required-pair operations
quality
package/export
calibration
```

Use exact source names.

Do not replace them with `llm-csp` commands.

---

# Part 23 — Preserve CLI entry point

If original package exposes:

```text
spp-maker
```

or another executable, preserve it exactly.

Verify from installed package:

```bash
<source-command> --help
```

Do not rename the executable.

---

# Part 24 — Restore MCP server

Restore the original SPP MCP implementation.

Audit:

```text
server module
transport
tools
input schemas
output schemas
resource lookup
configuration
error normalization
```

Use exact source tool names.

---

# Part 25 — Machine-readable MCP surface

Create:

```text
docs/fidelity/spp_maker_mcp_surface.json
```

For every source MCP tool record:

```text
name
source implementation
input schema
output schema
archive implementation
parity status
```

No invented tool names.

---

# Part 26 — Restore calibration software

Restore source calibration code.

Include:

```text
calibration commands
parameter handling
metrics
schemas
quality analysis
```

Do not copy generated calibration output yet.

---

# Part 27 — Restore publishing/index registry

The earlier migration omitted publishing/index registry code.

Restore it if operational at the selected source revision.

Preserve source behavior.

Do not copy generated registry artifacts unless required later.

---

# Part 28 — Restore corpus-preparation software

Restore source code used to prepare SPP fitting corpora when operational.

Distinguish:

```text
software
```

from:

```text
large generated/source corpora
```

Software comes now.

Assets come later.

---

# Part 29 — Restore plotting/reporting code

If source exposes plotting/report generation as part of its supported CLI/runtime, restore it.

Generated plots/reports do not belong in the package.

---

# Part 30 — Restore schemas

Inventory every source schema.

Restore exact:

```text
JSON Schema
dataclass
Pydantic
manifest structure
```

where operational.

Compare with archive-generated manifests.

No schema redesign.

---

# Part 31 — Restore configuration surface

Inventory all original configuration:

```text
environment variables
config files
defaults
CLI arguments
POT roots
corpus roots
QLIP output roots
calibration paths
MCP settings
```

Preserve original names/defaults unless repository relocation requires path adjustment.

---

# Part 32 — Record path rewrites

Every relocated path must be documented.

Create a table in:

```text
docs/fidelity/SPP_MAKER_RESTORATION.md
```

with:

```text
source path behavior
archive path behavior
reason
parity test
```

Only location changes are allowed.

---

# Part 33 — Audit source POT holdings

Do not copy them.

Create:

```text
docs/fidelity/SPP_POT_ASSET_MANIFEST.csv
```

Inventory all POT assets known from:

```text
SPP-Maker-QLIP
Skill-Loop-CSP
QLIP
```

For this ticket specifically identify which POTs the SPP source expects.

Columns:

```text
source_repository
source_path
pair
size
sha256
library_role
runtime_required
generated_or_source
provenance
redistribution_status
duplicate_group
```

---

# Part 34 — Deduplicate asset inventory conceptually

The audit found approximately:

```text
SPP POTs: 27,041
Skill-Loop POTs: 55,870
QLIP POTs: 19,486
```

Determine by SHA-256 how much overlap exists.

Do not copy any of them.

The later asset ticket should restore one source-faithful physical representation without unnecessarily storing byte-identical duplicates.

But do not alter logical paths expected by source code.

Symlinks/hardlinks/materialization may later preserve logical layouts.

---

# Part 35 — Identify canonical regulator library

Determine exactly which POT library the source system used as:

```text
broad regulator
```

Record:

```text
path
file count
pair count
hash manifest
generation provenance
```

Do not assume the QLIP or Skill-Loop copy is authoritative.

Trace actual source configuration/runtime use.

---

# Part 36 — Identify request-specific POT output

Distinguish:

```text
persistent source/regulator POT library
```

from:

```text
generated request-specific SPP output
```

Generated request outputs are not archive assets.

The software for generating them must be restored.

---

# Part 37 — Identify QLIP handoff assets

Trace source handoff:

```text
SPP pipeline
→ package_for_qlip
→ QLIP
```

Determine exactly what files/directories are produced and consumed.

Record source artifact tree.

---

# Part 38 — Restore source artifact tree

Using synthetic/source-safe fixtures, run the source pipeline and archive pipeline.

Compare:

```text
file names
relative directories
manifest schemas
POT bytes
metadata
status
```

Normalize only the root directory.

Require parity.

---

# Part 39 — Direct fitting parity

Run identical small safe CIF corpus through:

```text
original SPP source
archive restored SPP
```

Compare:

```text
required pairs
histograms
potential arrays
POT bytes
quality metrics
manifest
```

Require exact or source-defined numerical parity.

---

# Part 40 — Scoring parity

Run identical:

```text
CIF/Atoms
+
POT set
```

through both.

Compare exact score.

No tolerance change unless source numerical serialization requires it.

---

# Part 41 — QLIP packaging parity

Run identical fitted POT set through source and archive `qlip_package`.

Compare:

```text
selected files
directory structure
POT hashes
manifest
QLIP request data
```

---

# Part 42 — Regulator parity

Using a small source-safe regulator fixture:

```text
request-specific pairs
+
regulator pairs
```

compare source/archive union and fallback decisions.

This is critical because earlier packaging moved this logic elsewhere.

---

# Part 43 — Failure parity

Test source vs archive for:

```text
missing CIF corpus
missing required pair
bad POT
incomplete regulator coverage
invalid config
invalid formula
invalid QLIP output location
```

Compare exception/status behavior.

---

# Part 44 — Restore source tests

Original audit baseline:

```text
128 passed
1 dependency-sensitive schema snapshot failure
```

Migrate/run source tests against archive package.

Do not weaken assertions.

Investigate the one source failure separately and document whether it is:

```text
environment/dependency drift
real source defect
snapshot incompatibility
```

Do not "fix" it unless required for migration parity.

---

# Part 45 — Preserve dependency versions where behavior-sensitive

If the schema snapshot failure depends on a library version, identify exact source environment expectations.

Do not pin an old dependency blindly.

Document:

```text
source version
current archive version
behavior difference
```

No unrelated dependency upgrades.

---

# Part 46 — Installed package test

Build and install the restored package into an isolated environment.

Verify:

```python
import spp_maker
import spp_maker_qlip
```

and source CLI/MCP imports.

No sibling SPP-Maker checkout may appear on `sys.path`.

---

# Part 47 — Existing `llm_csp.spp` compatibility

Run all existing archive SPP tests.

Where the reduced wrapper duplicates source implementation, prefer delegating to restored source code **only if parity is proven**.

Do not delete compatibility APIs used by the v0.1 deterministic workflow.

---

# Part 48 — Existing workflow compatibility

Run:

```text
llm_csp.workflow
```

tests.

Its SPP behavior must remain unchanged.

If current workflow contains logic actually owned by original SPP-Maker, do not move it during this ticket unless needed for exact parity.

Document the overlap for later Skill-Loop restoration.

---

# Part 49 — Existing QLIP compatibility

Run the current packaged QLIP integration tests with restored SPP software.

Do not modify QLIP scientific code.

---

# Part 50 — No POT asset requirement for unit suite

Use safe fixtures/synthetic generated POTs for software testing.

Large production regulator libraries are deferred.

Tests requiring the canonical broad library must be clearly skipped/classified.

---

# Part 51 — Recovery status

Update:

```text
docs/fidelity/RECOVERY_STATUS.md
```

Expected successful state:

```text
SPP-Maker-QLIP software: RESTORED
SPP/POT operational assets: PENDING
```

Do not mark the entire SPP system restored yet.

---

# Part 52 — Update source matrix

Update SPP-Maker software rows in:

```text
docs/fidelity/SOURCE_TO_ARCHIVE_MATRIX.csv
```

Use:

```text
RESTORED
ALREADY_PARITY_VERIFIED
ASSET_DEFERRED
HISTORICAL_NON_RUNTIME
```

No unexplained software gaps.

---

# Part 53 — Restoration documentation

Create:

```text
docs/fidelity/SPP_MAKER_RESTORATION.md
```

Include:

```text
source revision
package layout
restored namespaces
CLI surface
MCP surface
configuration
path changes
common_contract
regulator behavior
QLIP package handoff
source test results
direct parity results
deferred POT assets
```

---

# Part 54 — Full archive regression

Run:

```text
SPP source tests
SPP direct parity tests
current llm_csp.spp tests
QLIP integration tests
Crystal-DB tests that do not require blocked DB
validation tests
deterministic workflow tests
fidelity guards
whole archive suite
```

No scientific regression permitted.

---

# Part 55 — Do not touch Crystal blocked asset status

Ticket 25 established:

```text
CRYSTAL_DB_BLOCKED_PROVENANCE
```

Do not change this status.

Do not add or regenerate a replacement Crystal database.

---

# Part 56 — No agent restoration yet

Do not touch:

```text
Skill-Loop Planner
Run Manager
Evaluator
Orchestrator
LM Studio reasoning runtime
Ollama reasoning runtime
Skill-Loop prompts
```

Their dependencies are still being restored.

---

# Part 57 — Commit

Commit only to:

```text
recovery/source-fidelity
```

Suggested:

```text
feat: restore full SPP-Maker-QLIP software surface
```

Push to:

```text
origin/recovery/source-fidelity
```

No merge/tag/release.

---

# Required completion report

## 1. Branch

Starting commit, final commit, remote synchronization.

## 2. Source revision

Confirm scientific/licensing revisions.

## 3. Restored namespaces

Confirm:

```text
spp_maker
spp_maker_qlip
```

## 4. Core fitting

Report restored CIF, neighbor, histogram and potential-fitting functionality.

## 5. POT I/O/scoring

Report source parity.

## 6. Required-pair logic

Report source parity.

## 7. `common_contract`

Report exact restored responsibilities.

## 8. Regulator behavior

Report source behavior and parity.

## 9. QLIP packaging

Report:

```text
QLIP_Outputs
Final_QLIP_output
package_for_qlip
```

or exact source equivalents.

## 10. CLI

List all restored commands/entry points.

## 11. MCP

List exact source MCP tools and transport.

## 12. Calibration/publishing

Report restored operational software.

## 13. Schemas

Report schema parity.

## 14. Configuration

List source environment/configuration surface.

## 15. Path rewrites

List relocation-only changes.

## 16. POT asset inventory

Report file counts, overlaps and canonical regulator determination.

## 17. Direct fitting parity

Report source/archive results.

## 18. Scoring parity

Report exact scores.

## 19. QLIP handoff parity

Report artifact-tree/file/hash equality.

## 20. Failure parity

Report source/archive comparisons.

## 21. Source tests

Compare against:

```text
128 passed
1 dependency-sensitive failure
```

## 22. Existing archive tests

Report regressions/full counts.

## 23. Recovery status

Exactly one:

```text
SPP_MAKER_SOFTWARE_RESTORED
SPP_MAKER_SOFTWARE_GAPS_REMAIN
```

## 24. Scientific behavior

Expected:

```text
NO_SCIENTIFIC_BEHAVIOR_CHANGE
```

## 25. Crystal status

Confirm it remains:

```text
CRYSTAL_DB_BLOCKED_PROVENANCE
```

## 26. v0.1 integrity

Confirm peeled `v0.1.0` remains:

```text
2dbf5e8852dc62c42d97385bc96ea90166d0fc74
```

## 27. Git status

Report clean tracked worktree and untouched unrelated local files.

---

# Acceptance criteria

* [ ] Exact SPP source revision used.
* [ ] Original `spp_maker` namespace restored.
* [ ] Original `spp_maker_qlip` namespace restored.
* [ ] Core CIF/neighbor/histogram/fitting code restored.
* [ ] POT I/O restored.
* [ ] Scoring restored.
* [ ] Required-pair behavior restored.
* [ ] Quality diagnostics restored.
* [ ] `common_contract` restored where operational.
* [ ] Regulator behavior restored.
* [ ] Complete QLIP handoff restored.
* [ ] `QLIP_Outputs`/source output conventions restored.
* [ ] Original CLI restored.
* [ ] Original MCP restored.
* [ ] Calibration software restored.
* [ ] Publishing/index software restored where operational.
* [ ] Source schemas restored.
* [ ] Source configuration restored.
* [ ] Production POTs inventoried but not blindly copied.
* [ ] Source-vs-archive fitting parity passes.
* [ ] Source-vs-archive scoring parity passes.
* [ ] Source-vs-archive QLIP packaging parity passes.
* [ ] Source failure behavior preserved.
* [ ] Existing `llm_csp.spp` compatibility remains green.
* [ ] Existing workflow remains green.
* [ ] No new architecture added.
* [ ] No scientific behavior change.
* [ ] Crystal provenance block remains truthful.
* [ ] `main` and v0.1 unchanged.

Stop after Ticket 26.

Do not begin POT-library restoration.
