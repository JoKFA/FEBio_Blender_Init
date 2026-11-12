"""The display mesh carried by the tet mesh: our stand-in for Ziva's zEmbedder (docs/05 sections 1 and 3).

Every display vertex remembers one tet and its four barycentric coordinates λ there, so that after a
run its position is Σ λ_j x_j of that tet's four nodes. The tet is the one that contains the vertex;
for a vertex outside the mesh (65 % of the lip vertices, docs/05 section 1) it is the boundary tet that
owns the boundary face nearest to the vertex, and λ then has a negative entry: the position is
extrapolated with the same affine map. The attachment mapping (ADR-36) uses the very same tet and λ,
so a hard display vertex follows its bone exactly.

Everything is geometric mm (docs/05 section 2): the embedding is computed on the rest tet mesh and
applied to positions that `run` has already divided by k.
"""

from dataclasses import dataclass

import numpy as np

from asrp_core import tetmesh


@dataclass
class Embedding:
    tet: np.ndarray  # (v,) index of each display vertex's tet
    nodes: np.ndarray  # (v, 4) that tet's node indices (0-based, into the tet mesh)
    bary: np.ndarray  # (v, 4) barycentric coordinates λ, summing to 1; negative entries outside
    distance_mm: np.ndarray  # (v,) distance from the vertex to its tet: 0 inside

    @property
    def outside(self) -> np.ndarray:
        return self.distance_mm > 0


def barycentric(corners: np.ndarray, points: np.ndarray) -> np.ndarray:
    """λ of each point in its own tet: corners (v, 4, 3), points (v, 3) -> (v, 4)."""
    a = corners[:, 0]
    edges = np.stack([corners[:, k] - a for k in (1, 2, 3)], axis=2)
    local = np.linalg.solve(edges, (points - a)[..., None])[..., 0]
    return np.concatenate([1 - local.sum(axis=1, keepdims=True), local], axis=1)


def embed(mesh: tetmesh.TetMesh, points) -> Embedding:
    """Find each point's tet and barycentric coordinates (rule above)."""
    points = np.asarray(points, dtype=float)
    tet = tetmesh.containing_tets(mesh.nodes, mesh.tets, points)
    distance = np.zeros(len(points))
    outside = tet < 0
    if outside.any():
        faces, owner = tetmesh.boundary_faces_and_tets(mesh.tets)
        d, nearest = tetmesh.nearest_triangles(points[outside], mesh.nodes[faces])
        tet[outside] = owner[nearest]
        distance[outside] = d
    nodes = mesh.tets[tet]
    return Embedding(tet, nodes, barycentric(mesh.nodes[nodes], points), distance)


def apply(e: Embedding, node_positions) -> np.ndarray:
    """Display vertex positions (v, 3) for one set of tet node positions (n, 3)."""
    x = np.asarray(node_positions, dtype=float)[e.nodes]  # (v, 4, 3)
    return np.einsum("vj,vjk->vk", e.bary, x)


def clipped(bary: np.ndarray) -> np.ndarray:
    """λ̃: negative coordinates set to 0, then scaled to sum to 1 (docs/05 section 3)."""
    c = np.clip(bary, 0.0, None)
    return c / c.sum(axis=1, keepdims=True)


def spread(bary: np.ndarray) -> np.ndarray:
    """λ̂ = (λ̃ + 1/4) / 2: how a vertex's spring weight is shared among its tet's four nodes (docs/05
    section 3). Every node gets at least 1/8 and the four still sum to 1, so no node that a hard
    attachment would hold is left without a spring (with plain λ̃ a vertex outside its tet can give a
    node 0, and then stiffening the springs never reaches the hard result)."""
    return (clipped(bary) + 0.25) / 2
