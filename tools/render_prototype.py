"""Load a prototype run's playback in Blender, check it frame by frame, and render stills with the bones for context.

    blender --background --factory-startup --python-exit-code 1 --python tools/render_prototype.py -- <run_dir> [--check-only] [--out <dir>]

Loads <run_dir>/playback.json with the add-on's Load Result operator (as a researcher would), then compares
Blender's evaluated lip mesh with physics/display.json + display.npy (what asrp computed) at frames 0, the settled frame
(settled_shape.frame in <run_dir>/run_report.json), the fully open frame and the last one. Then, unless --check-only, adds the skull and the jaw from <run_dir>'s copies of the
meshes (the jaw moved by its driver's transform from trajectory.json on each frame) and renders three side
views: rest (frame 0), settled (the settled frame) and jaw fully open (the frame where the jaw's angle is largest) to
<out>/prototype_rest.png, prototype_settled.png, prototype_open.png (default out: data/preview).

With --version final (a run that has a landmark layer) it loads and checks the final version (physics +
landmarks, <run_dir>/final/display.npy) instead of the physics one. With --last <name> it renders only the last
frame, from the side and from the front, to <out>/<name>_side.png and <out>/<name>_front.png (the page's front pictures come from tools/render_comparison.py).

With --frames-dir <dir> [--frames-size <px>] it also renders every frame of the same side view to
<dir>/frame_000.png ... (default 560 px square), for assembling an animation (the README's animation).
"""

import json
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "blender_addon"))

import asrp_blender  # noqa: E402
import bpy  # noqa: E402
import numpy as np  # noqa: E402  (Blender bundles it)
from mathutils import Matrix  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
run_dir = Path(args[0]).resolve()
check_only = "--check-only" in args
version = args[args.index("--version") + 1] if "--version" in args else "physics"
last_name = args[args.index("--last") + 1] if "--last" in args else None
out = Path(args[args.index("--out") + 1]).resolve() if "--out" in args else REPO / "data" / "preview"

report = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))
settled_shape = report.get("settled_shape") or {}
if not settled_shape.get("available") or not isinstance(settled_shape.get("frame"), int):
    sys.exit(f"{run_dir} has no settled shape (run_report.json settled_shape: {settled_shape or 'missing'}); "
             "the trajectory must name settle_until_frame >= 1 with the drivers still until then. Nothing was rendered.")
settled = settled_shape["frame"]

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj)
asrp_blender.register()
assert bpy.ops.asrp.load_playback(directory=str(run_dir), version=version) == {"FINISHED"}
lips = bpy.context.view_layer.objects.active
scene = bpy.context.scene

display_dir = run_dir / ("final" if version == "final" else "physics")
display_header = json.loads((display_dir / "display.json").read_text())  # header; the numbers are in .npy
display = np.load(display_dir / display_header["array"], allow_pickle=False)
assert list(display.shape) == display_header["shape"], f"{display_dir.name}/display.json and its array do not belong together"
motion = json.loads((run_dir / "trajectory.json").read_text())
scene_json = json.loads((run_dir / "scene.json").read_text())
jaw = next(b for b in scene_json["bones"] if b["name"] == "jaw")
jaw_motion = motion["drivers"][jaw["driver"]]


def angle(m):
    return math.acos(max(-1.0, min(1.0, (m[0] + m[5] + m[10] - 1) / 2)))


open_frame = max(range(len(jaw_motion)), key=lambda f: angle(jaw_motion[f]))
frames = sorted({0, settled, open_frame, len(display) - 1})
assert (scene.frame_start, scene.frame_end) == (0, len(display) - 1)
worst = moved = 0.0
for f in frames:
    scene.frame_set(f)
    ev = lips.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    assert len(mesh.vertices) == len(display[f])
    for v, p in zip(mesh.vertices, display[f]):
        worst = max(worst, math.dist(v.co, p))
        moved = max(moved, math.dist(v.co, display[0][v.index]))
    ev.to_mesh_clear()
