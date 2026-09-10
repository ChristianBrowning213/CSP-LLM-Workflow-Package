import numpy as np

# class Grid:

#     def __init__(self, kind=None, **kwargs):
#         self.kind = kind
#         self.parameters = kwargs

def uniform(steps):
    """
    Returns uniform grid of steps points. These are fractional coordinates.
    
    density=4 will generate points with x coordinates 0, 0.25, 0.5 and 0.75.
    Note that 1 is kind of another cell already. So, side/ions is the step size
    There will be prod(ions_on_side) points in total in the cell.
    """
            
    if isinstance(steps, int):
        steps = [steps]*3

    step = 1.0 / np.array(steps)

    pos = np.zeros((steps[0] * steps[1] * steps[2], 3))
    #print("The total number of points in the cell is ", len(self.ions))

    row = 0
    for (i, j, k) in np.ndindex(steps[0], steps[1], steps[2]):
        pos[row,] = np.array([i * step[0], j * step[1], k * step[2]])
        row = row + 1
    return pos