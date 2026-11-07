"""Spike S2 (T-04): can the real lip mesh be tet-meshed, at what size, and how good are the tets?

Reads data/lab_export/mesh_middleres_OrbicularisOris.obj, converts it to mm, Z up (x 0.962, the
provisional unit, docs/11 Q3), and runs asrp_core.tetmesh at three edge lengths: tetSz 26.37 in mm
(25.4), half and double. For each it prints nodes, tets, time, volume against the surface's own,
the worst tets, and whether the 10,240 display vertices can be embedded: how many fall inside a
tet, and how far outside the rest are (they would be embedded in the nearest boundary tet).

The surface intersects itself at the mouth corners (266 triangles, found while doing T-04), which
is why TetGen refuses it and fTetWild is used.

    uv run python spikes/s2_tetmesh.py
"""

import sys
import time
from pathlib import Path

import numpy as np

from asrp_core.playback import boundary_faces
from asrp_core.tetmesh import quality, surface_volume, tetrahedralize

LIPS = Path(__file__).resolve().parents[1] / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj"
MM_PER_UNIT = 0.962
TET_SZ = 26.37  # zTet1, scene units (docs/13 E-02)
EDGES_MM = [TET_SZ * MM_PER_UNIT / 2, TET_SZ * MM_PER_UNIT, TET_SZ * MM_PER_UNIT * 2]


def read_lips_mm():
    vertices, triangles = [], []
    with LIPS.open(encoding="ascii") as f:
        for line in f:
            if line.startswith("v "):
                x, y, z = (float(c) * MM_PER_UNIT for c in line.split()[1:4])
                vertices.append((x, -z, y))
            elif line.startswith("f "):
                face = [int(c.split("/")[0]) - 1 for c in line.split()[1:]]
                triangles += [(face[0], face[i], face[i + 1]) for i in range(1, len(face) - 1)]
    return np.array(vertices), np.array(triangles)


def inside_any_tet(nodes, tets, points, tol=1e-9):
    """Whether each point lies in some tet (barycentric coordinates all >= 0), in chunks."""
    a = nodes[tets[:, 0]]
    m = np.stack([nodes[tets[:, k]] - a for k in (1, 2, 3)], axis=2)  # (t, 3, 3)
    inv = np.linalg.inv(m)
    found = np.zeros(len(points), dtype=bool)
    for start in range(0, len(points), 256):
        p = points[start : start + 256]
        local = np.einsum("tij,ptj->pti", inv, p[:, None, :] - a[None])  # (p, t, 3)
        bary = np.concatenate([1 - local.sum(axis=2, keepdims=True), local], axis=2)
        found[start : start + 256] = (bary >= -tol).all(axis=2).any(axis=1)
    return found


def distance_to_triangles(points, tri):
    """Shortest distance from each point to a set of triangles (n, 3, 3)."""
    best = np.full(len(points), np.inf)
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    n = np.cross(b - a, c - a)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    for start in range(0, len(points), 256):
        p = points[start : start + 256, None, :]
        # Foot of the perpendicular, counted only when it lands inside the triangle.
        h = np.einsum("ptj,tj->pt", p - a, n)
        foot = p - h[..., None] * n
        inside = np.ones(h.shape, dtype=bool)
        for u, v in ((a, b), (b, c), (c, a)):
            inside &= np.einsum("ptj,tj->pt", np.cross(v - u, foot - u), n) >= 0
        d = np.where(inside, np.abs(h), np.inf)
        for u, v in ((a, b), (b, c), (c, a)):
            s = np.clip(np.einsum("ptj,tj->pt", p - u, v - u) / np.einsum("tj,tj->t", v - u, v - u), 0, 1)
            d = np.minimum(d, np.linalg.norm(p - (u + s[..., None] * (v - u)), axis=2))
        best[start : start + 256] = d.min(axis=1)
    return best


def main():
    if not LIPS.is_file():
        sys.exit(f"{LIPS} is missing; it comes from tools/maya_export.py (docs/12)")
    vertices, triangles = read_lips_mm()
    enclosed = abs(surface_volume(vertices, triangles))
    print(f"lips: {len(vertices)} vertices, {len(triangles)} triangles, encloses {enclosed:,.0f} mm3")
    print(f"{'edge mm':>8} {'nodes':>6} {'tets':>6} {'time s':>6} {'vol %':>6} {'min vol mm3':>11} "
          f"{'min angle':>9} {'median edge':>11} {'inside':>7} {'max out mm':>10}")
    for edge in EDGES_MM:
        started = time.perf_counter()
        mesh = tetrahedralize(vertices, triangles, edge_mm=edge)
        seconds = time.perf_counter() - started
        q = quality(mesh)
        inside = inside_any_tet(mesh.nodes, mesh.tets, vertices)
        shell = np.array([face for face, _ in boundary_faces({"lips": mesh.tets.tolist()})])
        outside = distance_to_triangles(vertices[~inside], mesh.nodes[shell]) if (~inside).any() else np.zeros(1)
        print(f"{edge:8.1f} {q.nodes:6d} {q.tets:6d} {seconds:6.1f} {100 * (q.volume_mm3 / enclosed - 1):+6.1f} "
              f"{q.min_tet_volume_mm3:11.3f} {q.min_dihedral_deg:8.1f}d {q.median_edge_mm:11.1f} "
              f"{inside.mean():7.1%} {outside.max():10.2f}")


if __name__ == "__main__":
    main()
