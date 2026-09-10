from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from qlip.resources import base_data_root


class BaseDataRegistry:
    def __init__(self, data_dir: Optional[str | Path] = None):
        self.data_dir = Path(data_dir).expanduser().resolve() if data_dir else _default_data_dir()

    def load_json(self, name: str) -> Dict[str, Any]:
        path = self.data_dir / name
        if not path.exists():
            raise FileNotFoundError(f"QLIP base data file not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    @lru_cache(maxsize=None)
    def elements(self) -> Dict[str, Any]:
        return self.load_json("elements.json")

    @lru_cache(maxsize=None)
    def radii(self) -> Dict[str, Any]:
        return self.load_json("radii.json")

    @lru_cache(maxsize=None)
    def ionic_radii(self) -> Dict[str, Any]:
        return self.load_json("ionic_radii.json")

    @lru_cache(maxsize=None)
    def radius_policy(self) -> Dict[str, Any]:
        return self.load_json("radius_policy.json")

    @lru_cache(maxsize=None)
    def pair_distance_policy(self) -> Dict[str, Any]:
        return self.load_json("pair_distance_policy.json")

    @lru_cache(maxsize=None)
    def provenance(self) -> Dict[str, Any]:
        return self.load_json("provenance.json")

    def element_symbols(self) -> list[str]:
        return [record["symbol"] for record in self.elements().get("records", [])]

    def radius_record(self, symbol: str) -> Dict[str, Any]:
        records = self.radii().get("records", {})
        try:
            return records[str(symbol)]
        except KeyError as exc:
            raise KeyError(f"No QLIP radius data for element '{symbol}'") from exc

    def get_radius_record(self, symbol: str) -> Dict[str, Any]:
        return self.radius_record(symbol)

    def atomic_radius(self, symbol: str) -> float:
        return self.get_default_radius(symbol)

    def get_default_radius(self, symbol: str) -> float:
        field = self.radius_policy().get("default_radius_field", "qlip_default_radius_angstrom")
        record = self.radius_record(symbol)
        value = record.get(field)
        if value is None:
            raise KeyError(f"No usable QLIP radius field '{field}' for element '{symbol}'")
        return float(value)

    def atomic_radius_map(self, symbols: Optional[Iterable[str]] = None) -> Dict[str, float]:
        if symbols is None:
            symbols = self.element_symbols()
        return {str(symbol): self.atomic_radius(str(symbol)) for symbol in symbols}

    def radius_source(self, symbol: str) -> Optional[str]:
        record = self.radius_record(symbol)
        field = self.radius_policy().get("default_radius_field", "qlip_default_radius_angstrom")
        if field == "qlip_default_radius_angstrom":
            return record.get("qlip_default_radius_source_id")
        return record.get(field.replace("_angstrom", "_source_id"))

    def get_ionic_radii(
        self,
        symbol: str,
        oxidation_state: Optional[int] = None,
        coordination: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        records = self.ionic_radii().get("records", {})
        try:
            rows = list(records[str(symbol)].get("ionic_radii", []))
        except KeyError as exc:
            raise KeyError(f"No QLIP ionic radii data for element '{symbol}'") from exc
        if oxidation_state is not None:
            rows = [row for row in rows if row.get("oxidation_state") == int(oxidation_state)]
        if coordination is not None:
            rows = [row for row in rows if row.get("coordination") == str(coordination)]
        return rows

    def get_base_data_provenance(self) -> Dict[str, Any]:
        return self.provenance()


def _default_data_dir() -> Path:
    env = os.environ.get("QLIP_BASE_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return base_data_root()


@lru_cache(maxsize=1)
def default_registry() -> BaseDataRegistry:
    return BaseDataRegistry()
