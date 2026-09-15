import pyomo.environ as pyo
import json
from pathlib import Path
import os
import spglib
import numpy as np


class SpaceGroup:
    """
    A class to handle space group constraints.

    It has to be used with care. I don't pay much attention to 
    the unit cell standartisation and so forth. I am just applying 
    space group operations and check whether the associated points
    are next to each other to force them being the same.

    Ideally, you want to have a grid that respects the symmetry 
    and every position is associated with the whole crystallorgraphic 
    orbit as the set of allowed positions.
    """

    def __init__(self, group):
        """
        group (int) : Hall numbers of the group, 
                      Hall numbers are given here: https://yseto.net/en/sg/sg1
        """
        self.group = group

    def attach(self, allocation):
        """ 
        We are adding a list of equality constraints
        for the atomic positions that should be equivalent.
        We go through the list joining all equivalent positions.
        """

        m = allocation.m

        sym_op = spglib.get_symmetry_from_database(self.group)

        R, t = sym_op['rotations'], sym_op['translations']  # R: (n,3,3), t: (n,3)
        def wrap(x): return x - np.floor(x)

        pos2process = list(range(len(allocation.positions)))

        while len(pos2process) > 1:

            pos_id = pos2process[0]
            images = [wrap(Rk @ allocation._grid[pos_id] + tk) for Rk, tk in zip(R, t)]
            
            i = 1

            while i < len(pos2process):
                
                for j, pos in enumerate(images):
                    
                    if np.sum((allocation._grid[pos_id] - images[j])**2) < 5*1e-4:
                        pass

                del[j]

            del[0]

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