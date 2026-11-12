"""The panel's real timer path in a WINDOWED Blender: needs a display, is not part of tools/verify.py.

    "<blender.exe>" --factory-startup --python tools/panel_windowed_check.py -- \
        --scene <scene.json> --motion-a <a.json> --motion-b <b.json> --work <folder>

Blender quits itself at the end. `--work` receives the runs, the screenshots (one viewport render per shown entry, at the last
frame) and `windowed_check.json`. The scene should be the lab lips (`asrp import-asset data/lab_export <dir>`),
the two motions two different landmark motions on the same scene, so that the final shapes differ.

It drives the panel only through its operators (asrp.run, asrp.cancel_run, asrp.show_result), lets the add-on's
own `bpy.app.timers` callback follow each run, and prints:
  - per entry (physics / A final / B final): the visible object and the position (mm) of one lower-lip vertex
    at the last frame, read from the evaluated mesh;
  - a third run cancelled from the operator: the list is unchanged and nothing is visible;
  - the largest gap between two calls of the add-on's timer callback while a run was going.
"""

import json
import math
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "blender_addon"))

import asrp_blender  # noqa: E402
import bpy  # noqa: E402
import mathutils  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name):
    return argv[argv.index(name) + 1]


SCENE, MOTION_A, MOTION_B, WORK = opt("--scene"), opt("--motion-a"), opt("--motion-b"), Path(opt("--work"))
WORK.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SESSION = asrp_blender.SESSION
result = {"ok": False}
calls = []  # (time, running, progress lines so far, run folder) of every call of the add-on's timer callback

original_tick = asrp_blender.tick


def timed_tick():
    calls.append((time.monotonic(), SESSION.running, SESSION.progress_lines, SESSION.run_dir.name if SESSION.run_dir else None))
    return original_tick()


asrp_blender.tick = timed_tick  # ensure_timer() looks the name up when it registers


def say(msg):
    print(msg, flush=True)


def visible():
    return [o.name for o in bpy.data.objects if o.name.startswith("ASRP") and not o.hide_viewport and not o.hide_render]


def start(motion, name):
    sc = bpy.context.scene
    sc.asrp_scene_path, sc.asrp_trajectory_path, sc.asrp_runs_dir, sc.asrp_run_name = SCENE, motion, str(WORK / "runs"), name
    assert bpy.ops.asrp.run() == {"FINISHED"}


def wait_for_end():
    while not (SESSION.state in asrp_blender.ENDED and SESSION.handled):
        yield 0.2


def last_frame_vertices(entry):
    sc = bpy.context.scene
    sc.frame_set(sc.frame_end)
    bpy.context.view_layer.update()
    evaluated = entry.obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    points = [tuple(v.co) for v in mesh.vertices]
    evaluated.to_mesh_clear()
    return points


def find_view3d():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                return window, area, next(r for r in area.regions if r.type == "WINDOW")
    return None


def screenshots(tag, obj):
    """A viewport render (bpy.ops.render.opengl, side view of the shown object) at the current frame.
    `bpy.ops.screen.screenshot` was tried and gave a black or stale image here, so it is not used."""
    found = find_view3d()
    if found is None:
        return {"error": "no 3D view found"}
    window, area, region = found
    rv3d = area.spaces[0].region_3d
    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    rv3d.view_location = sum(corners, mathutils.Vector()) / 8
    rv3d.view_distance = 0.25
    rv3d.view_rotation = mathutils.Euler((math.radians(90), 0, math.radians(90))).to_quaternion()
    path = WORK / f"{tag}.png"
    try:
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.render.opengl(view_context=True, write_still=False)
            bpy.data.images["Render Result"].save_render(str(path))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"image": str(path), "bytes": path.stat().st_size}


def open_panel(name):
    """Draw a real panel as a popup (bpy.ops.wm.call_panel): a draw error is printed to the console by Blender, which
    this script's caller greps for."""
    window, area, region = find_view3d()
    with bpy.context.temp_override(window=window, area=area, region=region):
        return bpy.ops.wm.call_panel(name=name, keep_open=False)


