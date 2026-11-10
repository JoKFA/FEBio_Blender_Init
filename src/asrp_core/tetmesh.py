"""Fill a closed surface with tetrahedra for FEBio, check the result, and keep it on disk.

Ziva tet-meshes the lips itself and keeps only the size (`tetSz`), so we do it here (docs/13
E-02). The tool is fTetWild, through `pytetwild`: the lip mesh intersects itself where the upper
and lower lips fold into each other at the mouth corners (docs/05 pit 9), and fTetWild takes the
solid the surface encloses instead of refusing it, as TetGen does.

fTetWild gives a different mesh on every run, even single-threaded with the same input (docs/05
pit 12), so the mesh is generated once, explicitly (`tools/build_tetmesh.py`), written to
`data/tetmesh/` and read back with `load`, which checks its hash. Nothing regenerates it behind
the caller's back (requirement R-06: same input, same result).

Everything is in mm, Z up, the units and axes the rest of the core uses.
"""

import contextlib
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FORMAT = "asrp-tetmesh"
FORMAT_VERSION = 1

# Each tet's faces, as the corner they are opposite, wound so that they point outward when the
# tet is positively oriented. Used for the boundary and for dihedral angles.
_OPPOSITE_FACES = ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1))


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


def tetrahedralize(
    vertices_mm, triangles, edge_mm: float, envelope_mm: float, num_threads: int = 0
) -> TetMesh:
    """Tet-mesh the solid a closed triangle surface encloses.

    edge_mm is the target tet edge length; envelope_mm is how far the mesh boundary may stray from
    the input surface. The envelope, not the edge, decides how closely the mesh follows the
    surface, and so whether two parts of the surface closer than about twice the envelope stay
    apart (docs/05 pit 10). The result is not reproducible (pit 12): save it, don't regenerate it.
    """
    vertices = np.asarray(vertices_mm, dtype=np.float64)
    faces = np.asarray(triangles, dtype=np.int32)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("expected vertices as (n, 3) and triangles as (m, 3); split quads first")
    if edge_mm <= 0 or envelope_mm <= 0:
        raise ValueError(f"edge length and envelope must be positive, got {edge_mm} and {envelope_mm} mm")
    # Imported here, not at the top: reading a saved mesh (`load`) must not pull in fTetWild, and
    # only tools/build_tetmesh.py and the spikes ever generate one.
    import pytetwild

    # pytetwild takes the envelope relative to the bounding-box diagonal.
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    # fTetWild writes __tracked_surface.stl into the working directory, quiet or not; keep it out
    # of the repo and the run folder.
    with tempfile.TemporaryDirectory() as scratch, contextlib.chdir(scratch):
        nodes, tets = pytetwild.tetrahedralize(
            vertices,
            faces,
            edge_length_abs=edge_mm,
            epsilon=envelope_mm / diagonal,
            num_threads=num_threads,
            quiet=True,
        )
    tets = np.array(tets, dtype=np.int64)
    # fTetWild writes every tet with negative volume; FEBio wants positive. Swapping two corners
    # flips one tet, so do it per tet rather than assuming the whole mesh is reversed.
    flip = signed_volumes(nodes, tets) < 0
    tets[flip] = tets[flip][:, [0, 2, 1, 3]]
    return TetMesh(np.asarray(nodes, dtype=np.float64), tets)


# --- measures -------------------------------------------------------------------------------


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
            # Outward normals: the angle between two faces is 180 degrees minus the angle between
            # their normals.
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


# --- topology -------------------------------------------------------------------------------


class _Sets:
    """Union-find over 0..n-1."""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)

    def count(self) -> int:
        return len({self.find(a) for a in range(len(self.parent))})


def _join_shared(cells: np.ndarray, facets: tuple[tuple[int, ...], ...], keep=None) -> _Sets:
    """Union cells that share a facet (a sorted tuple of node ids); keep(facet nodes) filters."""
    sets = _Sets(len(cells))
    keys = np.concatenate([np.sort(cells[:, list(f)], axis=1) for f in facets])
    owner = np.tile(np.arange(len(cells)), len(facets))
    if keep is not None:
        mask = keep(keys)
        keys, owner = keys[mask], owner[mask]
    if len(keys) == 0:
        return sets
    _, group = np.unique(keys, axis=0, return_inverse=True)
    order = np.argsort(group, kind="stable")
    g, o = group[order], owner[order]
    for k in np.nonzero(g[1:] == g[:-1])[0]:
        sets.union(int(o[k]), int(o[k + 1]))
    return sets


