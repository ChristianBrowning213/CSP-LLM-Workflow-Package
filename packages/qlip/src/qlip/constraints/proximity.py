import pyomo.environ as pyo

from qlip.data.registry import default_registry

class AtomicRadii:
    """
    Class adding proximity constraints based on the sizes of atoms
    """

    def __init__(self, radii=None):
        """
        It simply takes a dictionary of radii
        """
        if radii:
            self.rad = radii
        else:
            self.rad = default_registry().atomic_radius_map()

    def attach(self, allocation):

        m = allocation.m

        m.atomic_radii = pyo.ConstraintList()

        collision = {}

        for t1, t2 in allocation.pairs:
            collision[(t1, t2)] = self.rad[t1] + self.rad[t2]

        for i in m.Pos:
            for j in range(i+1, len(allocation.positions)):

                for t1, t2 in allocation.pairs:

                    if allocation._dist[i,j] < collision[t1,t2]:
                        m.atomic_radii.add(m.x[t1,i] + m.x[t2,j] <= 1)
                        m.atomic_radii.add(m.x[t2,i] + m.x[t1,j] <= 1)
        
