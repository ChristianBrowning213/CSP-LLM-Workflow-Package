# T26_14_CORRECTION_01 — Fix Three Bugs in POT Inventory Script

## Owner

Grunt (swarm — single bounded correction pass).

## Depends on

T26_14 attempt 1 (REJECTED by independent review — script has 3 real bugs
that would corrupt output against real data, even though its own synthetic
self-test passed, because the self-test's fixture filenames were invented
to match the same wrong assumption as the parsing bug).

## Objective

Fix exactly three bugs in `scripts/pot_asset_inventory.py`. Do not rewrite
unrelated parts of the script.

## Bug 1 — duplicate-group data loss

In `write_manifest()`, this loop:

```python
for sha256, files in hash_groups.items():
    if len(files) > 1:
        for file_info in files:
            file_info['duplicate_group'] = duplicate_group_id
            file_info_by_sha[sha256] = file_info   # BUG: overwritten each iteration
        duplicate_group_id += 1
    else:
        file_info = files[0]
        file_info['duplicate_group'] = 0
        file_info_by_sha[sha256] = file_info
```

`file_info_by_sha` is keyed by `sha256` alone, so when multiple files share
a hash, only the LAST one processed survives — every other duplicate-group
member is silently dropped from the final CSV. Fix: collect and write every
individual file's row (e.g. build a flat list of all file_info dicts, not a
dict keyed by sha256), so a duplicate group of N files produces N output
rows, all sharing the same `duplicate_group` id.

## Bug 2 — wrong pair-name filename convention

```python
def get_pair_name(filename):
    if filename.endswith('.POT'):
        base_name = filename[:-4]
    else:
        base_name = filename
    parts = base_name.split('_')
    if len(parts) >= 2:
        return '_'.join(parts[:-1])
    else:
        return base_name
```

This assumes an underscore-suffixed convention (`<pair>_<suffix>.POT`).
Real POT files use a hyphen-separated species-pair convention with NO
suffix, e.g. `Cl-Na.POT`, `C-Si.POT` (confirmed directly against
`SPP-Maker-QLIP`'s `artifacts/nacl_pair_extraction_diagnostic_spp_root/`).
Fix: the pair name is simply the filename stem (everything before `.POT`),
with no further splitting:

```python
def get_pair_name(filename):
    if filename.endswith('.POT'):
        return filename[:-4]
    return filename
```

Do not attempt to normalize hyphen order (e.g. `Na-Cl` vs `Cl-Na`) — record
the pair name exactly as it appears in the filename. Reverse-pair grouping
is out of scope for this correction.

## Bug 3 — broken `source_repository` for absolute external paths

```python
rel_path = os.path.relpath(filepath)
if '/' in rel_path or '\\' in rel_path:
    repo_name = rel_path.split(os.sep)[0]
else:
    repo_name = 'unknown'
```

This derives the repository name from a path relative to the CURRENT
WORKING DIRECTORY, which breaks when Claude invokes the script with
absolute external paths (e.g.
`C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP`) — `os.path.relpath` would
produce something like `..\..\..\SPP-Maker-QLIP\...`, making `repo_name`
resolve to `..`. Fix: derive the repository name from the root directory
argument itself, not from a CWD-relative computation. Change
`find_pot_files()` to return `(root_dir, filepath)` pairs instead of bare
paths, and derive `repo_name = os.path.basename(os.path.normpath(root_dir))`
at the point where you know which root_dir a file came from. Thread this
through `process_pot_files()` so `source_repository` is set correctly
regardless of whether `root_dirs` are relative or absolute paths.

## Archive files expected to change

- `scripts/pot_asset_inventory.py` (the 3 fixes above only).
- Update `scripts/test_pot_inventory.py`'s fixtures/assertions if they
  encoded the old (wrong) underscore-suffix filename convention — use
  hyphenated filenames like the real convention instead (e.g.
  `test_pair_1.POT` → `A-B.POT`), and add a duplicate-group case with 3+
  files sharing one hash to prove Bug 1's fix (assert all 3 rows appear in
  the output, not just one).
- Remove `scripts/final_test.py` if it is a redundant/leftover ad hoc test
  file not referenced by anything (check first; do not remove something
  still in use).

## Forbidden changes

- Do not change the CSV column schema.
- Do not add write/copy/delete operations on `.POT` files — the script
  must remain strictly read-only against scanned directories.
- Do not touch `test_data/repo1/`, `test_data/repo2/` fixtures beyond what's
  needed to exercise the duplicate-group fix (adding new synthetic fixture
  files is fine; do not touch anything outside `scripts/`, `test_data/`,
  and `docs/fidelity/SPP_POT_ASSET_MANIFEST.csv`).

## Tests the grunt must run

- Your updated self-test suite, including a new case with 3+ files sharing
  one SHA-256 (e.g. identical byte content in 3 files across 2 synthetic
  repos) — assert the output CSV contains all 3 rows with the same
  `duplicate_group` id, not just 1.
- A case with a hyphenated filename (e.g. `A-B.POT`) — assert `pair` in the
  output is exactly `A-B`, not mangled.
- Re-run with an absolute path as one of the root directories — assert
  `source_repository` is the correct basename, not `..` or `unknown`.

## Tests Claude must independently rerun

- Read the corrected script in full.
- Re-run the updated self-tests independently.
- Confirm the script is still strictly read-only (`rb` mode only, no
  `shutil`/`os.remove`/write calls against scanned paths).

## Acceptance criteria

- [ ] Duplicate groups of 3+ files all appear in the output CSV.
- [ ] Hyphenated pair names are preserved exactly, unmangled.
- [ ] `source_repository` is correct for both relative and absolute root
      directory arguments.
- [ ] Script remains read-only.
- [ ] No column schema change.

## Expected outputs / artifacts

- Corrected `scripts/pot_asset_inventory.py`, ready for Claude to run
  against the real repositories afterward.
