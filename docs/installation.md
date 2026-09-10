# Installation

## Requirements

- Python 3.11 or newer.
- A supported Gurobi installation and usable licence for solving.
- Git and network access while installing the optional pinned SCA extra.

From a repository clone, the supported integrated installation is:

~~~shell
python -m pip install ".[validation]"
~~~

This installs llm_csp, qlip, and crystal_db plus the pinned SCA backend.
Developers may use:

~~~shell
python -m pip install -e ".[validation,test]"
~~~

The nested packages/qlip and packages/crystal_db projects remain independently
buildable, but integrated users do not install them separately.

## Offline verification

~~~shell
llm-csp demo --output ./runs
~~~

The command needs no production database, LM Studio endpoint, broad POT tree,
or network. It does require Gurobi and, for a fully successful validation
result, the validation extra.

## Production configuration

Copy configs/examples/srtio3_production.json, replace its obvious placeholders,
then run llm-csp run --config CONFIG --json. Supply:

- a Crystal-DB database containing the matching text/index identity;
- the LM Studio-compatible endpoint settings from .env.example;
- a broad regulator POT root with every required pair;
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
