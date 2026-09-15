# chem_registry.py
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

@dataclass
class PrototypeSpec:
    name: str
    builder: Callable[..., "Structure"]           # returns pymatgen Structure
    decorator: Dict[str, str]                     # map prototype labels -> real species
    params: Dict[str, float]                      # e.g., {"a": 3.90}

@dataclass
class ChemistryPlan:
    chem: str                                     # e.g., "SrTiO3"
    family: str                                   # e.g., "perovskite"
    prototypes: List[PrototypeSpec]
    # which motif emitters to call (by function name in motif_extract.py)
    motif_emitters: List[str]                     # e.g., ["perovskite_TiO6_motif", "perovskite_SrO12_motif"]

def plan_for(chem: str, a: float) -> ChemistryPlan:
    """
    Minimal registry: extend as you add more families (RP, spinel, pyrochlore, ...).
    """
    chem_u = chem.replace(" ", "")
    if chem_u.lower() in {"srtio3", "srtio_3", "srti o3"}:
        from .prototypes import proto_perovskite_ABO3
        spec = PrototypeSpec(
            name="ABO3_cubic_Pm-3m",
            builder=proto_perovskite_ABO3,
            decorator={"A": "Sr", "B": "Ti", "X": "O"},
            params={"a": a}
        )
        return ChemistryPlan(
            chem="SrTiO3",
            family="perovskite",
            prototypes=[spec],
            motif_emitters=["perovskite_TiO6_motif", "perovskite_SrO12_motif"]
        )
    raise ValueError(f"No registry entry for chemistry: {chem}")
