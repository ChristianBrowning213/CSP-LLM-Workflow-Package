# SrTiO3 POT provenance

Audit date: 2026-09-12. Scope: the six POT files under
`packages/qlip/src/qlip/resources/spp/`. The files were inspected but not
modified or replaced.

## Exact assets

| Pair | SHA-256 |
| --- | --- |
| O-O | `45d0b5d18b7ebcf4ec5b34b37f510be6f4d7b39dfc5379ac8442d18820bab6eb` |
| O-Sr | `1082622447502233a736b148ef191dc33122195223a6370ce00776324acc34f7` |
| O-Ti | `f0bfa99dc765c7a2f3c632113c588a4516d253f78e18f12806d9c9c304a4556a` |
| Sr-Sr | `f5492b8f04dd406b740d53e3406a2e05b99ef09575e6f0fc88c9ee1d489398a6` |
| Sr-Ti | `574d60742a956d3ba0dfe789c4e83dfd4c839174278e992a748516bce00b1388` |
| Ti-Ti | `57cf57d594f16ee75deb1113be0b0d612d1b11a45e89f79e7543546263af7c5a` |

These are exact copies of the corresponding QLIP files at frozen revision
`a619ab379c62b5edefd6bb00076267e149f283ce`.

## Repository and creator evidence

The POT set first appears in reachable QLIP history in commit
`6aed49df639722a1fcfe5b991d1e90551482a5d5` (`needed spps`), authored and
committed on 2026-01-29 by `ChristianBrowning213
<christian.browning213@gmail.com>`. That commit adds nine ordered/mirrored
files but no manifest, command, input record, or provenance note. A committer
identity is custody evidence; it is not proof of who created the parameters or
of permission for underlying data.

QLIP contains `tools/generators/make_srtio3_pots.py`. Its reachable path
history includes commit `be45f2300117862d444020ba9c77866fb03a2f60`, authored
by `ChristianBrowning213 <christian@warmstorm.co>` on 2026-01-23, before the
POT-adding commit. No commit message explicitly connects the script to the
added files.

## Generation and input evidence

The script is self-contained. It reads no CIF, corpus, manifest, or external
data file. It evaluates 800 points from 1.2 to 10.0 Angstrom using a
Born-Mayer term plus Wolf-screened Coulomb term. It hard-codes:

- Sr-O `(A=1769.51, rho=0.319894)`, Ti-O `(14567.40, 0.197584)`, and
  O-O `(6249.17, 0.231472)`;
- charges Sr `+1.84`, Ti `+2.36`, O `-1.40`;
- Wolf alpha `0.2`, cutoff `10.0`, and cation-repulsion scale `0.25`.

An isolated execution of the committed script on the matching Windows text
environment reproduced all six files byte-for-byte, including every SHA-256
above. The exact match is strong evidence that this is the generator, but it
does not supply provenance for the hard-coded parameters. The script does not
fix its output encoding or newline convention, so a future reproducibility
test must also control the text environment.

No QLIP/SPP README, command record, provenance JSON, data manifest, source-CIF
reference, corpus identifier, or citation was found for those parameters. The
script calls them only "literature-style." There is therefore no identifiable
input structure or training corpus to clear.

## External-source comparison and tool evidence

The older `ipcsp-spp` repository was checked because it contains SrTiO
resources. Its `ipcsp2/data/SrTiO/spp.lib` is a differently formatted spline
library, and its `buck.lib` uses different Sr-O, Ti-O, and O-O parameters and
formal charges (`Sr +2`, `Ti +4`, `O -2`). No exact external copy or matching
parameter source was identified. This negative comparison does not prove
independent creation.

The only required generation tool is Python's standard `math` library. QLIP's
MIT licence covers the repository software at the frozen revision, but a
software licence and the ability to recompute numbers do not by themselves
establish the origin or redistribution rights of embedded scientific
parameters.

## Decision

Asset-set classification: **D. provenance unresolved**.

Release classification: **POT_ASSETS_BLOCKED**.

Ticket 14 distribution status: **REMOVED_FROM_PUBLIC_DISTRIBUTION**. The
classification describes the assets; the hashes above remain their deletion
identity.

The generator and likely generation method are identifiable, but the source,
creator authority, citation, and redistribution basis for its hard-coded
scientific parameters are not. Generated numerical data is not presumed
unrestricted.

## Applied fallback

The public distribution omits these six files while leaving QLIP and SPP
scientific algorithms unchanged. It requires user-supplied POT assets and
replaces the bundled offline SrTiO3 demonstration. Production use
already requires an appropriate user-supplied POT root for broader chemistry.
Scientific tests now require `LLM_CSP_EXTERNAL_POT_ROOT` and are marked
`requires_external_scientific_assets`.