assert worst < 1e-4, f"Blender's lips are {worst} mm off {display_dir.name}/display.json"
assert moved > 1.0, f"the lips barely move in Blender ({moved} mm): is the cache applied?"
print(f"{len(display[0])} vertices at frames {frames}: max error vs display.json {worst:.2e} mm, max motion {moved:.2f} mm")
print("PROTOTYPE PLAYBACK CHECK PASSED")
if check_only:
    sys.exit(0)


def read_obj(path: Path):
    vs, fs = [], []
    for line in path.read_text().splitlines():
        if line.startswith("v "):
            vs.append([float(c) for c in line.split()[1:4]])
        elif line.startswith("f "):
            fs.append([int(c.split("/")[0]) - 1 for c in line.split()[1:]])
    return vs, fs


def add(name: str, path: Path, color):
    vs, fs = read_obj(path)
    me = bpy.data.meshes.new(name)
    me.from_pydata(vs, [], fs)
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    ob.scale = (0.001,) * 3
    return ob


skull = add("skull", run_dir / next(b for b in scene_json["bones"] if b["name"] == "skull")["mesh"]["path"],
            (0.82, 0.8, 0.74, 0.35))
jaw_obj = add("jaw", run_dir / jaw["mesh"]["path"], (0.55, 0.62, 0.75, 1.0))
lips.data.materials[0].diffuse_color = (0.85, 0.25, 0.25, 1.0)

# Side view: the face looks down +Y (asrp_core.asset.coords), so look along -X with +Y to the right.
lo = [min(p[i] for p in display[0]) for i in range(3)]
hi = [max(p[i] for p in display[0]) for i in range(3)]
centre = [(a + b) / 2 / 1000 for a, b in zip(lo, hi)]
cam_data = bpy.data.cameras.new("side")
cam_data.type = "ORTHO"
cam_data.ortho_scale = 0.16
cam = bpy.data.objects.new("side", cam_data)
cam.location = (0.4, centre[1] - 0.03, centre[2] - 0.02)
cam.rotation_euler = (math.pi / 2, 0, math.pi / 2)
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_object_outline = True
scene.display.shading.show_xray = False
scene.world.color = (1.0, 1.0, 1.0)
scene.render.resolution_x = scene.render.resolution_y = 720
scene.render.image_settings.file_format = "PNG"
out.mkdir(parents=True, exist_ok=True)

if last_name:
    front = bpy.data.objects.new("front", cam_data.copy())
    front.data.ortho_scale = 0.14
    front.location = (centre[0], centre[1] + 0.4, centre[2] - 0.005)
    front.rotation_euler = (math.pi / 2, 0, math.pi)  # look along -Y at the face, Z up
    scene.collection.objects.link(front)
    scene.frame_set(len(display) - 1)
    m = jaw_motion[len(display) - 1]
    jaw_obj.matrix_world = Matrix.Scale(0.001, 4) @ Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
    for view, camera in (("side", cam), ("front", front)):
        scene.camera = camera
        scene.render.filepath = str(out / f"{last_name}_{view}.png")
        bpy.ops.render.render(write_still=True)
        print(f"rendered the last frame ({len(display) - 1}), {view} view: {scene.render.filepath}")
    sys.exit(0)

for label, f in (("rest", 0), ("settled", settled), ("open", open_frame)):
    scene.frame_set(f)
    m = jaw_motion[f]
    jaw_obj.matrix_world = Matrix.Scale(0.001, 4) @ Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
    scene.render.filepath = str(out / f"prototype_{label}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered frame {f} ({label}): {scene.render.filepath}")

if "--frames-dir" in args:
    frames_dir = Path(args[args.index("--frames-dir") + 1]).resolve()
    frames_dir.mkdir(parents=True, exist_ok=True)
    size = int(args[args.index("--frames-size") + 1]) if "--frames-size" in args else 560
    scene.render.resolution_x = scene.render.resolution_y = size
    for f in range(len(display)):
        scene.frame_set(f)
        m = jaw_motion[f]
        jaw_obj.matrix_world = Matrix.Scale(0.001, 4) @ Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])
        scene.render.filepath = str(frames_dir / f"frame_{f:03d}.png")
        bpy.ops.render.render(write_still=True)
    print(f"rendered {len(display)} frames to {frames_dir}")
