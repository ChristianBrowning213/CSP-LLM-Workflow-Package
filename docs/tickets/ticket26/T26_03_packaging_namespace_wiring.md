# T26_03 — Packaging & Namespace Wiring

## Owner

Grunt (local-grunt), Claude-reviewed.

## Depends on

T26_02 (verbatim baseline committed).

## Objective

Wire the verbatim `packages/spp_maker_qlip/` tree into the unified archive's
build so that `import spp_maker`, `import spp_maker_qlip`, and
`import spp_maker_mcp` succeed, and the `spp-maker` / `spp-maker-mcp`
console scripts are installed — using only allowed changes (paths, imports,
packaging metadata, resource lookup, config lookup, compatibility aliases).

## Authoritative source

`packages/spp_maker_qlip/` verbatim baseline from T26_02. Reference pattern:
root `pyproject.toml`'s existing `[tool.setuptools.packages.find].where`
entries for `packages/qlip/src` and `packages/crystal_db/src`, and those
packages' own standalone `pyproject.toml` files.

## Archive files expected to change

- `pyproject.toml` (root) — add `packages/spp_maker_qlip/src` to
  `[tool.setuptools.packages.find].where`; add any required
  `[tool.setuptools.package-data]` entries (e.g. `rules/*.yaml` if resources
  are loaded via package data rather than a relative path); add
  `[project.scripts]` entries `spp-maker` and `spp-maker-mcp` if not already
  wired via the sub-package's own build.
- `packages/spp_maker_qlip/pyproject.toml` — packaging metadata only
  (license-files entry, package-data entries) if needed for the unified
  build; `name`/`version`/`dependencies`/existing `[project.scripts]` must
  not change.
- Any `__init__.py` under `packages/spp_maker_qlip/src/**` may gain a
  compatibility import alias ONLY if the module already does path/resource
  lookup relative to its own file location and that lookup breaks under the
  new repository-relative location. Do not add aliases speculatively.

## In-scope behavior

- Repository-relative path fixes needed purely because the package now
  lives under `packages/spp_maker_qlip/` instead of a standalone repo root
  (e.g. a hardcoded `Path(__file__).parents[2]` assumption that no longer
  resolves correctly).
- Console-script wiring.

## Forbidden changes

- Any change to a function body implementing CIF loading, neighbor
  generation, histogram construction, potential fitting, POT I/O, scoring,
  required-pair logic, regulator logic, or QLIP packaging logic.
- Renaming `spp_maker`, `spp_maker_qlip`, `spp_maker_mcp`, `spp-maker`,
  `spp-maker-mcp`, or any public symbol/tool name.
- Adding new architecture, new abstraction layers, or new config systems.

## Implementation requirements

- Follow the `packages/qlip/` and `packages/crystal_db/` precedent exactly
  for how a sub-package is both independently buildable and discoverable
  from the root package: root `pyproject.toml`
  `[tool.setuptools.packages.find].where` currently reads
  `["src", "packages/qlip/src", "packages/crystal_db/src"]` — append
  `"packages/spp_maker_qlip/src"`.
- Root `[project.scripts]` currently only has `llm-csp = ...`. Add
  `spp-maker = "spp_maker.cli:main"` and
  `spp-maker-mcp = "spp_maker_mcp.server:main"` (confirm the exact target
  callable against `packages/spp_maker_qlip/pyproject.toml`'s own
  `[project.scripts]`, which already has this verbatim from source — do not
  invent a different entry point).
- **Do not touch these lines — verified as relocation-safe, no edit
  needed:** `Path(__file__).resolve().parents[2]` in
  `src/spp_maker/cli.py:912`, `src/spp_maker/qlip_outputs_packages.py:105`,
  `src/spp_maker/run_orchestrator.py:242,580`, and
  `src/spp_maker_mcp/server.py:192`. Each already resolves correctly to
  `packages/spp_maker_qlip/` because that directory sits at the same
  depth-from-`src/` as the original standalone repo root. `get_git_sha()`
  (`src/spp_maker/publish.py:102`) runs `git rev-parse HEAD` with
  `cwd=repo_root` — since `packages/spp_maker_qlip/` is a subdirectory of
  this unified repo's own working tree, it will correctly report the
  unified archive's HEAD SHA. If, during testing, you find one of these
  actually does need a change, stop and report it as a BLOCKER rather than
  editing it — this contradicts prior analysis and needs Claude's review.
- Run `pip install -e .` (or the project's existing dev-install flow) from
  repo root afterward and confirm the three imports succeed.

## Source-fidelity / parity requirements

`git diff` of every file under `packages/spp_maker_qlip/src/**` against the
T26_02 baseline commit must show **only** import/path-lookup/packaging
lines changed — no other line differences. Any changed line must be
individually justifiable as one of the ticket's allowed-change categories.

## Tests the grunt must run

- `python -c "import spp_maker, spp_maker_qlip, spp_maker_mcp"`
- `pip install -e .` from repo root (or equivalent) completes without error.
- `spp-maker --help` and `spp-maker-mcp --help` (or `python -m` fallback if
  no console-script shim is active yet) run without a traceback.

## Tests Claude must independently rerun

- Re-run all of the above from a clean shell.
- `git diff <T26_02-commit> -- packages/spp_maker_qlip/src` reviewed line by
  line for scope creep.
- Confirm no sibling `SPP-Maker-QLIP` checkout leaked onto `sys.path`
  (`python -c "import spp_maker, sys; print(spp_maker.__file__)"` must point
  inside this repository).

## Acceptance criteria

- [ ] `import spp_maker`, `import spp_maker_qlip`, `import spp_maker_mcp`
      succeed from the unified environment.
- [ ] `spp-maker` and `spp-maker-mcp` entry points are installed.
- [ ] Diff against T26_02 baseline contains only allowed-category changes.
- [ ] No scientific/behavioral line changed.

## Expected outputs / artifacts

- Updated root `pyproject.toml`.
- Updated `packages/spp_maker_qlip/pyproject.toml` (packaging-only diff).
- GRUNT_PATCH capturing exactly this diff for Claude's independent review.
