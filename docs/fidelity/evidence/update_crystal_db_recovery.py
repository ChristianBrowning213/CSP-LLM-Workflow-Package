"""Generate Ticket 24 Crystal-DB recovery evidence deterministically."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
REVISION = "e33d5cc55be01f800a7cf055cc1793d982deb5bc"
PACKAGE = ROOT / "packages" / "crystal_db"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tree_details(root: Path) -> tuple[int, int, str]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    total = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        file_hash = sha256(path)
        size = path.stat().st_size
        total += size
        digest.update(f"{relative}\0{size}\0{file_hash}\n".encode())
    return len(files), total, digest.hexdigest()


def source_manifest() -> None:
    paths = subprocess.check_output(
        ["git", "-C", str(SOURCE), "ls-tree", "-r", "--name-only", REVISION],
        text=True,
        encoding="utf-8",
    ).splitlines()
    output = ROOT / "docs" / "fidelity" / "evidence" / "CRYSTAL_DB_SOURCE_MANIFEST.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_revision", "source_path", "size_bytes", "sha256", "archive_disposition"])
        for source_path in paths:
            payload = subprocess.check_output(["git", "-C", str(SOURCE), "show", f"{REVISION}:{source_path}"])
            writer.writerow([REVISION, source_path, len(payload), hashlib.sha256(payload).hexdigest(), disposition(source_path)])


def disposition(path: str) -> str:
    restored = (
        "crystal_db/", "mcp_server/", "tests/", "scripts/", "configs/", "benchmarks/",
        "demo_cifs/", "data/", "examples/",
    )
    if path.startswith(restored) or path in {
        "config.yaml", "policies.yaml", "pyproject.toml", "requirements-dev.txt",
        "eval_phase2.py", "eval_phase4.py", "eval_phase6.py", "demo_phase0.py",
        "demo_phase1.py", "grab_mp_bulk.py", "Visualise.py", "EVAL_PROTOCOL.md",
        "LEGAL_DATA_POLICY.md",
    }:
        return "RESTORED"
    return "HISTORICAL_NON_RUNTIME"


def asset_manifest() -> list[dict[str, str]]:
    data_root = SOURCE / "data"
    tracked = set(subprocess.check_output(["git", "-C", str(SOURCE), "ls-files"], text=True, encoding="utf-8").splitlines())
    rows: list[dict[str, str]] = []
    for path in sorted(data_root.iterdir()):
        relative = path.relative_to(SOURCE).as_posix()
        if path.is_dir():
            count, size, digest = tree_details(path)
            asset_type = "CIF_CORPUS" if path.name == "mp_stable_10k" else "GENERATED_INDEX_OR_OUTPUT"
            role = "canonical retrieval CIF corpus" if path.name == "mp_stable_10k" else "generated cache, calibration, benchmark, or specialist corpus"
            required = "yes" if path.name in {"mp_stable_10k"} else "no_or_workflow_specific"
            recreatable = "yes_from_database_or_acquisition" if path.name != "mp_stable_10k" else "only_from_original_acquisition"
            notes = f"directory tree: {count} files"
        else:
            size, digest = path.stat().st_size, sha256(path)
            asset_type = "RUNTIME_DATABASE" if path.suffix == ".db" else "BENCHMARK_CASES_OR_FIXTURE"
            role = "canonical retrieval database" if path.name == "phase6_mp_10k.db" else "specialist database, benchmark cases, or transient fixture"
            required = "yes" if path.name == "phase6_mp_10k.db" else "no_or_workflow_specific"
            recreatable = "yes_from_source_corpus" if path.suffix == ".db" else "source_dependent"
            notes = "single file"
        rows.append({
            "source_path": str(path), "type": asset_type, "size": str(size), "SHA256": digest,
            "tracked_or_local": "tracked" if relative in tracked else "local_ignored_or_untracked",
            "runtime_role": f"{role}; {notes}", "required_for_default_workflow": required,
            "recreatable": recreatable, "provenance_status": "REQUIRES_TICKET_25_REVIEW",
            "redistribution_status": "PENDING_TICKET_25", "recommended_archive_path": f"data/crystal_db/{path.name}",
        })
    artifacts = SOURCE / "artifacts"
    count = sum(1 for path in artifacts.rglob("*") if path.is_file())
    size = sum(path.stat().st_size for path in artifacts.rglob("*") if path.is_file())
    rows.append({
        "source_path": str(artifacts), "type": "GENERATED_OUTPUT", "size": str(size),
        "SHA256": "DEFERRED_TICKET_25_PER_FILE_SELECTION", "tracked_or_local": "mixed_tracked_and_local",
        "runtime_role": f"generated reports/benchmarks ({count} files); not a default runtime database",
        "required_for_default_workflow": "no", "recreatable": "mixed",
        "provenance_status": "REQUIRES_CANONICAL_SUBSET_SELECTION", "redistribution_status": "PENDING_TICKET_25",
        "recommended_archive_path": "data/crystal_db/evidence/<approved-subset>",
    })
    output = ROOT / "docs" / "fidelity" / "CRYSTAL_DB_ASSET_MANIFEST.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        fields = ["source_path", "type", "size", "SHA256", "tracked_or_local", "runtime_role", "required_for_default_workflow", "recreatable", "provenance_status", "redistribution_status", "recommended_archive_path"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def mcp_surface() -> None:
    sys.path.insert(0, str(PACKAGE / "src"))
    from mcp_server import server  # noqa: PLC0415

    output_schemas = {
        "crystal.text_search": "text_search.v1.schema.json",
        "crystal.agent": "agent.v1.schema.json",
        "crystal.novelty_check": "novelty_check.v1.schema.json",
        "crystal.csp_pack": "csp_pack.v1.schema.json",
        "crystal.status": "backend_status.v1.schema.json",
        "crystal.bench_retrieval": "bench_retrieval.v1.schema.json",
    }
    tools = []
    for name, spec in server.TOOL_REGISTRY.items():
        schema_name = output_schemas[name]
        schema = json.loads((PACKAGE / "src" / "crystal_db" / "schemas" / schema_name).read_text(encoding="utf-8-sig"))
        tools.append({
            "kind": "tool", "name": name, "source_implementation": f"mcp_server.server.{spec.handler.__name__}",
            "input_schema": spec.input_schema, "output_schema": schema,
            "archive_implementation": f"mcp_server.server.{spec.handler.__name__}", "parity_status": "EXACT_EXCEPT_PATH_RELOCATION",
        })
    payload = {
        "source_revision": REVISION,
        "server": "mcp_server.server",
        "transport": "stdio; FastMCP when available with JSON-RPC stdio fallback",
        "tools": tools,
        "resources": [],
        "prompts": [],
    }
    (ROOT / "docs" / "fidelity" / "crystal_db_mcp_surface.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def update_matrix(asset_rows: list[dict[str, str]]) -> None:
    matrix = ROOT / "docs" / "fidelity" / "SOURCE_TO_ARCHIVE_MATRIX.csv"
    with matrix.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    for field in ("recovery_ticket", "recovery_status", "recovery_archive_path"):
        if field not in fields:
            fields.append(field)
    # Keep this evidence generator safe to rerun: replace, rather than append,
    # the Ticket 24 synthetic rows that describe local production assets.
    rows = [
        row for row in rows
        if not (
            row["source_repo"] == "Crystal-DB"
            and row.get("recovery_ticket") == "24"
            and row.get("source_entry_point") == "local runtime asset"
        )
    ]
    for row in rows:
        if row["source_repo"] != "Crystal-DB":
            continue
        path = row["source_path_or_capability"]
        status = disposition(path)
        row["recovery_ticket"] = "24"
        row["recovery_status"] = status
        row["recovery_archive_path"] = archive_path(path) if status == "RESTORED" else ""
    for asset in asset_rows:
        rows.append({
            "source_repo": "Crystal-DB", "source_revision": REVISION,
            "source_path_or_capability": asset["source_path"], "source_entry_point": "local runtime asset",
            "source_tests": "source suite / canonical workflow", "archive_path": "", "classification": "EXTERNALIZED_BUT_ORIGINALLY_LOCAL",
            "behaviour_parity": "DEFERRED", "data_dependency": asset["runtime_role"], "external_dependency": "",
            "notes": "Production/local asset inventoried but not copied by Ticket 24.", "recommended_action": "Ticket 25 provenance and asset restoration",
            "recovery_ticket": "24", "recovery_status": "ASSET_DEFERRED_TO_TICKET_25", "recovery_archive_path": asset["recommended_archive_path"],
        })
    with matrix.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def archive_path(path: str) -> str:
    if path.startswith("crystal_db/"):
        return f"packages/crystal_db/src/{path}"
    if path.startswith("mcp_server/"):
        return f"packages/crystal_db/src/{path}"
    return f"packages/crystal_db/{path}"


if __name__ == "__main__":
    source_manifest()
    assets = asset_manifest()
    mcp_surface()
    update_matrix(assets)
    print("Crystal-DB recovery evidence updated")
