"""Generate read-only, revision-addressed source-fidelity evidence tables."""

from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tarfile
import ast


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent
REPOSITORIES = (
    ("Skill-Loop-CSP", Path(r"C:\Users\brown\Documents\GitHub\Skill-Loop-CSP"),
     "b2130661b4690623877e852dc03132506aa720dd", None),
    ("Crystal-DB", Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB"),
     "e33d5cc55be01f800a7cf055cc1793d982deb5bc", None),
    ("SPP-Maker-QLIP", Path(r"C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP"),
     "3a2d557811973265f3373ec881cc8057a89789d2", None),
    ("qlip", Path(r"C:\Users\brown\Documents\GitHub\qlip"),
     "a619ab379c62b5edefd6bb00076267e149f283ce", None),
    ("Structured_Crystal_Analyser", Path(r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser"),
     "e5b291312151f34949a5e6ef0f43bebfeb752bc9", None),
    ("CSP-LLM-Workflow-Package", ROOT, "206ea8ecd9acc25e813e676359929fd7ad3efc0f",
     ("src/", "packages/", "configs/", "data/", "examples/", "scripts/", "tests/")),
)


def evidence(path: str) -> tuple[str, str, str]:
    lower = path.lower()
    runtime = ""
    tests = ""
    config = ""
    if lower.startswith(("src/", "crystal_db/", "sca/")) or "/src/" in lower:
        runtime = "executable source/package module"
    elif lower.startswith(("scripts/", "mcp_server/", "tools/")):
        runtime = "script, tool, or server entry-point candidate"
    elif lower.startswith(("data/", "prompts/", "skills/", "reference_sets/")):
        runtime = "runtime/resource candidate; disposition requires call-site evidence"
    if lower.startswith("tests/") or "/tests/" in lower:
        tests = "source test or test fixture"
    if lower.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".schema")):
        config = "structured configuration/schema/resource candidate"
    return runtime, tests, config


def file_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return suffix[1:] if suffix else "extensionless"


def revision_rows(name: str, repo: Path, revision: str, roots: tuple[str, ...] | None):
    process = subprocess.Popen(
        ["git", "-C", str(repo), "archive", "--format=tar", revision],
        stdout=subprocess.PIPE,
    )
    assert process.stdout is not None
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                path = member.name.replace("\\", "/")
                if roots is not None and not path.startswith(roots):
                    continue
                stream = archive.extractfile(member)
                assert stream is not None
                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                runtime, tests, config = evidence(path)
                yield (
                    name, revision, path, member.size, digest.hexdigest(), file_type(path),
                    "tracked_at_revision", runtime, tests, config,
                )
    finally:
        process.stdout.close()
        returncode = process.wait()
        if returncode not in (0, 141):
            raise RuntimeError(f"git archive failed for {name}: {returncode}")


def write_revision_inventory() -> None:
    path = OUTPUT / "FILE_INVENTORY.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow((
            "repository", "revision", "path", "size_bytes", "sha256", "file_type",
            "tracked_status", "runtime_import_or_use_evidence", "test_use_evidence",
            "configuration_use_evidence",
        ))
        for values in REPOSITORIES:
            writer.writerows(revision_rows(*values))


ASSET_ROOTS = {
    "Skill-Loop-CSP": ("data", "artifacts", "out", "outputs", "runs", "reports", "prompts", "config", "memory"),
    "Crystal-DB": ("data", "demo_cifs", "artifacts", "tmp", "configs"),
    "SPP-Maker-QLIP": ("data", "QLIP_Outputs", "artifacts", "out", "rules"),
    "qlip": ("data", "artifacts"),
    "Structured_Crystal_Analyser": ("data", "reference_sets", "reports", "configs"),
}


def directory_summary(root: Path) -> tuple[int, int]:
    count = 0
    size = 0
    for parent, directories, files in os.walk(root):
        directories[:] = [item for item in directories if item not in {
            ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "OMatG",
        }]
        for name in files:
            path = Path(parent, name)
            try:
                size += path.stat().st_size
                count += 1
            except OSError:
                continue
    return count, size


def write_local_asset_summary() -> None:
    lookup = {name: repo for name, repo, _, _ in REPOSITORIES}
    with (OUTPUT / "LOCAL_ASSET_SUMMARY.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("repository", "path", "exists", "file_count", "size_bytes", "note"))
        for name, roots in ASSET_ROOTS.items():
            repo = lookup[name]
            for relative in roots:
                path = repo / relative
                count, size = directory_summary(path) if path.exists() else (0, 0)
                writer.writerow((
                    name, relative, path.exists(), count, size,
                    "working-tree observation; may combine tracked, ignored, generated, and runtime files",
                ))


_ENV_PATTERNS = (
    re.compile(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"os\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]"),
)
_SIBLING_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/][^\n'\"]*GitHub[^\n'\"]*|\.\.[\\/](?:qlip|Crystal-DB|SPP-Maker-QLIP|Structured_Crystal_Analyser|Skill-Loop-CSP)[^\s'\"]*)",
    re.IGNORECASE,
)


def source_evidence_rows(name: str, repo: Path, revision: str, roots: tuple[str, ...] | None):
    process = subprocess.Popen(
        ["git", "-C", str(repo), "archive", "--format=tar", revision],
        stdout=subprocess.PIPE,
    )
    assert process.stdout is not None
    symbols: list[tuple] = []
    environment: list[tuple] = []
    paths: list[tuple] = []
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                if not member.isfile() or member.size > 5_000_000:
                    continue
                path = member.name.replace("\\", "/")
                if roots is not None and not path.startswith(roots):
                    continue
                if Path(path).suffix.lower() not in {".py", ".toml", ".yaml", ".yml", ".json", ".md", ".txt"}:
                    continue
                stream = archive.extractfile(member)
                assert stream is not None
                text = stream.read().decode("utf-8", errors="replace")
                if path.endswith(".py"):
                    try:
                        tree = ast.parse(text)
                    except SyntaxError:
                        tree = None
                    if tree is not None:
                        for node in tree.body:
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                                symbols.append((name, revision, path, node.lineno, kind, node.name))
                for pattern in _ENV_PATTERNS:
                    for match in pattern.finditer(text):
                        line = text.count("\n", 0, match.start()) + 1
                        environment.append((name, revision, path, line, match.group(1)))
                for match in _SIBLING_PATTERN.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    paths.append((name, revision, path, line, " ".join(match.group(0).split())[:500]))
    finally:
        process.stdout.close()
        returncode = process.wait()
        if returncode not in (0, 141):
            raise RuntimeError(f"git archive evidence pass failed for {name}: {returncode}")
    return symbols, environment, paths


def write_source_evidence() -> None:
    symbol_rows: list[tuple] = []
    env_rows: list[tuple] = []
    path_rows: list[tuple] = []
    for values in REPOSITORIES:
        symbols, environment, paths = source_evidence_rows(*values)
        symbol_rows.extend(symbols)
        env_rows.extend(environment)
        path_rows.extend(paths)
    outputs = (
        ("SOURCE_SYMBOLS.csv", ("repository", "revision", "path", "line", "kind", "symbol"), symbol_rows),
        ("ENVIRONMENT_VARIABLES.csv", ("repository", "revision", "path", "line", "variable"), sorted(set(env_rows))),
        ("SIBLING_PATH_REFERENCES.csv", ("repository", "revision", "path", "line", "reference"), sorted(set(path_rows))),
    )
    for filename, header, rows in outputs:
        with (OUTPUT / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_revision_inventory()
    write_local_asset_summary()
    write_source_evidence()
