from importlib.metadata import PackageNotFoundError, version

from qlip.core.solve import solve

try:
    __version__ = version("qlip")
except PackageNotFoundError:
    # The integrated llm-csp distribution also contains this namespace.
    __version__ = version("llm-csp")

__all__ = ["solve"]
