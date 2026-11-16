"""Front pictures of the lips for docs/15: ours with the coarse lattice, ours with the fine mesh, Ziva's full face.

    uv run python tools/render_comparison.py --coarse-aa <run> --fine-aa <run> --ziva <Ziva export folder>
                                             [--coarse-jaw <run> --fine-jaw <run>] [--out data/preview]

Written for the page, and run again whenever its numbers change. It runs in two halves. This half (plain Python)
reads our runs with the product's reader and Ziva's export with the reader `asrp compare` uses (ziva_compare.read_ziva,
which sits on ziva_export.py), picks one frame of each, and writes the points into one temporary .npz. Then it starts
Blender with `--background` (never a window) on this same file, and that half renders the pictures with the
Workbench engine.

The camera is the same for every picture: orthographic, in front of the mouth, looking along -Y (the face looks down
+Y, docs/04 section 3), 0.10 m wide, centred on the middle of the lips at rest. The shading is the same too: one
colour, studio light, no outline, white background. Triangles are the rest triangles of the lab's lip mesh (Ziva
re-triangulates every frame, the vertex numbering does not change, so the pictures draw every source on the same
triangles). Written to <out>:

    prototype_aa36_physics_{coarse,fine,ziva}.png    the physics layer at frame 36 (the end of the AA motion)
    prototype_aa36_final_{coarse,fine,ziva}.png      the final shape (physics plus the landmark layer) at frame 36
    prototype_jaw32_{coarse,fine}.png                the jaw-opens-12-degrees motion at its widest frame, physics layer

The pictures hold the lab's lip mesh drawn as an image: the repository is private and already holds pictures of that
mesh (ADR-19). No vertex data of Ziva's runs is written anywhere in the repository: the .npz lives in a temporary
folder that is deleted afterwards.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AA_FRAME = 36
JAW_FRAME = 32
WIDTH_M = 0.10
SIZE = (600, 600)
LIP_COLOUR = (0.86, 0.36, 0.38, 1.0)


def main_python() -> None:
    sys.path.insert(0, str(REPO / "src"))
    import numpy as np

    from asrp_core import ziva_compare
    from asrp_core.doctor import BLENDER_CANDIDATES, locate

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--coarse-aa", required=True, help="run folder of the AA motion on the coarse lattice")
    parser.add_argument("--fine-aa", required=True, help="run folder of the AA motion on the fine mesh")
    parser.add_argument("--ziva", required=True, help="the Ziva export folder of the full-face AA run (outside the repo)")
    parser.add_argument("--coarse-jaw", help="run folder of the 12 degree jaw motion on the coarse lattice")
    parser.add_argument("--fine-jaw", help="run folder of the 12 degree jaw motion on the fine mesh")
    parser.add_argument("--out", default=str(REPO / "data" / "preview"))
    args = parser.parse_args()

    ours = {"coarse": ziva_compare.read_run(args.coarse_aa), "fine": ziva_compare.read_run(args.fine_aa)}
    frames = ours["coarse"].side.physics.shape[0]
    ziva = ziva_compare.read_ziva(args.ziva, ours["coarse"].mm_per_scene_unit, frames)
    shown: dict[str, np.ndarray] = {}
    for name, run in ours.items():
        if run.side.final is None:
            raise SystemExit(f"the {name} AA run has no final shape: it is not a run of the lab's AA motion")
        shown[f"prototype_aa36_physics_{name}"] = run.side.physics[AA_FRAME]
        shown[f"prototype_aa36_final_{name}"] = run.side.final[AA_FRAME]
    if ziva.side.final is None:
        raise SystemExit(ziva.side.final_missing)
    shown["prototype_aa36_physics_ziva"] = ziva.side.physics[AA_FRAME]
    shown["prototype_aa36_final_ziva"] = ziva.side.final[AA_FRAME]
    for name, folder in (("coarse", args.coarse_jaw), ("fine", args.fine_jaw)):
        if folder:
            shown[f"prototype_jaw32_{name}"] = ziva_compare.read_run(folder).side.physics[JAW_FRAME]

    rest = ours["coarse"].side.physics[0]
    centre = (rest.min(axis=0) + rest.max(axis=0)) / 2
    blender = locate("ASRP_BLENDER", ["blender"], BLENDER_CANDIDATES)
    if blender.path is None:
        raise SystemExit("Blender not found (set ASRP_BLENDER)")
    work = Path(tempfile.mkdtemp(prefix="asrp_render_comparison_"))
    try:
        np.savez(work / "points.npz", triangles=np.asarray(ziva.triangles, dtype=np.int64), centre=centre,
                 names=np.array(sorted(shown)), **{k: np.asarray(v, dtype=np.float64) for k, v in shown.items()})
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        done = subprocess.run([str(blender.path), "--background", "--factory-startup", "--python-exit-code", "1",
                               "--python", str(Path(__file__).resolve()), "--", str(work / "points.npz"), str(out)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        sys.stdout.write("".join(ln + "\n" for ln in done.stdout.splitlines() if ln.startswith("rendered ")))
        if done.returncode != 0:
            raise SystemExit(f"Blender failed:\n{done.stdout[-1500:]}\n{done.stderr[-1500:]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main_blender() -> None:
    import math

    import bpy
    import numpy as np

    args = sys.argv[sys.argv.index("--") + 1:]
    data = np.load(args[0], allow_pickle=False)
    out = Path(args[1])
    triangles = data["triangles"].tolist()
    centre = data["centre"] / 1000.0  # millimetres to the metres the camera uses

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "SINGLE"
    shading.single_color = LIP_COLOUR[:3]
    shading.show_object_outline = False
    shading.show_xray = False
    scene.world.color = (1.0, 1.0, 1.0)
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.render.image_settings.file_format = "PNG"

    cam_data = bpy.data.cameras.new("front")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = WIDTH_M
    cam = bpy.data.objects.new("front", cam_data)
    cam.location = (centre[0], centre[1] + 0.4, centre[2] - 0.004)
    cam.rotation_euler = (math.pi / 2, 0, math.pi)  # looks along -Y at the face, Z up
    scene.collection.objects.link(cam)
    scene.camera = cam

    obj = None
    for name in [str(n) for n in data["names"]]:
        points = data[name]
        if obj is None:
            mesh = bpy.data.meshes.new("lips")
            mesh.from_pydata(points.tolist(), [], triangles)
            obj = bpy.data.objects.new("lips", mesh)
            obj.scale = (0.001,) * 3
            scene.collection.objects.link(obj)
        else:
            obj.data.vertices.foreach_set("co", points.reshape(-1).tolist())
            obj.data.update()
        scene.render.filepath = str(out / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print(f"rendered {name}: {scene.render.filepath}")


if __name__ == "__main__":
    try:
        import bpy  # noqa: F401  (only inside Blender)
    except ImportError:
        main_python()
    else:
        main_blender()
