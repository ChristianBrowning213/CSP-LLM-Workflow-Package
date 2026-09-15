from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CapViolationError(ValueError):
    pass


@dataclass(slots=True)
class Caps:
    max_cif_count: int
    max_runtime_seconds: int
    max_output_bytes: int


def enforce_requested_caps(args: dict[str, Any], caps: Caps) -> None:
    timeout = args.get("timeout_seconds")
    if timeout is not None and int(timeout) > caps.max_runtime_seconds:
        raise CapViolationError(
            f"Requested timeout_seconds={timeout} exceeds max_runtime_seconds={caps.max_runtime_seconds}."
        )


def enforce_result_caps(result: dict[str, Any], caps: Caps) -> None:
    cif_count = result.get("cif_count")
    if cif_count is not None and int(cif_count) > caps.max_cif_count:
        raise CapViolationError(f"cif_count={cif_count} exceeds max_cif_count={caps.max_cif_count}.")
    output_bytes = result.get("output_bytes")
    if output_bytes is not None and int(output_bytes) > caps.max_output_bytes:
        raise CapViolationError(
            f"output_bytes={output_bytes} exceeds max_output_bytes={caps.max_output_bytes}."
        )
