"""Generate the lips' tet mesh once and write it to data/tetmesh/lips.json (T-04, ADR-20).

fTetWild gives a different mesh on every run (docs/05 pit 12), so this is the only place it runs
for the product: the file is committed, and everything downstream reads it with
asrp_core.tetmesh.load, which checks its hash. Rerun this only on purpose (new lip export, new
unit, new parameters) and commit the result. It refuses to write a mesh that fails the checks in
asrp_core.tetmesh.check; it retries a few times, since fTetWild's result varies run to run.

    uv run python tools/build_tetmesh.py [--out data/tetmesh/lips.json] [--mm-per-scene-unit 0.962]

Without --out this overwrites the committed data/tetmesh/lips.json; pass --out to try things.
"""

import argparse
import platform
import sys
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import numpy as np

from asrp_core import tetmesh

REPO = Path(__file__).resolve().parents[1]
LIPS = REPO / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj"
OUT = REPO / "data" / "tetmesh" / "lips.json"
MM_PER_SCENE_UNIT = 0.962  # provisional default, docs/11 Q3 / A-09; --mm-per-scene-unit overrides
# Chosen in T-04 (ADR-20, evidence from spikes/s2_tetmesh.py): a tight envelope, about
# fTetWild's own default (1e-3 of the 122.7 mm diagonal), keeps the mouth slit open up to where
# the surface crosses itself, the same on both sides, in every run tried. Envelopes of 0.5 mm and
# up leave the lips touching along an edge or at a vertex where the slit narrows to about the
# envelope, nearly every run. The edge length hardly matters once the envelope is this tight
# (25.4 and 12.7 give the same mesh size); 25.4 is tetSz in mm.
EDGE_MM = 25.4
ENVELOPE_MM = 0.12
# In the small sample behind ADR-20 (6 runs at 0.12 mm) 1 left a non-manifold edge and 5 passed
# every check; the next attempt usually passes. 6 attempts is a guess, not a measured rate.
ATTEMPTS = 6


def read_lips_mm(path: Path = LIPS, mm_per_scene_unit: float = MM_PER_SCENE_UNIT):
    """The lip OBJ in mm, Z up, triangles: Maya (x, y, z) -> (x, -z, y), the conversion T-02 will
    own (docs/03 section 10). The OBJ is already in scene coordinates (ADR-18)."""
    vertices, triangles = [], []
    with path.open(encoding="ascii") as f:
        for line in f:
            if line.startswith("v "):
                x, y, z = (float(c) * mm_per_scene_unit for c in line.split()[1:4])
                vertices.append((x, -z, y))
            elif line.startswith("f "):
                face = [int(c.split("/")[0]) - 1 for c in line.split()[1:]]
                triangles += [(face[0], face[i], face[i + 1]) for i in range(1, len(face) - 1)]
    return np.array(vertices), np.array(triangles)


def build(
    out: Path,
    edge_mm: float = EDGE_MM,
    envelope_mm: float = ENVELOPE_MM,
    mm_per_scene_unit: float = MM_PER_SCENE_UNIT,
) -> tetmesh.Report:
    if not LIPS.is_file():
        sys.exit(f"{LIPS} is missing; it comes from tools/maya_export.py (docs/12)")
    vertices, triangles = read_lips_mm(mm_per_scene_unit=mm_per_scene_unit)
    for attempt in range(1, ATTEMPTS + 1):
        started = time.perf_counter()
        mesh = tetmesh.tetrahedralize(vertices, triangles, edge_mm, envelope_mm)
        seconds = time.perf_counter() - started
        report = tetmesh.check(mesh, vertices, triangles)
        print(f"attempt {attempt}: {report.quality.nodes} nodes, {report.quality.tets} tets, {seconds:.1f} s; "
              f"apart {report.separation.width_mm:.2f} of {report.surface_separation.width_mm:.2f} mm, "
              f"genus {report.topology.boundary_genus}, "
              f"{'ok' if not report.failures else '; '.join(report.failures)}", flush=True)
        for note in report.notes:
            print(f"  note: {note}", flush=True)
        if not report.failures:
            break
    else:
        sys.exit(f"no attempt out of {ATTEMPTS} passed the checks; nothing written")

    meta = {
        "units": "mm",
        "up_axis": "Z",
        "axes_from_maya": "(x, y, z) -> (x, -z, y)",
        "mm_per_scene_unit": mm_per_scene_unit,
        "source": {"path": LIPS.relative_to(REPO).as_posix(), "sha256": tetmesh.file_sha256(LIPS)},
        "params": {"tool": "fTetWild via pytetwild", "edge_mm": edge_mm, "envelope_mm": envelope_mm,
                   "num_threads": 0, "other": "pytetwild defaults"},
        "tools": {"pytetwild": version("pytetwild"), "numpy": np.__version__,
                  "python": platform.python_version(), "platform": platform.platform()},
        "generated_seconds": round(seconds, 1),
        "attempt": attempt,
        "checks": {k: v for k, v in asdict(report).items() if k != "failures"},
    }
    digest = tetmesh.save(out, mesh, meta)
    print(f"wrote {out} (content sha256 {digest[:12]})")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--edge-mm", type=float, default=EDGE_MM)
    parser.add_argument("--envelope-mm", type=float, default=ENVELOPE_MM)
    parser.add_argument("--mm-per-scene-unit", type=float, default=MM_PER_SCENE_UNIT)
    args = parser.parse_args()
    build(args.out, args.edge_mm, args.envelope_mm, args.mm_per_scene_unit)


if __name__ == "__main__":
    main()
