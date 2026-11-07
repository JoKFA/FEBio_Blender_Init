"""Fill a closed surface with tetrahedra for FEBio, and measure the result.

Ziva tet-meshes the lips itself and keeps only the size (`tetSz`), so we do it here (docs/13
E-02). The tool is fTetWild, through `pytetwild`: the lip mesh intersects itself where the upper
and lower lips fold into each other at the mouth corners (T-04), and fTetWild takes the solid the
surface encloses instead of refusing it, as TetGen does. The tets do not follow the surface
exactly: the fine display mesh is embedded in them afterwards, as Ziva's zEmbedder does.

Everything is in mm, the units the rest of the core uses.
"""

import contextlib
import tempfile
from dataclasses import dataclass

import numpy as np
import pytetwild

# Sharper detail is finer than the tets can follow anyway once the surface is embedded, and a
# tight envelope makes fTetWild resolve every crease regardless of the edge length asked for:
# on the lip mesh the default envelope (0.13 mm) gave ~6,500 nodes at 5, 12.7, 25.4 and 50.8 mm
# alike. Tying the envelope to the edge length makes the size setting mean what it says.
ENVELOPE_PER_EDGE = 1 / 20

# Each tet's faces, as the corner they are opposite; used for dihedral angles.
_OPPOSITE_FACES = ((1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2))


@dataclass
class TetMesh:
    nodes: np.ndarray  # (n, 3) float, mm
    tets: np.ndarray  # (m, 4) int, 0-based, positively oriented (FEBio's tet4 order)


@dataclass
class Quality:
    nodes: int
    tets: int
    volume_mm3: float
    min_tet_volume_mm3: float
    min_dihedral_deg: float
    median_edge_mm: float


def tetrahedralize(vertices_mm, triangles, edge_mm: float, envelope_mm: float | None = None) -> TetMesh:
    """Tet-mesh the solid a closed triangle surface encloses.

    edge_mm is the target tet edge length; envelope_mm is how far the mesh boundary may stray from
    the input surface (default edge_mm / 20).
    """
    vertices = np.asarray(vertices_mm, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("expected vertices as (n, 3) and triangles as (m, 3); split quads first")
    if edge_mm <= 0:
        raise ValueError(f"edge length must be positive, got {edge_mm} mm")
    envelope = edge_mm * ENVELOPE_PER_EDGE if envelope_mm is None else envelope_mm
    # pytetwild takes the envelope relative to the bounding-box diagonal.
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    # fTetWild writes __tracked_surface.stl into the working directory, quiet or not; keep it out
    # of the repo and the run folder.
    with tempfile.TemporaryDirectory() as scratch, contextlib.chdir(scratch):
        nodes, tets = pytetwild.tetrahedralize(
            vertices, faces, edge_length_abs=edge_mm, epsilon=envelope / diagonal, quiet=True
        )
    tets = np.array(tets, dtype=np.int64)
    # fTetWild writes every tet with negative volume; FEBio wants positive. Swapping two corners
    # flips one tet, so do it per tet rather than assuming the whole mesh is reversed.
    flip = signed_volumes(nodes, tets) < 0
    tets[flip] = tets[flip][:, [0, 2, 1, 3]]
    return TetMesh(np.asarray(nodes, dtype=np.float64), tets)


def signed_volumes(nodes, tets) -> np.ndarray:
    a, b, c, d = (nodes[tets[:, i]] for i in range(4))
    return np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a) / 6


def min_dihedral_deg(nodes, tets) -> np.ndarray:
    """Smallest dihedral angle of each tet. A flattened tet has one near 0."""
    normals = []
    for face in _OPPOSITE_FACES:
        a, b, c = (nodes[tets[:, k]] for k in face)
        n = np.cross(b - a, c - a)
        normals.append(n / np.linalg.norm(n, axis=1, keepdims=True))
    smallest = np.full(len(tets), 180.0)
    for i in range(4):
        for j in range(i + 1, 4):
            # The angle between two faces is 180 degrees minus the angle between their normals.
            cos = np.clip(np.einsum("ij,ij->i", normals[i], normals[j]), -1.0, 1.0)
            smallest = np.minimum(smallest, 180.0 - np.degrees(np.arccos(cos)))
    return smallest


def quality(mesh: TetMesh) -> Quality:
    volumes = signed_volumes(mesh.nodes, mesh.tets)
    pairs = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
    edges = np.concatenate(
        [np.linalg.norm(mesh.nodes[mesh.tets[:, i]] - mesh.nodes[mesh.tets[:, j]], axis=1) for i, j in pairs]
    )
    return Quality(
        nodes=len(mesh.nodes),
        tets=len(mesh.tets),
        volume_mm3=float(volumes.sum()),
        min_tet_volume_mm3=float(volumes.min()),
        min_dihedral_deg=float(min_dihedral_deg(mesh.nodes, mesh.tets).min()),
        median_edge_mm=float(np.median(edges)),
    )


def surface_volume(vertices, triangles) -> float:
    """Volume a closed, outward-wound triangle surface encloses (divergence theorem)."""
    v = np.asarray(vertices, dtype=np.float64)
    t = np.asarray(triangles)
    return float(np.einsum("ij,ij->i", v[t[:, 0]], np.cross(v[t[:, 1]], v[t[:, 2]])).sum() / 6)