def boundary_faces(tets) -> np.ndarray:
    """Faces that belong to exactly one tet, wound outward."""
    tets = np.asarray(tets)
    faces = np.concatenate([tets[:, list(f)] for f in _OPPOSITE_FACES])
    _, inverse, counts = np.unique(np.sort(faces, axis=1), axis=0, return_inverse=True, return_counts=True)
    return faces[counts[inverse] == 1]


def tet_components(tets) -> int:
    """How many pieces the tets make, counting two tets as joined only through a shared face."""
    return _join_shared(np.asarray(tets), ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))).count()


@dataclass
class Topology:
    components: int  # pieces of the solid (face-connected tets)
    nonmanifold_edges: int  # boundary edges not shared by exactly two boundary faces
    nonmanifold_vertices: int  # boundary vertices whose faces do not form one fan
    boundary_components: int
    boundary_genus: int  # total genus of the boundary surface(s); a ring is 1


def surface_topology(triangles) -> tuple[int, int, int, int]:
    """(non-manifold edges, non-manifold vertices, components, genus) of a triangle surface."""
    tri = np.asarray(triangles)
    edges = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    unique_edges, edge_counts = np.unique(edges, axis=0, return_counts=True)
    bad_edges = int((edge_counts != 2).sum())
    # A vertex is manifold when its triangles form a single fan: joined through edges at the vertex.
    corners = np.concatenate([tri[:, 0], tri[:, 1], tri[:, 2]])
    owners = np.tile(np.arange(len(tri)), 3)
    order = np.argsort(corners, kind="stable")
    corners, owners = corners[order], owners[order]
    starts = np.r_[0, np.nonzero(corners[1:] != corners[:-1])[0] + 1, len(corners)]
    bad_vertices = 0
    for s, e in zip(starts[:-1], starts[1:]):
        fan = tri[owners[s:e]]
        v = corners[s]
        # Each triangle at v has two edges through v, named by the other end.
        others = [tuple(int(x) for x in row if x != v) for row in fan]
        sets = _Sets(len(fan))
        first: dict[int, int] = {}
        for i, pair in enumerate(others):
            for w in pair:
                if w in first:
                    sets.union(i, first[w])
                else:
                    first[w] = i
        bad_vertices += sets.count() != 1
    pieces = _join_shared(tri, ((0, 1), (1, 2), (0, 2))).count()
    vertices = len(np.unique(tri))
    euler = vertices - len(unique_edges) + len(tri)
    genus = (2 * pieces - euler) // 2
    return int(bad_edges), int(bad_vertices), int(pieces), int(genus)


def topology(mesh: TetMesh) -> Topology:
    bad_edges, bad_vertices, pieces, genus = surface_topology(boundary_faces(mesh.tets))
    return Topology(tet_components(mesh.tets), bad_edges, bad_vertices, pieces, genus)


# --- upper and lower lip apart ----------------------------------------------------------------


def slice_pieces(points, cells, x0: float) -> int:
    """How many pieces the cells cut by the plane x = x0 make.

    Two cut cells are in the same piece when they share a facet (an edge for triangles, a face
    for tets) that the plane also cuts. Away from the mouth corners a slice through the lip ring
    gives two pieces, upper and lower lip; where they are welded together it gives one.
    """
    points = np.asarray(points)
    cells = np.asarray(cells)
    xs = points[cells][:, :, 0]
    cut = cells[(xs.min(axis=1) < x0) & (xs.max(axis=1) > x0)]
    if len(cut) == 0:
        return 0
    n = cells.shape[1]
    facets = tuple(tuple(i for i in range(n) if i != skip) for skip in range(n))

    def crossed(keys):
        fx = points[keys][:, :, 0]
        return (fx.min(axis=1) < x0) & (fx.max(axis=1) > x0)

    return _join_shared(cut, facets, crossed).count()


