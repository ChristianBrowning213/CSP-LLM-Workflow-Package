"""Registry for benchmark evaluators."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.util import find_spec
from typing import Protocol


class BenchmarkEvaluator(Protocol):
    """Protocol implemented by benchmark evaluators."""

    name: str
    description: str


@dataclass(frozen=True)
class EvaluatorSpec:
    name: str
    description: str
    factory_path: str
    optional_dependencies: tuple[str, ...] = field(default_factory=tuple)
    block_on_missing_dependencies: bool = True

    @property
    def available(self) -> bool:
        return all(find_spec(dependency) is not None for dependency in self.optional_dependencies)

    @property
    def missing_dependencies(self) -> list[str]:
        return [
            dependency
            for dependency in self.optional_dependencies
            if find_spec(dependency) is None
        ]

    def create(self, **kwargs):
        missing = self.missing_dependencies
        if missing and self.block_on_missing_dependencies:
            names = ", ".join(missing)
            raise RuntimeError(f"Evaluator '{self.name}' requires optional dependencies: {names}")

        module_name, class_name = self.factory_path.rsplit(":", 1)
        module = __import__(module_name, fromlist=[class_name])
        evaluator_class = getattr(module, class_name)
        return evaluator_class(**kwargs)


_REGISTRY: dict[str, EvaluatorSpec] = {
    "pre_dft_validity": EvaluatorSpec(
        name="pre_dft_validity",
        description="CrystaLLM-style parse, composition, symmetry, multiplicity, contact, geometry, duplicate, and novelty checks.",
        factory_path="sca.evaluators.pre_dft_validity:PreDftValidityBenchmarkEvaluator",
    ),
    "cif_parse": EvaluatorSpec(
        name="cif_parse",
        description="Standalone CIF parse and invalid-species checks.",
        factory_path="sca.evaluators.intent_satisfaction:CifParseBenchmarkEvaluator",
    ),
    "geometry": EvaluatorSpec(
        name="geometry",
        description="Standalone basic geometry checks.",
        factory_path="sca.evaluators.intent_satisfaction:GeometryBenchmarkEvaluator",
    ),
    "local_environment": EvaluatorSpec(
        name="local_environment",
        description="Generic site coordination, polyhedra, and framework diagnostics.",
        factory_path="sca.evaluators.topology:LocalEnvironmentBenchmarkEvaluator",
    ),
    "family_topology": EvaluatorSpec(
        name="family_topology",
        description="Policy-driven crystal-family topology validation.",
        factory_path="sca.evaluators.topology:FamilyTopologyBenchmarkEvaluator",
    ),
    "intent_satisfaction": EvaluatorSpec(
        name="intent_satisfaction",
        description="Deterministic prompt-intent satisfaction checks for generated CIFs.",
        factory_path="sca.evaluators.intent_satisfaction:IntentSatisfactionBenchmarkEvaluator",
    ),
    "alignn": EvaluatorSpec(
        name="alignn",
        description="Optional ALIGNN formation-energy prediction evaluator.",
        factory_path="sca.evaluators.alignn_benchmark:AlignnBenchmarkEvaluator",
        optional_dependencies=("alignn",),
    ),
    "structure_match": EvaluatorSpec(
        name="structure_match",
        description="StructureMatcher target-CIF match evaluator with exact and anonymous modes.",
        factory_path="sca.evaluators.structure_match:StructureMatchBenchmarkEvaluator",
    ),
    "novelty": EvaluatorSpec(
        name="novelty",
        description="Local novelty check against a supplied reference corpus.",
        factory_path="sca.evaluators.novelty_benchmark:NoveltyBenchmarkEvaluator",
    ),
    "spp": EvaluatorSpec(
        name="spp",
        description="Statistical Pair Potential plausibility scorer.",
        factory_path="sca.evaluators.spp:SppBenchmarkEvaluator",
    ),
    "chgnet_static": EvaluatorSpec(
        name="chgnet_static",
        description="Optional CHGNet static surrogate-energy evaluator.",
        factory_path="sca.evaluators.chgnet:ChgnetStaticBenchmarkEvaluator",
        optional_dependencies=("chgnet",),
        block_on_missing_dependencies=False,
    ),
    "chgnet_relax": EvaluatorSpec(
        name="chgnet_relax",
        description="Optional CHGNet relaxation with before/after force, energy, and reference-match metrics.",
        factory_path="sca.evaluators.chgnet_relax:ChgnetRelaxBenchmarkEvaluator",
        optional_dependencies=("chgnet",),
        block_on_missing_dependencies=False,
    ),
    "m3gnet_static": EvaluatorSpec(
        name="m3gnet_static",
        description="Optional MatGL/M3GNet static surrogate-energy evaluator.",
        factory_path="sca.evaluators.mlip:M3GNetStaticBenchmarkEvaluator",
        optional_dependencies=("matgl",),
        block_on_missing_dependencies=False,
    ),
    "mace_static": EvaluatorSpec(
        name="mace_static",
        description="Optional MACE ASE static surrogate-energy evaluator.",
        factory_path="sca.evaluators.mlip:MaceStaticBenchmarkEvaluator",
        optional_dependencies=("mace",),
        block_on_missing_dependencies=False,
    ),
    "sevennet_static": EvaluatorSpec(
        name="sevennet_static",
        description="Optional SevenNet ASE static surrogate-energy evaluator.",
        factory_path="sca.evaluators.mlip:SevenNetStaticBenchmarkEvaluator",
        optional_dependencies=("sevenn",),
        block_on_missing_dependencies=False,
    ),
    "mlip_ensemble": EvaluatorSpec(
        name="mlip_ensemble",
        description="Consensus and disagreement metrics across available MLIP energy columns.",
        factory_path="sca.evaluators.mlip:MlipEnsembleBenchmarkEvaluator",
    ),
    "relaxation_intent_retention": EvaluatorSpec(
        name="relaxation_intent_retention",
        description="Generated-to-relaxed structural change and crystallographic intent retention.",
        factory_path="sca.evaluators.relaxation_intent_retention:RelaxationIntentRetentionEvaluator",
    ),
    "post_dft_intent_retention": EvaluatorSpec(
        name="post_dft_intent_retention",
        description="Generated-to-DFT-relaxed structural and intent retention.",
        factory_path="sca.dft.analysis.transition:PostDftIntentRetentionEvaluator",
    ),
    "property_targets": EvaluatorSpec(
        name="property_targets",
        description="Compare predicted benchmark properties against manifest target values.",
        factory_path="sca.evaluators.property:PropertyTargetsBenchmarkEvaluator",
    ),
    "predicted_hull": EvaluatorSpec(
        name="predicted_hull",
        description="Predicted/surrogate energy-above-hull from local phase diagram entries.",
        factory_path="sca.evaluators.property:PredictedHullBenchmarkEvaluator",
    ),
    "evidence_traceability": EvaluatorSpec(
        name="evidence_traceability",
        description="Audits retrieved evidence relevance and links from evidence to constraints.",
        factory_path="sca.evaluators.unique_csp:EvidenceTraceabilityBenchmarkEvaluator",
    ),
    "constraint_faithfulness": EvaluatorSpec(
        name="constraint_faithfulness",
        description="Checks output rows against prompt-derived formula, SG, family, and contact constraints.",
        factory_path="sca.evaluators.unique_csp:ConstraintFaithfulnessBenchmarkEvaluator",
    ),
    "solver_certificate": EvaluatorSpec(
        name="solver_certificate",
        description="Audits solver status, feasibility, objective, counts, timing, and infeasibility evidence.",
        factory_path="sca.evaluators.unique_csp:SolverCertificateBenchmarkEvaluator",
    ),
    "evidence_faithfulness": EvaluatorSpec(
        name="evidence_faithfulness",
        description="Checks final explanations for unsupported retrieved-evidence claims.",
        factory_path="sca.evaluators.unique_csp:EvidenceFaithfulnessBenchmarkEvaluator",
    ),
    "audit_bundle_completeness": EvaluatorSpec(
        name="audit_bundle_completeness",
        description="Checks traceable CSP bundle artifact completeness and reproducibility metadata.",
        factory_path="sca.evaluators.unique_csp:AuditBundleCompletenessBenchmarkEvaluator",
    ),
}


def list_evaluator_specs() -> list[EvaluatorSpec]:
    return sorted(_REGISTRY.values(), key=lambda spec: spec.name)


def get_evaluator_spec(name: str) -> EvaluatorSpec:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY))
        raise KeyError(f"Unknown evaluator '{name}'. Available evaluators: {available}") from exc


def create_evaluator(name: str, **kwargs):
    return get_evaluator_spec(name).create(**kwargs)
