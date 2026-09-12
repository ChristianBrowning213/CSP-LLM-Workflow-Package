"""Paths to QLIP's small, wheel-bundled runtime resources."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def package_root() -> Path:
    """Return the installed QLIP package directory."""
    return Path(str(files("qlip"))).resolve()


def base_data_root() -> Path:
    """Return the bundled chemistry/base-data directory."""
    return Path(str(files("qlip.resources").joinpath("base"))).resolve()


def bundled_spp_root() -> Path:
    """Report that scientific POT assets are intentionally external."""
    raise RuntimeError(
        "QLIP does not distribute scientific POT assets; provide pot_root or set "
        "QLIP_SPP_POT_DIR to a compatible user-supplied POT library"
    )


def schema_path(name: str) -> Path:
    """Return one bundled runtime schema by file name."""
    return Path(str(files("qlip.resources").joinpath("schemas", name))).resolve()


__all__ = ["base_data_root", "bundled_spp_root", "package_root", "schema_path"]
