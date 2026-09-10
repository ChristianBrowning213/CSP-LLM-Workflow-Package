from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Type

import pyomo.environ as pyo

from qlip.constraints.proximity import AtomicRadii
from qlip.core.models import PluginCatalogEntry
from qlip.core.paths import allowed_path_roots, resolve_and_check_path
from qlip.plugins.base import ConstraintPlugin, GuidancePlugin


class ConstraintRegistry:
    _registry: Dict[str, Type[ConstraintPlugin]] = {}

    @classmethod
    def register(cls, plugin_cls: Type[ConstraintPlugin]) -> None:
        cls._registry[plugin_cls.id] = plugin_cls

    @classmethod
    def get(cls, plugin_id: str) -> Optional[Type[ConstraintPlugin]]:
        return cls._registry.get(plugin_id)

    @classmethod
    def list(
        cls,
        ids: Optional[Iterable[str]] = None,
        tags_any: Optional[Iterable[str]] = None,
        include_params_schema: bool = True,
    ) -> List[PluginCatalogEntry]:
        return _list_plugins(cls._registry, "constraint", ids, tags_any, include_params_schema)


class GuidanceRegistry:
    _registry: Dict[str, Type[GuidancePlugin]] = {}

    @classmethod
    def register(cls, plugin_cls: Type[GuidancePlugin]) -> None:
        cls._registry[plugin_cls.id] = plugin_cls

    @classmethod
    def get(cls, plugin_id: str) -> Optional[Type[GuidancePlugin]]:
        return cls._registry.get(plugin_id)

    @classmethod
    def list(
        cls,
        ids: Optional[Iterable[str]] = None,
        tags_any: Optional[Iterable[str]] = None,
        include_params_schema: bool = True,
    ) -> List[PluginCatalogEntry]:
        return _list_plugins(cls._registry, "guidance", ids, tags_any, include_params_schema)


def _list_plugins(
    registry: Dict[str, Type[Any]],
    kind: str,
    ids: Optional[Iterable[str]],
    tags_any: Optional[Iterable[str]],
    include_params_schema: bool,
) -> List[PluginCatalogEntry]:
    id_set = {str(i) for i in ids} if ids else None
    tag_set = {str(t) for t in tags_any} if tags_any else None
    entries: List[PluginCatalogEntry] = []
    for plugin_id, plugin_cls in sorted(registry.items()):
        if id_set and plugin_id not in id_set:
            continue
        tags = list(getattr(plugin_cls, "tags", []) or [])
        if tag_set and not (tag_set & set(tags)):
            continue
        params_schema = dict(getattr(plugin_cls, "params_schema", {}) or {})
        if not include_params_schema:
            params_schema = {}
        entry = PluginCatalogEntry(
            id=plugin_id,
            kind=kind,
            title=getattr(plugin_cls, "title", plugin_id),
            description=getattr(plugin_cls, "description", ""),
            tags=tags,
            params_schema=params_schema,
            capabilities=dict(getattr(plugin_cls, "capabilities", {}) or {}),
            version=getattr(plugin_cls, "version", "1.0"),
        )
        entries.append(entry)
    return entries


class _ScaledAtomicRadiiConstraint:
    def __init__(self, radii: Dict[str, float], allow_self_overlap: bool = False):
        self.rad = radii
        self.allow_self_overlap = allow_self_overlap

    def attach(self, allocation) -> None:
        m = allocation.m
        m.atomic_radii = pyo.ConstraintList()

        collision: Dict[tuple[str, str], float] = {}
        for t1, t2 in allocation.pairs:
            if self.allow_self_overlap and t1 == t2:
                continue
            collision[(t1, t2)] = self.rad[t1] + self.rad[t2]

        for i in m.Pos:
            for j in range(i + 1, len(allocation.positions)):
                for t1, t2 in allocation.pairs:
                    if self.allow_self_overlap and t1 == t2:
                        continue
                    if allocation._dist[i, j] < collision[(t1, t2)]:
                        m.atomic_radii.add(m.x[t1, i] + m.x[t2, j] <= 1)
                        m.atomic_radii.add(m.x[t2, i] + m.x[t1, j] <= 1)


