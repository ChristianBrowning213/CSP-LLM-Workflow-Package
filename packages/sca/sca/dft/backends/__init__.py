"""DFT backend registry."""

from sca.dft.backends.base import DFTBackend
from sca.dft.backends.castep import CastepBackend


def get_backend(name: str) -> DFTBackend:
    normalized = name.strip().lower()
    if normalized == "castep":
        return CastepBackend()
    raise KeyError(f"Unknown DFT backend {name!r}. Available: castep")


__all__ = ["CastepBackend", "DFTBackend", "get_backend"]

