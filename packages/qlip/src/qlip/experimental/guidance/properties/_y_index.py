# qlip/experimental/guidance/properties/_y_index.py
from __future__ import annotations
from typing import Tuple, Any

def iter_Y_with_shell(allocation):
    """
    Yield triples ((i,j,t,u,shell), var) for all Y entries.
    If model Y index lacks shell, we try allocation.guidence_shell_of((i,j)) or fallback to shell=1.
    """
    m = allocation.m
    Y = getattr(m, "Y", None)
    if Y is None:
        return  # nothing

    # Pyomo VarData container exposes .index_set() or ._index for iter
    for idx in Y:
        # idx may be 4-tuple or 5-tuple
        if isinstance(idx, tuple):
            if len(idx) == 5:
                i,j,t,u,sh = idx
                yield (i,j,str(t),str(u),int(sh)), Y[idx]
            elif len(idx) == 4:
                i,j,t,u = idx
                # try to get shell from allocation
                getter = getattr(allocation, "guidence_shell_of", None)
                if callable(getter):
                    sh = int(getter((i,j)))
                else:
                    sh = 1
                yield (i,j,str(t),str(u),sh), Y[idx]
        # otherwise ignore
