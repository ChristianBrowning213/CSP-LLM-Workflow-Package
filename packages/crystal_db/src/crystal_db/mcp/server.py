"""Compatibility alias for the source-faithful :mod:`mcp_server.server`."""

from mcp_server import server as _source_server

globals().update(
    {
        name: value
        for name, value in vars(_source_server).items()
        if not (name.startswith("__") and name.endswith("__"))
    }
)


if __name__ == "__main__":  # pragma: no cover - delegated entry point
    raise SystemExit(_source_server.main())
