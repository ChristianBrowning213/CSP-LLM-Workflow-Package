# T26_08_CORRECTION_01 — Restore QLIP_Outputs Static Content (Verbatim Copy Only)

## Owner

Grunt (swarm — single bounded correction pass, run SOLO, not concurrently
with any other heavy ticket).

## Depends on

T26_08 attempt 3 — REJECTED. That attempt created files in the WRONG
location (unified repo root `QLIP_Outputs/`, which must not exist — this
repo's QLIP_Outputs lives only under `packages/spp_maker_qlip/`), invented
a `QLIP_Outputs/PACKAGES/` directory that does not exist anywhere in the
source repository, and wrote fabricated 6-byte placeholder content into
`latest.txt` files instead of the real verbatim source bytes.

## Objective

Copy 9 already-verified, byte-exact staged files into their correct
location. This is a **pure file copy** — no content should be typed,
generated, or "restored from memory." Every byte already exists, verified,
at the staging path below.

## Authoritative source

Already extracted, byte-verified by Claude via `git show` from
`SPP-Maker-QLIP` at `3a2d557811973265f3373ec881cc8057a89789d2`, staged at:

```
.grunt-staging/spp_maker_source/3a2d557811973265f3373ec881cc8057a89789d2/QLIP_Outputs/
    CONSTRAINTS/.gitkeep
    CONSTRAINTS/latest.txt
    CONSTRAINTS/runs/.gitkeep
    GUIDANCES/.gitkeep
    GUIDANCES/latest.txt
    GUIDANCES/runs/.gitkeep
    INTEGRATION.md
    README.md
    SPP/runs/.gitkeep
```

**Use these staged files as your ONLY source for content. Do not re-derive,
retype, or invent content for any of these files.**

Note: `QLIP_Outputs/SPP/latest.txt` is deliberately NOT included in this
list — it is handled separately in T26_08_CORRECTION_02, because its
correct content depends on a freshly-generated run that does not exist yet.
Do not create `SPP/latest.txt` in this subticket.

## Archive files expected to change

Copy each staged file verbatim (byte-for-byte, e.g. `cp`, not retyped) to
the exact same relative path under:

```
packages/spp_maker_qlip/QLIP_Outputs/
```

For example: `.grunt-staging/.../QLIP_Outputs/INTEGRATION.md` →
`packages/spp_maker_qlip/QLIP_Outputs/INTEGRATION.md`.

## Forbidden changes

- **Do not create ANY file or directory under the unified repository root's
  own `QLIP_Outputs/`** (i.e. `C:\...\CSP-LLM-Workflow-Package\QLIP_Outputs\`
  must not exist after this ticket — only
  `packages/spp_maker_qlip/QLIP_Outputs/` is correct).
- **Do not create a `PACKAGES/` directory anywhere** — it does not exist in
  the source repository. Only `CONSTRAINTS/`, `GUIDANCES/`, and `SPP/` are
  real.
- Do not create `QLIP_Outputs/SPP/latest.txt` (see note above — separate
  ticket).
- Do not edit the content of any of the 9 listed files — copy exactly.
- Do not touch any file outside `packages/spp_maker_qlip/QLIP_Outputs/`.

## Implementation requirements

```
cp .grunt-staging/spp_maker_source/3a2d557811973265f3373ec881cc8057a89789d2/QLIP_Outputs/INTEGRATION.md packages/spp_maker_qlip/QLIP_Outputs/INTEGRATION.md
```
(and equivalently for the other 8 files, creating parent directories as
needed).

After copying, run this sanity check and include its output in your report:

```
python -c "
import hashlib
files = ['CONSTRAINTS/.gitkeep','CONSTRAINTS/latest.txt','CONSTRAINTS/runs/.gitkeep','GUIDANCES/.gitkeep','GUIDANCES/latest.txt','GUIDANCES/runs/.gitkeep','INTEGRATION.md','README.md','SPP/runs/.gitkeep']
for f in files:
    a = open(f'.grunt-staging/spp_maker_source/3a2d557811973265f3373ec881cc8057a89789d2/QLIP_Outputs/{f}','rb').read()
    b = open(f'packages/spp_maker_qlip/QLIP_Outputs/{f}','rb').read()
    print(f, 'MATCH' if a == b else 'MISMATCH')
"
```

## Source-fidelity / parity requirements

All 9 files must show `MATCH`. A single `MISMATCH` means REJECT.

## Tests the grunt must run

- The hash/byte sanity check above.
- Confirm (e.g. `ls` or equivalent) that no `QLIP_Outputs/` directory exists
  at the repository root, and no `PACKAGES/` directory exists anywhere.

## Tests Claude must independently rerun

- Re-run the byte-comparison sanity check independently.
- Confirm no repo-root `QLIP_Outputs/` and no `PACKAGES/` directory exist.
- Diff each copied file against a fresh `git show` from the live source
  repo directly (belt-and-suspenders beyond the staged-file comparison).

## Acceptance criteria

- [ ] All 9 files present at `packages/spp_maker_qlip/QLIP_Outputs/`.
- [ ] All 9 byte-identical to source.
- [ ] No files created at the unified repo root.
- [ ] No `PACKAGES/` directory anywhere.
- [ ] `SPP/latest.txt` not created (deferred to CORRECTION_02).

## Expected outputs / artifacts

- `packages/spp_maker_qlip/QLIP_Outputs/` populated with verbatim static
  source content, ready for T26_08_CORRECTION_02 to add the freshly
  generated run and `SPP/latest.txt`.
