"""FEBio -> Blender round trip, checked frame by frame inside a real Blender.

    blender --background --factory-startup --python-exit-code 1 --python tools/check_playback.py

Runs spike S1 through the core (uv venv, real FEBio) into a temp folder, loads the
bundle with the add-on's Load Result operator, then compares Blender's evaluated
mesh against positions parsed straight from the FEBio log, not from our own cache.
"""

import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # keep the repo clean when run from the verify gate
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "blender_addon"))
sys.path.insert(0, str(REPO / "src"))  # asrp_core is stdlib-only, so Blender can read the log with it

import asrp_blender  # noqa: E402
import bpy  # noqa: E402

from asrp_core import febio, playback  # noqa: E402

out = Path(tempfile.mkdtemp(prefix="asrp_playback_"))
proc = subprocess.run(
    [shutil.which("uv"), "run", "--project", str(REPO), "python", str(REPO / "spikes" / "s1_dynamic_jaw.py"), str(out)],
    capture_output=True,
    text=True,
)
assert proc.returncode == 0, f"S1 failed:\n{proc.stdout}\n{proc.stderr}"

asrp_blender.register()
try:
    result = bpy.ops.asrp.load_playback(directory=str(out))
    assert result == {"FINISHED"}, f"load_playback returned {result}"
    obj = bpy.context.view_layer.objects.active
    scene = bpy.context.scene

    import json

    manifest = json.loads((out / "playback.json").read_text())
    truth = febio.read_node_data(out / "s1.log", "positions").values
    assert (scene.frame_start, scene.frame_end, scene.render.fps) == (0, len(truth) - 1, 30)
    assert all(math.isclose(s, 0.001, rel_tol=1e-6) for s in obj.scale), tuple(obj.scale)  # float32

    worst, moved = 0.0, 0.0
    for frame in (0, 15, 16, 30, 45):
        scene.frame_set(frame)
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        assert len(mesh.vertices) == len(manifest["node_ids"])
        for vertex, node in zip(mesh.vertices, manifest["node_ids"]):
            worst = max(worst, math.dist(vertex.co, truth[frame][node]))
            moved = max(moved, math.dist(vertex.co, truth[0][node]))
        evaluated.to_mesh_clear()

    assert worst < 1e-4, f"Blender vertices are {worst} mm off the FEBio log"
    assert moved > 1.0, f"mesh barely moves ({moved} mm): is the cache applied?"
    print(f"{len(manifest['node_ids'])} vertices x frames 0/15/16/30/45: max error vs FEBio log {worst:.2e} mm, "
          f"max motion {moved:.2f} mm")
    # The landmark layer's "final" version (T-09): a fixture bundle whose playback_final.pc2 is the physics cache
    # moved by SHIFT mm in x; the loader must pick the cache the version names.
    SHIFT = 2.0
    layered = out / "layered"
    layered.mkdir()
    shutil.copy(out / "playback.pc2", layered / "playback.pc2")
    playback.write_pc2(layered / "playback_final.pc2",
                       [[[c + (SHIFT if i == 0 else 0.0) for i, c in enumerate(truth[f][n])]
                         for n in manifest["node_ids"]] for f in range(len(truth))])
    versions = {"physics": "playback.pc2", "final": "playback_final.pc2"}
    (layered / "playback.json").write_text(json.dumps({**manifest, "versions": versions}))
    try:  # an operator that reports an ERROR raises in a script
        refused = bpy.ops.asrp.load_playback(directory=str(layered), version="nonsense") != {"FINISHED"}
    except RuntimeError as exc:
        refused = "versions" in str(exc)
    assert refused, "an unknown version must be refused, not loaded"
    for version, shift in (("physics", 0.0), ("final", SHIFT)):
        assert bpy.ops.asrp.load_playback(directory=str(layered), version=version) == {"FINISHED"}
        obj = bpy.context.view_layer.objects.active
        assert version in obj.name, f"{obj.name!r} does not say which version it is"
        assert obj.modifiers["ASRP result"].filepath.endswith(versions[version])
        scene.frame_set(30)
        mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        worst = max(math.dist(v.co, (truth[30][n][0] + shift, truth[30][n][1], truth[30][n][2]))
                    for v, n in zip(mesh.vertices, manifest["node_ids"]))
        assert worst < 1e-4, f"version {version}: vertices are {worst} mm from where they should be"
    print(f"layered bundle: 'physics' and 'final' (shifted {SHIFT} mm) both load and play")
    print("PLAYBACK CHECK PASSED")
    shutil.rmtree(out)
finally:
    asrp_blender.unregister()
