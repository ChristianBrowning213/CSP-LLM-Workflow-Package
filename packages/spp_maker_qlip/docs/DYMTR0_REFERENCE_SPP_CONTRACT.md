# Dmytro reference SPP contract

Contract identifier: `dmytro_gr_v1`.

The preserved CoAs2 reference fit constructs a centered periodic supercell with each lattice-vector length at least 20 A and additionally requires every half-face height to cover `r_max + 3 sigma + 0.5 A`. Unit-cell atoms are the centers and supercell atoms are the neighbours. The central zero-distance self image is excluded. Canonical unordered pair counts use Gaussian deposition `exp[-0.5((r_k-d)/sigma)^2]`, truncated at three sigma, on 200 centers from 0.025 through 9.975 A (`r_max=10 A`, bin width `0.05 A`, sigma `0.1 A`).

For each structure and pair, shell normalization is

`g_AB(r) = counts_AB(r) / (4 pi r^2 dr * prefactor_AB)`.

For equal species, `prefactor_AA=N_unit(A)*rho_super(A)`. For unlike species, `prefactor_AB=N_unit(A)*rho_super(B)+N_unit(B)*rho_super(A)`. Structure-weighted `g(r)` curves are averaged per pair, with a denominator containing only structures that supply that pair. The potential is then exactly `U(r)=-ln(g(r)+1e-12)`.

The reference artifact is dimensionless, unshifted, unbandpassed, and has no short-range floor or corpus-derived scalar. The later historical CoAs2 calibration (`lambda=0.2206159719451987`) was a separate orchestration operation and is not part of this artifact contract.

The implementation is `spp_maker.common_contract`; the canonical geometry and normalization implementation remains `spp_maker.supercell_gr` and the CLI supercell builder.
