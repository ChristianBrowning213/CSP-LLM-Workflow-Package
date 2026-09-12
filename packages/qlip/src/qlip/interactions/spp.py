import os
from pathlib import Path
import numpy as np
from scipy.interpolate import interp1d

DEFAULT_SPP_CUTOFF = 11.0
ZERO_DISTANCE_TOL = 1e-12
SOFT_MISSING_PAIR_R0 = 2.0
SOFT_MISSING_PAIR_POWER = 6.0
SOFT_MISSING_PAIR_MAX = 100.0
REGULARISATION_ENV_VARS = ("QLIP_SPP_REGULARISATION_DIR", "QLIP_SPP_REGULARIZATION_DIR")

def _resolve_spp_dir(cli_or_arg=None) -> Path:
    if cli_or_arg:
        return Path(cli_or_arg).expanduser().resolve()
    env = os.environ.get("QLIP_SPP_POT_DIR")
    if env:
        return Path(env).expanduser().resolve()
    raise RuntimeError(
        "SPP POT root is required; provide pot_root or set QLIP_SPP_POT_DIR "
        "to a compatible user-supplied POT library"
    )


def _canonical_symbol(symbol):
    text = str(symbol).strip()
    if not text:
        return text
    return text[:1].upper() + text[1:].lower()


def canonical_pair_key(a, b):
    """Canonical unordered element-pair key used for POT lookup and reporting."""
    return tuple(sorted([_canonical_symbol(a), _canonical_symbol(b)], key=str.lower))


def canonical_pair_name(a, b):
    return "-".join(canonical_pair_key(a, b))


def _resolve_regularisation_dir(raw=None):
    if raw:
        return Path(raw).expanduser().resolve()
    for name in REGULARISATION_ENV_VARS:
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser().resolve()
    return None


def _pair_from_pot_path(path: Path):
    for candidate in (path.stem, path.parent.name):
        if "-" not in candidate:
            continue
        left, right = candidate.split("-", 1)
        if left.strip() and right.strip():
            return canonical_pair_key(left, right)
    return None


class SPP:
    """
    Represents a single Statistically Derived Proxy Potential (SPP) for a given atom pair.
    Provides interpolation for U(r) values.
    """
    def __init__(self, r_grid, U_grid):
        """
        Initialize the SPP with a grid of distances and corresponding potential values.
        Args:
            r_grid (np.ndarray): Array of distances (Angstrom).
            U_grid (np.ndarray): Array of SPP values at those distances.
        """
        self.r_grid = r_grid
        self.U_grid = U_grid
        # Create an interpolation function for the potential
        self.interp = interp1d(r_grid, U_grid, kind='cubic', bounds_error=False, fill_value=0)

    def __call__(self, r):
        """
        Evaluate the SPP at a given distance r (Angstrom).
        Args:
            r (float): Distance between two atoms.
        Returns:
            float: SPP value at distance r.
        """
        return self.interp(r)


def _as_cell_matrix(cell):
    matrix = np.asarray(cell, dtype=float)
    if matrix.shape != (3, 3):
        try:
            matrix = np.asarray(cell.array, dtype=float)
        except AttributeError:
            pass
    if matrix.shape != (3, 3):
        raise ValueError("cell must be a 3x3 lattice matrix")
    return matrix


def _image_depth(cell, cutoff):
    cell_matrix = _as_cell_matrix(cell)
    norms = np.linalg.norm(cell_matrix, axis=1)
    positive_norms = norms[norms > ZERO_DISTANCE_TOL]
    if len(positive_norms) != 3:
        raise ValueError("cell lattice vectors must be non-zero")
    return int(np.ceil(float(cutoff) / float(np.min(positive_norms))) + 1)


def periodic_pair_multiplicity(diagonal_self_image):
    """Return the unordered-pair weight for one periodic image term."""
    return 0.5 if diagonal_self_image else 1.0


