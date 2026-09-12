# Installation

## Requirements

- Python 3.11 or newer.
- A supported Gurobi installation and usable licence for solving (not needed
  for the installation smoke).

From a repository clone, the supported integrated installation is:

~~~shell
python -m pip install .
~~~

This installs llm_csp, qlip, and crystal_db. It does not install SCA: the
upstream SCA revision has no explicit licence, so Ticket 11 removed its Git URL
from the public package metadata. The lazy validation adapter remains usable
only with a separately authorized compatible backend supplied by the user.
Developers may use:

~~~shell
python -m pip install -e ".[test]"
~~~

The nested packages/qlip and packages/crystal_db projects remain independently
buildable, but integrated users do not install them separately.

## Offline verification

~~~shell
llm-csp demo --output ./runs
~~~

The command needs no production database, LM Studio endpoint, POT tree,
Gurobi, or network. It validates software boundaries and writes `smoke.json`;
it performs no optimization and produces no scientific prediction. The public
package does not provide an SCA installation command.

## Production configuration

Copy configs/examples/srtio3_production.json, replace its obvious placeholders,
then run llm-csp run --config CONFIG --json. Supply:

- a Crystal-DB database containing the matching text/index identity;
- the LM Studio-compatible endpoint settings from .env.example;
- a compatible user-supplied regulator POT root with every required pair, or
  POTs fitted/generated from evidence the user is entitled to use;
- a finite QLIP design space and solver limits;
- a caller-owned output root.

No source-repository checkout is consulted at runtime. See
docs/external_assets.md for the complete asset contract.

## CLI exit codes

| Code | Meaning |
| ---: | --- |
| 0 | completed successfully |
| 2 | invalid command, JSON, or workflow configuration |
| 3 | required runtime/backend unavailable, including validation unavailable |
| 4 | scientific run blocked or failed |

With --json, configuration errors and workflow results are machine-readable.
