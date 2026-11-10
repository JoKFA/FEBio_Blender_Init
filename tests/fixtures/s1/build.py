"""Write spike S1's model as the example scene.json and trajectory.json in this folder (T-05).

    uv run python tests/fixtures/s1/build.py [out_dir]

The model is the one spikes/s1_dynamic_jaw.py builds (imported, not copied): a soft-tissue column
on a rigid jaw block, its top face held by a fixed "skull", the jaw turning about the x axis
through PIVOT, gravity from t = 0. tests/test_scene.py rebuilds it in a temp folder and expects
the committed files byte for byte, so these files always say what S1 is.

How S1 maps onto the scene format: the tissue's tets are the tet mesh, its boundary the surface
mesh; the jaw block's boundary is the jaw's mesh; S1's skull is only a set of fixed nodes, so its
mesh is the tissue's top face. S1 shares nodes between tissue and jaw, and fixes the top nodes;
both are hard attachments on those surface vertices. S1 is built in mm, Z up, so there is no unit
or axis conversion (mm_per_scene_unit 1.0).
"""

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "spikes"))

import s1_dynamic_jaw as s1  # noqa: E402

from asrp_core import scene, tetmesh, trajectory  # noqa: E402

DRIVER = "jaw_hinge"


def write_obj(path: Path, header: str, vertices, faces) -> None:
    lines = [f"# {header}"]
    lines += [f"v {x!r} {y!r} {z!r}" for x, y, z in vertices]
    lines += ["f " + " ".join(str(i + 1) for i in face) for face in faces]
    path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def surface(nodes: dict, tets: list) -> tuple[list[int], np.ndarray]:
    """The node ids on the boundary of tets (sorted) and the outward boundary triangles, indexed
    into that list."""
    boundary = tetmesh.boundary_faces(np.array(tets))
    ids = sorted({int(n) for n in boundary.ravel()})
    index = {n: i for i, n in enumerate(ids)}
    return ids, np.vectorize(index.get)(boundary)


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    nodes, tissue_tets, jaw_tets = s1.build_mesh()

    tissue_ids, tissue_faces = surface(nodes, tissue_tets)
    write_obj(out / "tissue.obj", "S1 soft-tissue column, surface, mm, Z up",
              [nodes[n] for n in tissue_ids], tissue_faces.tolist())
    tissue_sha = tetmesh.file_sha256(out / "tissue.obj")

    tet_ids = sorted({n for t in tissue_tets for n in t})
    tet_index = {n: i for i, n in enumerate(tet_ids)}
    tet = tetmesh.TetMesh(np.array([nodes[n] for n in tet_ids], dtype=float),
                          np.array([[tet_index[n] for n in t] for t in tissue_tets], dtype=np.int64))
    content = tetmesh.save(out / "tissue_tet.json", tet, {
        "units": "mm", "up_axis": "Z", "axes_from_maya": "none: S1 is built in mm, Z up",
        "mm_per_scene_unit": 1.0, "source": {"path": "tissue.obj", "sha256": tissue_sha},
        "params": {"tool": "Kuhn split of a hex grid, spikes/s1_dynamic_jaw.py"},
    })

    jaw_ids, jaw_faces = surface(nodes, jaw_tets)
    write_obj(out / "jaw.obj", "S1 rigid jaw block, surface, mm, Z up", [nodes[n] for n in jaw_ids], jaw_faces.tolist())
    # S1's skull is the set of fixed top nodes; its mesh is that face, wound to face down into the tissue.
    top = sorted(s1.node_id(i, j, len(s1.ZS) - 1) for j in range(len(s1.YS)) for i in range(len(s1.XS)))
    grid = {n: k for k, n in enumerate(top)}
    nx = len(s1.XS)
    quads = [(grid[top[j * nx + i]], grid[top[j * nx + i + 1]], grid[top[(j + 1) * nx + i + 1]], grid[top[(j + 1) * nx + i]])
             for j in range(len(s1.YS) - 1) for i in range(nx - 1)]
    write_obj(out / "skull.obj", "S1 skull: the fixed top face of the tissue, mm, Z up",
              [nodes[n] for n in top], [(a, d, c, b) for a, b, c, d in quads])

    def ref(name):
        return scene.FileRef(name, tetmesh.file_sha256(out / name))

    def own_source(name):
        return scene.SourceObj(name, tetmesh.file_sha256(out / name))

    def ours(value, note=""):
        return scene.Param(value, "ours", note)

    tissue_index = {n: i for i, n in enumerate(tissue_ids)}
    on_jaw = [[tissue_index[n], 1.0] for n in tissue_ids if nodes[n][2] == 0.0]
    on_skull = [[tissue_index[n], 1.0] for n in tissue_ids if nodes[n][2] == s1.ZS[-1]]
    jaw_volume = (s1.XS[-1] - s1.XS[0]) * (s1.YS[-1] - s1.YS[0]) * (0.0 - s1.ZS[0])

    model = scene.Scene(
        origin={"asset": "spike S1 (spikes/s1_dynamic_jaw.py)", "export": "none: built in code",
                "tool": "tests/fixtures/s1/build.py",
                "notes": "S1's skull is a set of fixed nodes; here it is a fixed bone whose mesh is the top face"},
        units=scene.Units(ours(1.0, "S1 is built in mm"), ours(1.0), "none: S1 is built in mm, Z up"),
        soft_tissues=[scene.SoftTissue(
            "tissue", ref("tissue.obj"), own_source("tissue.obj"),
            scene.TetRef("tissue_tet.json", content),
            scene.Material("neo-Hookean", {
                "E_mpa": ours(s1.TISSUE["E"], "20 kPa, placeholder as in S1"),
                "nu": ours(s1.TISSUE["v"]),
                "density_t_per_mm3": ours(s1.TISSUE["density"], "1060 kg/m3"),
            }),
        )],
        bones=[
            scene.Bone("skull", ref("skull.obj"), own_source("skull.obj"),
                       ours(None, "S1 has fixed nodes, no skull body"), "fixed"),
            scene.Bone("jaw", ref("jaw.obj"), own_source("jaw.obj"),
                       ours(s1.JAW_DENSITY * jaw_volume, "S1's jaw density 1.9e-9 t/mm3 times the block's volume"),
                       "prescribed", DRIVER),
        ],
        drivers=[scene.Driver(DRIVER, scene.Hinge(list(s1.PIVOT), [1.0, 0.0, 0.0], "ours",
                                                  "S1's hinge: x axis through PIVOT"))],
        attachments=[
            scene.Attachment("tissue_on_jaw", "tissue", "jaw", "hard", ours(None, "S1 shares these nodes"), on_jaw),
            scene.Attachment("tissue_on_skull", "tissue", "skull", "hard", ours(None, "S1 fixes these nodes"), on_skull),
        ],
        landmarks=None,
        solver=scene.Solver(
            "dynamic", ours(s1.FPS), ours(1, "S1: one FEBio time step per frame"),
            ours(0.0, "FEBio's default: no damping (docs/05 pit 2)"),
            ours([0.0, 0.0, s1.GRAVITY], "physical direction; the FEBio writer flips the sign (ADR-10)"),
        ),
    )
    scene.write(out / "scene.json", model)

    angles = [s1.jaw_angle(n / s1.FPS) for n in range(s1.FRAMES + 1)]
    motion = trajectory.Trajectory(
        fps=s1.FPS, frames=len(angles),
        drivers={DRIVER: trajectory.hinge_transforms(s1.PIVOT, (1.0, 0.0, 0.0), angles)},
        source="spikes/s1_dynamic_jaw.py jaw_angle (settle, open, hold), via asrp_core.trajectory.hinge_transforms",
    )
    trajectory.write(out / "trajectory.json", motion)


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE)
