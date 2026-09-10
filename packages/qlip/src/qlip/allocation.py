import os
import numpy as np
from ase.formula import Formula
import pyomo.environ as pyo
from pyomo.environ import Var, Binary
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Dict, List, Tuple, Iterable

from qlip.motifs import MotifRecord, load_motif_catalog, compatible_subset


class Allocation:
    """
    Core lattice allocation with optional motif hints.

    Motif semantics (Option B, shareable oxygen):
      - m.motif[k] is ON only if all required atom occupancies are present:
            m.motif[k] <= x[sp,i]  for every (sp,i) in footprint(k)
      - No reverse forcing (atoms can be present without claiming a motif).
      - At most one motif per anchor site (prevents trivial bonus stacking).
      - Tiny bonus -eps * sum_k motif[k] to prefer tagging existing structures.
    """

    def __init__(self, atoms, positions=None, cost=None, constraints=None):
        self.atoms = atoms

        if atoms.symbols:
            formula = Formula(atoms.get_chemical_formula())
            self.count: Dict[str, int] = formula.count()
            self.types = list(self.count.keys())
            self.pairs = [tuple(sorted([t1, t2]))
                          for t1, t2 in combinations_with_replacement(self.types, 2)]

        self.positions = positions
        self.cost = cost
        self.constraints = list(constraints) if constraints else []
        self.ordered_orbits: List[Dict[str, object]] = []
        self.explicit_vacancy_count: int | None = None

        # Motif plumbing
        self._raw_motif_catalog: Dict[str, MotifRecord] | None = None
        self._prepared_motif_catalog: Dict[str, MotifRecord] | None = None
        self._motif_site_count: int | None = None
        self._motif_constraints_registered: bool = False

        # Introspection: index -> (name, anchor_idx, [(species, site), ...])
        self._motif_meta: Dict[int, Tuple[str, int, List[Tuple[str, int]]]] = {}

    # keep scaled grid handy when positions set
    def __setattr__(self, key, value):
        if key == "positions" and value is not None:
            super().__setattr__("_grid", value.get_scaled_positions())
        super().__setattr__(key, value)
        if key == "positions" and value is not None:
            raw_catalog = getattr(self, "_raw_motif_catalog", None)
            if raw_catalog:
                try:
                    self._prepare_motifs_if_needed()
                except ValueError:
                    # may be partially initialized; defer to encode()
                    pass

    # ───────────────────────── Motifs: load/prepare ─────────────────────────

    def enable_motifs(self, artifact_dir=None, include: Iterable[str] | None = None):
        """Hydrate motif catalog; constraints added during encode()."""
        if not getattr(self, "types", None):
            raise ValueError("Stoichiometry must be initialized before enabling motifs.")

        if artifact_dir is None:
            raise ValueError("artifact_dir is required; generated motif artifacts are not bundled")

        catalog = load_motif_catalog(artifact_dir, self.types, include=include)
        self._raw_motif_catalog = catalog
        self._prepared_motif_catalog = None
        self._motif_site_count = None
        self._motif_constraints_registered = False
        self._motif_meta = {}

        if catalog and self.positions is not None:
            self._prepare_motifs_if_needed()

    def _prepare_motifs_if_needed(self):
        """Filter motifs to current grid/site domain and cache."""
        if not self._raw_motif_catalog:
            return
        if self.positions is None:
            raise ValueError("Motif support requires positions to be defined.")

        site_count = len(self.positions)
        if self._prepared_motif_catalog is not None and self._motif_site_count == site_count:
            return

        self._prepared_motif_catalog = compatible_subset(self._raw_motif_catalog, site_count)
        self._motif_site_count = site_count
        self._motif_constraints_registered = False
        self._motif_meta = {}  # will be filled when we build vars

    # ───────────────────────── Distances & costs ────────────────────────────

    def _compute_distances(self):
        """Pairwise distances with minimum image convention."""
        self._dist = self.positions.get_all_distances(mic=True)

    def _dist2cost(self, pair: Tuple[str, str]):
        """Map distance matrix to interaction costs for a given pair."""
        if hasattr(self.cost, "pair_cost_matrix"):
            return np.asarray(self.cost.pair_cost_matrix(pair, self.positions), dtype=float)
        vals, inv = np.unique(self._dist, return_inverse=True)
        # avoid zeros on diagonal: replace by min cell length
        self_interaction_length = min(self.positions.cell.lengths())
        vals[np.isclose(vals, 0.0, atol=1e-8)] = self_interaction_length
        mapped = self.cost(pair, vals)
        return mapped[inv].reshape(self._dist.shape)

    # ───────────────────────── Motif constraints (shareable atoms) ──────────

    def _attach_motifs_linking(self, eps_bonus: float = 1e-6):
        """
        Create a binary Var m.motif over concrete motif instances and add:
          - Implications: motif[k] <= x[sp,i]  ∀ (sp,i) in footprint(k)
          - One-per-anchor: sum_{k: anchor(k)=i} motif[k] <= 1
          - Objective bonus: -eps_bonus * sum_k motif[k]
        """
        cat = self._prepared_motif_catalog
        if not cat or self._motif_constraints_registered:
            return

        m = self.m
        meta: Dict[int, Tuple[str, int, List[Tuple[str, int]]]] = {}
        footprints: Dict[int, List[Tuple[str, int]]] = {}
        anchor_of: Dict[int, int] = {}  # k -> anchor site
        k = 0
        for name, rec in cat.items():
            for anchor_idx, neighs in rec.instances:
                fp = [(rec.anchor, anchor_idx)] + list(neighs)
                meta[k] = (name, anchor_idx, list(neighs))
                footprints[k] = fp
                anchor_of[k] = anchor_idx
                k += 1

        K = list(footprints.keys())
        if not K:
            self._motif_meta = {}
            self._motif_constraints_registered = True
            return

        # Decision vars
        m.motif = Var(K, domain=Binary)
        self._motif_meta = meta  # for post-solve introspection

        # (A) Implications: motif[k] ≤ x[sp,i] for all sites in footprint
        m.motif_implies = pyo.ConstraintList()
        for kk, fp in footprints.items():
            z = m.motif[kk]
            for sp_req, i in fp:
                m.motif_implies.add(z <= m.x[sp_req, i])

        # (B) One-per-anchor to avoid trivial bonus stacking on the same center
        m.motif_per_anchor = pyo.ConstraintList()
        # group motif ids by anchor index
        by_anchor: Dict[int, List[int]] = {}
        for kk, aidx in anchor_of.items():
            by_anchor.setdefault(aidx, []).append(kk)
        for aidx, kk_list in by_anchor.items():
            if len(kk_list) > 1:
                m.motif_per_anchor.add(sum(m.motif[kk] for kk in kk_list) <= 1)

        # (C) Objective bonus hook (store so we can add to objective after creation)
        self._motif_bonus_eps = float(eps_bonus)
        self._motif_ids = K

        self._motif_constraints_registered = True

    # ───────────────────────── Build & Solve ────────────────────────────────

    def encode(self):
        if self.positions is None:
            raise ValueError("Please define the grid first")

        self._compute_distances()
        self._prepare_motifs_if_needed()

        self.m = pyo.ConcreteModel()

        # Sets & atom vars
        self.m.Pos = pyo.RangeSet(0, len(self.positions) - 1)
        self.m.Types = pyo.Set(initialize=self.types)
        self.m.x = pyo.Var(self.m.Types, self.m.Pos, domain=pyo.Binary)
        # A uniform indexed variable keeps model serialization stable.  Each
        # state is initialized deterministically; sites whose request does not
        # enable vacancy are fixed to zero below.
        self.m.vacancy = pyo.Var(self.m.Pos, domain=pyo.Binary, initialize=0)

        vacancy_enabled_sites: set[int] = set()
        orbit_claimed_sites: set[int] = set()
        for orbit in self.ordered_orbits:
            indices = {int(i) for i in orbit["site_indices"]}
            orbit_claimed_sites.update(indices)
            states = {str(value) for value in orbit.get("allowed_species", [])}
            declared = bool(orbit.get("vacancy_allowed", False)) or "VACANCY" in states
            fixed_species = orbit.get("fixed_species")
            required_state = str(orbit.get("required_state", "AUTO")).upper()
            requires_full = required_state == "FULL" or bool(orbit.get("required_occupancy", True))
            enabled = declared and not fixed_species and (required_state == "EMPTY" or not requires_full)
            if enabled:
                vacancy_enabled_sites.update(indices)
        # Traditional non-orbit grids retain their existing ability to leave
        # candidate sites empty. Ordered-orbit requests opt in per orbit.
        if not self.ordered_orbits:
            vacancy_enabled_sites.update(int(i) for i in self.m.Pos)
        fixed_zero_sites = sorted(set(int(i) for i in self.m.Pos) - vacancy_enabled_sites)
        for i in fixed_zero_sites:
            self.m.vacancy[i].fix(0)
        self.vacancy_state_diagnostics = {
            "representation": "uniform_indexed_binary",
            "initialized_value": 0,
            "vacancy_enabled_site_indices": sorted(vacancy_enabled_sites),
            "vacancy_fixed_zero_site_indices": fixed_zero_sites,
            "ordered_orbit_site_indices": sorted(orbit_claimed_sites),
            "requested_vacancy_count": self.explicit_vacancy_count,
        }

        # Optional symmetry-closed ordered-site groups.  This is deliberately
        # generic: callers supply site indices and permitted species, while
        # the core allocation model enforces a common assignment per group.
        self.m.ordered_orbit_constraints = pyo.ConstraintList()
        for orbit in self.ordered_orbits:
            indices = [int(i) for i in orbit["site_indices"]]
            allowed = set(str(t) for t in orbit["allowed_species"])
            vacancy_allowed = bool(orbit.get("vacancy_allowed", False)) or "VACANCY" in allowed
            allowed.discard("VACANCY")
            representative = indices[0]
            close_orbit = not bool(orbit.get("allow_partial_occupation", False))
            for i in indices:
                for t in self.types:
                    if t not in allowed:
                        self.m.ordered_orbit_constraints.add(self.m.x[t, i] == 0)
                    elif i != representative and close_orbit:
                        self.m.ordered_orbit_constraints.add(
                            self.m.x[t, i] == self.m.x[t, representative]
                        )
                vacancy_enabled = i in vacancy_enabled_sites
                if vacancy_enabled and i != representative and close_orbit:
                    self.m.ordered_orbit_constraints.add(
                        self.m.vacancy[i] == self.m.vacancy[representative]
                    )
                fixed_species = orbit.get("fixed_species")
                required_state = str(orbit.get("required_state", "AUTO")).upper()
                if fixed_species:
                    self.m.ordered_orbit_constraints.add(self.m.x[str(fixed_species), i] == 1)
                elif required_state == "EMPTY":
                    self.m.ordered_orbit_constraints.add(self.m.vacancy[i] == 1)
                elif required_state == "FULL" or bool(orbit.get("required_occupancy", True)):
                    self.m.ordered_orbit_constraints.add(
                        sum(self.m.x[t, i] for t in self.types) == 1
                    )

        # Attach external constraints (that depend only on x)
        for constraint in self.constraints:
            constraint.attach(self)

        # Attach motifs BEFORE building the objective so we can include the bonus term
        self._attach_motifs_linking(eps_bonus=1e-6)

        # Objective: unordered site-pair energy. Costs that expose
        # pair_cost_matrix can provide diagonal self-image coefficients;
        # off-diagonal coefficients are consumed once for each i < j pair.
        terms = []
        include_diagonal = bool(getattr(self.cost, "include_diagonal_pair_terms", False))
        for t1, t2 in self.pairs:
            pair_cost = self._dist2cost((t1, t2))
            if t1 == t2:
                terms.append(sum(
                    pair_cost[i, j] * self.m.x[t1, i] * self.m.x[t1, j]
                    for i in self.m.Pos for j in self.m.Pos if i < j
                ))
                if include_diagonal:
                    terms.append(sum(
                        pair_cost[i, i] * self.m.x[t1, i]
                        for i in self.m.Pos
                    ))
            else:
                terms.append(sum(
                    pair_cost[i, j] * self.m.x[t1, i] * self.m.x[t2, j]
                    for i in self.m.Pos for j in self.m.Pos if i < j
                ))
                terms.append(sum(
                    pair_cost[i, j] * self.m.x[t2, i] * self.m.x[t1, j]
                    for i in self.m.Pos for j in self.m.Pos if i < j
                ))

        obj_expr = sum(terms)

        # Tiny tie-break bonus for motifs (if defined)
        if hasattr(self.m, "motif") and getattr(self, "_motif_ids", None):
            eps = getattr(self, "_motif_bonus_eps", 1e-6)
            obj_expr = obj_expr - eps * sum(self.m.motif[k] for k in self._motif_ids)

        self.m.obj = pyo.Objective(expr=obj_expr, sense=pyo.minimize)

        # Stoichiometry
        self.m.stoic = pyo.Constraint(
            self.m.Types,
            rule=lambda m, t: sum(m.x[t, i] for i in m.Pos) == self.count[t]
        )

        # Every candidate site has exactly one explicit state: a species or
        # vacancy. Motifs do not consume site capacity.
        self.m.excl = pyo.Constraint(
            self.m.Pos,
            rule=lambda m, i: sum(m.x[t, i] for t in m.Types) + m.vacancy[i] == 1
        )
        expected_vacancies = len(self.positions) - sum(self.count.values())
        requested_vacancies = self.explicit_vacancy_count
        if requested_vacancies is not None and int(requested_vacancies) != expected_vacancies:
            raise ValueError(
                f"Explicit vacancy count {requested_vacancies} conflicts with site/formula count {expected_vacancies}."
            )
        self.m.vacancy_count = pyo.Constraint(
            expr=sum(self.m.vacancy[i] for i in self.m.Pos) == expected_vacancies
        )

        print("The model has been generated")

    def _available_solvers(self, names: Iterable[str]) -> list[str]:
        available: list[str] = []
        for name in names:
            try:
                solver = pyo.SolverFactory(name)
            except Exception:
                continue
            try:
                if solver is not None and solver.available(exception_flag=False):
                    available.append(name)
            except Exception:
                continue
        return available

    def solve(self, solver_name: str | None = None):
        requested = solver_name or os.getenv("QLIP_SOLVER") or "gurobi"
        if requested != "gurobi":
            raise RuntimeError("Only the Gurobi solver is supported.")

        solver = pyo.SolverFactory("gurobi")
        if solver is None or not solver.available(exception_flag=False):
            raise RuntimeError("Gurobi solver is not available.")

        res = solver.solve(self.m, tee=False)
        if res.solver.termination_condition == pyo.TerminationCondition.infeasible:
            print("There are no feasible solutions")
            return

        print("The best score:", pyo.value(self.m.obj))
        for t in self.m.Types:
            print(t, ": ",
                  [tuple(self._grid[i]) for i in self.m.Pos if pyo.value(self.m.x[t, i]) == 1])
