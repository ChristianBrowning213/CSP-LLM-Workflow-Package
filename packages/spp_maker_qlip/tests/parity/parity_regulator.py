"""Regulator parity (Ticket 26 Part 42).

No source CLI verb exposes regulator union/fallback decisions directly —
`spp-maker`'s subcommands are only `fit`, `score`, `calibrate`, `run`
(confirmed by grep against cli.py during T26_05), none of which take
regulator-pair arguments. That logic lives in
`common_contract.choose_pair_blend`/`blend_contract_roots`, which the
ticket forbids importing directly in this harness (subprocess-CLI only, to
avoid the fabricated-API failure mode from earlier attempts).

Rather than fabricate a fake regulator CLI invocation, this is honestly
reported as BLOCKED: no real, verified entry point exists to drive this
comparison via the CLI surface this harness is restricted to. A future
subticket could add this comparison via a small, explicitly-scoped script
that Claude writes directly against `common_contract.py`'s real, verified
functions (as investigation/testing work, not blind delegation) rather
than attempting it here.
"""

from __future__ import annotations

import json


def run() -> dict:
    return {
        "status": "BLOCKED",
        "reason": (
            "No spp-maker CLI verb exposes regulator union/fallback decisions "
            "(only fit/score/calibrate/run exist). The real logic is in "
            "common_contract.choose_pair_blend/blend_contract_roots, which this "
            "subprocess-only harness is not permitted to import directly (see "
            "module docstring). Requires a dedicated, narrowly-scoped follow-up."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
