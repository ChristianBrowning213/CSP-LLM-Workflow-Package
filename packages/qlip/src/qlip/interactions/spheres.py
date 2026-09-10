"""Hard spheres interaction."""

import numpy as np


class HardSpheres:
    
    def __init__(self, radii):
        self.radii = radii

    def __call__(self, pair, distances):
        # distances = np.asarray(distances)
        return np.where(distances < 2*self.radii, 1, 0)
