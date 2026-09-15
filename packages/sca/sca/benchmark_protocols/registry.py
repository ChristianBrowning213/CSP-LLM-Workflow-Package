"""Registry access for literature benchmark protocols."""

from __future__ import annotations

from sca.benchmark_protocols.literature_values import built_in_protocols
from sca.benchmark_protocols.schema import BenchmarkProtocol


def list_protocols() -> list[BenchmarkProtocol]:
    return sorted(built_in_protocols(), key=lambda protocol: protocol.protocol_id)


def get_protocol(protocol_id: str) -> BenchmarkProtocol:
    protocols = {protocol.protocol_id: protocol for protocol in list_protocols()}
    try:
        return protocols[protocol_id]
    except KeyError as exc:
        available = ", ".join(sorted(protocols))
        raise KeyError(f"Unknown protocol '{protocol_id}'. Available protocols: {available}") from exc


def select_protocols(selector: str) -> list[BenchmarkProtocol]:
    if selector.strip().lower() == "all":
        return list_protocols()
    selected = []
    for token in [item.strip() for item in selector.split(",") if item.strip()]:
        selected.append(get_protocol(token))
    if not selected:
        raise ValueError("At least one protocol must be selected")
    return selected
