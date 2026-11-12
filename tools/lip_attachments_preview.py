"""Render the four lip attachment sets on the real meshes, for a person to look at (docs/09 T-03).

    blender --background --factory-startup --python-exit-code 1 --python tools/lip_attachments_preview.py -- data/lab_export data/preview/lip_attachments.png

Migration tool, not product code. Scene coordinates as they are in the OBJ files (Y up); the
camera looks along -Z, the way the face does. The lip is grey; each attachment set is drawn as a
small marker on its vertex, in front of everything else (the upper set sits on the inner side of
the lip, where the front view would hide it): upper lip (zAttachment1) red, lower lip
(zAttachment2) blue, left corner (zAttachment9) green, right corner (zAttachment10) orange. Skull
and jaw are beige. Uses the Workbench engine so it does not need a GPU.
"""

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bpy  # noqa: E402

from asrp_core.asset import coords  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
lab, out = Path(args[0]).resolve(), Path(args[1]).resolve()
export = json.loads((lab / "lip_attachments.json").read_text(encoding="utf-8"))

COLOURS = {  # attachment -> marker colour
    "zAttachment1": (0.90, 0.10, 0.10),
    "zAttachment2": (0.10, 0.30, 0.90),
    "zAttachment9": (0.10, 0.70, 0.20),
    "zAttachment10": (0.95, 0.55, 0.10),
}
LIP_GREY = (0.75, 0.75, 0.75)
BONE = (0.85, 0.82, 0.70)
MARK = 0.35  # half-size of a marker, scene units
OCTA_VERTS = [(MARK, 0, 0), (-MARK, 0, 0), (0, MARK, 0), (0, -MARK, 0), (0, 0, MARK), (0, 0, -MARK)]
OCTA_FACES = [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4), (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)]


def material(name, rgb):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1.0)
    return mat


def add_mesh(name, verts, faces, mat, in_front=False):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.show_in_front = in_front
    bpy.context.scene.collection.objects.link(obj)
    return obj


def markers(name, points, mat):
    """One small octahedron per point, all in one mesh."""
    verts, faces = [], []
    for p in points:
        base = len(verts)
        verts += [(p[0] + dx, p[1] + dy, p[2] + dz) for dx, dy, dz in OCTA_VERTS]
        faces += [tuple(base + i for i in f) for f in OCTA_FACES]
    return add_mesh(name, verts, faces, mat, in_front=True)


bpy.ops.wm.read_factory_settings(use_empty=True)

lips_v, lips_f = coords.read_obj(lab / "mesh_middleres_OrbicularisOris.obj")
skull_v, skull_f = coords.read_obj(lab / "mesh_middleres_skull.obj")
jaw_v, jaw_f = coords.read_obj(lab / "mesh_middleres_Jaw.obj")

add_mesh("lips", lips_v, lips_f, material("lip_grey", LIP_GREY))
bone_mat = material("bone", BONE)
add_mesh("skull", skull_v, skull_f, bone_mat)
add_mesh("jaw", jaw_v, jaw_f, bone_mat)

counts = {}
for g in export["groups"]:
    name = g["attachment"]
    points = [lips_v[v] for v, _ in g["vertices"]]
    counts[name] = len(points)
    markers(name, points, material(name, COLOURS[name]))
print("markers per set:", counts)
if not all(counts[n] > 0 for n in COLOURS):
    sys.exit("a set has no markers: nothing to look at")

# front view: orthographic camera on +Z looking along -Z, framed on the lip
xs = [v[0] for v in lips_v]
ys = [v[1] for v in lips_v]
cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
cam_data = bpy.data.cameras.new("camera")
cam_data.type = "ORTHO"
cam_data.ortho_scale = 1.35 * max(max(xs) - min(xs), max(ys) - min(ys))
cam = bpy.data.objects.new("camera", cam_data)
cam.location = (cx, cy, 500.0)
bpy.context.scene.collection.objects.link(cam)
bpy.context.scene.camera = cam

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.render.resolution_x, scene.render.resolution_y = 1400, 1000
scene.render.image_settings.file_format = "PNG"
scene.world = bpy.data.worlds.new("white")
scene.world.color = (1.0, 1.0, 1.0)
out.parent.mkdir(parents=True, exist_ok=True)
scene.render.filepath = str(out)
bpy.ops.render.render(write_still=True)
print("wrote", out)
