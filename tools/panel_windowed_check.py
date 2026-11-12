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
  - the largest gap between two calls of the add-on's timer callback while a run was going;
  - the shown result's object deleted with the viewport's X (object.delete): the panel must not claim it is shown;
  - File > Open (read_homefile) in the middle of a run: the run is still followed to its end and loaded;
  - every panel drawn as a popup, with Python errors on stderr captured and asserted absent (a panel whose draw
    raises on purpose proves the capture can fail).

Second mode, `--quit-midrun` (same arguments): starts a run, waits until FEBio is running, writes the run's process
tree to `quit_tree.txt`, then quits Blender mid-run. The add-on's atexit handler must have cancelled the run. A detached
helper started from Blender does not survive its exit here, so the check is by hand, once Blender has quit (about 10 s):
    powershell -NoProfile -Command "Get-Content <work>/quit_tree.txt | ForEach-Object { $id = ($_ -split ' ')[0]; Get-Process -Id $id -ErrorAction SilentlyContinue }"
which must print nothing (every process of the run's tree is gone, FEBio included).
"""

import json
import math
import subprocess
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
QUIT_MIDRUN = "--quit-midrun" in argv


class Capture:
    """sys.stderr that also keeps what was written: Blender prints a panel's draw error there."""

    def __init__(self, inner):
        self.inner, self.text = inner, []

    def write(self, s):
        self.text.append(s)
        return self.inner.write(s)

    def flush(self):
        self.inner.flush()

    def __getattr__(self, name):
        return getattr(self.inner, name)


sys.stderr = Capture(sys.stderr)
calls = []  # (time, running, progress lines so far, run folder) of every call of the add-on's timer callback

original_tick = asrp_blender.tick


def timed_tick():
    calls.append((time.monotonic(), SESSION.running, SESSION.progress_lines, SESSION.run_dir.name if SESSION.run_dir else None))
    return original_tick()


asrp_blender.tick = timed_tick  # ensure_timer() looks the name up when it registers


def say(msg):
    print(msg, flush=True)


def visible():
    return [o.name for o in bpy.data.objects
            if o.name.startswith("ASRP") and o.users_collection and not o.hide_viewport and not o.hide_render]


def start(motion, name):
    sc = bpy.context.scene
    sc.asrp_scene_path, sc.asrp_trajectory_path, sc.asrp_runs_dir, sc.asrp_run_name = SCENE, motion, str(WORK / "runs"), name
    assert bpy.ops.asrp.run() == {"FINISHED"}


def wait_for_end():
    last = time.monotonic()
    while not (SESSION.state in asrp_blender.ENDED and SESSION.handled):
        if time.monotonic() - last > 15:
            last = time.monotonic()
            say(f"  ... waiting: state {SESSION.state}, {SESSION.progress_lines} progress lines")
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
    mark = len(sys.stderr.text)
    with bpy.context.temp_override(window=window, area=area, region=region):
        finished = bpy.ops.wm.call_panel(name=name, keep_open=False)
    return finished, mark


def draw_errors(mark):
    return "".join(sys.stderr.text[mark:])


def draw_panel(name):
    """Open the panel as a popup, let Blender draw it, and assert that no Python error was printed meanwhile."""
    finished, mark = open_panel(name)
    yield 0.7
    errors = draw_errors(mark)
    assert "Traceback" not in errors, f"panel {name} raised while drawing:\n{errors}"
    say(f"panel {name} drawn as a popup {finished}, no Python error on stderr")


class ASRP_PT_selftest(bpy.types.Panel):
    """A panel that raises on purpose: proves that draw_panel's capture can fail."""
    bl_label = "selftest"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"

    def draw(self, context):
        raise ValueError("selftest draw error")


def tree_of(pid):
    table = {}
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId),$($_.ParentProcessId),$($_.Name)\" }"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.count(",") < 2:
            continue
        child, parent, name = line.strip().split(",", 2)
        table.setdefault(int(parent), []).append((int(child), name))
    found, todo = {}, [pid]
    while todo:
        for child, name in table.get(todo.pop(), []):
            found[child] = name
            todo.append(child)
    return found


