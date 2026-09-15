"""Centralized component-root resolution for the frozen CSV workflow."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT_VARIABLES = (
    "CRYSTAL_DB_ROOT",
    "SPP_MAKER_ROOT",
    "QLIP_ROOT",
    "SCA_ROOT",
)


class ComponentConfigurationError(RuntimeError):
    """Raised when a required external component root is unavailable."""


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ComponentConfigurationError(f"invalid .env line {line_number}: expected NAME=VALUE")
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in ROOT_VARIABLES:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def _git_head(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unavailable"


@dataclass(frozen=True, slots=True)
class ComponentRoots:
    crystal_db: Path
    spp_maker: Path
    qlip: Path
    sca: Path
    repo_root: Path
    dotenv_path: Path

    @classmethod
    def load(
        cls,
        repo_root: Path,
        *,
        environ: dict[str, str] | None = None,
        required: Iterable[str] = ROOT_VARIABLES,
    ) -> "ComponentRoots":
        root = Path(repo_root).resolve()
        dotenv_path = root / ".env"
        dotenv = _parse_dotenv(dotenv_path)
        actual = os.environ if environ is None else environ
        missing: list[str] = []
        resolved: dict[str, Path] = {}
        for name in ROOT_VARIABLES:
            raw_value = actual[name] if name in actual else dotenv.get(name, "")
            raw = str(raw_value or "").strip()
            if not raw:
                if name in set(required):
                    missing.append(f"{name} is not configured")
                resolved[name] = Path("__UNCONFIGURED__").resolve()
                continue
            candidate = Path(os.path.expandvars(os.path.expanduser(raw)))
            if not candidate.is_absolute():
                candidate = root / candidate
            resolved[name] = candidate.resolve()
            if name in set(required) and not resolved[name].is_dir():
                missing.append(f"{name} does not exist or is not a directory: {resolved[name]}")
        if missing:
            source = f"repository .env ({dotenv_path}) and process environment"
            raise ComponentConfigurationError(
                "component-root configuration failed using " + source + ":\n- " + "\n- ".join(missing)
            )
        return cls(
            crystal_db=resolved["CRYSTAL_DB_ROOT"],
            spp_maker=resolved["SPP_MAKER_ROOT"],
            qlip=resolved["QLIP_ROOT"],
            sca=resolved["SCA_ROOT"],
            repo_root=root,
            dotenv_path=dotenv_path,
        )

    def activate_imports(self, *, include_sca: bool = False) -> None:
        roots = [self.crystal_db, self.spp_maker / "src", self.qlip / "src"]
        if include_sca:
            roots.append(self.sca)
        for root in reversed(roots):
            value = str(root.resolve())
            if value not in sys.path:
                sys.path.insert(0, value)

    def as_dict(self) -> dict[str, str]:
        return {
            "CRYSTAL_DB_ROOT": str(self.crystal_db),
            "SPP_MAKER_ROOT": str(self.spp_maker),
            "QLIP_ROOT": str(self.qlip),
            "SCA_ROOT": str(self.sca),
        }

    def provenance(self) -> dict[str, object]:
        paths = self.as_dict()
        return {
            "configuration_source": {
                "dotenv_path": str(self.dotenv_path),
                "environment_overrides_dotenv": True,
                "variable_names": list(ROOT_VARIABLES),
            },
            "resolved_component_roots": paths,
            "repository_heads": {
                "Skill-Loop-CSP": _git_head(self.repo_root),
                "Crystal-DB": _git_head(self.crystal_db),
                "SPP-Maker-QLIP": _git_head(self.spp_maker),
                "qlip": _git_head(self.qlip),
                "Structured_Crystal_Analyser": _git_head(self.sca),
            },
        }

    def diagnostics(self) -> list[dict[str, object]]:
        checks = (
            ("CRYSTAL_DB_ROOT", self.crystal_db, ("crystal_db", "data")),
            ("SPP_MAKER_ROOT", self.spp_maker, ("src",)),
            ("QLIP_ROOT", self.qlip, ("src", "data")),
            ("SCA_ROOT", self.sca, ("sca",)),
        )
        rows = []
        for name, root, children in checks:
            missing = [child for child in children if not (root / child).exists()]
            rows.append(
                {
                    "variable": name,
                    "status": "PASS" if root.is_dir() and not missing else "FAIL",
                    "resolved_root": str(root),
                    "required_subpaths": [str(root / child) for child in children],
                    "missing_subpaths": missing,
                }
            )
        return rows


__all__ = [
    "ComponentConfigurationError",
    "ComponentRoots",
    "ROOT_VARIABLES",
]
