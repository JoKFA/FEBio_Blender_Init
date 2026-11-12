"""One-off measurement (not product code): do the lip attachment groups share tet nodes?

Each attached lip vertex (data/lab_export/lip_attachments.json) is embedded in the tet mesh
(data/tetmesh/lips.json): the tet that contains it, else the tet it is nearest to (distance estimated as the
largest signed distance to a face plane, a lower bound of the true distance). The nodes of those tets are the
nodes a boundary condition for that group would touch. Prints nodes per group, nodes shared between the hard
(upper lip -> skull) group and each spring group, nodes shared between spring groups, and the largest
vertex-to-tet distance against the median tet edge.

    uv run python spikes/attachment_overlap.py
"""

import itertools
import json
from pathlib import Path

import numpy as np

from asrp_core import tetmesh
from asrp_core.asset import coords

REPO = Path(__file__).resolve().parents[1]
MM_PER_SCENE_UNIT = 0.962
HARD = "zAttachment1"
SPRINGS = ["zAttachment2", "zAttachment9", "zAttachment10"]


def embed(points, nodes, tets):
    """For each point: (tet index, distance to it in mm; 0 when inside)."""
    a, b, c, d = (nodes[tets[:, i]] for i in range(4))
    # Face i is opposite vertex i; inward normals and altitudes give signed distance to each face plane.
    verts = [a, b, c, d]
    normals, offsets = [], []
    for i in range(4):
        p, q, r = (verts[j] for j in range(4) if j != i)
        n = np.cross(q - p, r - p)
        n /= np.linalg.norm(n, axis=1, keepdims=True)
        sign = np.sign(((verts[i] - p) * n).sum(1))  # make n point toward the opposite vertex
        n *= sign[:, None]
        normals.append(n)
        offsets.append((n * p).sum(1))
    normals, offsets = np.stack(normals, 1), np.stack(offsets, 1)  # (m, 4, 3), (m, 4)
    tet_ids, dists = [], []
    for x in points:
        signed = (normals * x).sum(2) - offsets  # (m, 4): positive = inside side of that face
        out = np.maximum(-signed.min(axis=1), 0.0)  # distance outside the worst face plane; 0 inside
        k = int(out.argmin())
        tet_ids.append(k)
        dists.append(float(out[k]))
    return np.array(tet_ids), np.array(dists)


def main():
    mesh, _ = tetmesh.load(REPO / "data" / "tetmesh" / "lips.json")
    export = json.loads((REPO / "data" / "lab_export" / "lip_attachments.json").read_text(encoding="utf-8"))
    verts, _ = coords.read_obj(REPO / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj")
    verts_mm = coords.to_mm_zup(verts, MM_PER_SCENE_UNIT)
    edges = np.concatenate([np.linalg.norm(mesh.nodes[mesh.tets[:, i]] - mesh.nodes[mesh.tets[:, j]], axis=1)
                            for i, j in itertools.combinations(range(4), 2)])
    median_edge = float(np.median(edges))

    node_sets, worst = {}, {}
    for g in export["groups"]:
        idx = [v for v, _ in g["vertices"]]
        tet_ids, dist = embed(verts_mm[idx], mesh.nodes, mesh.tets)
        node_sets[g["attachment"]] = set(mesh.tets[tet_ids].ravel().tolist())
        worst[g["attachment"]] = (float(dist.max()), int((dist > 0).sum()), len(idx))

    print(f"tet mesh: {len(mesh.nodes)} nodes, {len(mesh.tets)} tets, median edge {median_edge:.2f} mm")
    for name, s in node_sets.items():
        w = worst[name]
        print(f"{name}: {len(s)} nodes; vertices outside every tet {w[1]}/{w[2]}, max distance {w[0]:.3f} mm")
    for name in SPRINGS:
        print(f"shared {HARD} & {name}: {len(node_sets[HARD] & node_sets[name])} nodes")
    for a, b in itertools.combinations(SPRINGS, 2):
        print(f"shared {a} & {b}: {len(node_sets[a] & node_sets[b])} nodes")
    overall = max(w[0] for w in worst.values())
    print(f"max vertex-to-tet distance {overall:.3f} mm = {overall / median_edge:.3f} x median tet edge")


if __name__ == "__main__":
    main()
