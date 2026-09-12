# Release dependency matrix

The integrated llm-csp wheel contains llm_csp, qlip, and crystal_db. Public
metadata provides test and validation extras. The validation extra pins the
separately maintained, MIT-licensed SCA 0.1.1 package; MCP extras remain
available only on the component projects.

| Dependency | Class | Required by | Installation | Import? | Offline demo? | Production retrieval? | Solver? | Extra / notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Python >=3.11 | CORE | Integrated stack | System | Yes | Yes | Yes | Yes | QLIP sets the effective floor |
| ASE | CORE | SPP, QLIP, demo | pip | SPP operations | Yes | No | Yes | |
| NumPy | CORE | SPP, QLIP | pip | Some modules | Yes | No | Yes | |
| SciPy | CORE | QLIP | pip | QLIP | Yes | No | Yes | |
| PyYAML | CORE | SPP configuration | pip | No | Yes | No | No | |
| Pymatgen | CORE | QLIP/topology handoff | pip | QLIP | Yes | No | Yes | |
| Pyomo | CORE | QLIP | pip | QLIP | Yes | No | Yes | |
| gurobipy | CORE | QLIP | pip | QLIP | Yes | No | Yes | Native runtime/licence also required |
| Crystal-DB code | CORE | Retrieval adapter | Included namespace | No (lazy workflow use) | Fixture bypasses production call | Yes | No | |
| QLIP code | CORE | Workflow | Included namespace | Workflow surface | Yes | No | Yes | |
| SCA 0.1.1 | OPTIONAL | Validation adapter | Root `validation` extra, pinned to licensed commit `3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af` | No (lazy) | Optional | No | No | Candidate is preserved if absent |
| pandas, pydantic, rich, tqdm, typer | OPTIONAL | SCA | Installed transitively only by the validation extra | Only when SCA loads | Optional | No | No | SCA base dependencies |
| ALIGNN | EXTERNAL_SYSTEM | External SCA model evaluation | Not declared by this distribution | No | No | No | No | Not supported by default path |
| jsonschema | CORE | QLIP request validation | pip | No for top-level import | Yes | No | Before solve | Crystal-DB can also use it for full schema validation |
| mcp | OPTIONAL/TEST | Crystal-DB and QLIP MCP servers/tests | component mcp extras or root test extra | No | No | No | No | MCP is not used by workflow |
| pytest | TEST | Test suite | test extras | No | No | No | No | |
| setuptools, wheel, build | BUILD | Distribution build | Isolated build environment | No | No | No | No | Not runtime dependencies |
| Gurobi native runtime/licence | EXTERNAL_SYSTEM | QLIP | Gurobi vendor | No | Yes | No | Yes | No fallback solver |
| LM Studio-compatible service | EXTERNAL_SYSTEM | Crystal-DB text retrieval | User managed | No | No | Yes in lmstudio mode | No | |
| BGE-M3 model | EXTERNAL_DATA | Crystal-DB | User supplied | No | No | Yes in canonical production mode | No | Must match index identity/dimension |
| Crystal-DB SQLite/index | EXTERNAL_DATA | Crystal-DB | User supplied | No | No | Yes | No | Not bundled |
| Broad regulator POT tree | EXTERNAL_DATA | SPP/QLIP | User supplied | No | No | Indirectly | Yes for production chemistry | No scientific POT is bundled; an explicit compatible root is required |

Version strategy: llm-csp, crystal-db, and qlip use synchronized 0.1.0 versions
for the first integrated contract. SCA is independently versioned at 0.1.1 and
is pinned by exact licensed Git revision.
