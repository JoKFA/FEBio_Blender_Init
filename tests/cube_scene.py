"""Small box scenes with textbook answers for the generator's tests (T-06a, docs/07 section 2).

`write` puts a complete asrp-scene/1 folder on disk: a box of soft tissue cut into tets (each hex of a
grid split into six, positively oriented), its boundary as the display mesh (optionally with some
vertices pushed outward, so that they lie outside every tet), a fixed bone "skull", a bone "plate" that
follows driver "plate_drive", and the attachments asked for. `motion` writes the trajectory.
"""

import itertools
import json
from pathlib import Path

import numpy as np

from asrp_core import scene, tetmesh, trajectory

DRIVER = "plate_drive"


def box(size, cells):
    """Nodes (n, 3) and positive tets of a box [0, size] split into cells[0] x cells[1] x cells[2] hexes."""
    nx, ny, nz = cells
    ids = {}
    nodes = []
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                ids[i, j, k] = len(nodes)
                nodes.append([size[0] * i / nx, size[1] * j / ny, size[2] * k / nz])
    nodes = np.array(nodes, dtype=float)
    tets = []
    for i, j, k in itertools.product(range(nx), range(ny), range(nz)):
        for axes in itertools.permutations(range(3)):
            corner, tet = [0, 0, 0], [ids[i, j, k]]
            for axis in axes:
                corner[axis] = 1
                tet.append(ids[i + corner[0], j + corner[1], k + corner[2]])
            if tetmesh.signed_volumes(nodes, np.array([tet]))[0] < 0:
                tet[1], tet[2] = tet[2], tet[1]
            tets.append(tet)
    return nodes, np.array(tets, dtype=np.int64)


def _obj(path: Path, vertices, faces) -> None:
    lines = [f"v {float(x)!r} {float(y)!r} {float(z)!r}" for x, y, z in vertices]
    lines += ["f " + " ".join(str(int(i) + 1) for i in f) for f in faces]
    path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def write(folder: Path, *, size=(10.0, 10.0, 10.0), cells=(4, 4, 4), E=0.015, nu=0.45, density=1.06e-9,
          gravity=(0.0, 0.0, -9810.0), k=1.0, write_k=True, hinge=((5.0, -10.0, 10.0), (1.0, 0.0, 0.0)),
          attachments=(), push=None, fps=30, unused_node=False) -> dict:
    """attachments: [(name, target "skull" | "plate", kind, stiffness or None, select(vertices) -> indices)].
    push: {display vertex index: outward offset vector}. unused_node: add a tet-mesh node no tet uses.
    Returns the display vertices, the tet mesh and the scene path."""
    folder.mkdir(parents=True, exist_ok=True)
    nodes, tets = box(size, cells)
    faces = tetmesh.boundary_faces(tets)
    used = sorted({int(n) for n in faces.ravel()})
    index = {n: i for i, n in enumerate(used)}
    display = nodes[used].copy()
    for v, offset in (push or {}).items():
        display[v] += offset
    _obj(folder / "tissue.obj", display, [[index[int(n)] for n in f] for f in faces])
    sha = tetmesh.file_sha256(folder / "tissue.obj")
    saved = np.vstack([nodes, [[50.0, 50.0, 50.0]]]) if unused_node else nodes
    content = tetmesh.save(folder / "tissue_tet.json", tetmesh.TetMesh(saved, tets), {
        "units": "mm", "up_axis": "Z", "axes_from_maya": "none: a test box", "mm_per_scene_unit": 1.0,
        "source": {"path": "tissue.obj", "sha256": sha}, "params": {"tool": "tests/cube_scene.py"}})
    for bone in ("skull", "plate"):
        _obj(folder / f"{bone}.obj", [[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]])

    def ours(v, note="test"):
        return scene.Param(v, "ours", note)

    def ref(name):
        return scene.FileRef(name, tetmesh.file_sha256(folder / name))

    atts = []
    for name, target, kind, stiffness, select in attachments:
        atts.append(scene.Attachment(name, "tissue", target, kind, ours(stiffness),
                                     [[int(v), 1.0] for v in select(display)]))
    model = scene.Scene(
        origin={"asset": "test box", "export": "none", "tool": "tests/cube_scene.py", "notes": ""},
        units=scene.Units(ours(1.0), ours(k), "none", physics_length_scale_defaulted=not write_k),
        soft_tissues=[scene.SoftTissue("tissue", ref("tissue.obj"), scene.SourceObj("tissue.obj", sha),
                                       scene.TetRef("tissue_tet.json", content),
                                       scene.Material("neo-Hookean", {"E_mpa": ours(E), "nu": ours(nu),
                                                                      "density_t_per_mm3": ours(density)}))],
        bones=[scene.Bone("skull", ref("skull.obj"), scene.SourceObj("skull.obj", "0"), ours(None), "fixed"),
               scene.Bone("plate", ref("plate.obj"), scene.SourceObj("plate.obj", "0"), ours(None), "prescribed", DRIVER)],
        drivers=[scene.Driver(DRIVER, None if hinge is None else scene.Hinge(list(hinge[0]), list(hinge[1]), "ours"))],
        attachments=atts,
        landmarks=None,
        solver=scene.Solver("dynamic", ours(fps), ours(1), ours(0.0), ours(list(gravity))),
    )
    scene.write(folder / "scene.json", model)
    return {"display": display, "nodes": nodes, "tets": tets, "scene": folder / "scene.json"}


def motion(folder: Path, transforms, fps=30, name="motion.json", settle=None) -> Path:
    """settle: the trajectory's settle_until_frame (None: not stated, so check (c) is not run)."""
    path = folder / name
    trajectory.write(path, trajectory.Trajectory(fps, len(transforms), {DRIVER: [list(map(float, m)) for m in transforms]},
                                                 "tests/cube_scene.py", settle_until_frame=settle))
    return path


def still(frames: int) -> list:
    return [np.eye(4).ravel().tolist()] * frames


def turn(frames: int, ramp: int, angle: float, pivot, axis) -> list:
    angles = [angle * min(1.0, f / ramp) for f in range(frames)]
    return trajectory.hinge_transforms(pivot, axis, angles)


def shift(frames: int, ramp: int, offset) -> list:
    out = []
    for f in range(frames):
        m = np.eye(4)
        m[:3, 3] = np.asarray(offset, dtype=float) * min(1.0, f / ramp)
        out.append(m.ravel().tolist())
    return out


def report(run_dir: Path) -> dict:
    return json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))
