"""Hash non-transient files present in the five source worktrees into a compressed CSV."""

from __future__ import annotations

import csv
import gzip
import hashlib
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPOS = {
    "Skill-Loop-CSP": Path(r"C:\Users\brown\Documents\GitHub\Skill-Loop-CSP"),
    "Crystal-DB": Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB"),
    "SPP-Maker-QLIP": Path(r"C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP"),
    "qlip": Path(r"C:\Users\brown\Documents\GitHub\qlip"),
    "Structured_Crystal_Analyser": Path(r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser"),
}
EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist", ".tox", ".mypy_cache", ".ruff_cache", ".codex_pytest_tmp", ".tmp_pytest"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    output = HERE / "LOCAL_FILE_INVENTORY.csv.gz"
    with gzip.open(output, "wt", newline="", encoding="utf-8", compresslevel=6) as stream:
        writer = csv.writer(stream)
        writer.writerow(["repository", "path", "size_bytes", "sha256", "tracked_status"])
        for name, root in REPOS.items():
            tracked = set(subprocess.check_output(["git", "-C", str(root), "ls-files"], text=True, encoding="utf-8").splitlines())
            for path in root.rglob("*"):
                try:
                    relative = path.relative_to(root).as_posix()
                    if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
                        continue
                    if not path.is_file() or path.suffix.lower() in EXCLUDED_SUFFIXES:
                        continue
                    writer.writerow([name, relative, path.stat().st_size, digest(path), "tracked" if relative in tracked else "untracked_or_ignored"])
                except (OSError, PermissionError):
                    writer.writerow([name, relative, "", "", "unreadable"])
    print(output)


if __name__ == "__main__":
    main()