def periodic_spp_sum(
    frac_i,
    frac_j,
    cell,
    spp,
    cutoff=DEFAULT_SPP_CUTOFF,
    diagonal_self_image=None,
):
    """
    Sum SPP contributions over all periodic images within a cutoff.

    ``frac_i`` and ``frac_j`` are fractional coordinates in the cell basis.
    Counting convention matches the solver objective: each unordered site pair
    is represented once by the caller, and this helper sums all valid periodic
    images for that one site pair. The central zero-distance self image is
    skipped, while translated self-images within ``cutoff`` receive weight
    0.5 because the symmetric translation enumeration contains both +T and
    -T. Callers that know atom identity should pass ``diagonal_self_image``;
    otherwise coincident fractional coordinates are treated as a self pair.
    """
    cutoff = float(cutoff)
    if cutoff <= 0:
        return 0.0
    frac_i = np.asarray(frac_i, dtype=float)
    frac_j = np.asarray(frac_j, dtype=float)
    if diagonal_self_image is None:
        diagonal_self_image = bool(
            np.allclose(frac_i, frac_j, rtol=0.0, atol=ZERO_DISTANCE_TOL)
        )
    cell_matrix = _as_cell_matrix(cell)
    depth = _image_depth(cell_matrix, cutoff)

    total = 0.0
    for sx in range(-depth, depth + 1):
        for sy in range(-depth, depth + 1):
            for sz in range(-depth, depth + 1):
                shift = np.array([sx, sy, sz], dtype=float)
                disp = (frac_j + shift - frac_i) @ cell_matrix
                distance = float(np.linalg.norm(disp))
                if distance <= ZERO_DISTANCE_TOL or distance > cutoff:
                    continue
                total += float(spp(distance))
    return float(total * periodic_pair_multiplicity(diagonal_self_image))


def soft_missing_pair_penalty(
    distance,
    *,
    r0=SOFT_MISSING_PAIR_R0,
    power=SOFT_MISSING_PAIR_POWER,
    max_penalty=SOFT_MISSING_PAIR_MAX,
    eps=1e-6,
):
    """Finite soft repulsion for partial-SPP pairs without POT coverage."""
    d = max(float(distance), float(eps))
    value = float((float(r0) / d) ** float(power))
    return min(float(max_penalty), value)

