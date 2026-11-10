"""Spike S2 (T-04): which fTetWild settings give a lip tet mesh we can build on?

Compares envelopes tied to the edge length (the first version of T-04: envelope = edge / 20)
against fixed tight envelopes, on the real lip mesh (mm, Z up, x 0.962, docs/11 Q3). For each
candidate and each repeat it prints nodes, tets, time, smallest dihedral angle, median edge,
volume against the surface's, solid pieces, boundary genus against the expected (the surface's 1
plus the pockets past the mouth-corner crossings, docs/13 E-03), non-manifold boundary
edges/vertices, how wide along x the upper and lower lips stay apart against the
surface's own width, the left/right difference of that, and how many display vertices fall
outside every tet and how far. Repeats differ because fTetWild is not reproducible (docs/05
pit 12); that is why the chosen mesh is saved (tools/build_tetmesh.py).

    uv run python spikes/s2_tetmesh.py [repeats]
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build_tetmesh import LIPS, read_lips_mm  # noqa: E402

from asrp_core import tetmesh  # noqa: E402

# (label, edge mm, envelope mm). tetSz 26.37 scene units x 0.962 = 25.4 mm.
CANDIDATES = [
    ("edge/20", 12.7, 0.635),
    ("edge/20", 25.4, 1.27),
    ("edge/20", 50.7, 2.535),
    ("fixed", 25.4, 1.0),
    ("fixed", 25.4, 0.5),
    ("fixed", 25.4, 0.25),
    ("fixed", 25.4, 0.12),
    ("fixed", 12.7, 0.12),
]


def main():
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    if not LIPS.is_file():
        sys.exit(f"{LIPS} is missing; it comes from tools/maya_export.py (docs/12)")
    vertices, triangles = read_lips_mm()
    enclosed = abs(tetmesh.surface_volume(vertices, triangles))
    print(f"lips: {len(vertices)} vertices, {len(triangles)} triangles, encloses {enclosed:,.0f} mm3")
    print("| envelope | edge mm | env mm | nodes | tets | s | min angle | median edge | vol % | pieces | genus "
          "| expected | non-manifold e/v | apart mm | apart % | L/R diff mm | outside % | p95 out mm | max out mm | checks |")
    print("|" + "---|" * 20)
    for label, edge, envelope in CANDIDATES:
        for _ in range(repeats):
            started = time.perf_counter()
            mesh = tetmesh.tetrahedralize(vertices, triangles, edge, envelope)
            seconds = time.perf_counter() - started
            r = tetmesh.check(mesh, vertices, triangles)
            q, t = r.quality, r.topology
            print(f"| {label} | {edge} | {envelope} | {q.nodes} | {q.tets} | {seconds:.1f} | {q.min_dihedral_deg:.1f} "
                  f"| {q.median_edge_mm:.2f} | {100 * (q.volume_mm3 / enclosed - 1):+.1f} | {t.components} "
                  f"| {t.boundary_genus} | {r.expected_genus} | {t.nonmanifold_edges}/{t.nonmanifold_vertices} "
                  f"| {r.separation.width_mm:.2f} of {r.surface_separation.width_mm:.2f} | {100 * r.separation_ratio:.1f} "
                  f"| {r.asymmetry_mm:.2f} | {100 * r.outside_fraction:.0f} | {r.outside_p95_mm:.2f} | {r.outside_max_mm:.2f} "
                  f"| {'pass' if not r.failures else 'FAIL'} |", flush=True)


if __name__ == "__main__":
    main()