def _cross_section(points, triangles, x0: float):
    """The segments (k, 2, 2), in (y, z), where x = x0 cuts the triangles, and each one's piece."""
    xs = points[triangles][:, :, 0]
    cut = triangles[(xs.min(axis=1) < x0) & (xs.max(axis=1) > x0)]
    ends = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        pa, pb = points[cut[:, a]], points[cut[:, b]]
        s = (x0 - pa[:, 0]) / np.where(pa[:, 0] == pb[:, 0], 1.0, pb[:, 0] - pa[:, 0])
        hit = (pa[:, 0] - x0) * (pb[:, 0] - x0) < 0
        ends.append((hit, (pa + s[:, None] * (pb - pa))[:, 1:]))
    # A triangle the plane cuts (missing its vertices) crosses exactly two of its edges.
    hits = np.stack([h for h, _ in ends], axis=1)
    pts = np.stack([p for _, p in ends], axis=1)
    segments = np.stack([pts[i][hits[i]] for i in range(len(cut))]) if len(cut) else np.zeros((0, 2, 2))

    def crossed(keys):
        fx = points[keys][:, :, 0]
        return (fx.min(axis=1) < x0) & (fx.max(axis=1) > x0)

    sets = _join_shared(cut, ((0, 1), (1, 2), (0, 2)), crossed)
    return segments, np.array([sets.find(i) for i in range(len(cut))])


def _segments_cross(a, b) -> np.ndarray:
    """(len a, len b) whether 2D segments a[i] and b[j] intersect."""
    p, r = a[:, None, 0], a[:, None, 1] - a[:, None, 0]
    q, s = b[None, :, 0], b[None, :, 1] - b[None, :, 0]

    def cross(u, v):
        return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]

    den = cross(r, s)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = cross(q - p, s) / den
        u = cross(q - p, r) / den
    return (den != 0) & (t >= 0) & (t <= 1) & (u >= 0) & (u <= 1)


APART, CROSSING, JOINED = 2, 1, 0  # what a slice of the lips shows


def surface_slice_state(points, triangles, x0: float) -> int:
    """APART when the slice x = x0 of a surface has two or more pieces that do not cross each
    other; CROSSING when it has two or more but they pass through each other; else JOINED.

    The lip surface intersects itself at the mouth corners (docs/05 pit 9): there the upper and
    lower lip are two pieces of the slice but pass through each other, so they are not apart and
    no tet mesh can keep them apart.
    """
    segments, labels = _cross_section(np.asarray(points), np.asarray(triangles), x0)
    if len(set(labels.tolist())) < 2:
        return JOINED
    hits = _segments_cross(segments, segments) & (labels[:, None] != labels[None, :])
    return CROSSING if hits.any() else APART


def surface_apart(points, triangles, x0: float) -> bool:
    return surface_slice_state(points, triangles, x0) == APART


@dataclass
class Separation:
    """Where along x the upper and lower lips are apart, as slices with two or more pieces."""

    start_mm: float  # first slice of the run of separated slices around the centre
    end_mm: float
    width_mm: float
    pockets: int  # runs of crossing slices with separated slices on both sides (surfaces only)


def separation(points, cells, xs) -> Separation:
    """The run of consecutive slices x in xs, through the middle of xs, where the lips are apart.

    For tets, apart means the slice cuts two or more pieces. For a triangle surface it also means
    the pieces do not cross each other (surface_apart). Only the run through the middle counts:
    a weld anywhere between the centre and a corner ends the run there, even if the slit opens
    again further out.
    """
    xs = np.asarray(xs, dtype=float)
    cells = np.asarray(cells)
    if len(xs) == 0:  # a mesh smaller than one slice step has nothing to slice
        return Separation(0.0, 0.0, 0.0, 0)
    if cells.shape[1] == 3:
        state = np.array([surface_slice_state(points, cells, x) for x in xs])
    else:
        state = np.array([APART if slice_pieces(points, cells, x) >= 2 else JOINED for x in xs])
    apart = state == APART
    pockets, k = 0, 0
    while k < len(state):
        if state[k] != CROSSING:
            k += 1
            continue
        j = k
        while j < len(state) and state[j] == CROSSING:
            j += 1
        pockets += int(k > 0 and j < len(state) and state[k - 1] == APART and state[j] == APART)
        k = j
    mid = len(xs) // 2
    if not apart[mid]:
        return Separation(float(xs[mid]), float(xs[mid]), 0.0, pockets)
    lo = mid
    while lo > 0 and apart[lo - 1]:
        lo -= 1
    hi = mid
    while hi < len(xs) - 1 and apart[hi + 1]:
        hi += 1
    return Separation(float(xs[lo]), float(xs[hi]), float(xs[hi] - xs[lo]), pockets)


