"""Render a few frames of a playback bundle from the side, for a quick visual check.

    blender --background --factory-startup --python tools/render_playback.py -- <bundle_dir> <out_dir> [frames...]

Adds a hinge-axis marker and a skull plate for context (S1 geometry); writes frame_XX.png.
"""

import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "blender_addon"))

import bpy  # noqa: E402

import asrp_blender  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1 :]
# Absolute paths: Blender resolves a relative render.filepath against its own base, not the cwd.
bundle, out = Path(args[0]).resolve(), Path(args[1]).resolve()
frames = [int(f) for f in args[2:]] or [0, 15, 30, 45]
out.mkdir(parents=True, exist_ok=True)

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj)

asrp_blender.register()
assert bpy.ops.asrp.load_playback(directory=str(bundle)) == {"FINISHED"}

# Context props in metres: hinge axis through (5, -30, 0) mm, skull plate at z = 30 mm.
bpy.ops.mesh.primitive_cylinder_add(radius=0.0015, depth=0.016, location=(0.005, -0.030, 0.0), rotation=(0, math.pi / 2, 0))
bpy.ops.mesh.primitive_cube_add(size=1, location=(0.005, 0.005, 0.0315), scale=(0.014, 0.014, 0.003))
grey = bpy.data.materials.new("context")
grey.diffuse_color = (0.35, 0.35, 0.4, 1.0)
for obj in bpy.context.selected_objects:
    obj.data.materials.append(grey)

scene = bpy.context.scene
cam_data = bpy.data.cameras.new("side")
cam_data.type = "ORTHO"
cam_data.ortho_scale = 0.052
cam = bpy.data.objects.new("side", cam_data)
cam.location = (0.2, -0.012, 0.009)
cam.rotation_euler = (math.pi / 2, 0, math.pi / 2)  # look along -X, Z up, +Y to the right
scene.collection.objects.link(cam)
scene.camera = cam

scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_object_outline = True
scene.world.color = (1.0, 1.0, 1.0)
scene.render.resolution_x = scene.render.resolution_y = 480
scene.render.image_settings.file_format = "PNG"

for frame in frames:
    scene.frame_set(frame)
    scene.render.filepath = str(out / f"frame_{frame:02d}.png")
    bpy.ops.render.render(write_still=True)
    print(f"rendered {scene.render.filepath}")
