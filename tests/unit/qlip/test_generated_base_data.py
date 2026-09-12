from __future__ import annotations

import hashlib
import json

from qlip.data.generated import generated_resource


FORMER_CANONICAL_SHA256 = {
    "elements.json": "1456486184a1854330bfaf99afee734c41a0f47b0f7a0dff2a22268738c9f75d",
    "radii.json": "fab9add217a03f460f75e5f8d4bc673cbe8a3e5e5ed7afcc9f048e5c087f9a6f",
    "ionic_radii.json": "acb6af1a4f67c6246c4db1689ee533a1c9d31efea00ab50535730fa4acd42a07",
}


def _former_windows_serialization(payload: dict) -> bytes:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return text.replace("\n", "\r\n").encode("utf-8")


def test_generated_tables_match_every_former_canonical_value() -> None:
    for name, expected_hash in FORMER_CANONICAL_SHA256.items():
        payload = generated_resource(name)
        assert hashlib.sha256(_former_windows_serialization(payload)).hexdigest() == expected_hash

    assert len(generated_resource("elements.json")["records"]) == 118
    assert len(generated_resource("radii.json")["records"]) == 118
    assert sum(
        len(record["ionic_radii"])
        for record in generated_resource("ionic_radii.json")["records"].values()
    ) == 486
