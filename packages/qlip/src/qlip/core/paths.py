from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List

from qlip.resources import bundled_spp_root, package_root


def find_repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for parent in [here] + list(here.parents):
        if (parent / ".git").exists():
            return parent
        if (parent / "docs").exists() and (parent / "src").exists():
            return parent
    return here


def _split_allowed_roots(value: str) -> List[str]:
    if not value:
        return []
    if ";" in value:
        return [v for v in value.split(";") if v]
    if os.name != "nt":
        return [v for v in value.split(":") if v]
    matches = list(re.finditer(r"[A-Za-z]:(?:\\\\|/)", value))
    if len(matches) <= 1:
        return [value]
    parts = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(value)
        parts.append(value[start:end])
    return [p for p in parts if p]


def allowed_path_roots() -> List[Path]:
    env = os.environ.get("QLIP_ALLOWED_PATH_ROOTS", "")
    if env:
        parts = _split_allowed_roots(env)
        return [Path(p).expanduser().resolve() for p in parts if p]

    package = package_root()
    return [
        Path.cwd().resolve(),
        package,
        bundled_spp_root(),
    ]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        return path.is_relative_to(root)
    except AttributeError:
        return os.path.commonpath([str(path), str(root)]) == str(root)


def resolve_and_check_path(path: str | Path, allowed_roots: Iterable[Path], must_exist: bool = True) -> Path:
    p = Path(path).expanduser()
    resolved = p.resolve()
    if must_exist and not resolved.exists():
        raise ValueError(f"Rejected path (does not exist). path={resolved}")

    for root in allowed_roots:
        root_resolved = Path(root).expanduser().resolve()
        if _is_relative_to(resolved, root_resolved):
            return resolved

    roots = [str(Path(r).expanduser().resolve()) for r in allowed_roots]
    raise ValueError(f"Rejected path (not in allowed roots). path={resolved} allowed_roots={roots}")