class SPPCollection:
    """
    Loads and manages a collection of SPPs for all relevant atom pairs.
    Provides scoring for atomic structures using the SPP potentials.
    """
    include_diagonal_pair_terms = True

    def __init__(
        self,
        spp_dir=None,
        cutoff=DEFAULT_SPP_CUTOFF,
        missing_pair_policy="neutral",
        regularisation_spp_dir=None,
        regularisation_weight=0.0,
        regularization_spp_dir=None,
        regularization_weight=None,
    ):
        """
        Args:
            spp_dir (str): Path to the directory containing SPP .POT files.
        """
        self.spp_dir = _resolve_spp_dir(spp_dir)
        self.cutoff = float(cutoff)
        self.missing_pair_policy = str(missing_pair_policy or "neutral")
        if regularization_weight is not None:
            regularisation_weight = regularization_weight
        if regularization_spp_dir and not regularisation_spp_dir:
            regularisation_spp_dir = regularization_spp_dir
        self.regularisation_weight = float(regularisation_weight or 0.0)
        self.regularisation_spp_dir = _resolve_regularisation_dir(regularisation_spp_dir)
        if not self.spp_dir.exists():
            raise RuntimeError(
                "SPP POT root not found.\n"
                f"expected: {self.spp_dir}\n"
                "Fix: provide pot_root or set QLIP_SPP_POT_DIR to a compatible "
                "user-supplied POT library."
            )
        self.spps = {}  # Dictionary to store SPP objects for each atom pair
        self.maps = {}  # Dictionary of vectorised function to map distances to spp
        self.regularisation_spps = {}
        self.regularisation_maps = {}
        self.regularisation_load_errors = []
        if self.regularisation_weight > 0.0:
            self.load_regularisation()

    def _missing_pair_spp(self):
        if getattr(self, "missing_pair_policy", "neutral") == "soft_repulsive":
            return soft_missing_pair_penalty
        return None

    def _regularisation_spp(self, key):
        if float(getattr(self, "regularisation_weight", 0.0) or 0.0) <= 0.0:
            return None
        return getattr(self, "regularisation_spps", {}).get(key)

    def _resolve_pot_path(self, a, b):
        pair1 = f"{a.upper()}-{b.upper()}"
        pair2 = f"{b.upper()}-{a.upper()}"
        candidates = [
            self.spp_dir / pair1 / f"{pair1}.POT",
            self.spp_dir / pair2 / f"{pair2}.POT",
            self.spp_dir / f"{pair1}.POT",
            self.spp_dir / f"{pair2}.POT",
        ]
        for path in candidates:
            if path.exists():
                return path
        attempts = "\n".join(f"  - {p}" for p in candidates)
        raise RuntimeError(
            f"SPP POT file not found for pair {a}-{b}.\n"
            f"pot_root: {self.spp_dir}\n"
            f"attempted:\n{attempts}"
        )

    def load(self, pairs):
        """
        Load SPPs for all unique pairs in the provided set.
        Args:
            pairs (Iterable[Tuple[str, str]]): Atom type pairs to load SPPs for.
        Raises:
            RuntimeError: If a required SPP .POT file is missing.
        """
        if os.environ.get("QLIP_DEBUG_SPP") == "1":
            print(f"[SPP] pot_root={self.spp_dir}")
        for pair in pairs:
            a, b = pair
            # Always sort the pair alphabetically for consistency
            key = canonical_pair_key(a, b)
            if key in self.spps:
                continue  # Already loaded
            try:
                pot_file = self._resolve_pot_path(a, b)
            except RuntimeError:
                if self.missing_pair_policy in {"soft_repulsive", "fallback"}:
                    continue
                raise
            # Read the .POT file to get r and U(r)
            r_grid, U_grid = self._read_pot(pot_file)
            # Create an SPP object and store it in the dictionary
            self.spps[key] = SPP(r_grid, U_grid)
            # create a vectorised version of the SPP call function
            self.maps[key] = np.vectorize(self.spps[key])

    def load_regularisation(self, root=None):
        raw_root = _resolve_regularisation_dir(root) if root else getattr(self, "regularisation_spp_dir", None)
        if raw_root is None:
            raise RuntimeError("regularisation_spp_dir is required when regularisation_weight is greater than zero.")
        root_path = Path(raw_root).expanduser().resolve()
        self.regularisation_spp_dir = root_path
        if not root_path.exists():
            raise RuntimeError(f"regularisation_spp_dir does not exist: {root_path}")
        pot_files = sorted(root_path.rglob("*.POT"))
        if not pot_files:
            raise RuntimeError(f"regularisation_spp_dir contains no .POT files: {root_path}")

        loaded = 0
        for pot_file in pot_files:
            key = _pair_from_pot_path(pot_file)
            if key is None or key in self.regularisation_spps:
                continue
            try:
                r_grid, U_grid = self._read_pot(pot_file)
                self.regularisation_spps[key] = SPP(r_grid, U_grid)
                self.regularisation_maps[key] = np.vectorize(self.regularisation_spps[key])
                loaded += 1
            except Exception as exc:
                self.regularisation_load_errors.append({"path": str(pot_file), "error": str(exc)})
        if loaded == 0:
            raise RuntimeError(
                f"regularisation_spp_dir contains no loadable .POT files: {root_path}"
            )
        return loaded

    @staticmethod
    def _read_pot(filename):
        """
        Read an SPP .POT file and return r and U(r) arrays.
        Args:
            filename (str): Path to the .POT file.
        Returns:
            Tuple[np.ndarray, np.ndarray]: r_grid, U_grid
        """
        data = []
        with open(filename, 'r') as f:
            for line in f:
                # Ignore lines that are not data (e.g., headers, comments)
                line = line.strip()
                if line == '':
                    continue
                if line.lower().startswith('spline'):
                    continue
                if line[0].isalpha():
                    continue
                # Split the line into parts and convert to floats
                parts = line.split()
                if len(parts) == 2:
                    r_value = float(parts[0])
                    U_value = float(parts[1])
                    data.append([r_value, U_value])
        # Convert the data list to numpy arrays
        data = np.array(data)
        r_grid = data[:, 0]
        U_grid = data[:, 1]
        return r_grid, U_grid

    def get(self, a, b):
        """
        Retrieve the SPP object for a given atom pair.
        Args:
            a (str): Atom type 1
            b (str): Atom type 2
        Returns:
            SPP: The SPP object for the pair
        """
        key = canonical_pair_key(a, b)
        return self.spps[key]

    def score(self, symbols, positions, cell, pbc=True):
        """
        Compute the total SPP score for a structure.
        Periodic scoring uses the same unordered-pair convention as objective
        compilation: off-diagonal atom pairs are counted once, central
        self-distances are excluded, and translated self-images are included.
        Args:
            symbols (List[str]): List of atom symbols (e.g., ['O', 'Sr', 'Ti', ...])
            positions (np.ndarray): Nx3 array of atomic positions
            cell (np.ndarray): 3x3 cell matrix
            pbc (bool): Whether to use periodic boundary conditions
        Returns:
            float: The total SPP score (lower is more stable/likely)
        """
        spp_score = 0.0
        n_atoms = len(symbols)
        inv_cell = np.linalg.inv(_as_cell_matrix(cell))
        frac_positions = np.asarray(positions, dtype=float) @ inv_cell
        if pbc:
            for i in range(n_atoms):
                pair = canonical_pair_key(symbols[i], symbols[i])
                spp = self.spps.get(pair)
                reg_spp = self._regularisation_spp(pair)
                if spp is not None:
                    spp_score += periodic_spp_sum(
                        frac_positions[i],
                        frac_positions[i],
                        cell,
                        spp,
                        cutoff=self.cutoff,
                        diagonal_self_image=True,
                    )
                if reg_spp is not None:
                    spp_score += self.regularisation_weight * periodic_spp_sum(
                        frac_positions[i],
                        frac_positions[i],
                        cell,
                        reg_spp,
                        cutoff=self.cutoff,
                        diagonal_self_image=True,
                    )
        # Loop over all unique pairs of atoms
        for i in range(n_atoms):
            for j in range(i+1, n_atoms):
                atom1 = symbols[i]
                atom2 = symbols[j]
                pair = canonical_pair_key(atom1, atom2)
                # Get the SPP object for this pair
                spp = self.spps.get(pair)
                reg_spp = self._regularisation_spp(pair)
                if spp is None and reg_spp is None:
                    spp = self._missing_pair_spp()
                    if spp is None:
                        continue
                if pbc:
                    if spp is not None:
                        spp_score += periodic_spp_sum(
                            frac_positions[i],
                            frac_positions[j],
                            cell,
                            spp,
                            cutoff=self.cutoff,
                            diagonal_self_image=False,
                        )
                    if reg_spp is not None:
                        spp_score += self.regularisation_weight * periodic_spp_sum(
                            frac_positions[i],
                            frac_positions[j],
                            cell,
                            reg_spp,
                            cutoff=self.cutoff,
                            diagonal_self_image=False,
                        )
                else:
                    distance = float(np.linalg.norm(np.asarray(positions[j]) - np.asarray(positions[i])))
                    if ZERO_DISTANCE_TOL < distance <= self.cutoff:
                        if spp is not None:
                            spp_score += float(spp(distance))
                        if reg_spp is not None:
                            spp_score += self.regularisation_weight * float(reg_spp(distance))
        return spp_score

    def pair_cost_matrix(self, pair, positions, cutoff=None):
        """
        Compile periodic all-image SPP coefficients for candidate site pairs.

        The returned matrix is symmetric for convenient lookup, but the solver
        consumes it with an unordered ``i < j`` off-diagonal convention. Diagonal
        entries represent translated self-image contributions only; the central
        zero-distance self image is excluded by ``periodic_spp_sum``.
        """
        key = canonical_pair_key(pair[0], pair[1])
        spp = self.spps.get(key)
        reg_spp = self._regularisation_spp(key)
        if spp is None and reg_spp is None:
            spp = self._missing_pair_spp()
            if spp is None:
                raise KeyError(key)
        cutoff = self.cutoff if cutoff is None else float(cutoff)
        frac = positions.get_scaled_positions()
        cell = positions.cell
        n_sites = len(frac)
        matrix = np.zeros((n_sites, n_sites), dtype=float)
        for i in range(n_sites):
            for j in range(i, n_sites):
                coeff = 0.0
                if spp is not None:
                    coeff += periodic_spp_sum(
                        frac[i],
                        frac[j],
                        cell,
                        spp,
                        cutoff=cutoff,
                        diagonal_self_image=i == j,
                    )
                if reg_spp is not None:
                    coeff += float(getattr(self, "regularisation_weight", 0.0) or 0.0) * periodic_spp_sum(
                        frac[i],
                        frac[j],
                        cell,
                        reg_spp,
                        cutoff=cutoff,
                        diagonal_self_image=i == j,
                    )
                matrix[i, j] = coeff
                matrix[j, i] = coeff
        return matrix
    
    def __call__(self, pair, distances):
        return self.maps[pair](distances)

def compute_spp_objective(atoms, spp):
    """
    Compute the SPP objective for a given ASE Atoms object and SPPCollection.
    Args:
        atoms (ase.Atoms): The structure to score.
        spp (SPPCollection): The loaded SPP potentials.
    Returns:
        float: The total SPP score for the structure.
    """
    # Get the chemical symbols, positions, and cell from the Atoms object
    symbols = atoms.get_chemical_symbols()
    positions = atoms.get_positions()
    cell = atoms.get_cell()
    # Compute the SPP score using the SPPCollection
    score = spp.score(symbols, positions, cell, pbc=True)
    return score 