class AtomicRadiiConstraintPlugin(ConstraintPlugin):
    id = "proximity.atomic_radii"
    title = "Atomic radii minimum separation"
    description = "Enforces minimum pairwise separation based on atomic radii scale."
    tags = ["geometry", "feasibility"]
    params_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scale": {"type": "number", "minimum": 0, "default": 1.0},
            "allow_self_overlap": {"type": "boolean", "default": False},
        },
        "required": ["scale"],
    }
    capabilities = {"requires_distances": True}

    @classmethod
    def apply(cls, allocation, params: Dict[str, Any]) -> None:
        scale = float(params.get("scale", 1.0))
        allow_self_overlap = bool(params.get("allow_self_overlap", False))
        if scale <= 0:
            scale = 1.0

        base = AtomicRadii()
        radii = {k: float(v) * scale for k, v in base.rad.items()}
        allocation.constraints.append(_ScaledAtomicRadiiConstraint(radii, allow_self_overlap))


class MotifLinkingConstraintPlugin(ConstraintPlugin):
    id = "motif.linking"
    title = "Motif linking constraints"
    description = "Enable motif linkage constraints and objective tie-break bonus."
    tags = ["motif", "feasibility"]
    params_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "motif_dir": {"type": "string"},
            "include": {"type": "array", "items": {"type": "string"}},
        },
        "default": {},
    }
    capabilities = {"requires_motif_artifacts": True}

    @classmethod
    def apply(cls, allocation, params: Dict[str, Any]) -> None:
        motif_dir = params.get("motif_dir")
        if motif_dir:
            motif_dir = resolve_and_check_path(motif_dir, allowed_path_roots(), must_exist=True)
        include = params.get("include")
        allocation.enable_motifs(artifact_dir=motif_dir, include=include)


def _scale_objective(model, weight: float) -> None:
    if weight == 1.0:
        return
    objs = list(model.component_objects(pyo.Objective, active=True))
    if not objs:
        return
    obj = objs[0]
    expr = obj.expr * float(weight)
    name = obj.name
    sense = obj.sense
    model.del_component(obj)
    model.add_component(name, pyo.Objective(expr=expr, sense=sense))


class ObjectiveEnergySPPGuidancePlugin(GuidancePlugin):
    id = "objective.energy_spp"
    title = "SPP energy objective"
    description = "Use SPP energy as the base objective."
    tags = ["objective"]
    params_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "pot_root": {"type": "string"},
            "mode": {"type": "string", "enum": ["complete", "partial"]},
            "supported_pairs": {"type": "array", "items": {"type": "string"}},
            "missing_pairs": {"type": "array", "items": {"type": "string"}},
            "missing_pair_policy": {"type": "string", "enum": ["neutral", "zero", "soft_repulsive", "fallback", "block"]},
            "missing_pair_penalty": {"type": "number"},
            "regularisation_spp_dir": {"type": "string"},
            "regularisation_weight": {"type": "number", "minimum": 0, "default": 0.0},
            "regularization_spp_dir": {"type": "string"},
            "regularization_weight": {"type": "number", "minimum": 0, "default": 0.0},
            "strict_pair_coverage": {"type": "boolean"},
            "cutoff": {"type": "number", "exclusiveMinimum": 0, "default": 11.0},
            "spp_cutoff": {"type": "number", "exclusiveMinimum": 0},
        },
        "default": {},
    }

    @classmethod
    def apply(
        cls, allocation, invocation: Dict[str, Any], guidance_mode: str
    ) -> List[GuidanceContribution]:
        if guidance_mode != "weighted_sum":
            return []
        weight = float(invocation.get("weight", 1.0))
        _scale_objective(allocation.m, weight)
        return []


_BUILTINS_REGISTERED = False


def register_builtin_plugins() -> None:
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return
    ConstraintRegistry.register(AtomicRadiiConstraintPlugin)
    ConstraintRegistry.register(MotifLinkingConstraintPlugin)
    GuidanceRegistry.register(ObjectiveEnergySPPGuidancePlugin)
    _BUILTINS_REGISTERED = True


register_builtin_plugins()