def slice_positions(points, step_mm: float = 0.25) -> np.ndarray:
    """Slice planes across the x range, symmetric about x = 0, offset so they miss mesh vertices."""
    reach = float(np.abs(np.asarray(points)[:, 0]).max())
    half = np.arange(step_mm * 0.5 + 1.234e-4, reach, step_mm)
    return np.concatenate([-half[::-1], half])


# --- how well the display mesh can be embedded -------------------------------------------------


def inside_any_tet(nodes, tets, points, tol=1e-9) -> np.ndarray:
    """Whether each point lies in some tet (barycentric coordinates all >= 0)."""
    corners = nodes[tets]  # (t, 4, 3)
    a = corners[:, 0]
    inv = np.linalg.inv(np.stack([corners[:, k] - a for k in (1, 2, 3)], axis=2))
    lo, hi = corners.min(axis=1) - tol, corners.max(axis=1) + tol
    # A uniform grid of cells about twice the median tet size: each point only tests the tets
    # whose bounding box touches its cell.
    size = 2 * float(np.median((hi - lo).max(axis=1)))
    origin = lo.min(axis=0)
    first, last = np.floor((lo - origin) / size).astype(int), np.floor((hi - origin) / size).astype(int)
    grid: dict[tuple, list[int]] = {}
    for t, (f, l) in enumerate(zip(first.tolist(), last.tolist())):
        for i in range(f[0], l[0] + 1):
            for j in range(f[1], l[1] + 1):
                for k in range(f[2], l[2] + 1):
                    grid.setdefault((i, j, k), []).append(t)
    cells = np.floor((np.asarray(points) - origin) / size).astype(int)
    found = np.zeros(len(points), dtype=bool)
    for n, (p, cell) in enumerate(zip(points, cells.tolist())):
        near = np.array(grid.get(tuple(cell), []), dtype=int)
        if len(near) == 0:
            continue
        near = near[((lo[near] <= p) & (p <= hi[near])).all(axis=1)]
        local = np.einsum("tij,tj->ti", inv[near], p - a[near])
        bary = np.concatenate([1 - local.sum(axis=1, keepdims=True), local], axis=1)
        found[n] = (bary >= -tol).all(axis=1).any()
    return found


def _distance_exact(points, tri) -> np.ndarray:
    """Shortest distance from each point to a set of triangles (n, 3, 3), all pairs."""
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    n = np.cross(b - a, c - a)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    p = points[:, None, :]
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
    return d.min(axis=1)


def distance_to_triangles(points, tri) -> np.ndarray:
    """Shortest distance from each point to a set of triangles (n, 3, 3).

    The nearest triangle corner bounds the answer from above, so only triangles whose bounding
    box is that close need the exact test.
    """
    points = np.asarray(points, dtype=float)
    corners = tri.reshape(-1, 3)
    lo, hi = tri.min(axis=1), tri.max(axis=1)
    best = np.empty(len(points))
    for start in range(0, len(points), 128):
        chunk = points[start : start + 128]
        bound = np.sqrt(((chunk[:, None, :] - corners[None]) ** 2).sum(axis=2).min(axis=1))
        for k, (p, ub) in enumerate(zip(chunk, bound)):
            gap = np.maximum(np.maximum(lo - p, p - hi), 0.0)
            near = (gap * gap).sum(axis=1) <= ub * ub + 1e-12
            best[start + k] = _distance_exact(p[None], tri[near])[0]
    return best


def outside_distances(mesh: TetMesh, points) -> np.ndarray:
    """How far each point is outside the tet mesh: 0 inside, else distance to its boundary."""
    points = np.asarray(points, dtype=float)
    inside = inside_any_tet(mesh.nodes, mesh.tets, points)
    out = np.zeros(len(points))
    if (~inside).any():
        out[~inside] = distance_to_triangles(points[~inside], mesh.nodes[boundary_faces(mesh.tets)])
    return out