def quit_midrun():
    yield 1.0
    start(MOTION_A, "Q")
    while SESSION.progress_lines < 3:  # FEBio is running
        assert SESSION.running, (SESSION.state, SESSION.error)
        yield 0.3
    tree = {SESSION.proc.pid: "uv(root)", **tree_of(SESSION.proc.pid)}
    (WORK / "quit_tree.txt").write_text("\n".join(f"{p} {n}" for p, n in tree.items()), encoding="utf-8")
    say(f"quitting Blender mid-run: {SESSION.progress_lines} progress lines, run folder {SESSION.run_dir}, process tree {tree}")
    assert any(n.lower().startswith("febio") for n in tree.values()), "FEBio was not running: this would prove nothing"
    result["ok"] = True
    yield 0.2


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
    bpy.utils.register_class(ASRP_PT_selftest)  # the capture must be able to fail
    _, mark = open_panel("ASRP_PT_selftest")
    yield 0.7
    bpy.utils.unregister_class(ASRP_PT_selftest)
    assert "selftest draw error" in draw_errors(mark), "a panel that raises was not noticed: the draw-error assertion proves nothing"
    say("self-test: a panel that raises while drawing was caught on stderr")
    for name in ("ASRP_PT_results", "ASRP_PT_checks", "ASRP_PT_run"):
        yield from draw_panel(name)
    # a third run, cancelled from the operator
    before = [(e.label, e.run_dir) for e in sc.asrp_results]
    start(MOTION_A, "C")
    assert visible() == [], visible()
    while SESSION.run_dir is None and SESSION.running:
        yield 0.2
    yield 2.0
    assert SESSION.running
    yield from draw_panel("ASRP_PT_run")  # drawn while the run is going: progress bar and cancel button
    assert bpy.ops.asrp.cancel_run() == {"FINISHED"}
    yield from wait_for_end()
    after = [(e.label, e.run_dir) for e in sc.asrp_results]
    say(f"run C cancelled: state {SESSION.state}, exit {SESSION.exit_code}, list unchanged {before == after} ({len(after)} entries), "
        f"visible {visible()}, playback.json in its folder {(SESSION.run_dir / 'playback.json').exists()}")
    assert SESSION.state == "cancelled" and before == after and visible() == []
    snap = list(calls)  # runs A, B, C: the gap figure leaves out the file load of run D, which stalls Blender by itself
    # the shown result's object deleted with the viewport's X: the list must not go on claiming it is shown
    assert bpy.ops.asrp.show_result(index=3) == {"FINISHED"}
    shown = asrp_blender.shown_entry(sc)
    assert shown is not None and shown.label.endswith("final shape")
    deleted = shown.obj.name
    for o in bpy.context.selected_objects:
        o.select_set(False)
    shown.obj.select_set(True)
    bpy.context.view_layer.objects.active = shown.obj
    window, area, region = find_view3d()
    with bpy.context.temp_override(window=window, area=area, region=region):
        assert bpy.ops.object.delete() == {"FINISHED"}
    claim = sc.asrp_shown
    say(f"X-delete of {deleted!r}: asrp_shown still {claim} (it is the index of the deleted entry), "
        f"shown_entry {asrp_blender.shown_entry(sc)}, visible {visible()}, entry 3 object {sc.asrp_results[3].obj}")
    assert asrp_blender.shown_entry(sc) is None and visible() == []
    yield from draw_panel("ASRP_PT_results")
    yield from draw_panel("ASRP_PT_checks")
    # File > Open in the middle of a run: the timer is persistent, the run is followed to its end and loaded
    start(MOTION_A, "D")
    while SESSION.run_dir is None:
        yield 0.2
    yield 2.0
    assert SESSION.running
    say(f"File > Open in the middle of run D ({SESSION.progress_lines} progress lines so far)")
    assert bpy.ops.wm.read_homefile() == {"FINISHED"}
    yield 0.5
    say(f"after the load: results in the new scene {len(bpy.context.scene.asrp_results)}, state {SESSION.state}, "
        f"timer registered {bpy.app.timers.is_registered(asrp_blender.tick)}")
    assert len(bpy.context.scene.asrp_results) == 0 and SESSION.running
    yield from wait_for_end()
    sc = bpy.context.scene
    assert SESSION.state == "complete" and not SESSION.load_error, (SESSION.state, SESSION.load_error)
    say(f"run D after the file load: {SESSION.state}, results in the new file's scene {[e.label for e in sc.asrp_results]}, visible {visible()}")
    assert len(sc.asrp_results) == 2 and len(visible()) == 1
    yield from draw_panel("ASRP_PT_run")
    yield from draw_panel("ASRP_PT_checks")
    # two calls of the same run (a new run, which this script starts after its own work, is not a gap of the timer)
    pairs = [(b[0] - a[0], a, b) for a, b in zip(snap, snap[1:]) if a[1] and b[1] and a[2] <= b[2] and (a[3] == b[3] or a[3] is None)]
    gaps = [g for g, _, _ in pairs]
    for g, a, b in sorted(pairs, key=lambda p: -p[0])[:3]:
        say(f"  gap {g:.3f} s in {a[3]} between progress lines {a[2]} and {b[2]}")
    say(f"timer callback: {len(snap)} calls, {len(gaps)} gaps inside runs, largest gap {max(gaps):.3f} s (asked for {asrp_blender.TICK_S} s)")
    result.update(ok=True, largest_timer_gap_s=max(gaps), positions=pos, screenshots={t: points[t + " shots"] for t in wanted})


def drive():
    try:
        return next(generator)
    except StopIteration:
        pass
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        result["error"] = traceback.format_exc()
    if QUIT_MIDRUN:  # quit with the add-on still registered and the run still going: the atexit handler must clean up
        say("QUIT MIDRUN: quitting now; read quit_leftover.txt in 30 s" if result["ok"] else f"QUIT MIDRUN FAILED: {result.get('error')}")
        bpy.ops.wm.quit_blender()
        return None
    (WORK / "windowed_check.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    say("WINDOWED CHECK PASSED" if result["ok"] else "WINDOWED CHECK FAILED")
    asrp_blender.unregister()
    bpy.ops.wm.quit_blender()
    return None


asrp_blender.register()
generator = quit_midrun() if QUIT_MIDRUN else script()
bpy.app.timers.register(drive, first_interval=1.0, persistent=True)  # File > Open must not end the script
