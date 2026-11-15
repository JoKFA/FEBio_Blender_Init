"""Generate the lips' tet mesh once and write it to data/tetmesh/lips.json (T-04, ADR-20).

fTetWild gives a different mesh on every run (docs/05 pit 12), so this is the only place it runs
for the product: the file is committed, and everything downstream reads it with
asrp_core.tetmesh.load, which checks its hash. Rerun this only on purpose (new lip export, new
unit, new parameters) and commit the result. It refuses to write a mesh that fails the checks in
asrp_core.tetmesh.check; it retries a few times, since fTetWild's result varies run to run.

    uv run python tools/build_tetmesh.py [--out data/tetmesh/lips.json] [--mm-per-scene-unit 0.962]

Without --out this overwrites the committed data/tetmesh/lips.json; pass --out to try things.

    uv run python tools/build_tetmesh.py --method lattice [--cell-mm 25.37] [--out data/tetmesh/lips_lattice.json]

The lattice method (ADR-44) makes the second, coarse mesh without fTetWild: cubes, 6 tets each,
deterministic. Its default output is data/tetmesh/lips_lattice.json; it builds twice and prints
both hashes, and check_lattice builds a third time before anything is written. It does not touch
lips.json.
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
from asrp_core.asset import coords

REPO = Path(__file__).resolve().parents[1]
LIPS = REPO / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj"
OUT = REPO / "data" / "tetmesh" / "lips.json"
LATTICE_OUT = REPO / "data" / "tetmesh" / "lips_lattice.json"
MM_PER_SCENE_UNIT = 0.962  # the lab controller's conversion (ADR-31); --mm-per-scene-unit overrides
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
# Ziva's own tet size for the lips (docs/03 section 5: tetSz, in scene units). The lattice's cell edge
# is derived from it, not tuned: cell_mm = 26.37 x mm_per_scene_unit (25.37 mm at 0.962).
ZIVA_TET_SIZE_SCENE_UNITS = 26.37


def read_lips_mm(path: Path = LIPS, mm_per_scene_unit: float = MM_PER_SCENE_UNIT):
    """The lip OBJ in mm, Z up, as triangles, through the project's one conversion
    (asrp_core.asset.coords, docs/03 section 10). The OBJ is already in scene coordinates (ADR-18)."""
    vertices, faces = coords.read_obj(path)
    return coords.to_mm_zup(vertices, mm_per_scene_unit), coords.triangulate(faces)


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
        "axes_from_maya": coords.AXES,
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


LATTICE_NOTE = (
    "Upper and lower lip are NOT separated in this mesh: one cube can hold both, so the slit is not a gap "
    "in the tets. That is on purpose (Ziva's mesh is as coarse and moves the lips as one body, ADR-44). "
    "Use lips.json when the lips must stay apart."
)


def build_lattice(
    out: Path,
    cell_mm: float | None = None,
    mm_per_scene_unit: float = MM_PER_SCENE_UNIT,
    shift_mm=(0.0, 0.0, 0.0),
) -> tetmesh.LatticeReport:
    if not LIPS.is_file():
        sys.exit(f"{LIPS} is missing; it comes from tools/maya_export.py (docs/12)")
    derived = cell_mm is None
    if derived:
        cell_mm = ZIVA_TET_SIZE_SCENE_UNITS * mm_per_scene_unit
    vertices, triangles = read_lips_mm(mm_per_scene_unit=mm_per_scene_unit)
    mesh = tetmesh.lattice_tetrahedralize(vertices, triangles, cell_mm, shift_mm)
    again = tetmesh.lattice_tetrahedralize(vertices, triangles, cell_mm, shift_mm)
    first, second = (tetmesh.content_sha256(m.nodes, m.tets) for m in (mesh, again))
    print(f"built twice: content sha256 {first} and {second}: {'identical' if first == second else 'DIFFERENT'}")
    report = tetmesh.check_lattice(mesh, vertices, triangles, cell_mm, shift_mm)
    q = report.quality
    print(f"lattice {cell_mm:.4f} mm: {q.nodes} nodes, {q.tets} tets, {report.cubes_kept} cubes "
          f"({report.cubes_touched} touched), min tet volume {q.min_tet_volume_mm3:.2f} mm3, min dihedral "
          f"{q.min_dihedral_deg:.2f} deg, display vertices outside {report.outside_count}, embedded rest error "
          f"{report.embedded_rest_max_mm:.2e} mm, {'ok' if not report.failures else '; '.join(report.failures)}")
    if report.failures:
        sys.exit("the lattice failed its checks; nothing written")
    source = (f"Ziva's tetSz {ZIVA_TET_SIZE_SCENE_UNITS} scene units x mm_per_scene_unit {mm_per_scene_unit} "
              "(docs/03 section 5); derived, not tuned" if derived else "given with --cell-mm")
    meta = {
        "kind": tetmesh.KIND_LATTICE,
        "upper_and_lower_lip_separated": False,
        "warning": LATTICE_NOTE,
        "units": "mm",
        "up_axis": "Z",
        "axes_from_maya": coords.AXES,
        "mm_per_scene_unit": mm_per_scene_unit,
        "source": {"path": LIPS.relative_to(REPO).as_posix(), "sha256": tetmesh.file_sha256(LIPS)},
        "params": {
            "tool": "asrp_core.tetmesh.lattice_tetrahedralize (no fTetWild)",
            "cell_mm": cell_mm,
            "cell_mm_source": source,
            "origin_rule": "minimum corner of the lip surface's bounding box, moved back by shift_mm",
            "shift_mm": [float(v) for v in shift_mm],
            "cube_rule": "a cube is kept when a surface sample (every vertex, plus a barycentric grid of at most "
                         "cell/4 spacing on each triangle) falls in it, or when no path of 6-neighbouring empty "
                         "cubes leads from it to the outside (the closed shell is filled); a cube is [i, i+1) cells",
            "split": "6 positive Kuhn tets per cube along the (0,0,0)-(1,1,1) diagonal, nodes welded",
            "deterministic": "same input, same bytes; checks.rebuild_identical",
        },
        "tools": {"numpy": np.__version__, "python": platform.python_version()},
        "checks": {k: v for k, v in asdict(report).items() if k != "failures"},
    }
    digest = tetmesh.save(out, mesh, meta)
    print(f"wrote {out} (content sha256 {digest[:12]})")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--method", choices=("fine", "lattice"), default="fine",
                        help="fine: fTetWild (default, as before); lattice: regular cubes (ADR-44)")
    parser.add_argument("--out", type=Path, default=None,
                        help="default: data/tetmesh/lips.json, or lips_lattice.json with --method lattice")
    parser.add_argument("--cell-mm", type=float, default=None,
                        help="lattice cell edge; default Ziva's tetSz 26.37 x mm_per_scene_unit")
    parser.add_argument("--edge-mm", type=float, default=EDGE_MM)
    parser.add_argument("--envelope-mm", type=float, default=ENVELOPE_MM)
    parser.add_argument("--mm-per-scene-unit", type=float, default=MM_PER_SCENE_UNIT)
    args = parser.parse_args()
    if args.method == "lattice":
        build_lattice(args.out or LATTICE_OUT, args.cell_mm, args.mm_per_scene_unit)
        return
    if args.cell_mm is not None:
        parser.error("--cell-mm is for --method lattice")
    build(args.out or OUT, args.edge_mm, args.envelope_mm, args.mm_per_scene_unit)


if __name__ == "__main__":
    main()
