import numpy as np
import matplotlib.pyplot as plt
from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

# ============================================================
# CLEAN FRONT-FACING 3D SEMANTIC LANDSCAPE
#
# Output:
#   semantic_landscape_front.png
#   semantic_landscape_front_transparent.png
#   semantic_landscape_front.svg
#
# Designed for Photoshop:
# - no labels
# - no legend
# - no axes
# - clean dots / contours / dashed lines
# - camera is front-facing, not behind the landscape
# ============================================================

np.random.seed(9)

# ------------------------------------------------------------
# 1. Semantic island definitions
# ------------------------------------------------------------
clusters = {
    "perovskite": {
        "center": (-2.2, 1.0),
        "sigma": (1.05, 0.85),
        "amp": 3.0,
        "color": "#3B73B9",
        "n": 28,
    },
    "spinel": {
        "center": (2.0, 1.45),
        "sigma": (0.9, 0.75),
        "amp": 2.35,
        "color": "#4DA64D",
        "n": 22,
    },
    "garnet": {
        "center": (2.25, -1.65),
        "sigma": (1.0, 0.85),
        "amp": 2.1,
        "color": "#D24B4B",
        "n": 22,
    },
    "layered": {
        "center": (-1.25, -2.05),
        "sigma": (1.15, 0.8),
        "amp": 2.0,
        "color": "#8E5AAE",
        "n": 20,
    },
}

# ------------------------------------------------------------
# 2. Landscape generation
# ------------------------------------------------------------
def gaussian2d(X, Y, cx, cy, sx, sy, amp):
    return amp * np.exp(
        -(((X - cx) ** 2) / (2 * sx ** 2) + ((Y - cy) ** 2) / (2 * sy ** 2))
    )


def landscape_height(x, y):
    z = 0.0
    for c in clusters.values():
        cx, cy = c["center"]
        sx, sy = c["sigma"]
        amp = c["amp"]
        z += gaussian2d(x, y, cx, cy, sx, sy, amp)
    return z


x = np.linspace(-5, 5, 280)
y = np.linspace(-5, 5, 280)
X, Y = np.meshgrid(x, y)

Z = landscape_height(X, Y)

# Subtle ripple so it looks less artificially perfect
Z += 0.035 * np.sin(2.2 * X) * np.cos(1.7 * Y)

# ------------------------------------------------------------
# 3. Generate dots on each semantic island
# ------------------------------------------------------------
points = []

for name, cfg in clusters.items():
    cx, cy = cfg["center"]
    sx, sy = cfg["sigma"]
    n = cfg["n"]

    px = np.random.normal(cx, sx * 0.38, n)
    py = np.random.normal(cy, sy * 0.38, n)

    px = np.clip(px, -4.8, 4.8)
    py = np.clip(py, -4.8, 4.8)

    pz = landscape_height(px, py) + 0.10 + np.random.uniform(0.0, 0.08, n)

    for i in range(n):
        points.append(
            {
                "cluster": name,
                "x": px[i],
                "y": py[i],
                "z": pz[i],
                "color": cfg["color"],
            }
        )

px_all = np.array([p["x"] for p in points])
py_all = np.array([p["y"] for p in points])
pz_all = np.array([p["z"] for p in points])
cluster_all = np.array([p["cluster"] for p in points])

# ------------------------------------------------------------
# 4. Query and retrieval geometry
# ------------------------------------------------------------

# Query starts from the actual front-left foreground.
# This is one of the important fixes.
query_origin = np.array([-4.3, -4.3, 4.15])

# Query lands near perovskite-like island.
query_land_xy = np.array([-2.05, 0.9])
query_land_z = float(landscape_height(query_land_xy[0], query_land_xy[1]) + 0.38)
query_land = np.array([query_land_xy[0], query_land_xy[1], query_land_z])

# Find nearest neighbours around query landing.
d2 = (px_all - query_land_xy[0]) ** 2 + (py_all - query_land_xy[1]) ** 2
nn_idx = np.argsort(d2)[:7]

# One selected neighbour for a dashed highlight line.
selected_nn_idx = nn_idx[2]

# One distant comparison point in another cluster.
far_cluster_indices = np.where(cluster_all == "garnet")[0]
far_idx = far_cluster_indices[
    np.argmin(
        (px_all[far_cluster_indices] - 2.2) ** 2
        + (py_all[far_cluster_indices] + 1.65) ** 2
    )
]

# ------------------------------------------------------------
# 5. Plot setup
# ------------------------------------------------------------
fig = plt.figure(figsize=(14, 10))
ax = fig.add_subplot(111, projection="3d")

# Surface
ax.plot_surface(
    X,
    Y,
    Z,
    cmap=cm.viridis,
    alpha=0.90,
    linewidth=0,
    antialiased=True,
    shade=True,
)

# Floor contour projection
z_floor = Z.min() - 0.35
ax.contour(
    X,
    Y,
    Z,
    zdir="z",
    offset=z_floor,
    levels=18,
    colors="black",
    linewidths=0.45,
    alpha=0.25,
)

# ------------------------------------------------------------
# 6. Dot clusters
# ------------------------------------------------------------
for name, cfg in clusters.items():
    mask = cluster_all == name
    ax.scatter(
        px_all[mask],
        py_all[mask],
        pz_all[mask],
        s=54,
        c=cfg["color"],
        alpha=0.92,
        edgecolors="white",
        linewidths=0.65,
        depthshade=False,
    )

