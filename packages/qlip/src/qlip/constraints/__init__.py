from __future__ import annotations

import warnings

def _missing(name: str, detail: str):
    warnings.warn(
        f"{name} is deprecated and no longer shipped: {detail}",
        DeprecationWarning,
        stacklevel=2,
    )

    class _Missing:
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(f"{name} is not available. {detail}")

    _Missing.__name__ = name
    return _Missing


from .proximity import AtomicRadii

try:
    from .motif_linking import MotifLinking
except Exception:
    MotifLinking = _missing("MotifLinking", "Module 'motif_linking' is not available.")


try:
    from .proximity_general import NoClosePairs
except Exception:
    NoClosePairs = _missing("NoClosePairs", "Module 'proximity_general' is not in this clean branch.")

try:
    from .coordination import CoordinationBounds
except Exception:
    CoordinationBounds = _missing("CoordinationBounds", "Module 'coordination' is not in this clean branch.")

try:
    from .spacegroup_orbits import SpaceGroupOrbits
except Exception:
    SpaceGroupOrbits = _missing("SpaceGroupOrbits", "Module 'spacegroup_orbits' is not in this clean branch.")

try:
    from .block_capacity import BlockCapacity
except Exception:
    BlockCapacity = _missing("BlockCapacity", "Module 'block_capacity' is not in this clean branch.")


__all__ = [
    "AtomicRadii",
    "MotifLinking",
    "NoClosePairs",
    "CoordinationBounds",
    "SpaceGroupOrbits",
    "BlockCapacity",
]