# --- the checks a mesh must pass before it is saved -------------------------------------------


@dataclass
class Report:
    quality: Quality
    topology: Topology
    surface_genus: int
    expected_genus: int  # surface genus plus pockets: what the solid the surface encloses has
    surface_separation: Separation
    separation: Separation
    separation_applicable: bool  # False when the surface has no slice with the lips apart
    separation_ratio: float | None  # tet width / surface width; None when not applicable
    asymmetry_mm: float  # |left loss - right loss| against the surface's own separated run
    outside_fraction: float  # display vertices outside every tet
    outside_p95_mm: float  # 95th percentile of how far outside, over all display vertices
    outside_max_mm: float
    failures: list[str]
    notes: list[str]  # checks that could not be made; they do not fail the mesh but must be read


# Upper and lower lip must stay apart over at least this share of the width where the surface
# itself has them apart (T-04).
MIN_SEPARATION_RATIO = 0.95
# Hard floors on tet quality (the committed lip mesh has 10.4 degrees and 0.0043 mm3). Below them
# FEBio's element Jacobians get so small that a few mm of motion turns a tet inside out.
MIN_DIHEDRAL_DEG = 5.0
MIN_TET_VOLUME_MM3 = 0.001


def check(mesh: TetMesh, vertices_mm, triangles, step_mm: float = 0.25) -> Report:
    """Measure a tet mesh against the surface it came from; failures lists what is wrong."""
    vertices = np.asarray(vertices_mm, dtype=float)
    triangles = np.asarray(triangles)
    q = quality(mesh)
    topo = topology(mesh)
    _, _, _, surface_genus = surface_topology(triangles)
    xs = slice_positions(vertices, step_mm)
    want = separation(vertices, triangles, xs)
    got = separation(mesh.nodes, mesh.tets, xs)
    # Where a self-intersecting surface crosses the slit shut and it opens again further out, the
    # opening is a pocket through the lip, front to back: a handle the solid has although the
    # surface, counted as a surface, does not. The lips have one past each mouth corner's
    # crossing (docs/05 pit 9, docs/13 E-03). A faithful tet mesh keeps them.
    expected_genus = surface_genus + want.pockets
    # A surface with no slice that has the lips apart (e.g. a mouth closed all along) gives
    # nothing to compare the tets with. Say so; do not let it pass as a perfect match.
    applicable = want.width_mm > 0
    ratio = got.width_mm / want.width_mm if applicable else None
    asymmetry = abs((got.start_mm - want.start_mm) - (want.end_mm - got.end_mm)) if applicable else 0.0
    out = outside_distances(mesh, vertices)

    failures = []
    notes = []
    if (signed_volumes(mesh.nodes, mesh.tets) <= 0).any():
        failures.append("some tets are inverted or flat")
    if q.min_dihedral_deg <= MIN_DIHEDRAL_DEG:
        failures.append(f"a tet has a dihedral angle of {q.min_dihedral_deg:.2f} degrees (need more than {MIN_DIHEDRAL_DEG:g})")
    if q.min_tet_volume_mm3 <= MIN_TET_VOLUME_MM3:
        failures.append(f"a tet has a volume of {q.min_tet_volume_mm3:.5f} mm3 (need more than {MIN_TET_VOLUME_MM3:g})")
    if topo.components != 1:
        failures.append(f"the solid is in {topo.components} pieces, expected 1")
    if topo.nonmanifold_edges or topo.nonmanifold_vertices:
        failures.append(
            f"boundary is not a manifold: {topo.nonmanifold_edges} edges, {topo.nonmanifold_vertices} vertices"
        )
    if topo.boundary_genus != expected_genus:
        failures.append(
            f"boundary genus {topo.boundary_genus}, expected {expected_genus} (the surface's {surface_genus} "
            f"plus {expected_genus - surface_genus} pockets where the slit opens again)"
        )
    if not applicable:
        notes.append(
            "separation check not applicable: the surface has no slice where upper and lower lip "
            "are apart, so the mesh could not be compared with it"
        )
    elif ratio < MIN_SEPARATION_RATIO:
        failures.append(
            f"upper and lower lip apart over {got.width_mm:.2f} mm, {ratio:.0%} of the surface's "
            f"{want.width_mm:.2f} mm (need {MIN_SEPARATION_RATIO:.0%})"
        )
    if applicable and asymmetry > q.median_edge_mm:
        failures.append(f"separation lost {asymmetry:.2f} mm more on one side than the other")
    return Report(
        q, topo, surface_genus, expected_genus, want, got, applicable, ratio, asymmetry,
        float((out > 0).mean()), float(np.percentile(out, 95)), float(out.max()), failures, notes,
    )  # fmt: skip


