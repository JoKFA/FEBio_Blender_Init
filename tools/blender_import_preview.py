"""Bring a Maya export into Blender, check it landed right, and save a preview scene.

    blender --background --factory-startup --python-exit-code 1 --python tools/blender_import_preview.py -- data/lab_export data/preview

Migration tool, not product code: T-02 turns the same steps into `asrp import-asset` and a
scene.json. Writes asset_preview.blend, plus WebP renders into <out>. Every render shows the REST
meshes; the jaw is posed by rotating its hinge, and the lips do not follow (that is FEBio's job).

Coordinate steps (docs/03 section 10, ADR-16): the OBJ files are already scene coordinates, the
export did step 1. Here: scene units -> mm (ADR-04), then Y-up -> Z-up. The data stays in mm and
the objects carry a 0.001 scale for display, the same convention as playback (ADR-09).
"""

import json
import math
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1 :]
export, out = Path(args[0]).resolve(), Path(args[1]).resolve()
MM_PER_UNIT = 0.962  # paper appendix V, unconfirmed: 11 Q3, so never hard-code it past this tool
SAMPLES = 48
out.mkdir(parents=True, exist_ok=True)

LOOKS = {  # object name -> (file, colour, alpha)
    "lips": ("mesh_middleres_OrbicularisOris.obj", (0.72, 0.13, 0.15), 1.0),
    "jaw": ("mesh_middleres_Jaw.obj", (0.82, 0.78, 0.68), 1.0),
    "skull": ("mesh_middleres_skull.obj", (0.82, 0.78, 0.68), 1.0),
    "teeth_upper": ("mesh_middleres_TeethUp.obj", (0.93, 0.92, 0.86), 1.0),
    "teeth_lower": ("mesh_middleres_TeethDown.obj", (0.93, 0.92, 0.86), 1.0),
    "skin_context": ("context_skin_cloth_copy_v5_pull_back.obj", (0.80, 0.62, 0.52), 0.16),
}
JAW_PARTS = ("jaw", "teeth_lower")


def to_mm_zup(p):
    """Scene coordinates (Maya, Y up, face looking down -Z) -> mm, Z up, face looking down +Y."""
    x, y, z = (c * MM_PER_UNIT for c in p)
    return (x, -z, y)


def read_obj(path):
    vertices, faces = [], []
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                vertices.append(tuple(float(c) for c in line.split()[1:4]))
            elif line.startswith("f "):
                faces.append([int(c) - 1 for c in line.split()[1:]])
    return vertices, faces


def material(name, colour, alpha):
    mat = bpy.data.materials.new(name)
    node = mat.node_tree.nodes["Principled BSDF"]
    node.inputs["Base Color"].default_value = (*colour, 1.0)
    node.inputs["Roughness"].default_value = 0.55
    node.inputs["Alpha"].default_value = alpha
    return mat


started = time.time()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj)
collection = bpy.data.collections.new("ASRP asset")
bpy.context.scene.collection.children.link(collection)

report = json.loads((export / "mesh_report.json").read_text())
assert report["obj_coordinates"] == "scene", "this tool expects OBJ files in scene coordinates"

objects, expected = {}, {}
for name, (filename, colour, alpha) in LOOKS.items():
    vertices, faces = read_obj(export / filename)
    expected[name] = [to_mm_zup(p) for p in vertices]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(expected[name], [], faces)
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    mesh.update()
    mesh.materials.append(material(name, colour, alpha))
    obj = bpy.data.objects.new(name, mesh)
    obj.scale = (0.001, 0.001, 0.001)  # data stays in mm, Blender shows metres
    collection.objects.link(obj)
    objects[name] = obj

# Everything we measure below comes back out of Blender, not from the lists we put in.
bpy.context.view_layer.update()
worst = 0.0
print(f"{'object':14s} {'verts':>6s} {'faces':>6s}  size in mm (x y z)")
for name, obj in objects.items():
    mesh = obj.data
    assert len(mesh.vertices) == len(expected[name]) > 0, name
    worst = max(worst, max(max(abs(a - b) for a, b in zip(v.co, e)) for v, e in zip(mesh.vertices, expected[name])))
    size = [d * 1000 for d in obj.dimensions]
    print(f"{name:14s} {len(mesh.vertices):6d} {len(mesh.polygons):6d}  {size[0]:6.1f} {size[1]:6.1f} {size[2]:6.1f}")
print(f"worst vertex difference after import: {worst:.6f} mm")
assert worst < 1e-3, f"vertices moved during import: {worst} mm"

# Lips lie in front of the skull, the skull above the jaw hinge: catches a wrong axis conversion.
lips_y = sum(v[1] for v in expected["lips"]) / len(expected["lips"])
skull_y = sum(v[1] for v in expected["skull"]) / len(expected["skull"])
skull_top = max(v[2] for v in expected["skull"])
hinge_mm = Vector(to_mm_zup(report["jaw_hinge"]["world_position"]))
assert lips_y > skull_y, "lips should be in front of the skull centre"
assert skull_top > hinge_mm.z, "skull top should be above the jaw hinge"