def script():
    sc = bpy.context.scene
    yield 1.0
    start(MOTION_A, "A")
    yield from wait_for_end()
    assert SESSION.state == "complete", (SESSION.state, SESSION.error)
    say(f"run A: {SESSION.state}, passed {SESSION.passed}, {len(sc.asrp_results)} entries, visible {visible()}")
    start(MOTION_B, "B")
    yield from wait_for_end()
    assert SESSION.state == "complete", (SESSION.state, SESSION.error)
    labels = [e.label for e in sc.asrp_results]
    say(f"run B: {SESSION.state}, passed {SESSION.passed}, entries {labels}, visible {visible()}")
    assert len(labels) == 4, labels
    wanted = {"physics (run A)": 0, "A final": 1, "B final": 3}
    points = {}
    for tag, index in wanted.items():
        assert bpy.ops.asrp.show_result(index=index) == {"FINISHED"}
        entry = sc.asrp_results[index]
        assert visible() == [entry.obj.name], (visible(), entry.obj.name)
        points[tag] = last_frame_vertices(entry)
        yield 0.6  # let the window redraw before the picture
        points[tag + " shots"] = screenshots(tag.replace(" ", "_").replace("(", "").replace(")", ""), entry.obj)
        yield 0.3
    phys, a, b = points["physics (run A)"], points["A final"], points["B final"]
    lower = sorted(range(len(phys)), key=lambda i: phys[i][2])[: len(phys) // 2]  # the lower half of the lips by height
    pick = max(lower, key=lambda i: math.dist(a[i], b[i]))
    say(f"lower-lip vertex {pick} (the lower-half vertex where A final and B final differ most), last frame {sc.frame_end}, mm:")
    pos = {}
    for tag in wanted:
        pos[tag] = points[tag][pick]
        say(f"  {tag:16} visible {sc.asrp_results[wanted[tag]].obj.name!r:40} position {tuple(round(c, 4) for c in points[tag][pick])}")
    d_ab, d_ap, d_bp = math.dist(a[pick], b[pick]), math.dist(a[pick], phys[pick]), math.dist(b[pick], phys[pick])
    say(f"  distances: A final-B final {d_ab:.4f}, A final-physics {d_ap:.4f}, B final-physics {d_bp:.4f} mm")
    assert min(d_ab, d_ap, d_bp) > 1e-3, "the three shapes are not different at this vertex"
    for tag in wanted:
        say(f"  screenshots {tag}: {points[tag + ' shots']}")
    for name in ("ASRP_PT_results", "ASRP_PT_checks", "ASRP_PT_run"):
        say(f"panel {name} drawn as a popup: {open_panel(name)}")
        yield 0.7
    # a third run, cancelled from the operator
    before = [(e.label, e.run_dir) for e in sc.asrp_results]
    start(MOTION_A, "C")
    assert visible() == [], visible()
    while SESSION.run_dir is None and SESSION.running:
        yield 0.2
    yield 2.0
    say(f"panel ASRP_PT_run drawn while the run is going (state {SESSION.state}): {open_panel('ASRP_PT_run')}")
    yield 0.7
    assert bpy.ops.asrp.cancel_run() == {"FINISHED"}
    yield from wait_for_end()
    after = [(e.label, e.run_dir) for e in sc.asrp_results]
    say(f"run C cancelled: state {SESSION.state}, exit {SESSION.exit_code}, list unchanged {before == after} ({len(after)} entries), "
        f"visible {visible()}, playback.json in its folder {(SESSION.run_dir / 'playback.json').exists()}")
    assert SESSION.state == "cancelled" and before == after and visible() == []
    # two calls of the same run (a new run, which this script starts after its own work, is not a gap of the timer)
    pairs = [(b[0] - a[0], a, b) for a, b in zip(calls, calls[1:]) if a[1] and b[1] and a[2] <= b[2] and (a[3] == b[3] or a[3] is None)]
    gaps = [g for g, _, _ in pairs]
    for g, a, b in sorted(pairs, key=lambda p: -p[0])[:3]:
        say(f"  gap {g:.3f} s in {a[3]} between progress lines {a[2]} and {b[2]}")
    say(f"timer callback: {len(calls)} calls, {len(gaps)} gaps inside runs, largest gap {max(gaps):.3f} s (asked for {asrp_blender.TICK_S} s)")
    result.update(ok=True, largest_timer_gap_s=max(gaps), positions=pos, screenshots={t: points[t + " shots"] for t in wanted})


def drive():
    try:
        return next(generator)
    except StopIteration:
        pass
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        result["error"] = traceback.format_exc()
    (WORK / "windowed_check.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    say("WINDOWED CHECK PASSED" if result["ok"] else "WINDOWED CHECK FAILED")
    asrp_blender.unregister()
    bpy.ops.wm.quit_blender()
    return None


asrp_blender.register()
generator = script()
bpy.app.timers.register(drive, first_interval=1.0)
