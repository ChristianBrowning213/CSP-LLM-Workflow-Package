"""Build the reproducible file-level source-to-archive fidelity matrix."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
OUTPUT = ROOT / "docs" / "fidelity" / "SOURCE_TO_ARCHIVE_MATRIX.csv"

FIELDS = [
    "source_repo", "source_revision", "source_path_or_capability", "source_entry_point",
    "source_tests", "archive_path", "classification", "behaviour_parity", "data_dependency",
    "external_dependency", "notes", "recommended_action",
]

REVISIONS = {
    "Skill-Loop-CSP": "b2130661b4690623877e852dc03132506aa720dd",
    "Crystal-DB": "e33d5cc55be01f800a7cf055cc1793d982deb5bc",
    "SPP-Maker-QLIP": "3a2d557811973265f3373ec881cc8057a89789d2",
    "qlip": "a619ab379c62b5edefd6bb00076267e149f283ce",
    "Structured_Crystal_Analyser": "e5b291312151f34949a5e6ef0f43bebfeb752bc9",
}


def candidate(repo: str, path: str) -> str:
    if repo == "qlip" and path.startswith("src/qlip/"):
        return "packages/qlip/" + path
    if repo == "Crystal-DB":
        if path.startswith("crystal_db/"):
            return "packages/crystal_db/src/" + path
        if path == "mcp_server/server.py":
            return "packages/crystal_db/src/crystal_db/mcp/server.py"
    if repo == "SPP-Maker-QLIP" and path.startswith("src/spp_maker/"):
        name = path.removeprefix("src/spp_maker/")
        if name in {
            "compat.py", "fit_hist.py", "fit_phi.py", "io_cif.py", "model.py",
            "neighbors.py", "pot_io.py", "score.py", "weights_csv.py",
        }:
            return "src/llm_csp/spp/" + name.replace("weights_csv.py", "weights.py")
    if repo == "Skill-Loop-CSP" and path.startswith("src/sok_llm_orchestrator/workflow/"):
        name = path.removeprefix("src/sok_llm_orchestrator/workflow/")
        proposed = "src/llm_csp/workflow/" + name
        return proposed
    return ""


def entry_point(repo: str, path: str) -> str:
    if path.endswith("__main__.py") or path.endswith("cli.py"):
        return "CLI/module entry point"
    if "mcp" in path.lower() and path.endswith("server.py"):
        return "MCP server entry point"
    if repo == "Skill-Loop-CSP" and "agentic/" in path and path.endswith("runtime.py"):
        return "agent runtime"
    if path.endswith("api.py"):
        return "Python API"
    return ""


def main() -> None:
    rows = list(csv.DictReader((EVIDENCE / "FILE_INVENTORY.csv").open(encoding="utf-8")))
    archive = {r["path"]: r for r in rows if r["repository"] == "CSP-LLM-Workflow-Package"}
    out = []
    for row in rows:
        repo, path = row["repository"], row["path"]
        if repo not in REVISIONS:
            continue
        target = candidate(repo, path)
        found = archive.get(target) if target else None
        if found:
            exact = row["sha256"] == found["sha256"]
            classification = "PRESERVED_EXACT" if exact else "PRESERVED_ADAPTED_WITH_PROVEN_PARITY"
            evidence = "SHA-256 identity" if exact else "Mapped implementation exists; parity is supported only where archive tests exercise it"
            action = "none" if exact else "retain adaptation evidence; restore original if parity is not demonstrated"
        elif any(part in path for part in ("data/", "QLIP_Outputs/", "artifacts/", "demo_cifs/")):
            classification = "EXTERNALIZED_BUT_ORIGINALLY_LOCAL"
            evidence = "Original tracked/local-data convention has no archive counterpart"
            action = "archive with provenance or document an approved exclusion"
        elif path.startswith(("tests/", "test/")) or "/tests/" in path or path.startswith(("docs/", "reports/", "examples/", "scripts/", "tools/")):
            classification = "HISTORICAL_NOT_SELECTED_SYSTEM"
            evidence = "No direct archive mapping; retained as source evidence/supporting material"
            action = "review when restoring the associated operational surface"
        else:
            classification = "MISSING_FROM_ARCHIVE"
            evidence = "No path-level counterpart in unified archive"
            action = "restore preserving namespace and behavior"
        out.append({
            "source_repo": repo,
            "source_revision": REVISIONS[repo],
            "source_path_or_capability": path,
            "source_entry_point": entry_point(repo, path),
            "source_tests": "source repository tests" if "test" not in path.lower() else path,
            "archive_path": target if found else "",
            "classification": classification,
            "behaviour_parity": "EXACT" if found and exact else ("PARTIAL_OR_UNPROVEN" if found else "ABSENT"),
            "data_dependency": "local resource candidate" if classification == "EXTERNALIZED_BUT_ORIGINALLY_LOCAL" else "",
            "external_dependency": "",
            "notes": evidence,
            "recommended_action": action,
        })

    new_paths = [
        "src/llm_csp/agentic/models.py", "src/llm_csp/agentic/state.py",
        "src/llm_csp/agentic/budgets.py", "src/llm_csp/agentic/approvals.py",
        "src/llm_csp/agentic/termination.py", "src/llm_csp/agentic/contracts.py",
        "src/llm_csp/agentic/model/", "src/llm_csp/agentic/planner.py",
        "src/llm_csp/agentic/tools/",
    ]
    for path in new_paths:
        out.append({
            "source_repo": "archive", "source_revision": "206ea8ecd9acc25e813e676359929fd7ad3efc0f",
            "source_path_or_capability": "", "source_entry_point": "v0.2 agentic API", "source_tests": "tests/unit/agentic; tests/integration/agentic",
            "archive_path": path, "classification": "NEW_NOT_IN_SOURCE",
            "behaviour_parity": "NEW_REPLACEMENT", "data_dependency": "", "external_dependency": "",
            "notes": "Ticket 18-21 implementation; no structural counterpart in frozen Skill-Loop agentic runtime",
            "recommended_action": "isolate as archive-native work; do not claim source fidelity",
        })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out)
    print(f"wrote {len(out)} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