# Highlight nearest neighbours
ax.scatter(
    px_all[nn_idx],
    py_all[nn_idx],
    pz_all[nn_idx] + 0.06,
    s=125,
    c="#F2A541",
    edgecolors="black",
    linewidths=1.2,
    depthshade=False,
    zorder=20,
)

# Query origin dot
ax.scatter(
    [query_origin[0]],
    [query_origin[1]],
    [query_origin[2]],
    s=170,
    c="black",
    edgecolors="black",
    linewidths=1.0,
    depthshade=False,
    zorder=30,
)

# Query landing star
ax.scatter(
    [query_land[0]],
    [query_land[1]],
    [query_land[2]],
    s=280,
    c="#FFD84D",
    marker="*",
    edgecolors="black",
    linewidths=1.25,
    depthshade=False,
    zorder=35,
)

# ------------------------------------------------------------
# 7. Dashed query line and arrowhead
# ------------------------------------------------------------
ax.plot(
    [query_origin[0], query_land[0]],
    [query_origin[1], query_land[1]],
    [query_origin[2], query_land[2]],
    linestyle="--",
    linewidth=2.8,
    color="black",
    alpha=0.95,
    zorder=25,
)

direction = query_land - query_origin
direction = direction / np.linalg.norm(direction)

arrow_start = query_land - direction * 0.58

ax.quiver(
    arrow_start[0],
    arrow_start[1],
    arrow_start[2],
    direction[0],
    direction[1],
    direction[2],
    length=0.44,
    color="black",
    linewidth=2.0,
    arrow_length_ratio=0.55,
    normalize=False,
)

# ------------------------------------------------------------
# 8. Ring around nearest-neighbour landing region
# ------------------------------------------------------------
theta = np.linspace(0, 2 * np.pi, 400)
ring_r = 0.78

ring_x = query_land_xy[0] + ring_r * np.cos(theta)
ring_y = query_land_xy[1] + ring_r * np.sin(theta)
ring_z = landscape_height(ring_x, ring_y) + 0.23

ax.plot(
    ring_x,
    ring_y,
    ring_z,
    color="#FFD84D",
    linewidth=3.2,
    alpha=0.96,
    zorder=24,
)

# ------------------------------------------------------------
# 9. Dashed pointer to selected neighbour
# ------------------------------------------------------------
sel = np.array(
    [
        px_all[selected_nn_idx],
        py_all[selected_nn_idx],
        pz_all[selected_nn_idx] + 0.13,
    ]
)

# Floating anchor point for Photoshop label later
sel_anchor = sel + np.array([-1.10, -0.75, 0.95])

ax.plot(
    [sel_anchor[0], sel[0]],
    [sel_anchor[1], sel[1]],
    [sel_anchor[2], sel[2]],
    linestyle="--",
    linewidth=2.0,
    color="#F2A541",
    alpha=0.96,
)

ax.scatter(
    [sel_anchor[0]],
    [sel_anchor[1]],
    [sel_anchor[2]],
    s=42,
    c="#F2A541",
    edgecolors="black",
    linewidths=0.8,
    depthshade=False,
)

ax.scatter(
    [sel[0]],
    [sel[1]],
    [sel[2]],
    s=175,
    c="#F2A541",
    edgecolors="black",
    linewidths=1.4,
    depthshade=False,
)

# ------------------------------------------------------------
# 10. Dashed pointer to distant comparison point
# ------------------------------------------------------------
far = np.array(
    [
        px_all[far_idx],
        py_all[far_idx],
        pz_all[far_idx] + 0.12,
    ]
)

far_anchor = far + np.array([1.15, -0.70, 1.05])

ax.plot(
    [far_anchor[0], far[0]],
    [far_anchor[1], far[1]],
    [far_anchor[2], far[2]],
    linestyle="--",
    linewidth=2.0,
    color="#D24B4B",
    alpha=0.96,
)

ax.scatter(
    [far_anchor[0]],
    [far_anchor[1]],
    [far_anchor[2]],
    s=42,
    c="#D24B4B",
    edgecolors="black",
    linewidths=0.8,
    depthshade=False,
)

ax.scatter(
    [far[0]],
    [far[1]],
    [far[2]],
    s=165,
    c="#D24B4B",
    edgecolors="black",
    linewidths=1.35,
    depthshade=False,
)

# ------------------------------------------------------------
# 11. Camera and layout
# ------------------------------------------------------------

# IMPORTANT:
# This is the front-facing view. This should stop the
# "we are behind the visualisation" issue.
ax.view_init(elev=20, azim=45)

# Zoom. Lower number = closer.
# If your matplotlib warns this is deprecated, it still usually works.
try:
    ax.dist = 8.2
except Exception:
    pass

ax.set_xlim(-5, 5)
ax.set_ylim(-5, 5)
ax.set_zlim(z_floor, Z.max() + 1.45)

# Remove axes, ticks, panes, grid
ax.set_axis_off()
ax.grid(False)

fig.patch.set_facecolor("white")
ax.set_facecolor("white")

plt.tight_layout(pad=0)

# ------------------------------------------------------------
# 12. Save outputs
# ------------------------------------------------------------
plt.savefig(
    "semantic_landscape_front.png",
    dpi=450,
    bbox_inches="tight",
    pad_inches=0.02,
    facecolor="white",
)

plt.savefig(
    "semantic_landscape_front_transparent.png",
    dpi=450,
    bbox_inches="tight",
    pad_inches=0.02,
    transparent=True,
)

plt.savefig(
    "semantic_landscape_front.svg",
    bbox_inches="tight",
    pad_inches=0.02,
    transparent=True,
)

plt.show()