from __future__ import annotations

from pathlib import Path
from typing import Any


class PathSandboxError(ValueError):
    pass


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_allowed_path(path: str | Path, allowed_roots: list[Path]) -> Path:
    resolved = Path(path).resolve()
    resolved_roots = [root.resolve() for root in allowed_roots]
    if any(_is_relative_to(resolved, root) for root in resolved_roots):
        return resolved
    raise PathSandboxError(f"path_not_allowed: {resolved}")


def validate_paths_in_args(
    args: dict[str, Any],
    read_keys: list[str],
    write_keys: list[str],
    allowed_read_roots: list[Path],
    allowed_write_roots: list[Path],
) -> None:
    for key in read_keys:
        value = args.get(key)
        if isinstance(value, str) and value:
            ensure_allowed_path(value, allowed_read_roots)
    for key in write_keys:
        value = args.get(key)
        if isinstance(value, str) and value:
            ensure_allowed_path(value, allowed_write_roots)
