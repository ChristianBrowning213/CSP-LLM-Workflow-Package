from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


DISALLOWED_MARKERS = ("<think", "```")


@dataclass(slots=True)
class JsonExtractionResult:
    ok: bool
    payload: dict[str, Any] | None
    reason: str | None
    contains_think: bool
    contains_fence: bool
    output_chars: int
    extraction_mode: str | None


def extract_single_json_object(
    text: str,
    *,
    max_chars: int,
) -> JsonExtractionResult:
    raw = str(text or "")
    lowered = raw.lower()
    contains_think = "<think" in lowered
    contains_fence = "```" in raw
    if contains_think:
        return JsonExtractionResult(
            ok=False,
            payload=None,
            reason="contains_think_block",
            contains_think=True,
            contains_fence=contains_fence,
            output_chars=len(raw),
            extraction_mode=None,
        )
    if contains_fence:
        return JsonExtractionResult(
            ok=False,
            payload=None,
            reason="contains_code_fence",
            contains_think=contains_think,
            contains_fence=True,
            output_chars=len(raw),
            extraction_mode=None,
        )
    if len(raw) > int(max_chars):
        return JsonExtractionResult(
            ok=False,
            payload=None,
            reason="oversize_output",
            contains_think=contains_think,
            contains_fence=contains_fence,
            output_chars=len(raw),
            extraction_mode=None,
        )
    if not raw.strip():
        return JsonExtractionResult(
            ok=False,
            payload=None,
            reason="empty_output",
            contains_think=contains_think,
            contains_fence=contains_fence,
            output_chars=len(raw),
            extraction_mode=None,
        )

    # Fast path: whole payload is one JSON object.
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return JsonExtractionResult(
                ok=False,
                payload=None,
                reason="json_not_object",
                contains_think=contains_think,
                contains_fence=contains_fence,
                output_chars=len(raw),
                extraction_mode="whole",
            )
        return JsonExtractionResult(
            ok=True,
            payload=dict(parsed),
            reason=None,
            contains_think=contains_think,
            contains_fence=contains_fence,
            output_chars=len(raw),
            extraction_mode="whole",
        )
    except json.JSONDecodeError:
        pass

    # Backup extractor: locate exactly one plausible top-level object.
    decoder = json.JSONDecoder()
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for idx, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, end = decoder.raw_decode(raw, idx)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            matches.append((idx, end, dict(obj)))
    unique_matches: list[tuple[int, int, dict[str, Any]]] = []
    seen: set[tuple[int, int]] = set()
    for item in matches:
        key = (item[0], item[1])
        if key in seen:
            continue
        seen.add(key)
        unique_matches.append(item)
    if not unique_matches:
        return JsonExtractionResult(
            ok=False,
            payload=None,
            reason="no_valid_json_object_found",
            contains_think=contains_think,
            contains_fence=contains_fence,
            output_chars=len(raw),
            extraction_mode="scan",
        )
    if len(unique_matches) > 1:
        return JsonExtractionResult(
            ok=False,
            payload=None,
            reason="repeated_json_payload",
            contains_think=contains_think,
            contains_fence=contains_fence,
            output_chars=len(raw),
            extraction_mode="scan",
        )
    _, _, payload = unique_matches[0]
    return JsonExtractionResult(
        ok=True,
        payload=payload,
        reason=None,
        contains_think=contains_think,
        contains_fence=contains_fence,
        output_chars=len(raw),
        extraction_mode="scan",
    )