# Jaw hinge: lower jaw and teeth hang off it. The axis is left-right (Blender X): jaw01's local
# Z, third row of its world matrix, is world X in the Maya scene (checked in maya_export output).
hinge = bpy.data.objects.new("jaw01_hinge", None)
hinge.empty_display_type = "SINGLE_ARROW"
hinge.empty_display_size = 0.04
hinge.location = hinge_mm * 0.001
collection.objects.link(hinge)
axis = report["jaw_hinge"]["world_matrix"][8:11]
assert max(abs(a) for a in axis) == abs(axis[0]) and abs(axis[0]) > 0.999, f"hinge axis is not left-right: {axis}"
for name in JAW_PARTS:
    obj = objects[name]
    obj.parent = hinge
    obj.matrix_parent_inverse = Matrix.Translation(-hinge.location)  # stay put when parented

# 300 landmarks: one small sphere per point, as children of a single point mesh.
landmarks = json.loads((export / "joints.json").read_text())
points = [to_mm_zup(j["world_position"]) for name, j in landmarks.items() if name.startswith("oor_")]
assert len(points) == 300
mesh = bpy.data.meshes.new("landmarks")
mesh.from_pydata(points, [], [])
holder = bpy.data.objects.new("landmarks", mesh)
holder.scale = (0.001, 0.001, 0.001)
holder.instance_type = "VERTS"
collection.objects.link(holder)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.1)
ball = bpy.context.active_object
ball.name = "landmark_ball"
ball.data.materials.append(material("landmark", (0.05, 0.45, 0.85), 1.0))
ball.parent = holder
ball.hide_render = False

center = (sum((Vector(p) for p in expected["lips"]), Vector()) / len(expected["lips"])) * 0.001

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = 1200, 900
scene.render.image_settings.file_format = "WEBP"
scene.render.image_settings.quality = 88
scene.render.film_transparent = True

for rot, energy in (((1.1, 0, 2.5), 3.2), ((1.3, 0, 4.3), 1.3), ((-0.6, 0, 0.3), 0.8)):
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = energy
    sun.rotation_euler = rot
    collection.objects.link(sun)

cam_data = bpy.data.cameras.new("view")
cam_data.lens = 85
cam = bpy.data.objects.new("view", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam


def shoot(name, offset, target, visible, jaw_degrees=0.0, ortho=None):
    for key, obj in objects.items():
        obj.hide_render = key not in visible
    holder.hide_render = "landmarks" not in visible
    ball.hide_render = "landmarks" not in visible
    hinge.rotation_euler = (math.radians(-jaw_degrees), 0, 0)
    cam_data.type = "ORTHO" if ortho else "PERSP"
    if ortho:
        cam_data.ortho_scale = ortho
    cam.location = target + Vector(offset)
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(out / f"{name}.webp")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {name}.webp")


# Chin must drop when the jaw opens: checked on the real rig, not assumed from the sign.
hinge.rotation_euler = (math.radians(-15), 0, 0)
bpy.context.view_layer.update()
jaw = objects["jaw"]
chin = max(jaw.data.vertices, key=lambda v: v.co.y)
open_z = (jaw.matrix_world @ chin.co).z
hinge.rotation_euler = (0, 0, 0)
bpy.context.view_layer.update()
closed_z = (jaw.matrix_world @ chin.co).z
print(f"chin drops {(closed_z - open_z) * 1000:.1f} mm at 15 degrees")
assert closed_z - open_z > 0.01, "opening the jaw should lower the chin by more than 10 mm"

bone = {"skull", "jaw", "teeth_upper", "teeth_lower"}
head_centre = center + Vector((0, -0.09, 0.02))
FRONT = (0.34, 0.92, 0.10)
shoot("01_all_parts", tuple(c * 1.32 for c in FRONT), head_centre, bone | {"lips", "skin_context"})
shoot("02_lips_on_bone", tuple(c * 0.62 for c in FRONT), center, bone | {"lips"})
shoot("03_lips_and_landmarks", (0.0, 0.34, 0.03), center, {"lips", "landmarks"})
shoot("04_side_hinge", (0.9, 0, 0), head_centre, bone | {"lips"}, ortho=0.34)
shoot("05_jaw_open_lips_stay", (0.9, 0, 0), head_centre, bone | {"lips"}, jaw_degrees=15, ortho=0.34)

hinge.rotation_euler = (0, 0, 0)
bpy.ops.wm.save_as_mainfile(filepath=str(out / "asset_preview.blend"))
print(f"{time.time() - started:.0f} s -> {out}")
print("BLENDER IMPORT PREVIEW PASSED")
