"""Portable Crystal-DB retrieval and CSP-evidence package."""

from importlib.metadata import PackageNotFoundError, version

from .api import backend_status, make_csp_pack, retrieve_text
from .csp_pack import run_csp_pack
from .retrieval import text_search

try:
    __version__ = version("crystal-db")
except PackageNotFoundError:
    # The integrated llm-csp distribution also contains this namespace.
    __version__ = version("llm-csp")

__all__ = ["backend_status", "make_csp_pack", "retrieve_text", "run_csp_pack", "text_search"]