# --- on disk ----------------------------------------------------------------------------------


def content_sha256(nodes, tets) -> str:
    """Hash of the mesh itself: nodes as little-endian float64, then tets as little-endian int64."""
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(nodes, dtype="<f8").tobytes())
    h.update(np.ascontiguousarray(tets, dtype="<i8").tobytes())
    return h.hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path: Path, mesh: TetMesh, meta: dict) -> str:
    """Write the mesh as JSON, one node or tet per line, with meta and the content hash.

    meta carries what the reader needs to trust and reproduce it: units, axes, the source
    surface's hash, parameters, tool versions, quality. Returns the content hash.
    """
    digest = content_sha256(mesh.nodes, mesh.tets)
    header = {"format": FORMAT, "format_version": FORMAT_VERSION, **meta, "content_sha256": digest}
    # Python's float repr round-trips exactly, so the hash survives the trip through text.
    lines = ["{"] + [f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in header.items()]
    lines.append('  "nodes": [')
    lines += [f"    [{x!r}, {y!r}, {z!r}]," for x, y, z in mesh.nodes.tolist()]
    lines[-1] = lines[-1].rstrip(",")
    lines.append("  ],")
    lines.append('  "tets": [')
    lines += [f"    [{a}, {b}, {c}, {d}]," for a, b, c, d in mesh.tets.tolist()]
    lines[-1] = lines[-1].rstrip(",")
    lines.append("  ]")
    lines.append("}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return digest


# What the readers of a saved mesh rely on; `load` insists on it so a hand-made or truncated file
# fails with a sentence instead of a KeyError later.
REQUIRED_FIELDS = ("units", "up_axis", "mm_per_scene_unit", "source", "content_sha256", "nodes", "tets")


def load(path: Path, surface: Path | None = None) -> tuple[TetMesh, dict]:
    """Read a saved mesh and check it is the one that was written. Returns (mesh, meta).

    With `surface` (the OBJ the mesh was made from) it also runs `check_source`, so one call tells
    the caller that both the mesh and its source are as they were.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != FORMAT or data.get("format_version") != FORMAT_VERSION:
        raise ValueError(
            f"{path} is not an {FORMAT} v{FORMAT_VERSION} file (format {data.get('format')!r}, "
            f"version {data.get('format_version')!r}); regenerate it with tools/build_tetmesh.py"
        )
    missing = [k for k in REQUIRED_FIELDS if k not in data]
    if "source" in data and not (isinstance(data["source"], dict) and "sha256" in data["source"]):
        missing.append("source.sha256")
    if missing:
        raise ValueError(
            f"{path} is missing {', '.join(missing)}, so it cannot be trusted; regenerate it with "
            "tools/build_tetmesh.py"
        )
    nodes = np.array(data.pop("nodes"), dtype=np.float64).reshape(-1, 3)
    tets = np.array(data.pop("tets"), dtype=np.int64).reshape(-1, 4)
    digest = content_sha256(nodes, tets)
    if digest != data["content_sha256"]:
        raise ValueError(
            f"{path} has been changed since it was written (content hash {digest[:12]}, recorded "
            f"{data['content_sha256'][:12]}). Restore it from git or regenerate it with "
            "tools/build_tetmesh.py"
        )
    if surface is not None:
        check_source(data, surface)
    return TetMesh(nodes, tets), data


def check_source(meta: dict, surface: Path) -> None:
    """Fail if the surface the mesh was made from has changed since."""
    digest = file_sha256(surface)
    if digest != meta["source"]["sha256"]:
        raise ValueError(
            f"{surface} is not the surface this tet mesh was made from (sha256 {digest[:12]}, "
            f"recorded {meta['source']['sha256'][:12]}); regenerate it with tools/build_tetmesh.py"
        )

