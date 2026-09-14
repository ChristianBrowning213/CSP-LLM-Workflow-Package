# Crystal-DB MCP Server

This server exposes Crystal-DB APIs as MCP tools over stdio JSON-RPC.

## Run (PowerShell)

```powershell
Set-Location C:\Users\brown\Documents\GitHub\Crystal-DB
python -m mcp_server.server
```

## Environment Variables

```powershell
$env:CRYSTALDB_PATH = "data\phase6_mp_10k.db"
$env:CRYSTALDB_CONFIG = "configs\retrieval_defaults.json"
$env:CRYSTALDB_POLICY_MODE = "safe"   # safe|demo
```

Relative `CRYSTALDB_PATH` and `CRYSTALDB_CONFIG` values are resolved against the Crystal-DB repo root, so the server can be launched from an external working directory without silently creating a fresh empty database.

LM Studio embedding backend variables (already used by Crystal-DB):

```powershell
$env:CRYSTALDB_EMBED_BASE_URL = "http://127.0.0.1:1234/v1"
$env:CRYSTALDB_EMBED_API_KEY = "lm-studio"
$env:CRYSTALDB_EMBED_TIMEOUT_S = "30"
```

## Claude Desktop / Claude Code MCP Config Example

```json
{
  "mcpServers": {
    "crystal-db": {
      "command": "python",
      "args": [
        "-m",
        "mcp_server.server"
      ],
      "cwd": "C:\\Users\\brown\\Documents\\GitHub\\Crystal-DB",
      "env": {
        "CRYSTALDB_PATH": "data\\phase6_mp_10k.db",
        "CRYSTALDB_CONFIG": "configs\\retrieval_defaults.json",
        "CRYSTALDB_POLICY_MODE": "safe"
      }
    }
  }
}
```

## Exposed Tool Names

- `crystal.text_search`
- `crystal.agent`
- `crystal.novelty_check`
- `crystal.csp_pack`
- `crystal.status`
- `crystal.bench_retrieval`
