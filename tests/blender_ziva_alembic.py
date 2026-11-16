"""Run INSIDE Blender (tests/test_compare_blender.py starts it, headless): Ziva's playback package against the
export's own Alembic file, frame by frame (docs/09 T-11).

    blender --background --factory-startup --python-exit-code 1 --python tests/blender_ziva_alembic.py -- \
        <package folder> <lips_physics.abc> <mm per scene unit> <result.json> [<fps for the control>]

Loads the package with the add-on's Load Result operator, imports the Alembic, and for every frame 0 to n-1 puts the
timeline on that frame (30 frames per second) and takes the largest distance between the package's evaluated
vertices and the Alembic's, vertex number against vertex number, both in mm (the Alembic's points are scene units
and Y up: Blender's importer turns the axes, we scale). Writes {"fps", "frames", "max_mm", "per_frame_max_mm"}.
With a fifth argument the timeline is set to that frame rate AFTER loading: the control that reads the Alembic
at the wrong time (24 frames per second reads frame 14 as frame 17.5).
"""

import json
import sys
from pathlib import Path

import bpy
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "blender_addon"))
import asrp_blender  # noqa: E402

package, abc, mm, result = sys.argv[sys.argv.index("--") + 1:][:4]
control_fps = sys.argv[sys.argv.index("--") + 5] if len(sys.argv) > sys.argv.index("--") + 5 else None
mm = float(mm)

asrp_blender.register()
assert bpy.ops.asrp.load_playback(directory=package) == {"FINISHED"}
ours = bpy.context.view_layer.objects.active
manifest = json.loads((Path(package) / "playback.json").read_text())
frames = manifest["frame_count"]

before = set(bpy.data.objects)
bpy.ops.wm.alembic_import(filepath=abc, as_background_job=False)
imported = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
assert len(imported) == 1, f"expected one mesh from the Alembic, got {[o.name for o in imported]}"
theirs = imported[0]

scene = bpy.context.scene
assert scene.render.fps == 30 and scene.render.fps_base == 1.0, "the add-on sets 30 frames per second"
if control_fps:
    scene.render.fps = int(control_fps)


def points(obj, world: bool) -> np.ndarray:
    """The evaluated vertices: in the object's own space (our package: mm), or through its world matrix (the
    Alembic's object carries Maya's axes and unit change in its transform, so its world points are scene units)."""
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    a = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", a)
    evaluated.to_mesh_clear()
    a = a.reshape(-1, 3)
    if world:
        m = np.array(obj.matrix_world)
        a = a @ m[:3, :3].T + m[:3, 3]
    return a


worst = []
for frame in range(frames):
    scene.frame_set(frame)
    mine, abc_points = points(ours, False), points(theirs, True) * mm
    assert mine.shape == abc_points.shape, (mine.shape, abc_points.shape)
    worst.append(float(np.linalg.norm(mine - abc_points, axis=1).max()))
Path(result).write_text(json.dumps({"fps": scene.render.fps, "frames": frames, "max_mm": max(worst),
                                    "per_frame_max_mm": worst}))
print(f"ziva package vs Alembic: {frames} frames at {scene.render.fps} fps, max {max(worst):.3e} mm")
