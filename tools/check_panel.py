"""The Blender panel's run / results / checks logic, driven headless against `asrp run` processes.

    blender --background --factory-startup --python-exit-code 1 --python tools/check_panel.py

`bpy.app.timers` do not fire in --background, so this drives the same function the timer calls
(`asrp_blender.tick()`) from a sleep loop, and starts / cancels runs through the panel's operators.
Scenes come from tests/cube_scene.py (a small box with a skin and a landmarks trajectory), written by this
same file run with plain Python (`uv run python tools/check_panel.py --make-scene <folder>`), because Blender's
Python has no numpy.

Real `asrp run` processes: (1) a complete run (progress seen, run folder learned before the process ended, two
results, one visible, switching, five checks read from the report, an object loaded by the old Load Result button
is in the same list); (2) a run that cannot start (missing trajectory) and a start that fails before the process
exists; (3) cancelled runs, before and after the run folder is known; (6) closing the session before the folder is
known kills the whole process tree; (5) a file load in the middle of a run. Before every failure / cancel case a
result is made visible, so "nothing of an old run is visible afterwards" can fail.

Stand-in `asrp` (`--fake-asrp`, a small script that prints the lines `asrp run` prints and copies a real run folder):
exit code 1 after `run COMPLETE` (plausibility check failed, results loaded, failed check listed), exit code 3 after
`run COMPLETE` (a crash: failed), a cancel that comes too late, a load that fails. These cases exercise the panel's
parsing and loading, NOT a real failing run (a failing plausibility check cannot be provoked cheaply on a real one).
The windowed (timer) path is tools/panel_windowed_check.py.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

sys.dont_write_bytecode = True  # keep the repo clean when run from the verify gate
REPO = Path(__file__).resolve().parents[1]
FRAMES = 6
NAMES = ["lm_a", "lm_b", "lm_c"]


def make_scene(folder: Path) -> None:
    """Plain Python (uv venv): the cube scene with a landmark skin, motion.json (with landmarks) and long.json (no landmarks)."""
    import dataclasses

    import numpy as np

    sys.path[:0] = [str(REPO / "tests"), str(REPO / "src")]
    import cube_scene as cs

    from asrp_core import scene as scene_module
    from asrp_core import skinning, tetmesh, trajectory

    c = cs.write(folder)
    vertices = len(c["display"])
    w = np.random.default_rng(7).uniform(0.05, 1.0, size=(vertices, len(NAMES)))
    w[::5, 2] = 0.0
    w /= w.sum(axis=1, keepdims=True)
    eye = np.eye(4).ravel().tolist()
    skin = {"format": skinning.FORMAT, "units": "mm", "axes": "test", "convention": "column vectors, row by row",
            "mesh": "tissue", "names": NAMES, "rest_world": [eye] * 3, "bind_pre": [eye] * 3, "geom": eye,
            "weights": [[[k, float(w[i, k])] for k in range(3) if w[i, k] != 0.0] for i in range(vertices)]}
    (folder / "skin_mm.json").write_text(json.dumps(skin), encoding="utf-8", newline="\n")
    s = scene_module.load(c["scene"])
    ref = scene_module.FileRef("skin_mm.json", tetmesh.file_sha256(folder / "skin_mm.json"))
    scene_module.write(c["scene"], dataclasses.replace(s, landmarks=scene_module.Landmarks(NAMES, [[0.0, 0.0, 0.0]] * 3, ref)))
    path = cs.motion(folder, cs.still(FRAMES))
    t = np.zeros((FRAMES, len(NAMES), 3))
    for f in range(2, FRAMES):
        for i in range(len(NAMES)):
            t[f, i, i % 3] = 5.0 * (f - 2) / (FRAMES - 3) * (i + 1)
    trajectory.write(path, dataclasses.replace(trajectory.read(path), landmarks={"names": NAMES, "translations_mm": t.tolist()}))
    cs.motion(folder, cs.still(240), name="long.json")  # long enough to be cancelled while FEBio is running


def fake_asrp(argv: list[str]) -> int:
    """Stand-in for `asrp run`: argv = mode, a finished run folder to copy, then the real command's arguments."""
    mode, source, rest = argv[0], Path(argv[1]), argv[2:]
    runs, name = Path(rest[rest.index("--runs-dir") + 1]), rest[rest.index("--name") + 1]
    folder = runs / f"{name}_fake"
    if mode == "silent":  # never says where its folder is, and ignores everything
        time.sleep(120)
    if mode == "nothing":  # `run NOT STARTED` without an ERROR line
        print("run NOT STARTED", flush=True)
        return 1
    if mode == "exit1":  # dies without a word
        return 1
    folder.mkdir(parents=True, exist_ok=True)
    print(f"env PYTHONIOENCODING={os.environ.get('PYTHONIOENCODING')}", flush=True)
    print(f"run folder {folder}", flush=True)
    print("progress   frame 1 / 3", flush=True)
    if mode == "stubborn":  # ignores the cancel file, and has a child process of its own
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        time.sleep(120)
    if mode == "late":
        time.sleep(4)  # a cancel file written meanwhile is ignored: the run completes
    if mode != "crash":
        shutil.copytree(source, folder, dirs_exist_ok=True)
    if mode == "checkfail":
        path = folder / "run_report.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["checks"]["d"].update(passed=False, message="stand-in: this check was made to fail")
        report["passed"] = False
        path.write_text(json.dumps(report), encoding="utf-8")
    print("progress   frame 3 / 3", flush=True)
    print(f"run folder {folder}", flush=True)
    print(f"run COMPLETE: 3 frames; plausibility {'FAILED' if mode == 'checkfail' else 'PASSED'}", flush=True)
    return {"checkfail": 1, "crash": 3}.get(mode, 0)


if "--make-scene" in sys.argv:
    make_scene(Path(sys.argv[sys.argv.index("--make-scene") + 1]))
    raise SystemExit(0)
if "--fake-asrp" in sys.argv:
    raise SystemExit(fake_asrp(sys.argv[sys.argv.index("--fake-asrp") + 1:]))

sys.path.insert(0, str(REPO / "blender_addon"))
sys.path.insert(1, str(REPO / "tools"))  # local_paths: where the data outside the repository lives on this machine

import asrp_blender  # noqa: E402
import bpy  # noqa: E402
from bpy.app.handlers import persistent  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SESSION = asrp_blender.SESSION
UV = shutil.which("uv")
TIMEOUT_S = 600
THIS = Path(__file__).resolve()


def visible():
    return [o.name for o in bpy.data.objects
            if o.name.startswith("ASRP") and o.users_collection and not o.hide_viewport and not o.hide_render]


def make_visible():
    """A result is on screen before a case that must hide it (or must not show it): returns its name."""
    sc = bpy.context.scene
    index = next(i for i, e in enumerate(sc.asrp_results) if asrp_blender.is_live(e.obj))
    assert bpy.ops.asrp.show_result(index=index) == {"FINISHED"}
    before = visible()
    assert len(before) == 1, before
    return before[0]


def drive(on_tick=None):
    """What the timer does, from a loop: call tick() until it stops asking for another call."""
    t0 = time.monotonic()
    while True:
        again = asrp_blender.tick()
        if on_tick:
            on_tick()
        if again is None:
            return
        assert time.monotonic() - t0 < TIMEOUT_S, f"the run did not end in {TIMEOUT_S} s: {list(SESSION.lines)[-5:]}"
        time.sleep(0.1)


def start(scene_file, motion, runs, name):
    sc = bpy.context.scene
    sc.asrp_scene_path, sc.asrp_trajectory_path, sc.asrp_runs_dir, sc.asrp_run_name = str(scene_file), str(motion), str(runs), name
    assert bpy.ops.asrp.run() == {"FINISHED"}
    assert SESSION.state == "running"


def powershell(script: str) -> str:
    return subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout


def descendants(pid: int) -> set[int]:
    table = {}
    for line in powershell("Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId),$($_.ParentProcessId)\" }").split():
        child, parent = line.split(",")
        table.setdefault(int(parent), []).append(int(child))
    found, todo = set(), [pid]
    while todo:
        for child in table.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


def alive(pids) -> set[int]:
    if not pids:
        return set()
    out = powershell(f"Get-Process -Id {','.join(map(str, pids))} -ErrorAction SilentlyContinue | ForEach-Object {{ $_.Id }}")
    return {int(x) for x in out.split()}


def wait_gone(pids, limit=8.0):
    """The processes that are still alive `limit` seconds from now (polled: Windows can take a moment to remove a killed tree
    when the machine is busy). An empty set means they are gone; a process that stays makes the caller's assert fail."""
    t0 = time.monotonic()
    left = alive(pids)
    while left and time.monotonic() - t0 < limit:
        time.sleep(0.25)
        left = alive(pids)
    return left


def stand_in(mode, source):
    return lambda *args: [UV, "run", "--project", str(REPO), "python", str(THIS), "--fake-asrp", mode, str(source), *args]


def case_complete(box, runs, tmp):
    sc = bpy.context.scene
    start(box / "scene.json", box / "motion.json", runs, "complete")
    folder_before_end = []

    def watch():
        if SESSION.running and SESSION.run_dir is not None:
            folder_before_end.append(SESSION.run_dir)

    drive(watch)
    assert SESSION.state == "complete", (SESSION.state, SESSION.error, list(SESSION.lines)[-5:])
    assert SESSION.progress_lines > 0, "no progress line was seen"
    assert folder_before_end, "the run folder was not known while the process was still running"
    assert SESSION.run_dir.is_dir() and "complete" in SESSION.run_dir.name, SESSION.run_dir
    assert len(sc.asrp_results) == 2, [e.label for e in sc.asrp_results]
    assert [e.version for e in sc.asrp_results] == ["physics", "final"]
    assert visible() == [sc.asrp_results[1].obj.name], visible()  # the final version is shown after a run
    assert sc.asrp_shown == 1
    first = sc.asrp_results[0].obj
    first.hide_set(True)  # a hide in the view layer (the eye icon) must not survive "show" (item 8)
    assert first.hide_get()
    assert bpy.ops.asrp.show_result(index=0) == {"FINISHED"}
    assert visible() == [first.name] and sc.asrp_shown == 0, visible()
    assert not first.hide_get(), "shown, but still hidden in the view layer"
    report = asrp_blender.read_report(sc.asrp_results[0].run_dir)
    rows = asrp_blender.check_rows(report)
    assert rows is not None and len(rows) == 5 and [r[0] for r in rows] == ["a", "b", "b2", "c", "d"], rows
    assert rows[0][2] == "PASS", rows[0]
    assert "applied" in report["landmark_layer"] and asrp_blender.landmark_summary(report)
    print(f"case 1 complete: state {SESSION.state}, passed {SESSION.passed}, {SESSION.progress_lines} progress lines, folder known "
          f"{len(folder_before_end)} ticks before the end, {len(sc.asrp_results)} results "
          f"({', '.join(e.label for e in sc.asrp_results)}), visible {visible()}, checks "
          + ", ".join(f"{k}={v}" for k, _, v, _ in rows))
    return SESSION.run_dir


def case_old_button(source, tmp, box, runs):
    """The old Load result button goes through the same list: Load run folder on the same folder adds the version that is
    missing, and a new run hides that object (not made visible by make_visible(): the button's own result is on screen)."""
    sc = bpy.context.scene
    count = len(sc.asrp_results)
    copy = tmp / "legacy"
    shutil.copytree(source, copy)
    assert bpy.ops.asrp.load_playback(directory=str(copy)) == {"FINISHED"}
    assert len(sc.asrp_results) == count + 1 and sc.asrp_results[count].obj is not None
    assert visible() == [sc.asrp_results[count].obj.name] and sc.asrp_shown == count, visible()
    assert bpy.context.view_layer.objects.active == sc.asrp_results[count].obj
    assert bpy.ops.asrp.load_run_folder(directory=str(copy)) == {"FINISHED"}  # adds the final version only
    assert [e.version for e in sc.asrp_results][count:] == ["physics", "final"], [e.version for e in sc.asrp_results]
    assert visible() == [sc.asrp_results[count + 1].obj.name], visible()
    try:
        bpy.ops.asrp.load_run_folder(directory=str(copy))
        raise AssertionError("loading a folder that is completely in the list again was not refused")
    except RuntimeError as exc:
        assert "already in the list" in str(exc), exc
    assert len(sc.asrp_results) == count + 2
    on_screen = visible()
    assert len(on_screen) == 1
    start(box / "scene.json", box / "no_such_motion.json", runs, "after_button")  # no make_visible() first
    assert visible() == [], f"{on_screen} (loaded by the old button) is still visible after a new run started"
    drive()
    assert SESSION.state == "not_started" and len(sc.asrp_results) == count + 2
    print(f"case 1b old Load result button: {[e.label for e in sc.asrp_results][count:]} in the list, Load run folder added only the "
          f"missing version, then a new run hid {on_screen} (visible now {visible()})")


def case_start_fails(box, runs, old_state):
    """The command cannot even be built (uv not found, Popen raising): the old outcome must not stay on show (item 2)."""
    sc = bpy.context.scene
    count, before = len(sc.asrp_results), make_visible()
    assert SESSION.state == old_state == "complete"

    def no_uv(*args):
        raise RuntimeError("Cannot find uv on PATH")

    SESSION.launcher = no_uv
    try:
        try:
            start(box / "scene.json", box / "motion.json", runs, "never")
            raise AssertionError("the operator did not refuse")
        except RuntimeError as exc:  # an operator that reports an ERROR raises in a script
            assert "Cannot find uv" in str(exc), exc
    finally:
        SESSION.launcher = asrp_blender.core_command
    assert SESSION.state == "not_started" and "Cannot find uv" in SESSION.error, (SESSION.state, SESSION.error)
    assert SESSION.passed is None and not SESSION.load_error and SESSION.handled
    assert len(sc.asrp_results) == count and visible() == [], visible()
    print(f"case 2b start fails: state {old_state} -> {SESSION.state}, error {SESSION.error!r}, visible before {[before]} -> after {visible()}")


def case_not_started(box, runs):
    sc = bpy.context.scene
    count, before = len(sc.asrp_results), make_visible()
    start(box / "scene.json", box / "no_such_motion.json", runs, "missing")
    assert visible() == [], "an old result is still visible after a new run started"
    assert sc.asrp_shown == -1
    drive()
    assert SESSION.state == "not_started", (SESSION.state, SESSION.error, list(SESSION.lines)[-5:])
    assert SESSION.error.strip(), "the ERROR text was not captured"
    assert len(sc.asrp_results) == count, "a failed run added an entry"
    assert visible() == [] and sc.asrp_shown == -1, visible()
    print(f"case 2 not started: state {SESSION.state}, exit {SESSION.exit_code}, error {SESSION.error[:100]!r}, entries {len(sc.asrp_results)} "
          f"(was {count}), visible before {[before]} -> after {visible()}")


def case_cancelled(box, runs, early=False):
    sc = bpy.context.scene
    count, before = len(sc.asrp_results), make_visible()
    start(box / "scene.json", box / "long.json", runs, "cancel_early" if early else "cancel")
    assert visible() == [], f"{before} is still visible after the run started"
    if early:
        assert SESSION.run_dir is None
        assert bpy.ops.asrp.cancel_run() == {"FINISHED"}  # before the folder is known: remembered, written later
    asked = []

    def watch():
        if not early and SESSION.run_dir is not None and not asked:
            assert bpy.ops.asrp.cancel_run() == {"FINISHED"}
            asked.append(SESSION.progress_lines)

    drive(watch)
    assert SESSION.state == "cancelled", (SESSION.state, SESSION.exit_code, SESSION.error, list(SESSION.lines)[-5:])
    assert SESSION.exit_code == 2, SESSION.exit_code
    assert SESSION.run_dir is not None and SESSION.run_dir.is_dir()
    assert not (SESSION.run_dir / "playback.json").exists() and not (SESSION.run_dir / "physics").exists()
    assert len(sc.asrp_results) == count and visible() == [], (len(sc.asrp_results), visible())
    print(f"case 3{'b early' if early else ''} cancelled: state {SESSION.state}, exit {SESSION.exit_code}, cancel asked "
          f"{f'after {asked[0]} progress lines' if asked else 'before the folder was known'}, playback.json present "
          f"{(SESSION.run_dir / 'playback.json').exists()}, entries {len(sc.asrp_results)}, visible {visible()} (was {[before]})")


def case_stand_in(box, runs, source):
    sc = bpy.context.scene
    try:
        # exit code 1 after `run COMPLETE`: complete, results loaded, the failed check listed
        SESSION.launcher = stand_in("checkfail", source)
        count = len(sc.asrp_results)
        start(box / "scene.json", box / "motion.json", runs, "checkfail")
        drive()
        assert (SESSION.state, SESSION.exit_code, SESSION.passed) == ("complete", 1, False), (SESSION.state, SESSION.exit_code)
        assert len(sc.asrp_results) == count + 2 and len(visible()) == 1, (len(sc.asrp_results), visible())
        rows = asrp_blender.check_rows(asrp_blender.read_report(asrp_blender.shown_entry(sc).run_dir))
        fails = [r[0] for r in rows if r[2] == "FAIL"]
        assert fails == ["d"], rows
        assert any(line == "env PYTHONIOENCODING=utf-8" for line in SESSION.lines), list(SESSION.lines)[:3]
        print(f"case 4a stand-in, exit 1 after run COMPLETE: state {SESSION.state}, passed {SESSION.passed}, results loaded "
              f"({len(sc.asrp_results) - count} new), failed checks {fails}, child saw PYTHONIOENCODING=utf-8")

        # exit code 3 after `run COMPLETE`: a crash, nothing loaded
        SESSION.launcher = stand_in("crash", source)
        count, before = len(sc.asrp_results), make_visible()
        start(box / "scene.json", box / "motion.json", runs, "crash")
        drive()
        assert SESSION.state == "failed" and SESSION.exit_code == 3 and SESSION.passed is None, (SESSION.state, SESSION.exit_code)
        assert "exit code 3" in SESSION.error and len(sc.asrp_results) == count and visible() == [], visible()
        print(f"case 4b stand-in, exit 3 after run COMPLETE: state {SESSION.state}, nothing loaded, visible {[before]} -> {visible()}, "
              f"error {SESSION.error[:60]!r}")

        # a cancel that comes after the run has completed
        SESSION.launcher = stand_in("late", source)
        count = len(sc.asrp_results)
        start(box / "scene.json", box / "motion.json", runs, "late")
        asked = []

        def watch():
            if SESSION.run_dir is not None and not asked:
                assert bpy.ops.asrp.cancel_run() == {"FINISHED"}
                asked.append(1)

        drive(watch)
        assert SESSION.state == "complete" and SESSION.cancel_too_late and len(sc.asrp_results) == count + 2
        print(f"case 4c stand-in, cancel too late: state {SESSION.state}, cancel_too_late {SESSION.cancel_too_late}, result loaded")

        # a load that fails: the timer callback must end in a visible error, not raise; nothing half-loaded stays
        real = asrp_blender.build_playback_object
        calls = []

        def boom(context, manifest, folder, version="physics"):
            calls.append(version)
            if version == "final":
                raise RuntimeError("stand-in: the second object cannot be built")
            return real(context, manifest, folder, version)

        SESSION.launcher = stand_in("ok", source)
        count, objects, before = len(sc.asrp_results), len(bpy.data.objects), make_visible()
        sc.render.fps, sc.frame_start, sc.frame_end = 24, 3, 99  # the physics load would change these (30 fps, 0..5)
        asrp_blender.build_playback_object = boom
        try:
            start(box / "scene.json", box / "motion.json", runs, "badload")
            drive()
        finally:
            asrp_blender.build_playback_object = real
        assert calls == ["physics", "final"], calls
        assert SESSION.state == "complete" and "second object" in SESSION.load_error, (SESSION.state, SESSION.load_error)
        assert len(sc.asrp_results) == count and len(bpy.data.objects) == objects and visible() == [], \
            (len(sc.asrp_results), count, len(bpy.data.objects), objects, visible())
        print(f"case 4d load fails after 'physics' was added: error shown {SESSION.load_error!r}, rolled back "
              f"(entries {count} -> {len(sc.asrp_results)}, objects {objects} -> {len(bpy.data.objects)})")
    finally:
        SESSION.launcher = asrp_blender.core_command


def case_malformed_reports():
    rows = asrp_blender.check_rows
    for bad in ([], None, {"checks": []}, {"checks": {"a": 5}}, {"checks": {"a": {"passed": "yes"}}}, "text"):
        assert rows(bad) is None, bad
        assert isinstance(asrp_blender.landmark_summary(bad), str)
    odd = {"checks": {"a": {"name": None, "passed": True, "message": None}}, "landmark_layer": {"applied": True, "landmarks_moved": None,
                                                                                               "max_translation_mm": None}}
    got = rows(odd)
    assert got is not None and got[0][1:] == ("a", "PASS", "") and len(got) == 5, got
    assert "?" in asrp_blender.landmark_summary(odd) and isinstance(asrp_blender.landmark_summary({"landmark_layer": [1]}), str)
    tmp = Path(tempfile.mkdtemp(prefix="asrp_report_"))
    try:
        (tmp / "run_report.json").write_text("[1, 2]", encoding="utf-8")
        assert asrp_blender.read_report(tmp) is None  # valid JSON, wrong shape
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("case 7 malformed reports: top-level list/None/str, checks as a list, a non-dict check, a bad verdict -> unreadable (None); "
          "null name / message / numbers -> still rows and a summary; no exception")


LABEL_MAX = 34  # characters one line holds at the default sidebar width (280 px); longer text is wrapped (wrapped() uses 32)


class Rec:
    """A stand-in for a panel layout that records what is drawn: ('label', text, alert, height, row), ('op', idname, text, depress, op,
    enabled, height, row) and ('prop', name, text, height, row). `height` is the row's scale_y (small lines are 0.7); `row` is the
    horizontal container the item is in (items of one row share one line of the panel), or None."""

    def __init__(self, log, alert=False, parent=None, kind="col"):
        self.log, self.alert, self.alignment, self.parent, self.own_enabled, self.kind = log, alert, "EXPAND", parent, True, kind
        self.own_scale = 1.0

    @property
    def enabled(self):  # as in Blender: a layout inside a greyed-out one is greyed out, whatever it sets for itself
        return self.own_enabled and (self.parent is None or self.parent.enabled)

    @enabled.setter
    def enabled(self, value):
        self.own_enabled = value

    @property
    def scale_y(self):
        return self.own_scale * (1.0 if self.parent is None else self.parent.scale_y)

    @scale_y.setter
    def scale_y(self, value):
        self.own_scale = value

    def line(self):
        node = self
        while node is not None:
            if node.kind == "row":
                return id(node)
            node = node.parent
        return None

    def label(self, text="", icon="NONE"):
        self.log.append(("label", text, self.alert, self.scale_y, self.line()))

    def operator(self, idname, text="", icon="NONE", depress=False):
        op = types.SimpleNamespace(index=-1)
        self.log.append(("op", idname, text, depress, op, self.enabled, self.scale_y, self.line()))  # sixth: the layout it is drawn in was enabled
        return op

    def prop(self, *args, **kw):
        self.log.append(("prop", args[1] if len(args) > 1 else "", kw.get("text"), self.scale_y, self.line()))

    def row(self, **kw):
        return Rec(self.log, self.alert, self, "row")

    split = row

    def column(self, **kw):
        return Rec(self.log, self.alert, self, "col")


ROW_PX, HEADER_PX, PAD_PX, BUDGET_PX = 21, 26, 8, 650  # a row of the panel, a panel header, the margin round an open panel; a 1080p window
EXPAND_ROWS = {"asrp_tet_choice": 2}  # a radio group is one row per choice


def rows_of(log) -> float:
    """How many rows of the panel a drawn log takes: one per item, items of one horizontal row count once (the tallest), a small line counts 0.7."""
    total, lines = 0.0, {}
    for r in log:
        h = r[3] if r[0] in ("label", "prop") else r[6]
        if r[0] == "prop":
            h *= EXPAND_ROWS.get(r[1], 1)
        line = r[4] if r[0] in ("label", "prop") else r[7]
        if line is None:
            total += h
        else:
            lines[line] = max(lines.get(line, 0.0), h)
    return total + sum(lines.values())


def panel_height(open_all: bool = False) -> float:
    """Pixels from the top of the ASRP tab to the bottom of the Results buttons, with the panels in their default open / closed state
    (`open_all`: every panel open), for what is drawn now: header per panel, rows, and a margin round every open panel."""
    order = ["ASRP_PT_main", "ASRP_PT_asset", "ASRP_PT_asset_details", "ASRP_PT_setup", "ASRP_PT_motion", "ASRP_PT_run", "ASRP_PT_results"]
    px = 0.0
    for name in order:
        cls = getattr(asrp_blender, name)
        px += HEADER_PX
        if open_all or "DEFAULT_CLOSED" not in getattr(cls, "bl_options", ()):
            rows = rows_of(draw_panel(cls))
            px += rows * ROW_PX + (PAD_PX if rows else 0)
    return px


def draw_panel(panel):
    log = []
    me = types.SimpleNamespace(layout=Rec(log))
    for name in ("draw_running", "draw_outcome", "draw_playback"):  # the Run panel's helper methods
        if hasattr(panel, name):
            setattr(me, name, types.MethodType(getattr(panel, name), me))
    panel.draw(me, bpy.context)
    too_long = [(r[0], (r[1] if r[0] == "label" else r[2] if r[0] == "op" else r[2])) for r in log
                if r[0] in ("label", "op", "prop") and len(str((r[1] if r[0] == "label" else r[2]) or "").rstrip()) > LABEL_MAX]
    assert not too_long, f"{panel.bl_label}: text that does not fit {LABEL_MAX} characters (cut off at the default sidebar width): {too_long}"
    return log


def case_layout(run1, tmp):
    """The Results panel groups the versions under one header per run; the Checks panel shows short fixed labels and the
    two reported-only rows. Drives the panels' draw() with a recording layout, so it checks what is drawn."""
    sc = bpy.context.scene
    count = len(sc.asrp_results)
    second = tmp / "second_run"
    shutil.copytree(run1, second)
    assert bpy.ops.asrp.load_run_folder(directory=str(second)) == {"FINISHED"}
    assert len(sc.asrp_results) == count + 2

    # the "Run other files" panel (the typed-path run; the three steps have no path field): the label above the field, the field without text
    log = draw_panel(asrp_blender.ASRP_PT_run_files)
    props = [r for r in log if r[0] == "prop"]
    assert [r[1] for r in props] == ["asrp_scene_path", "asrp_trajectory_path", "asrp_runs_dir", "asrp_run_name"], props
    assert all(r[2] == "" for r in props), props
    texts = [r[1] for r in log if r[0] == "label"]
    for label in ("Scene", "Motion (trajectory.json)", "Runs folder", "Run name"):
        assert label in texts, (label, texts)
    assert texts.index("Scene") < texts.index("Motion (trajectory.json)") < texts.index("Runs folder") < texts.index("Run name")

    # the Results panel: two runs, two headers, each with its versions, one version shown
    log = draw_panel(asrp_blender.ASRP_PT_results)
    groups = asrp_blender.result_groups(sc)
    assert len(groups) >= 2 and groups[-1] == [count, count + 1], groups
    headers = [r[1] for r in log if r[0] == "label" and r[1] and "deleted" not in r[1] and r[1] != "No result is shown"]
    assert headers == [sc.asrp_results[g[0]].run_name for g in groups], headers
    shows = [r for r in log if r[0] == "op" and r[1] == "asrp.show_result"]
    assert len(shows) == len(sc.asrp_results) and sum(1 for r in shows if r[3]) == 1, [(r[2], r[3]) for r in shows]
    assert [r[2] for r in shows[-2:]] == ["Physics only", "Final shape"], [r[2] for r in shows]
    assert all(r[2] in ("Physics only", "Final shape") for r in shows)
    order = [r[1] if r[0] == "label" else r[2] for r in log if r[0] == "label" or (r[0] == "op" and r[1] == "asrp.show_result")]
    head = sc.asrp_results[count].run_name
    assert order[-3:] == [head, "Physics only", "Final shape"], order  # header, then its two versions
    assert sc.asrp_results[count + 1].run_name == head and sum(1 for r in log if r[0] == "label" and r[1] == head) == 1
    # switching and removing still work
    assert bpy.ops.asrp.show_result(index=count) == {"FINISHED"} and visible() == [sc.asrp_results[count].obj.name]
    shows = [r for r in draw_panel(asrp_blender.ASRP_PT_results) if r[0] == "op" and r[1] == "asrp.show_result"]
    assert [i for i, r in enumerate(shows) if r[3]] == [count], [r[3] for r in shows]

    # the Checks panel (the second run's second entry is shown): short labels, the unknown key falls back to the report's name
    assert bpy.ops.asrp.show_result(index=count + 1) == {"FINISHED"}
    path = second / "run_report.json"
    original = json.loads(path.read_text(encoding="utf-8"))

    def checks_log(report):
        path.write_text(json.dumps(report), encoding="utf-8")
        asrp_blender._REPORTS.clear()
        return draw_panel(asrp_blender.ASRP_PT_checks)

    def text_of(log):
        return " ".join(r[1] for r in log if r[0] == "label")

    log = checks_log(original)
    texts = [r[1] for r in log if r[0] == "label"]
    expect = ["(a) Motion completed", "(b) Hard attachments", "(b2) Spring anchors",
              "(c) Gravity sag", "(d) Tet mesh valid"]
    assert [t for t in texts if t in expect] == expect, texts
    assert not [t for t in texts if t.startswith(("(a)", "(b)", "(b2)", "(c)", "(d)")) and t not in expect], texts  # no long name
    assert {"PASS", "FAIL", "NOT RUN"} & set(texts), texts  # the verdict is drawn
    assert all(len(t) <= 28 for t in expect), [len(t) for t in expect]  # short enough for the 280 px sidebar with PASS / FAIL on the right
    odd = json.loads(json.dumps(original))
    odd["checks"]["z"] = {"name": "Zeta thing", "passed": True, "message": ""}
    assert "(z) Zeta thing" in [r[1] for r in checks_log(odd) if r[0] == "label"]
    odd["checks"]["y"] = "not a check entry"  # an unreadable EXTRA entry is left out; the five known checks still show
    rows = asrp_blender.check_rows(odd)
    assert rows is not None and "y" not in [r[0] for r in rows] and [r[0] for r in rows][:5] == list(asrp_blender.CHECK_KEYS)
    del odd["checks"]["y"]

    # the reported-only rows: present when the report has the keys, absent when it has not, and the not-settled alert
    full = json.loads(json.dumps(original))
    full["surface_health"] = {"physics": {"last": {"flipped_faces": 7, "edges_shorter_than_half": 8, "edges_longer_than_double": 9}},
                              "final": {"last": {"flipped_faces": 2, "edges_shorter_than_half": 3, "edges_longer_than_double": 4}}}
    full["settled_shape"] = {"available": True, "tissue_step_max_mm": 0.0005, "tissue_settled": True}
    log = checks_log(full)
    text = text_of(log)
    assert "Surface (final): 2 flipped faces, 3 edges < 0.5x, 4 edges > 2x" in text, text
    assert "Settle: tissue moved 0.0005 mm in the last settle frame" in text, text
    assert "Tissue not settled" not in text
    full["surface_health"]["final"] = None
    assert "Surface (physics): 7 flipped faces, 8 edges < 0.5x, 9 edges > 2x" in text_of(checks_log(full))
    full["settled_shape"]["tissue_settled"] = False
    log = checks_log(full)
    alerts = " ".join(r[1] for r in log if r[0] == "label" and r[2])  # the alert-coloured lines (long text wraps to several)
    assert "Tissue not settled at the settle frame" in alerts, alerts
    assert "Tissue not settled" not in text_of(checks_log(full | {"settled_shape": {"tissue_step_max_mm": 0.1, "tissue_settled": None}}))
    warned = json.loads(json.dumps(original))
    warned["warnings"] = ["display surface: flipped faces, 3 in the final version at frame 21 (1 at the last frame). The plausibility checks look only "
                          "at the tet mesh, so a PASSED run can still have them. Reported, not a check"]
    log = checks_log(warned)
    need("Reported, not a check: display surface: flipped faces, 3 in the final version at frame 21 (1 at the last frame)." in text_of(log), "warning",
         f"the flipped-faces warning is not shown in the Checks section: {text_of(log)}")
    need(not [r for r in log if r[0] == "label" and r[1] == "FAIL"] and not [r for r in log if r[0] == "label" and r[2] and "flipped" in r[1]], "warning",
         "the warning is drawn as a failure")
    need([r[2] for r in asrp_blender.check_rows(warned)] == [r[2] for r in asrp_blender.check_rows(original)], "warning", "the warning changed a check")
    bare = json.loads(json.dumps(original))
    bare.pop("surface_health", None)
    bare["settled_shape"] = {"available": False, "frame": None}
    text = text_of(checks_log(bare))
    assert "Surface (" not in text and "Settle:" not in text and "Tissue not settled" not in text, text
    bare.pop("settled_shape")
    text = text_of(checks_log(bare))
    assert "Surface (" not in text and "Settle:" not in text and "Tissue not settled" not in text, text
    assert "Landmark layer" in text  # the rest of the panel is still drawn

    # removing a run's entries removes its header
    for index in (count + 1, count):
        assert bpy.ops.asrp.remove_result(index=index) == {"FINISHED"}
    assert len(sc.asrp_results) == count and len(asrp_blender.result_groups(sc)) == len(groups) - 1
    assert second.name == "second_run" and "second_run" not in [r[1] for r in draw_panel(asrp_blender.ASRP_PT_results) if r[0] == "label"]
    assert asrp_blender.check_label("z", "Zeta thing") == "(z) Zeta thing"
    print(f"case 10 layout: Run fields {len(props)} labels above empty-text fields; Results {len(groups)} runs -> {len(groups)} headers, "
          f"versions {[r[2] for r in shows[-2:]]}, one shown, switch and remove work; Checks {expect}, unknown key falls back to the "
          f"report's name; Surface / Settle rows present with the keys, absent without; not-settled alert drawn")


def case_deleted_object():
    sc = bpy.context.scene
    # What the viewport's X does: the object is unlinked from its collection but the list's pointer keeps it alive.
    make_visible()
    entry = asrp_blender.shown_entry(sc)
    assert entry is not None
    obj = entry.obj
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    assert entry.obj is not None, "the object is gone from bpy.data: this does not reproduce the X-delete"
    assert asrp_blender.shown_entry(sc) is None, "the list still claims an unlinked (X-deleted) object is shown"
    # And a removal from bpy.data altogether
    make_visible()
    entry = asrp_blender.shown_entry(sc)
    bpy.data.objects.remove(entry.obj, do_unlink=True)
    assert asrp_blender.shown_entry(sc) is None, "the list still claims a deleted object is shown"
    print("case 8 deleted shown object: unlinked (what X does) and removed from the data: shown_entry is None, the panel says nothing is shown")


def wait_for_folder(limit=60):
    """Poll (without the load step of tick()) until the run folder is known."""
    t0 = time.monotonic()
    while SESSION.run_dir is None:
        assert SESSION.running and time.monotonic() - t0 < limit, (SESSION.state, SESSION.error)
        SESSION.poll()
        time.sleep(0.1)


def process_tree():
    """uv's process and every descendant of it: what must be gone. Asserts there is something to watch."""
    t0 = time.monotonic()
    tree = set()
    while not tree and time.monotonic() - t0 < 20:
        tree = descendants(SESSION.proc.pid)
    assert tree, "no child process of the run was seen: this case would prove nothing"
    everyone = tree | {SESSION.proc.pid}
    assert alive(everyone), f"the run is not running (exit code {SESSION.proc.poll()})"
    return everyone


def case_close_before_folder(box, runs, source):
    """Closing the session before the run folder is known must not leave uv / python running. A stand-in that never
    names its folder and does not end by itself: with the real core this case depended on catching the run in the
    second or two before the folder line, and failed whenever the machine was slower or faster than that."""
    try:
        SESSION.launcher = stand_in("silent", source)
        start(box / "scene.json", box / "long.json", runs, "closed")
        everyone = process_tree()
        assert SESSION.run_dir is None
        SESSION.close()
    finally:
        SESSION.launcher = asrp_blender.core_command
    time.sleep(2)
    left = alive(everyone)
    assert not left, f"processes left running after close(): {left}"
    assert SESSION.proc.poll() is not None
    print(f"case 6a close before the folder is known: {len(everyone)} processes were running, 2 s after close() left: {sorted(left)}")


def case_process_cleanup(box, runs, source):
    """No process tree is ever left untracked: close with a known folder (cancel file, bounded wait, kill), a dropped
    session, a failing timer callback, and a cancel that never gets a folder. The stand-ins ignore every cancel."""
    sc = bpy.context.scene
    try:
        SESSION.launcher = stand_in("stubborn", source)
        start(box / "scene.json", box / "motion.json", runs, "stubborn_close")
        wait_for_folder()
        everyone = process_tree()
        t0 = time.monotonic()
        SESSION.close(wait=2.0)
        took = time.monotonic() - t0
        assert (SESSION.run_dir / "cancel").exists(), "close() did not write the cancel file first"
        assert 1.5 < took < 10, f"close(wait=2) took {took:.1f} s: the wait is not bounded as asked"
        time.sleep(1)
        left = wait_gone(everyone)
        assert not left, f"left after close() with a known folder: {left}"
        print(f"case 6b close with a known folder, process ignores the cancel file: cancel file written, waited {took:.1f} s, "
              f"then the tree of {len(everyone)} processes was killed; left: {sorted(alive(everyone))}")

        start(box / "scene.json", box / "motion.json", runs, "stubborn_reset")
        wait_for_folder()
        everyone = process_tree()
        SESSION.reset()
        time.sleep(1)
        left = wait_gone(everyone)
        assert not left and SESSION.state == "idle", left
        print(f"case 6c a dropped session (reset) kills its tree: {len(everyone)} processes, left {sorted(alive(everyone))}")

        start(box / "scene.json", box / "motion.json", runs, "stubborn_tick")
        wait_for_folder()
        everyone = process_tree()

        def broken():
            raise RuntimeError("stand-in: the poll step failed")

        SESSION.poll = broken
        try:
            assert asrp_blender.tick() is None  # must not raise
        finally:
            del SESSION.poll
        time.sleep(1)
        left = wait_gone(everyone)
        assert not left, left
        assert SESSION.state == "failed" and "poll step failed" in SESSION.load_error, (SESSION.state, SESSION.load_error)
        print(f"case 6d the timer callback fails while the process runs: state {SESSION.state}, tree of {len(everyone)} killed, "
              f"left {sorted(alive(everyone))}, error shown {SESSION.load_error!r}")

        SESSION.launcher = stand_in("silent", source)
        SESSION.cancel_wait_s = 2.0
        count = len(sc.asrp_results)
        start(box / "scene.json", box / "motion.json", runs, "silent")
        everyone = process_tree()
        assert bpy.ops.asrp.cancel_run() == {"FINISHED"}
        t0 = time.monotonic()
        drive()
        took = time.monotonic() - t0
        time.sleep(1)
        assert SESSION.state == "cancelled" and SESSION.run_dir is None and len(sc.asrp_results) == count, (SESSION.state, took)
        assert 1.5 < took < 15 and not alive(everyone), (took, alive(everyone))
        print(f"case 6e cancel before any run folder, bound 2 s: state {SESSION.state} after {took:.1f} s, tree of {len(everyone)} killed, "
              f"left {sorted(alive(everyone))}")

        for mode, state in (("nothing", "not_started"), ("exit1", "failed")):
            SESSION.launcher = stand_in(mode, source)
            start(box / "scene.json", box / "motion.json", runs, mode)
            drive()
            assert SESSION.state == state and "exit code 1" in SESSION.error, (SESSION.state, SESSION.error)
            print(f"case 6f stand-in '{mode}' (no ERROR line): state {SESSION.state}, error shown {SESSION.error!r}")
    finally:
        SESSION.launcher = asrp_blender.core_command
        SESSION.cancel_wait_s = 10.0


@persistent
def spy(*_args):
    SPIED.append(1)


SPIED: list = []


def case_file_load_mid_run(box, runs, tmp):
    """File > Open while a run goes: the timer survives, the opened file's shown result is hidden, a finished run's outcome
    is not the new file's banner, and the result of a run that ends after the load goes to the new file's scene."""
    sc = bpy.context.scene
    make_visible()
    saved = tmp / "shown.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(saved), copy=True) == {"FINISHED"}
    saved_entries = len(sc.asrp_results)
    handlers = bpy.app.handlers.load_post

    # (a) the timer's own persistence, without the handler: the saved shown result is still on screen (what the handler is for)
    start(box / "scene.json", box / "long.json", runs, "reload_a")
    handlers.remove(asrp_blender.on_load_post)
    try:
        assert bpy.ops.wm.open_mainfile(filepath=str(saved)) == {"FINISHED"}
    finally:
        handlers.append(asrp_blender.on_load_post)
    sc = bpy.context.scene
    assert len(sc.asrp_results) == saved_entries and SESSION.state == "running"
    assert bpy.app.timers.is_registered(asrp_blender.tick), "the timer did not survive the file load"
    assert len(visible()) == 1, "without the handler the saved result should still be shown: this check would prove nothing"

    # (b) a real load fires the handler: it re-arms a missing timer and hides the saved result while the run goes
    bpy.app.timers.unregister(asrp_blender.tick)
    handlers.append(spy)
    try:
        assert bpy.ops.wm.open_mainfile(filepath=str(saved)) == {"FINISHED"}
    finally:
        handlers.remove(spy)
    sc = bpy.context.scene
    assert SPIED, "a real file load did not call the load_post handlers"
    assert bpy.app.timers.is_registered(asrp_blender.tick), "the load_post handler did not re-arm the timer"
    assert visible() == [] and sc.asrp_shown == -1, (visible(), sc.asrp_shown)
    assert SESSION.state == "running"
    assert bpy.ops.asrp.cancel_run() == {"FINISHED"}
    drive()
    assert SESSION.state == "cancelled"

    # (c) the finished run's outcome is not the banner of a file opened afterwards
    assert bpy.ops.wm.open_mainfile(filepath=str(saved)) == {"FINISHED"}
    assert SESSION.state == "idle", SESSION.state

    # (d) a run that ends after the load: its result goes to the scene that is current then
    start(box / "scene.json", box / "motion.json", runs, "reload")
    assert bpy.ops.wm.open_mainfile(filepath=str(saved)) == {"FINISHED"}
    drive()
    sc = bpy.context.scene
    assert SESSION.state == "complete" and not SESSION.load_error, (SESSION.state, SESSION.load_error)
    assert len(sc.asrp_results) == saved_entries + 2 and len(visible()) == 1 and "reload" in visible()[0], (len(sc.asrp_results), visible())
    print(f"case 5 file load mid-run: (a) timer survived without the handler, saved result still shown; (b) a real load called the handlers "
          f"({len(SPIED)} call), re-armed the timer and hid the saved result; (c) a finished run's banner is cleared (state idle); "
          f"(d) the run that ended after the load went to the new scene ({len(sc.asrp_results)} entries, visible {visible()})")


def case_english_only():
    """The panel is English: no CJK character (ideographs, kana, hangul, full-width forms, CJK punctuation) in the add-on."""
    import re

    cjk = re.compile("[　-ヿ㐀-䶿一-鿿가-힯＀-￯]")
    files = sorted((REPO / "blender_addon").rglob("*.py")) + sorted((REPO / "blender_addon").rglob("*.toml"))
    assert len(files) >= 2, files  # the scan must have something to scan
    found = [f"{f.name}:{n}: {line.strip()[:60]}" for f in files
             for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if cjk.search(line)]
    assert not found, "CJK characters in the add-on:\n" + "\n".join(found)
    assert cjk.search("运行") and cjk.search("，"), "the pattern does not see CJK text"  # the scan can fail
    print(f"case 9 English only: {len(files)} add-on files scanned, no CJK character")


# --- the three steps on the real asset: Open asset, pick a motion, Run, and the result plays on the same five objects ----------

ROLES = ("skull", "jaw", "teeth_upper", "teeth_lower", "lips")
BONE_DRIVER = {"skull": "head", "teeth_upper": "head", "jaw": "jaw01", "teeth_lower": "jaw01"}  # from the card, not from the add-on
MOTIONS = {  # file: (layer the panel must show, frame in the middle of the motion, bones that must move, bones that must not)
    "jaw_open_12deg.json": ("physics", 32, ("jaw", "teeth_lower"), ("skull", "teeth_upper")),  # the jaw is open the widest at frame 32
    "head_shake.json": ("physics", 24, ("skull", "jaw"), ()),
    "neutral_to_AA.json": ("final", 25, ("jaw", "teeth_lower"), ("skull", "teeth_upper")),  # last: its last control replaces the five objects
}  # the order the cases run in (the panel's list order is TITLES)
TITLES = {  # what the panel's list shows, in the order it shows it: from the owner's words, not from the add-on
    "jaw_open_12deg.json": "Prototype 1: jaw opens 12 deg",
    "neutral_to_AA.json": "Prototype 2: neutral to AA",
    "head_shake.json": "Prototype 2: head shake",
}
LIPS_TOLERANCE_MM = 1e-5
BONE_TOLERANCE_MM = 1e-4  # the bones' quaternions are float32
MOVES_AT_LEAST_MM = 0.5  # a bone that "moves" at the checked frame moved at least this far from rest (the check must be able to fail)


class CheckFailed(AssertionError):
    """A check of the three-step flow failed; the message starts with the name of the check in brackets."""


def need(condition, tag, message):
    if not condition:
        raise CheckFailed(f"[{tag}] {message}")


def read_pc2(path):
    """(points, frames, float array) of a point cache file: 'POINTCACHE2\\0', version, points, start, rate, samples, float32 xyz."""
    import array
    import struct

    with open(path, "rb") as f:
        magic, version, points, _start, _rate, samples = struct.unpack("<12siiffi", f.read(32))
        need(magic == b"POINTCACHE2\0" and version == 1, "cache", f"{path} is not a version 1 point cache")
        data = array.array("f")
        data.fromfile(f, points * samples * 3)
    return points, samples, data


def read_npy_f64(path):
    """The numbers of a .npy of float64 (C order, version 1): the header is a python dict in text, then raw bytes."""
    import array
    import struct

    with open(path, "rb") as f:
        need(f.read(6) == b"\x93NUMPY", "cache", f"{path} is not a .npy file")
        major, _minor = f.read(2)
        length = struct.unpack("<H" if major == 1 else "<I", f.read(2 if major == 1 else 4))[0]
        header = f.read(length).decode("latin1")
        need("'<f8'" in header and "'fortran_order': False" in header, "cache", f"unexpected .npy header {header!r}")
        data = array.array("d")
        data.fromfile(f, (os.path.getsize(path) - f.tell()) // 8)
    return data


def max_diff(a, b):
    need(len(a) == len(b), "lips", f"two shapes with {len(a) // 3} and {len(b) // 3} vertices cannot be compared")
    return max(abs(x - y) for x, y in zip(a, b))


def frame_of(cache, frame):
    points, samples, data = cache
    need(0 <= frame < samples, "cache", f"frame {frame} is not in a cache of {samples} frames")
    return data[frame * points * 3:(frame + 1) * points * 3]


def lips_local_mm(obj):
    """The evaluated lips (the Mesh Cache modifier applied) in the object's own geometry, mm: not scaled to metres."""
    import array

    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = ev.to_mesh()
    co = array.array("f", bytes(4 * 3 * len(mesh.vertices)))
    mesh.vertices.foreach_get("co", co)
    ev.to_mesh_clear()
    return co


def snapshot(objs):
    return {role: (o.session_uid, o.name) for role, o in objs.items()}


BYSTANDER = "asrp_check_bystander"  # marks the objects this check puts in the scene to stand for a user's own objects


def mesh_objects():
    return [o for o in bpy.data.objects if o.type == "MESH" and o.users_collection and BYSTANDER not in o
            and o.get(asrp_blender.asset.ROLE_KEY) not in ("landmarks", "ziva_lips", "highlight_points")]  # the landmark dots are the sixth object, not one of the five


def bystander(name, size, at):
    """A box that is NOT the asset's: `size` metres along each axis (one number or three), centred at `at`."""
    sx, sy, sz = (size,) * 3 if isinstance(size, (int, float)) else size
    corners = [(x * sx / 2, y * sy / 2, z * sz / 2) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(corners, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = at
    obj[BYSTANDER] = True
    bpy.context.collection.objects.link(obj)
    return obj


def asset_now():
    sc = bpy.context.scene
    return {i.role: i.obj for i in sc.asrp_asset_objects}


def motion_transform(motion, role, frame):
    rows = motion["drivers"].get(BONE_DRIVER[role])
    return rows[frame] if rows is not None else [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def bone_error_mm(obj, m, frame):
    """The most any sampled vertex of the bone is from where the motion file puts it at this frame (mm). 0 if it is exact."""
    verts = obj.data.vertices
    step = max(1, len(verts) // 200)
    worst = 0.0
    for i in range(0, len(verts), step):
        x, y, z = verts[i].co
        want = (m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7], m[8] * x + m[9] * y + m[10] * z + m[11])
        got = obj.matrix_world @ verts[i].co
        worst = max(worst, max(abs(got[k] / 0.001 - want[k]) for k in range(3)))
    return worst


def bone_shift_mm(obj, m):
    """How far the motion transform m moves the bone's sampled vertices from rest (mm)."""
    verts = obj.data.vertices
    step = max(1, len(verts) // 200)
    worst = 0.0
    for i in range(0, len(verts), step):
        x, y, z = verts[i].co
        want = (m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7], m[8] * x + m[9] * y + m[10] * z + m[11])
        worst = max(worst, max(abs(want[k] - c) for k, c in enumerate((x, y, z))))
    return worst


def verify_three_step(case):
    """One function for the check and for every control. `case`: file, motion (parsed), run_dir, layer, frames (the middle one first),
    movers, still, ident (the snapshot of the five objects Open asset made). Raises CheckFailed with a tagged message."""
    sc, motion, run_dir = bpy.context.scene, case["motion"], Path(case["run_dir"])
    frames, mid = motion["frames"], case["frames"][0]
    # identity: the objects the result is on are the five Open asset made
    objs = asset_now()
    need(sorted(objs) == sorted(ROLES), "identity", f"the asset's objects are {sorted(objs)}, expected {sorted(ROLES)}")
    for role, obj in objs.items():
        uid, name = case["ident"][role]
        need(obj.session_uid == uid and obj.name == name and bpy.data.objects.get(name) is obj, "identity",
             f"the {role} object is not the one Open asset made (it was replaced by another object)")
        need(obj.users_collection and not obj.hide_viewport and not obj.hide_render, "identity", f"the {role} object is not visible")
    meshes = [o.name for o in mesh_objects() if o.name not in {n for _, n in case["ident"].values()}]
    need(not meshes, "identity", f"more mesh objects than the five of the asset: {meshes}")
    # timeline
    need((sc.frame_start, sc.frame_end, sc.render.fps, sc.render.fps_base) == (0, frames - 1, int(motion["fps"]), 1.0), "timeline",
         f"timeline {sc.frame_start}..{sc.frame_end} at {sc.render.fps} fps, the motion has {frames} frames at {motion['fps']} fps")
    # the lips: one Mesh Cache modifier, on the cache of the layer, evaluated frame by frame
    lips = objs["lips"]
    caches = [m for m in lips.modifiers if m.type == "MESH_CACHE"]
    need(len(caches) == 1, "lips", f"the lips have {len(caches)} Mesh Cache modifiers, expected 1")
    pc2 = {"physics": run_dir / "playback.pc2", "final": run_dir / "playback_final.pc2"}
    cache = {k: read_pc2(p) for k, p in pc2.items() if p.is_file()}
    for k in cache:  # the cache named after a layer holds that layer: its numbers are the run's own float64 mesh of the layer
        npy = run_dir / k / "display.npy"
        need(npy.is_file(), "cache", f"{npy} is missing")
        data, points = read_npy_f64(npy), cache[k][0]
        need(len(data) == cache[k][1] * points * 3, "cache", f"{npy} does not have the cache's {cache[k][1]} frames of {points} points")
        for f in case["frames"]:
            off = max_diff(frame_of(cache[k], f), data[f * points * 3:(f + 1) * points * 3])
            need(off < 3e-5, "cache", f"the {k} cache differs from {k}/display.npy by {off:.3g} mm at frame {f} (float32 rounding is below 3e-5)")
    need(case["layer"] in cache, "layer", f"the run folder has no {case['layer']} cache; it has {sorted(cache)}")
    other = [k for k in cache if k != case["layer"]]
    if other:  # the two layers must differ at the middle frame, or the check could not tell them apart
        gap = max_diff(frame_of(cache[case["layer"]], mid), frame_of(cache[other[0]], mid))
        need(gap > 0.05, "layer", f"the landmark layer is zero at frame {mid} (the layers differ by {gap:.3g} mm): pick another frame")
    for f in case["frames"]:
        sc.frame_set(f)
        bpy.context.view_layer.update()
        got = lips_local_mm(lips)
        diff = max_diff(got, frame_of(cache[case["layer"]], f))
        if diff >= LIPS_TOLERANCE_MM:
            for k in other:
                if max_diff(got, frame_of(cache[k], f)) < LIPS_TOLERANCE_MM:
                    raise CheckFailed(f"[layer] at frame {f} the lips show the {k} layer, the {case['layer']} layer was expected")
            for shift in (-1, 1):
                g = f + shift
                if 0 <= g < frames and max_diff(got, frame_of(cache[case["layer"]], g)) < LIPS_TOLERANCE_MM:
                    raise CheckFailed(f"[sync] at frame {f} the lips show the shape of frame {g}: not the same frame as the bones")
            raise CheckFailed(f"[lips] at frame {f} the lips differ from the {case['layer']} cache by {diff:.3g} mm (limit {LIPS_TOLERANCE_MM:g})")
        # bones in the same frame
        for role, obj in objs.items():
            if role == "lips":
                continue
            m = motion_transform(motion, role, f)
            err = bone_error_mm(obj, m, f)
            need(err < BONE_TOLERANCE_MM, "bones", f"at frame {f} the {role} is {err:.3g} mm from where the motion file puts it")
            if role in case["still"]:
                need(bone_shift_mm(obj, m) < 1e-9, "bones", f"the {role} must not move in this motion but the motion file moves it")
        if f == mid:
            for role in case["movers"]:
                shift = bone_shift_mm(objs[role], motion_transform(motion, role, f))
                need(shift >= MOVES_AT_LEAST_MM, "bones",
                     f"the {role} should move in this motion but the motion file moves it only {shift:.3g} mm at frame {f}")
    # frame 0: the lips are the asset's lips (the cache starts from the mesh Open asset built, same vertex order)
    sc.frame_set(0)
    bpy.context.view_layer.update()
    rest = array_of_mesh(lips)
    need(max_diff(lips_local_mm(lips), rest) < 1e-3, "lips", "at frame 0 the lips are not the asset's lips (vertex order or mesh differs)")
    return {"lips_mm": diff, "frames": case["frames"]}


def array_of_mesh(obj):
    import array

    co = array.array("f", bytes(4 * 3 * len(obj.data.vertices)))
    obj.data.vertices.foreach_get("co", co)
    return co


def expect_caught(case, tag, what, corrupt, names=None):
    """A control: `corrupt()` makes the result wrong in one way; the same check must fail with the matching check's tag
    and, when `names` is given, its message must name that object (a failure about another bone is not this control)."""
    corrupt()
    try:
        verify_three_step(case)
    except CheckFailed as exc:
        assert str(exc).startswith(f"[{tag}]"), f"control '{what}' failed the wrong check: {exc}"
        assert names is None or names in str(exc), f"control '{what}' was caught for another object: {exc}"
        print(f"  control '{what}': caught by the {tag} check: {exc}")
        return
    raise AssertionError(f"control '{what}' was NOT caught: the check passed on a result that is wrong")


def pick(file):
    sc = bpy.context.scene
    index = next((i for i, m in enumerate(sc.asrp_motions) if m.file == file), None)
    assert index is not None, f"{file} is not in the motion list {[m.file for m in sc.asrp_motions]}"
    assert bpy.ops.asrp.pick_motion(index=index) == {"FINISHED"} and sc.asrp_motion_index == index


def views_state():
    """Every 3D view's view matrix, perspective and distance (what a person sees of the camera)."""
    out = []
    for key, space in asrp_blender.asset.view3d_spaces(bpy.context):
        v = space.region_3d
        out.append((key, tuple(round(x, 9) for row in v.view_matrix for x in row), v.view_perspective, round(v.view_distance, 9)))
    return out


def three_steps_run(file, rest_check=False):
    """Step 2 and 3: pick the motion from the list, press Run, wait, return the run folder. No path is typed.
    rest_check: the moment the run has started, the result of the run before is gone from the asset.
    The timeline is put somewhere else first (frame 20, range 5..9), so that "the frame and the range are the motion's" can fail."""
    sc = bpy.context.scene
    pick(file)
    sc.frame_start, sc.frame_end = 5, 9
    sc.frame_current = 20
    if SESSION.state == "complete":  # a person would wait a moment too: a click within a second of the end of a run is refused
        time.sleep(max(0.0, asrp_blender.RUN_AGAIN_S + 0.1 - (time.monotonic() - SESSION.ended_at)))
    plays = len(asrp_blender.asset.PLAY_REQUESTS)
    views = views_state()
    assert views, "no 3D view with a view matrix: the check that a run leaves the views alone would prove nothing"
    assert bpy.ops.asrp.run_motion() == {"FINISHED"} and SESSION.state == "running"
    assert SESSION.target == "asset"
    try:  # a second click while it runs
        bpy.ops.asrp.run_motion()
        raise AssertionError("a second Run was accepted while a run is active")
    except RuntimeError as exc:
        assert "already in progress" in str(exc), exc
    if rest_check:
        assert_at_rest("a run has started")
    drive()
    assert SESSION.state == "complete" and not SESSION.load_error, (SESSION.state, SESSION.error, SESSION.load_error, list(SESSION.lines)[-5:])
    assert sc.asrp_scene_path == "" and sc.asrp_trajectory_path == "" and sc.asrp_runs_dir == "", "a path property was used"
    frames = json.loads((REPO / "data" / "lab_export" / "trajectories" / file).read_text(encoding="utf-8"))["frames"]
    need(sc.frame_current == 0, "after-run", f"after {file} the timeline is on frame {sc.frame_current}, not on the motion's first frame 0")
    need((sc.frame_start, sc.frame_end) == (0, frames - 1), "after-run",
         f"after {file} the frame range is {sc.frame_start}..{sc.frame_end}, the motion's is 0..{frames - 1}")
    requests = asrp_blender.asset.PLAY_REQUESTS[plays:]
    need(len(requests) == 1 and requests[0][:2] == (0, frames - 1), "after-run",
         f"after {file} the play request was {requests}, expected one request for frames 0..{frames - 1}")
    need(views_state() == views, "views", f"a run moved a 3D view: {views} -> {views_state()}")  # docs/06: a later Run does not move the view
    try:  # a click right after a run finished
        bpy.ops.asrp.run_motion()
        raise AssertionError("a Run was accepted at once after a run finished")
    except RuntimeError as exc:
        need("just finished" in str(exc), "run-twice", str(exc))
    return SESSION.run_dir


def assert_at_rest(label):
    """The asset is at rest: the lips have no cache, the bones do not move at a frame in the middle of the last motion."""
    sc = bpy.context.scene
    objs = asset_now()
    sc.frame_set(25)
    bpy.context.view_layer.update()
    assert not [m for m in objs["lips"].modifiers if m.type == "MESH_CACHE"], f"{label}: the lips still have a point cache"
    for role, obj in objs.items():
        if role != "lips":
            assert bone_error_mm(obj, motion_transform({"drivers": {}}, role, 25), 25) < BONE_TOLERANCE_MM, f"{label}: the {role} is not at rest"


def case_three_steps():
    sc = bpy.context.scene
    missing = [f for f in MOVES_FILES if not (REPO / "data" / "lab_export" / "trajectories" / f).is_file()]
    assert not missing, (f"the motion file(s) {missing} are not in data/lab_export/trajectories/. neutral_to_AA.json is the lab's motion "
                         "(T-34); until it is committed, generate a local stand-in there (never commit it). This check cannot pass without it.")
    sc.asrp_scene_path = sc.asrp_trajectory_path = sc.asrp_runs_dir = ""
    SESSION.reset()
    for index in reversed(range(len(sc.asrp_results))):  # the results of the cases before, and the factory scene's own meshes
        asrp_blender.remove_entry(sc, index)
    asrp_blender.asset.remove_objects([o for o in bpy.data.objects if o.type == "MESH"])
    assert not mesh_objects(), [o.name for o in mesh_objects()]
    # What a researcher's Blender holds when it opens: the start-up scene's 2 m cube at the origin. The asset is shown at its real
    # size, a head, and lands INSIDE that cube: a person then sees a cube and no asset (seen in the windowed walk-through,
    # 2026-11-15; this check used to delete the cube first, so it could not see it). Two more objects that do not enclose
    # the asset stand for a user's own things: they must be left alone.
    cube = bystander("Cube", 2.0, (0.0, 0.0, 0.0))
    beside = bystander("Beside", 0.05, (3.0, 0.0, 0.0))
    wall = bystander("Wall", (4.0, 0.02, 4.0), (0.0, 2.0, 0.0))  # large, but the asset is not inside it
    for name, allowed in (("open_asset", []), ("run_motion", []), ("pick_motion", ["index"])):  # no path property in the three steps
        props = [p.identifier for p in getattr(bpy.ops.asrp, name).get_rna_type().properties if p.identifier != "rna_type"]
        assert props == allowed, (name, props)
    # step 1: Open asset
    assert bpy.ops.asrp.open_asset() == {"FINISHED"}
    objs = asset_now()
    meshes = mesh_objects()
    assert sorted(objs) == sorted(ROLES) and len(meshes) == 5 and all(o.type == "MESH" and len(o.data.vertices) > 1000 for o in meshes), \
        (sorted(objs), [o.name for o in meshes])
    assert {o[asrp_blender.asset.ROLE_KEY] for o in meshes} == set(ROLES)
    ident = snapshot(objs)
    box, cube_box = asrp_blender.asset.asset_box(objs.values()), asrp_blender.asset.world_box(cube)
    extent = [round(box[1][i] - box[0][i], 3) for i in range(3)]
    assert all(0.05 < e < 0.5 for e in extent), f"the asset is not head-sized in Blender's metres: {extent}"
    assert all(cube_box[0][i] < box[0][i] and box[1][i] < cube_box[1][i] for i in range(3)), "the asset is not inside the start-up cube"
    assert cube.hide_get(), "the start-up cube still hides the asset: Open asset left it visible around the asset"
    assert cube.name in bpy.data.objects and cube.users_collection and len(cube.data.vertices) == 8, "the cube was deleted, not hidden"
    assert not beside.hide_get() and not wall.hide_get(), "Open asset hid an object the asset is not inside"
    assert all(not o.hide_get() for o in objs.values()), "an asset object is hidden"
    assert sc.asrp_asset_hidden == "Cube", sc.asrp_asset_hidden
    cube.hide_set(False)  # the rule itself, once more: shown again, it is found again; hidden, it is not reported twice
    assert asrp_blender.asset.hide_what_encloses(bpy.context, objs) == ["Cube"] and cube.hide_get()
    assert asrp_blender.asset.hide_what_encloses(bpy.context, objs) == []
    print(f"three steps, step 1 Open asset leaves the asset visible: the asset is {extent} m, inside the 2 m start-up cube; the cube "
          f"is hidden (not deleted), 'Beside' and 'Wall' are left alone; the panel says {sc.asrp_asset_hidden!r} was hidden")
    listed = {m.file: m for m in sc.asrp_motions}
    assert set(MOTIONS) <= set(listed) and all(not listed[f].error for f in MOTIONS), [(m.file, m.error) for m in sc.asrp_motions]
    assert listed["neutral_to_AA.json"].has_landmarks and not listed["head_shake.json"].has_landmarks
    need([m.file for m in sc.asrp_motions] == list(TITLES) and [m.title for m in sc.asrp_motions] == list(TITLES.values()), "motions",
         f"the list shows {[(m.file, m.title) for m in sc.asrp_motions]}, expected the three titles in this order: {list(TITLES.values())}")
    need(sc.asrp_motions[sc.asrp_motion_index].file == "neutral_to_AA.json" and sc.asrp_motions[sc.asrp_motion_index].source_tag == "lab_setting", "motions",
         f"the motion picked by default is {sc.asrp_motions[sc.asrp_motion_index].file}, expected the lab's motion")
    # the rule, without file names: the first usable lab motion, else the first usable one
    scratch = bpy.data.scenes.new("asrp_pick_rule")
    fake = lambda f, tag, **k: dict(file=f, title=f, frames=2, fps=30, source_tag=tag, **k)  # noqa: E731
    asrp_blender.asset.fill_motions(scratch, [fake("a.json", "ours"), dict(file="b.json", error="x"), fake("c.json", "ours")])
    need(scratch.asrp_motions[scratch.asrp_motion_index].file == "a.json", "motions", "without a lab motion the first usable one is not picked")
    asrp_blender.asset.fill_motions(scratch, [dict(file="a.json", error="x"), fake("b.json", "ours"), fake("c.json", "lab_setting"), fake("d.json", "lab_setting")])
    need(scratch.asrp_motions[scratch.asrp_motion_index].file == "c.json", "motions", "the first usable lab motion is not picked")
    bpy.data.scenes.remove(scratch)
    check_material(sc)
    print(f"three steps, step 1 Open asset: {len(meshes)} mesh objects {sorted(objs)}, vertices "
          f"{ {r: len(o.data.vertices) for r, o in objs.items()} }, motions listed {[asrp_blender.asset.motion_label(m) for m in sc.asrp_motions]}")
    draw_new_panels()
    check_landmarks_units_report(sc)
    check_tet_choice(sc)
    check_setup_rows(sc, "coarse")
    done = {}
    for file, (layer, mid, movers, still) in MOTIONS.items():
        motion = json.loads((REPO / "data" / "lab_export" / "trajectories" / file).read_text(encoding="utf-8"))
        run_dir = three_steps_run(file, rest_check=file != "jaw_open_12deg.json")  # the first run's result must be gone once the second starts
        check_run_section(run_dir, motion["frames"])
        frames = [mid, 36 if motion["frames"] > 36 else motion["frames"] - 2, motion["frames"] - 1]
        case = dict(file=file, motion=motion, run_dir=run_dir, layer=layer, frames=frames, movers=movers, still=still, ident=ident)
        summary = verify_three_step(case)
        assert sc.asrp_asset_layer == layer
        report = asrp_blender.read_report(run_dir)
        rows = asrp_blender.check_rows(report)
        print(f"three steps, steps 2 and 3 with {file}: run {run_dir.name}, state {SESSION.state}, passed {SESSION.passed}, layer shown "
              f"'{layer}', frames {frames} lips vs the {layer} cache {summary['lips_mm']:.2e} mm (limit {LIPS_TOLERANCE_MM:g}), bones "
              f"{[r for r in ROLES if r != 'lips']} equal the motion file, timeline 0..{sc.frame_end} at {sc.render.fps} fps, "
              f"checks {[f'{r[0]}={r[2]}' for r in rows]}")
        done[file] = case
        check_panels_on_result(file, layer, report, rows)
        check_b_not_run(rows, SESSION.passed)
        check_landmarks_hidden_with_result(sc)
        if file == "jaw_open_12deg.json":
            check_highlight(case)
            check_check_setup(sc)
            expect_caught(case, "bones", "jaw does not move in the jaw motion", lambda: asset_now()["jaw"].animation_data_clear(),
                          names="the jaw")
            repair(case)
        elif file == "head_shake.json":
            expect_caught(case, "bones", "skull does not move in the head shake", lambda: asset_now()["skull"].animation_data_clear(),
                          names="the skull")
            repair(case)
        else:
            check_compare_section(sc, case)
            expect_caught(case, "layer", "AA shown as the physics layer", lambda c=case: asrp_blender.asset.show_layer(sc, c["run_dir"], "physics"))
            repair(case)
            expect_caught(case, "sync", "lips one frame later than the bones", lambda: setattr(
                [m for m in asset_now()["lips"].modifiers if m.type == "MESH_CACHE"][0], "frame_start", 1.0))
            repair(case)
            expect_caught(case, "identity", "result put on newly created objects", lambda c=case: recreate_objects(c["run_dir"]))
    # Open asset on top of an asset that carries a finished run (seen by hand on 2026-11-15: the new objects were called
    # "ASRP jaw.001" and step 3 still said "Complete" although the new asset had no result)
    need(SESSION.state == "complete", "reopen", f"this check needs a finished run before it; the state is {SESSION.state!r}")
    # ... and with the comparison of that run on screen (the AA run, last; its comparison exists when the Ziva data is here):
    # Ziva's lips and the difference colours belong to the old result and must go with it (review finding, 2026-11-16)
    cmp = asrp_blender.compare
    shading_before = [(k, sp.shading.type, sp.shading.color_type) for k, sp in asrp_blender.asset.view3d_spaces(bpy.context)]
    with_compare = cmp.ready(sc)
    if with_compare:
        sc.asrp_show_ziva = True
        sc.asrp_show_heat = True
        need(asrp_blender.asset.is_live(sc.asrp_ziva_object) and cmp.heat_handler in bpy.app.handlers.frame_change_post, "reopen",
             "ticking both boxes before the second Open asset showed neither Ziva's lips nor the colours: this check would prove nothing")
    assert bpy.ops.asrp.open_asset() == {"FINISHED"}
    if with_compare:
        z = sc.asrp_ziva_object
        need(not asrp_blender.asset.is_live(z) and not any(o.name.startswith("Ziva lips") for o in bpy.data.objects), "reopen",
             "after a second Open asset the old result's 'Ziva lips' object is still in the scene")
        need(cmp.heat_handler not in bpy.app.handlers.frame_change_post, "reopen", "after a second Open asset the difference-colour handler is still installed")
        need([(k, sp.shading.type, sp.shading.color_type) for k, sp in asrp_blender.asset.view3d_spaces(bpy.context)] == shading_before, "reopen",
             "after a second Open asset the 3D views still show vertex colours")
        sc.asrp_show_ziva = False
        sc.asrp_show_heat = False
        print("three steps, Open asset again with Ziva's lips and the difference colours on: both went with the old result, the views are as before")
    else:
        NOT_VERIFIED.append("Open asset again with Ziva's lips and the difference colours on: no comparison on this machine (see the compare case)")
        print("  reopen with the comparison on: NOT VERIFIED (no comparison on this machine, see the compare case)")
    names = sorted(o.name for o in bpy.data.objects if o.name.startswith(asrp_blender.asset.ASSET_PREFIX))
    need(len(names) == 6 and all("." not in n for n in names), "reopen", f"after a second Open asset the objects are called {names}")
    need(SESSION.state == "idle" and "Complete" not in " ".join(labels_of(draw_panel(asrp_blender.ASRP_PT_run))), "reopen",
         f"after a second Open asset step 3 still shows the status of the run on the asset before it (state {SESSION.state!r})")
    print(f"three steps, Open asset again over a finished run: the six objects have their plain names {names} and step 3 shows no old status")
    case_fine_choice(sc)
    # leave nothing behind
    asrp_blender.asset.remove_objects(list(asset_now().values()))
    asrp_blender.asset.remove_landmarks(sc)
    sc.asrp_asset_objects.clear()
    print("three steps passed")


MOVES_FILES = tuple(MOTIONS)


def repair(case):
    """Undo a control: the result is put on the asset again (the same function the panel's Run uses), and must pass."""
    asrp_blender.asset.apply_result(bpy.context, case["run_dir"])
    verify_three_step(case)


def recreate_objects(run_dir):
    """What a wrong implementation does: delete the five objects, build five new ones with the same names, put the result on them."""
    sc = bpy.context.scene
    old = asset_now()
    asrp_blender.asset.remove_objects(list(old.values()))
    made = asrp_blender.asset.create_objects(bpy.context, Path(sc.asrp_asset_scene))
    asrp_blender.asset.register_objects(sc, made, Path(sc.asrp_asset_scene))
    asrp_blender.asset.apply_result(bpy.context, run_dir)


def asset_log():
    """What step 1 and its closed "Asset details" draw, one after the other."""
    return draw_panel(asrp_blender.ASRP_PT_asset) + draw_panel(asrp_blender.ASRP_PT_asset_details)


def labels_of(log):
    return [r[1] for r in log if r[0] == "label"]


def check_material(sc):
    """The scene the panel imported has Ziva's measured values (read from its scene.json), and the panel says so."""
    data = json.loads(Path(sc.asrp_asset_scene).read_text(encoding="utf-8"))
    params = data["soft_tissues"][0]["material"]
    need(params["E_mpa"]["source"] == "lab_setting" and params["nu"]["source"] == "lab_setting", "material",
         f"the imported scene's material values come from {params['E_mpa']['source']!r}, not from Ziva's measured settings (lab_setting)")
    need(abs(params["E_mpa"]["value"] - 0.012) < 1e-12 and abs(params["nu"]["value"] - 0.4) < 1e-12, "material",
         f"the imported scene has E {params['E_mpa']['value']} MPa and nu {params['nu']['value']}, Ziva's are 0.012 MPa and 0.4")
    line = "Material: 12 kPa, 0.4 (measured in Ziva)"
    need(sc.asrp_asset_material == line, "material", f"the stored material line is {sc.asrp_asset_material!r}, expected {line!r}")
    need(line in " ".join(labels_of(asset_log())), "material", "the Asset section does not show the material line")


def check_run_section(run_dir, frames):
    """After a run the Run section has Play / Pause, the frame line and the run folder with Open folder. A Blender without a
    window may or may not accept the play request, so both states are drawn with a stand-in context, and the real one must agree."""
    sc = bpy.context.scene
    log = draw_panel(asrp_blender.ASRP_PT_run)
    real_playing = bool(bpy.context.screen.is_animation_playing)
    plays = [r for r in log if r[0] == "op" and r[1] == "screen.animation_play"]
    word = "Pause" if real_playing else "Play"
    need(len(plays) == 1 and plays[0][2] == word, "after-run", f"the Run section has no {word} button after a run: {[(r[1], r[2]) for r in log if r[0] == 'op']}")
    text = " ".join(labels_of(log))
    need("Complete" in labels_of(log), "after-run", f"after a run the Run section does not end in 'Complete': {labels_of(log)}")  # F6
    shown = labels_of(draw_panel(asrp_blender.ASRP_PT_checks))
    need(Path(run_dir).name.replace(" ", "") in "".join(shown).replace(" ", ""), "after-run", f"the run name is not on its own wrapped line in Checks: {shown}")  # F3
    adv = draw_panel(asrp_blender.ASRP_PT_advanced)
    need(f"Project: {asrp_blender.core_project().name}" in " ".join(labels_of(adv)) and "Change project folder" in [r[2] for r in adv if r[0] == "op"], "after-run",
         f"the Advanced section does not say which project folder is in use: {labels_of(adv)}")  # F4
    need("Run files" not in text, "after-run", "the run folder is still in step 3")  # it is in Advanced now: step 3 stays short
    atext = " ".join(labels_of(adv)).replace(" ", "")
    need(f"Run files: {asrp_blender.asset.relative_to_project(run_dir)}".replace(" ", "") in atext, "after-run", f"Advanced does not show the run folder: {atext}")
    opens = [r for r in adv if r[0] == "op" and r[1] == "wm.path_open"]
    need(len(opens) == 1 and opens[0][4].filepath == str(run_dir) and opens[0][2] == "Open folder", "after-run", "no Open folder button for the run folder")
    # G2: with an asset open and a result on it, the three steps, Run / Pause, Complete and the Results buttons fit one screen (no scrolling)
    px, everything = panel_height(), panel_height(open_all=True)
    need(everything > BUDGET_PX, "height", f"with every panel open the height is {everything:.0f} px, not above the budget {BUDGET_PX}: this check could not fail")
    need(px <= BUDGET_PX, "height", f"the panel is {px:.0f} px high down to the Results buttons, the budget is {BUDGET_PX} px (1080p window): too long, the next step is below the fold")
    print(f"  height: {px:.0f} px down to the Results buttons in the default open / closed state (budget {BUDGET_PX}; every panel open: {everything:.0f})")
    for playing, button, line in ((True, "Pause", f"Playing frame 0 to {frames - 1}. Space bar pauses."),
                                  (False, "Play", f"Frame 0 to {frames - 1} is ready. Space bar plays.")):
        fake = types.SimpleNamespace(scene=sc, screen=types.SimpleNamespace(is_animation_playing=playing), region=None)
        log2 = []
        me = types.SimpleNamespace(layout=Rec(log2))
        asrp_blender.ASRP_PT_run.draw_playback(me, fake, me.layout)
        need(any(r[0] == "op" and r[1] == "screen.animation_play" and r[2] == button for r in log2), "after-run", f"no {button} button")
        need(line in " ".join(labels_of(log2)), "after-run", f"the line {line!r} is missing: {labels_of(log2)}")


def draw_new_panels():
    for panel in (asrp_blender.ASRP_PT_asset, asrp_blender.ASRP_PT_motion, asrp_blender.ASRP_PT_run):
        log = draw_panel(panel)
        assert log, panel
    # the words and the order of the panel
    titles = {c.__name__: c.bl_label for c in asrp_blender.classes if hasattr(c, "bl_label") and c.__name__.startswith("ASRP_PT_")}
    assert [titles[n] for n in ("ASRP_PT_asset", "ASRP_PT_setup", "ASRP_PT_motion", "ASRP_PT_run", "ASRP_PT_results", "ASRP_PT_compare", "ASRP_PT_checks", "ASRP_PT_advanced")] == [
        "1  Open the asset", "Physics setup", "2  Choose a motion", "3  Run", "Results", "Compare with Ziva", "Checks", "Advanced"], titles
    order = [c.__name__ for c in asrp_blender.classes if c.__name__.startswith("ASRP_PT_") and getattr(c, "bl_parent_id", "") == "ASRP_PT_main"]
    assert order == ["ASRP_PT_asset", "ASRP_PT_setup", "ASRP_PT_motion", "ASRP_PT_run", "ASRP_PT_results", "ASRP_PT_compare", "ASRP_PT_checks",
                     "ASRP_PT_advanced"], order
    assert asrp_blender.ASRP_PT_asset_details.bl_parent_id == "ASRP_PT_asset" and asrp_blender.ASRP_PT_asset_details.bl_label == "Asset details"
    for name in ("ASRP_PT_asset_details", "ASRP_PT_setup", "ASRP_PT_compare", "ASRP_PT_checks", "ASRP_PT_advanced", "ASRP_PT_run_files"):
        assert "DEFAULT_CLOSED" in getattr(asrp_blender, name).bl_options, name
    assert asrp_blender.ASRP_PT_run_files.bl_parent_id == "ASRP_PT_advanced"
    main = draw_panel(asrp_blender.ASRP_PT_main)
    assert not [r for r in main if r[0] == "op"], "the main panel has buttons although the project is known"
    adv = [r[1] for r in draw_panel(asrp_blender.ASRP_PT_advanced) if r[0] == "op"]
    assert adv == ["asrp.choose_project", "asrp.check_backend", "asrp.load_playback", "asrp.load_run_folder"], adv
    for panel in (asrp_blender.ASRP_PT_asset, asrp_blender.ASRP_PT_motion, asrp_blender.ASRP_PT_run, asrp_blender.ASRP_PT_results):
        assert "asrp.check_backend" not in [r[1] for r in draw_panel(panel) if r[0] == "op"]
    # step 1
    texts = labels_of(asset_log())
    assert "One asset for both prototypes: skull, jaw, teeth, lips." in " ".join(texts), texts
    assert any(t.startswith("Open: ") for t in texts), texts
    scene_files = f"Scene files: {asrp_blender.asset.relative_to_project(Path(bpy.context.scene.asrp_asset_scene).parent)}"
    assert scene_files.replace(" ", "") in "".join(texts).replace(" ", ""), (scene_files, texts)  # a long path wraps over lines
    assert "This .blend is the scene. Save it to keep the asset and the last result." in " ".join(texts), texts
    opens = [r for r in asset_log() if r[0] == "op" and r[1] == "wm.path_open" and r[2] == "Open folder"]
    assert len(opens) == 1 and opens[0][2] == "Open folder" and opens[0][4].filepath == str(Path(bpy.context.scene.asrp_asset_scene).parent), opens
    # step 2: the title on the button, the details on a second, smaller line
    log = draw_panel(asrp_blender.ASRP_PT_motion)
    ops = [r for r in log if r[0] == "op"]
    assert [r[2] for r in ops] == list(TITLES.values()) and sum(1 for r in ops if r[3]) == 1 and ops[1][3], [(r[2], r[3]) for r in ops]  # the lab's motion is picked
    details = [t for t in labels_of(log)]
    assert details == ["  51 frames, 30 fps, test motion", "  47 frames, 30 fps, lab motion", "  87 frames, 30 fps, test motion"], details
    assert all(len(t) <= LABEL_MAX for t in TITLES.values()), "a motion title is longer than its button holds"
    # no internal word where a plain one exists
    import re
    shown = " ".join(labels_of(asset_log()) + details + [r[2] for r in ops])
    assert not re.search(r"\b(ours|lab_setting|ziva_default|teeth_upper|teeth_lower)\b", shown), shown
    log = asset_log()
    assert [r[1] for r in log if r[0] == "op"] == ["asrp.open_asset", "wm.path_open", "wm.path_open"]
    assert [r[1] for r in draw_panel(asrp_blender.ASRP_PT_run) if r[0] == "op"] == ["asrp.run_motion"]


def check_panels_on_result(file, layer, report, rows):
    """The Results panel offers the layers of this run; the Checks panel reads this run's report: five rows, the surface
    lines of the layer on screen (last frame and worst frame), and the note when all five pass."""
    results = draw_panel(asrp_blender.ASRP_PT_results)
    layers = [r[2] for r in results if r[0] == "op" and r[1] == "asrp.set_layer"]
    assert layers == (["Physics only", "Final shape"] if layer == "final" else ["Physics only"]), layers
    pressed = [r[2] for r in results if r[0] == "op" and r[1] == "asrp.set_layer" and r[3]]
    assert pressed == [asrp_blender.asset.LAYER_WORDS[layer]], pressed
    texts = " ".join(r[1] for r in draw_panel(asrp_blender.ASRP_PT_checks) if r[0] == "label")
    for label in ("(a) Motion completed", "(b) Hard attachments", "(b2) Spring anchors", "(c) Gravity sag",
                  "(d) Tet mesh valid"):
        assert label in texts, (label, texts)
    assert f"Surface ({layer}):" in texts and f"Worst frame ({layer}):" in texts, texts
    note = "does not say the surface is fine" in texts
    assert note == asrp_blender.all_passed(rows), (note, [r[2] for r in rows])
    print(f"  panels for {file}: Results offers {layers}, Checks shows the five rows, 'Surface ({layer})' and 'Worst frame ({layer})' lines, "
          f"all-pass note {'shown' if note else 'not shown (a check did not pass)'}")


# --- round 2, part B: the tet mesh choice and Compare with Ziva ------------------------------------------------------------------

NOT_VERIFIED: list = []  # checks that could not run on this machine: printed at the end, never counted as passed


def tet_file_facts(name):
    t = json.loads((REPO / "data" / "tetmesh" / name).read_text(encoding="utf-8"))
    return len(t["tets"]), t.get("kind") or "fine", t.get("content_sha256")


def check_tet_choice(sc):
    """B1: the radio buttons, the line under them (the counts are the tet mesh files'), the message after a change, and what the
    imported scene really has."""
    coarse, fine = tet_file_facts("lips_lattice.json"), tet_file_facts("lips.json")
    need(coarse[:2] == (126, "lattice") and fine[:2] == (26721, "fine"), "tet-choice", f"the tet mesh files are {coarse[:2]} and {fine[:2]}")
    log = asset_log()
    props = [r for r in log if r[0] == "prop" and r[1] == "asrp_tet_choice"]
    need(len(props) == 1 and sc.asrp_tet_choice == "coarse" and sc.asrp_asset_tet == "coarse", "tet-choice", "no tet mesh choice on the panel, or it is not Coarse by default")
    items = {i.identifier: i.name for i in sc.bl_rna.properties["asrp_tet_choice"].enum_items}
    need(items == {"coarse": "Coarse lattice (Ziva's tet size)", "fine": "Fine (lips move separately)"}, "tet-choice", f"the choices are {items}")
    lines = {"coarse": f"{coarse[0]:,} tets. Moves the lips as one body, like Ziva. About 1 s per run.",
             "fine": f"{fine[0]:,} tets. Upper and lower lip move separately. About 30 s per run."}
    need(lines["coarse"].replace(" ", "") in " ".join(labels_of(log)).replace(" ", ""), "tet-choice", f"the coarse line is missing: {labels_of(log)}")
    uid = {r: o.session_uid for r, o in asset_now().items()}
    scene_before = sc.asrp_asset_scene
    sc.asrp_tet_choice = "fine"
    log = asset_log()
    text = " ".join(labels_of(log)).replace(" ", "")
    need(lines["fine"].replace(" ", "") in text and lines["coarse"].replace(" ", "") not in text, "tet-choice", "the line under the choice does not change with it")
    need("Press Open asset again to use this mesh.".replace(" ", "") in text, "tet-choice", "no message after changing the choice of an open asset")
    need(sc.asrp_asset_scene == scene_before and {r: o.session_uid for r, o in asset_now().items()} == uid, "tet-choice", "changing the choice changed the open asset")
    need("lattice" in " ".join(labels_of(draw_panel(asrp_blender.ASRP_PT_setup))), "tet-choice", "the Physics setup does not show the mesh the open asset has")
    sc.asrp_tet_choice = "coarse"
    need("Press Open asset again" not in " ".join(labels_of(asset_log())), "tet-choice", "the message stays after the choice is back")
    # the scene the panel imported: the lattice, all four attachments springs
    data = scene_data(sc)
    tet = data["soft_tissues"][0]["tet_mesh"]
    need(tet["content_sha256"] == coarse[2], "tet-choice", "the imported scene's tet mesh is not the lattice file")
    kinds = [a["kind"] for a in data["attachments"]]
    need(kinds == ["spring"] * 4, "tet-choice", f"the attachments of the coarse import are {kinds}, expected four springs")
    print(f"  tet choice: Coarse by default; the line says {lines['coarse']!r} / {lines['fine']!r} (counts from the files); a change after Open asset "
          f"leaves the asset alone and says to press Open asset again; the coarse import has the lattice ({coarse[0]} tets) and {kinds}")


def check_b_not_run(rows, passed):
    """With the lattice, check (b) is NOT RUN by design: the panel shows it as not run, not as failed, and it is no failure."""
    verdicts = {r[0]: r[2] for r in rows}
    need(verdicts["b"] == "NOT RUN" and "FAIL" not in verdicts.values() and passed is True, "not-run", f"check b is {verdicts['b']}, run passed {passed}, verdicts {verdicts}")
    log = draw_panel(asrp_blender.ASRP_PT_checks)
    labels = labels_of(log)
    need("NOT RUN" in labels and "FAIL" not in labels, "not-run", f"the Checks section shows {labels}")
    need(not [r for r in labels_of(draw_panel(asrp_blender.ASRP_PT_run)) if "plausibility check failed" in r], "not-run", "the Run section says a check failed")
    need(not any(r[0] == "label" and r[2] and "(b)" in r[1] for r in log), "not-run", "the NOT RUN check is drawn as a failure")


def case_fine_choice(sc):
    """With "Fine" the scene is what it was before (the fine tet mesh, a hard upper-lip attachment and springs) and a motion runs."""
    sc.asrp_tet_choice = "fine"
    try:
        assert bpy.ops.asrp.open_asset() == {"FINISHED"}
        need(sc.asrp_asset_tet == "fine", "tet-choice", "the open asset does not know it was imported with Fine")
        data = scene_data(sc)
        need(data["soft_tissues"][0]["tet_mesh"]["content_sha256"] == tet_file_facts("lips.json")[2], "tet-choice", "Fine did not import the fine tet mesh")
        need([a["kind"] for a in data["attachments"]] == ["hard", "spring", "spring", "spring"], "tet-choice", "Fine did not import our attachments")
        check_setup_rows(sc, "fine")
        ident = snapshot(asset_now())
        run_dir = three_steps_run("jaw_open_12deg.json")
        file = "jaw_open_12deg.json"
        layer, mid, movers, still = MOTIONS[file]
        motion = json.loads((REPO / "data" / "lab_export" / "trajectories" / file).read_text(encoding="utf-8"))
        verify_three_step(dict(file=file, motion=motion, run_dir=run_dir, layer=layer, frames=[mid, 36, 50], movers=movers, still=still, ident=ident))
        print(f"  Fine: the imported scene is the fine mesh with attachments hard / spring / spring / spring; jaw_open_12deg ran from the panel and "
              f"matches its cache (run {Path(run_dir).name})")
    finally:
        sc.asrp_tet_choice = "coarse"


def drive_compare(limit=900):
    t0 = time.monotonic()
    while True:
        again = asrp_blender.compare_tick()
        if again is None:
            return
        assert time.monotonic() - t0 < limit, f"the comparison did not end in {limit} s: {list(asrp_blender.compare.SESSION.lines)[-5:]}"
        time.sleep(0.2)


def read_f32(path):
    import array

    data = array.array("f")
    with open(path, "rb") as f:
        data.fromfile(f, os.path.getsize(path) // 4)
    return data


def check_compare_section(sc, case):
    """B2. Part one needs no outside data (the button, a wrong folder, plain-words errors). Part two runs `asrp compare` on the AA run
    against the lab's Ziva export (found through tools/local_paths.py) and checks the report's numbers, Ziva's lips, the colours."""
    cmp = asrp_blender.compare
    asrp_blender.set_ziva_preference("")
    log = draw_panel(asrp_blender.ASRP_PT_compare)
    button = [r for r in log if r[0] == "op" and r[1] == "asrp.compare"]
    need(len(button) == 1 and button[0][2] == "Compare" and not button[0][5], "compare", "Compare is enabled with no Ziva folder")
    need([r[1] for r in log if r[0] == "op"] == ["asrp.choose_ziva", "asrp.compare"] and "Ziva reference folder" in [r[2] for r in log if r[0] == "op"], "compare", "buttons")
    need("DEFAULT_CLOSED" in asrp_blender.ASRP_PT_compare.bl_options, "compare", "the section is open by default")
    need([c.__name__ for c in asrp_blender.classes if getattr(c, "bl_parent_id", "") == "ASRP_PT_main"].index("ASRP_PT_compare") ==
         [c.__name__ for c in asrp_blender.classes if getattr(c, "bl_parent_id", "") == "ASRP_PT_main"].index("ASRP_PT_results") + 1, "compare", "not right after Results")
    try:
        bpy.ops.asrp.compare()
        raise AssertionError("Compare did not refuse without a folder")
    except RuntimeError as exc:
        need("Choose the Ziva reference folder" in str(exc), "compare", str(exc))
    wrong = tmp / "not_a_ziva_folder"
    wrong.mkdir(exist_ok=True)
    asrp_blender.set_ziva_preference(str(wrong))
    log = draw_panel(asrp_blender.ASRP_PT_compare)
    need([r for r in log if r[1] == "asrp.compare"][0][5], "compare", "Compare is greyed out although a result and a folder are there")
    assert bpy.ops.asrp.compare() == {"FINISHED"}
    drive_compare()
    need(cmp.SESSION.state == "failed" and cmp.SESSION.error and "Traceback" not in cmp.SESSION.error, "compare", f"a wrong folder: {cmp.SESSION.state} {cmp.SESSION.error!r}")
    text = " ".join(labels_of(draw_panel(asrp_blender.ASRP_PT_compare)))
    need("The comparison failed:" in text and not cmp.ready(sc), "compare", f"the error is not shown in words: {text}")
    wrong_error = cmp.SESSION.error
    # part two: the lab's data
    import local_paths

    trip = local_paths.ziva_trip()
    folders = sorted((trip / "ziva_reference").glob("neutral_to_AA_export_*")) if trip is not None else []
    if not folders:
        NOT_VERIFIED.append("Compare with Ziva on the real AA export (numbers, Ziva's lips, difference colours): " + local_paths.HOW_TO_SET)
        print("  compare: part one done (button, wrong folder -> plain error). NOT VERIFIED, not counted as passed: the Ziva data is not on this machine; "
              + local_paths.HOW_TO_SET)
        asrp_blender.set_ziva_preference("")
        return
    asrp_blender.set_ziva_preference(str(folders[0]))
    cmp.SESSION.reset()
    assert bpy.ops.asrp.compare() == {"FINISHED"}
    drive_compare()
    need(cmp.SESSION.state == "done", "compare", f"the comparison ended {cmp.SESSION.state}: {cmp.SESSION.error} {list(cmp.SESSION.lines)[-4:]}")
    out = Path(sc.asrp_asset_run) / "compare"
    report = json.loads((out / "compare_report.json").read_text(encoding="utf-8"))
    need((out / "heatmap.json").is_file() and (out / "ziva_playback" / "playback.json").is_file(), "compare", "the comparison wrote no heat map or Ziva package")
    last = report["frames"]["last"]
    need(last == 46 and report["layers"]["final"].get("available") is not False, "compare", "the report has no numbers for the final layer: this check would prove nothing")
    for layer in ("final", "physics"):
        assert bpy.ops.asrp.set_layer(layer=layer) == {"FINISHED"}
        block = report["layers"][layer]
        text = " ".join(labels_of(draw_panel(asrp_blender.ASRP_PT_compare))).replace(" ", "")
        need(f"{asrp_blender.asset.LAYER_WORDS[layer]}, frame {last}:".replace(" ", "") in text, "compare", f"the section does not name the layer on display ({layer}): {text}")
        for want in (f"mean {block['mean_mm'][last]:.2f} mm, 95% {block['p95_mm'][last]:.2f} mm, max {block['max_mm'][last]:.2f} mm",
                     f"Worst frame: {block['worst']['mean_mm']['frame']} (mean {block['worst']['mean_mm']['value']:.2f} mm)",
                     "Reported only. There is no pass line."):
            need(want.replace(" ", "") in text, "compare", f"the section does not say {want!r} for the {layer} layer: {text}")
    assert bpy.ops.asrp.set_layer(layer="final") == {"FINISHED"}
    # Ziva's lips
    sc.asrp_show_ziva = True
    z = sc.asrp_ziva_object
    need(asrp_blender.asset.is_live(z) and z.name == "Ziva lips" and not z.hide_viewport and z.get(asrp_blender.asset.ROLE_KEY) == "ziva_lips", "ziva-lips", "no 'Ziva lips' object")
    mod = [m for m in z.modifiers if m.type == "MESH_CACHE"][0]
    need(mod.filepath.endswith("playback_final.pc2"), "ziva-lips", f"Ziva's lips do not follow the final layer: {mod.filepath}")
    for layer, pc2 in (("final", "playback_final.pc2"), ("physics", "playback.pc2")):
        assert bpy.ops.asrp.set_layer(layer=layer) == {"FINISHED"}
        sc.frame_set(25)
        bpy.context.view_layer.update()
        cache = read_pc2(out / "ziva_playback" / pc2)
        diff = max_diff(lips_local_mm(z), frame_of(cache, 25))
        need(diff < LIPS_TOLERANCE_MM and mod.filepath.endswith(pc2), "ziva-lips", f"Ziva's lips at frame 25 differ from {pc2} by {diff:.3g} mm")
    other = max_diff(frame_of(read_pc2(out / "ziva_playback" / "playback.pc2"), 25), frame_of(read_pc2(out / "ziva_playback" / "playback_final.pc2"), 25))
    need(other > 0.05, "ziva-lips", "the two Ziva caches are the same at frame 25: this check could not tell the layers apart")
    assert bpy.ops.asrp.set_layer(layer="final") == {"FINISHED"}
    sc.asrp_show_ziva = False
    need(z.hide_viewport and z.hide_render, "ziva-lips", "unticking Show Ziva's lips did not hide it")
    # the difference colours
    lips = asset_now()["lips"]
    attrs_before = [a.name for a in lips.data.color_attributes]
    spaces = list(asrp_blender.asset.view3d_spaces(bpy.context))
    shading_before = [(k, sp.shading.type, sp.shading.color_type) for k, sp in spaces]
    need(spaces, "heat", "no 3D view in this Blender")
    sc.asrp_show_heat = True
    need(cmp.heat_handler in bpy.app.handlers.frame_change_post, "heat", "no frame-change handler while the box is ticked")
    header = json.loads((out / "heatmap.json").read_text(encoding="utf-8"))
    values = read_f32(out / header["layers"]["final"]["file"])
    n = header["vertex_count"]
    need(len(values) == n * header["frames"] and n == len(lips.data.vertices), "heat", "the heat map does not fit the lips")
    seen = {}
    for frame in (25, 40):
        sc.frame_set(frame)
        block = values[frame * n:(frame + 1) * n]
        peak = max(range(n), key=lambda v: block[v])
        need(block[peak] > 1.0 and min(block) < block[peak], "heat", f"frame {frame}: the heat map is flat ({min(block)}..{block[peak]}): this check would prove nothing")
        col = colour_of_attr(lips.data, cmp.HEAT_ATTR)
        for v in (peak, 0, n // 2, n - 1, min(range(n), key=lambda v: block[v])):
            t = min(block[v] / 5.0, 1.0)
            got = col[4 * v:4 * v + 4]
            need(max(abs(got[0] - t), abs(got[1]), abs(got[2] - (1 - t)), abs(got[3] - 1)) < 1e-5, "heat",
                 f"frame {frame} vertex {v}: the colour is {tuple(got)}, the value {block[v]:.3f} mm should give ({t:.3f}, 0, {1 - t:.3f}, 1)")
        seen[frame] = tuple(col[4 * peak:4 * peak + 3])
    need(seen[25] != seen[40], "heat", "the colours did not change with the frame")
    need(SCALE_LINE in labels_of(draw_panel(asrp_blender.ASRP_PT_compare)), "heat", "the scale line is missing")
    sc.asrp_show_heat = False
    need(cmp.heat_handler not in bpy.app.handlers.frame_change_post, "heat", "the frame-change handler stays after unticking")
    need([a.name for a in lips.data.color_attributes] == attrs_before, "heat", "the colour attribute stays after unticking")
    need([(k, sp.shading.type, sp.shading.color_type) for k, sp in asrp_blender.asset.view3d_spaces(bpy.context)] == shading_before, "heat", "the views are not as they were")
    verify_three_step(case)  # the result on the asset is as it was
    print(f"  compare: a wrong folder -> {wrong_error[:60]!r} shown in the section; on the real AA export the report was written and the section's numbers equal it "
          f"(final: last frame mean {report['layers']['final']['mean_mm'][last]:.2f} mm; physics: {report['layers']['physics']['mean_mm'][last]:.2f} mm); "
          f"Ziva lips equal playback_final.pc2 / playback.pc2 at frame 25; the colours of 5 vertices at 2 frames equal the .f32 values on the 0 to 5 mm scale; "
          f"unticking removes the handler and restores the attributes and the views")
    asrp_blender.set_ziva_preference("")


SCALE_LINE = "Blue 0 mm, red 5 mm or more"


def colour_of_attr(mesh, name):
    import array

    co = array.array("f", bytes(4 * 4 * len(mesh.vertices)))
    mesh.color_attributes[name].data.foreach_get("color", co)
    return co


# --- finding the project: the order, and the add-on installed outside the repo ---------------------------------------------------


def fake_project(folder: Path) -> Path:
    (folder / "src" / "asrp_core").mkdir(parents=True)
    (folder / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8", newline="\n")
    return folder


def case_project_order(tmp):
    """core_project(): $ASRP_PROJECT, then the folder chosen in the preference, then the repo the add-on lives in. A chosen folder
    that is not a project is ignored; paths in the panel are relative to the project folder."""
    mine, other = fake_project(tmp / "proj_a"), fake_project(tmp / "proj_b")
    (tmp / "not_a_project").mkdir()
    env = os.environ.pop("ASRP_PROJECT", None)
    try:
        assert asrp_blender.core_project() == REPO, "with nothing set the repo the add-on lives in is the project"
        asrp_blender.set_project_preference(str(mine))
        assert asrp_blender.core_project() == mine, "the preference does not come before the repo"
        asrp_blender.set_project_preference(str(tmp / "not_a_project"))
        assert asrp_blender.core_project() == REPO, "a chosen folder that is not a project was used"
        asrp_blender.set_project_preference(str(mine))
        os.environ["ASRP_PROJECT"] = str(other)
        assert asrp_blender.core_project() == other, "$ASRP_PROJECT does not come before the preference"
    finally:
        del os.environ["ASRP_PROJECT"]
        if env is not None:
            os.environ["ASRP_PROJECT"] = env
        asrp_blender.set_project_preference("")
    assert asrp_blender.core_project() == REPO
    rel = asrp_blender.asset.relative_to_project
    assert rel(REPO / "runs" / "_asset" / "20261115-101010-123456") == "runs/_asset/20261115-101010-123456"
    assert rel(tmp) == tmp.as_posix(), "a folder outside the project is shown whole"
    assert asrp_blender.project_problem(tmp / "not_a_project") and asrp_blender.project_problem(REPO) is None
    # the chooser: a wrong folder is refused in plain words and stores nothing; a right one is stored and saved
    saved = []
    real = asrp_blender.save_preferences
    asrp_blender.save_preferences = lambda: saved.append(1) or True
    try:
        try:
            bpy.ops.asrp.choose_project(directory=str(tmp / "not_a_project"))
            raise AssertionError("a folder that is not a project was accepted")
        except RuntimeError as exc:
            assert "pyproject.toml" in str(exc) and "src/asrp_core" in str(exc), exc
        assert not saved and asrp_blender.preference_project() == ""
        assert bpy.ops.asrp.choose_project(directory=str(mine) + os.sep) == {"FINISHED"}
        assert saved == [1] and Path(asrp_blender.preference_project()) == mine and asrp_blender.core_project() == mine
    finally:
        asrp_blender.save_preferences = real
        asrp_blender.set_project_preference("")
    print("case 11 finding the project: environment variable, then the chosen folder, then the repo; a folder that is not a project is "
          "refused with a plain sentence and ignored; a chosen one is stored and the preferences saved; paths relative to the project")


CHILD_MARK = "--installed-child"


def blender_exe() -> str:
    return bpy.app.binary_path


def isolated(profile: Path, **extra) -> dict:
    """The environment of a child Blender: its own profile (never the real one), and no ASRP_PROJECT."""
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(profile), **{k: str(v) for k, v in extra.items()}}
    env.pop("ASRP_PROJECT", None)
    return env


def case_installed_copy(tmp):
    """The add-on built and installed the way the README says (into an isolated profile), loaded from outside the repo, started
    three times: (a) no project known -> the panel says "choose the project folder", the steps are greyed out, nothing raises
    in a way the researcher cannot read; the folder is chosen with the operator, Open asset works; (b) a second start: the add-on
    is still enabled and the folder is still chosen (the tick does not go away, the choice survives a restart)."""
    profile, dist = tmp / "profile", tmp / "dist"
    profile.mkdir()
    dist.mkdir()
    exe = blender_exe()
    done = subprocess.run([exe, "--factory-startup", "--command", "extension", "build", "--source-dir", str(REPO / "blender_addon" / "asrp_blender"),
                           "--output-dir", str(dist)], capture_output=True, text=True, env=isolated(profile))
    zips = sorted(dist.glob("asrp_blender-*.zip"))
    assert done.returncode == 0 and len(zips) == 1, (done.returncode, done.stdout[-300:], done.stderr[-300:])
    done = subprocess.run([exe, "--command", "extension", "install-file", "-r", "user_default", "-e", str(zips[0])],
                          capture_output=True, text=True, env=isolated(profile))
    assert done.returncode == 0 and "Installed" in done.stdout, (done.returncode, done.stdout[-300:], done.stderr[-300:])
    out = []
    for phase in ("a", "b"):
        done = subprocess.run([exe, "--background", "--python-exit-code", "1", "--python", str(THIS), "--", CHILD_MARK, phase, str(REPO), str(tmp)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=isolated(profile, ASRP_RUNS_DIR=tmp / "child_runs"),
                              timeout=TIMEOUT_S)
        lines = [x for x in done.stdout.splitlines() if x.startswith("CHILD ")]
        assert done.returncode == 0 and lines, f"the installed-copy check, phase {phase}, failed (exit {done.returncode}):\n{done.stdout[-3000:]}\n{done.stderr[-1500:]}"
        out += lines
    print("case 12 add-on installed in an isolated profile, loaded from outside the repo, no ASRP_PROJECT:\n  " + "\n  ".join(x[6:] for x in out))


def run_child(phase: str, repo: Path, tmp: Path) -> None:
    """Inside the child Blender: the add-on is the installed copy (bl_ext...), not the repo's."""
    import importlib

    if phase in ("save", "reopen", "missing"):
        return blend_child(phase, repo, tmp)
    assert os.environ.get("BLENDER_USER_RESOURCES") and "ASRP_PROJECT" not in os.environ, "the child does not run in an isolated profile"
    assert Path(os.environ["BLENDER_USER_RESOURCES"]).resolve() == (tmp / "profile").resolve()
    ab = importlib.import_module("bl_ext.user_default.asrp_blender")
    where = Path(ab.__file__).resolve()
    assert repo.resolve() not in where.parents, f"the add-on was loaded from the repo: {where}"
    enabled = [a.module for a in bpy.context.preferences.addons]
    assert "bl_ext.user_default.asrp_blender" in enabled and hasattr(bpy.types, "ASRP_PT_main"), f"the add-on is not enabled: {enabled}"
    prefs = ab.preferences()
    assert prefs is not None
    if phase == "a":
        assert prefs.project_dir == "" and ab.core_project() is None, (prefs.project_dir, ab.core_project())
        main = draw_panel(ab.ASRP_PT_main)
        mtext = " ".join(labels_of(main))
        assert "Choose the ASRP project folder." in labels_of(main) and "Asked once. Blender remembers." in labels_of(main), main
        assert mtext.count("stay grey") == 1, mtext  # the note is written once, under the chooser
        assert [r[1] for r in main if r[0] == "op"] == ["asrp.choose_project"], main
        line = " ".join(labels_of(draw_panel(ab.ASRP_PT_asset)))
        assert "Moves the lips as one body" in line and "?" not in line and "tets." not in line, line  # no count that is not known
        for panel in (ab.ASRP_PT_asset, ab.ASRP_PT_motion, ab.ASRP_PT_run):  # steps 1 to 3 greyed out, with the reason
            log = draw_panel(panel)
            assert "Choose the project folder first" not in " ".join(labels_of(log)), (panel.bl_label, log)  # no note on every step
            assert all(not r[5] for r in log if r[0] == "op"), f"{panel.bl_label}: a button is enabled while no project is known"
        for name in ("open_asset", "run_motion"):  # pressed anyway (from a script): a plain sentence, not the old one
            try:
                getattr(bpy.ops.asrp, name)()
                raise AssertionError(f"{name} did not refuse")
            except RuntimeError as exc:
                text = str(exc)
                assert "set ASRP_PROJECT" not in text and (name != "open_asset" or "Choose project folder" in text), text
        bad = tmp / "not_a_project"
        bad.mkdir(exist_ok=True)
        try:
            bpy.ops.asrp.choose_project(directory=str(bad))
            raise AssertionError("a folder that is not a project was accepted")
        except RuntimeError as exc:
            assert "pyproject.toml" in str(exc) and "src/asrp_core" in str(exc), exc
        assert prefs.project_dir == ""
        assert bpy.ops.asrp.choose_project(directory=str(repo)) == {"FINISHED"}
        assert Path(prefs.project_dir).resolve() == repo.resolve() and ab.core_project().resolve() == repo.resolve()
        assert not [r for r in draw_panel(ab.ASRP_PT_main) if r[0] == "label" and "Choose the ASRP" in r[1]]
        assert bpy.ops.asrp.open_asset() == {"FINISHED"}
        sc = bpy.context.scene
        assert len(sc.asrp_asset_objects) == 5 and [m.file for m in sc.asrp_motions] == list(TITLES), [m.file for m in sc.asrp_motions]
        print(f"CHILD phase a: loaded from {where.parent.name} outside the repo; no project -> 'Choose the ASRP project folder.' once, steps 1 to 3 "
              f"greyed out, open_asset refused in plain words; a wrong folder refused; the right one chosen; Open asset made "
              f"{len(sc.asrp_asset_objects)} objects, motions {[m.title for m in sc.asrp_motions]}, {sc.asrp_asset_material!r}")
    else:
        assert Path(prefs.project_dir).resolve() == repo.resolve(), f"the chosen folder did not survive the restart: {prefs.project_dir!r}"
        assert ab.core_project().resolve() == repo.resolve()
        assert not [r for r in draw_panel(ab.ASRP_PT_main) if r[0] == "label"]
        print(f"CHILD phase b: after a restart the add-on is still enabled ({len(enabled)} add-ons on) and the project folder is still {Path(prefs.project_dir).name!r}")


# --- round 2: landmarks, units, report, physics setup, highlight --------------------------------------------------------------


def scene_data(sc):
    return json.loads(Path(sc.asrp_asset_scene).read_text(encoding="utf-8"))


def check_landmarks_units_report(sc):
    """R-01: the sixth object, the units line, the import report lines. The numbers are read from the scene folder's files here, not
    taken from the add-on."""
    data = scene_data(sc)
    rest = data["landmarks"]["rest_positions_mm"]
    lm = sc.asrp_asset_landmarks
    need(asrp_blender.asset.is_live(lm) and lm.get(asrp_blender.asset.ROLE_KEY) == "landmarks", "landmarks", "Open asset made no landmarks object")
    need("landmarks" not in asset_now() and len(asset_now()) == 5, "landmarks", "the landmarks object counts as one of the five")
    need(len(rest) == 300, "landmarks", f"the scene has {len(rest)} landmarks, expected 300 (a check that sees nothing proves nothing)")
    verts = lm.data.vertices
    per = len(verts) // len(rest)
    need(len(verts) == per * len(rest) and per >= 4, "landmarks", f"the landmarks object has {len(verts)} vertices for {len(rest)} landmarks")
    worst = 0.0
    for i, p in enumerate(rest):
        centre = [sum(verts[i * per + k].co[a] for k in range(per)) / per for a in range(3)]
        worst = max(worst, max(abs(centre[a] - p[a]) for a in range(3)))
    need(worst < 1e-5, "landmarks", f"a landmark dot is {worst:.3g} mm from its rest position in scene.json")
    size = max(max(v.co[a] for v in verts[:per]) - min(v.co[a] for v in verts[:per]) for a in range(3))
    need(size >= 1.0, "landmarks", f"a landmark dot is {size:.3g} mm across: too small to see at the head's size")
    need(abs(lm.scale[0] - 0.001) < 1e-9 and not lm.hide_viewport and not lm.hide_render, "landmarks", "the dots are not shown at rest")
    log = asset_log()
    props = [r for r in log if r[0] == "prop" and r[1] == "asrp_show_landmarks"]
    need(len(props) == 1 and props[0][2] == "Show landmarks" and sc.asrp_show_landmarks, "landmarks", "no Show landmarks checkbox, or it is not on by default")
    sc.asrp_show_landmarks = False
    need(lm.hide_viewport, "landmarks", "Show landmarks off does not hide the dots")
    sc.asrp_show_landmarks = True
    need(not lm.hide_viewport, "landmarks", "Show landmarks on does not show the dots")
    # units
    mm = data["units"]["mm_per_scene_unit"]["value"]
    text = " ".join(labels_of(log))
    need(f"Units: mm (1 scene unit = {mm:g} mm)" in text and mm == 0.962, "units", f"the Asset section does not say 'Units: mm (1 scene unit = 0.962 mm)': {text}")
    # the import report
    report = json.loads((Path(sc.asrp_asset_scene).parent / "import_report.json").read_text(encoding="utf-8"))
    lips = next(m for m in report["meshes"] if m["role"] == "soft tissue")
    need(lips["vertices"] == len(asset_now()["lips"].data.vertices) == 10240, "report", "the report's lip vertex count is not the lips object's")
    for line in (f"Imported: {len(report['meshes'])} meshes, {report['landmarks']} landmarks", f"Lips: {lips['vertices']} vertices",
                 f"Problems found: {len(report['check']['errors'])} errors, {len(report['check']['warnings'])} warnings"):
        need(line.replace(" ", "") in text.replace(" ", ""), "report", f"the Asset section does not say {line!r}: {text}")
    need("Problems found: 0 errors, 0 warnings" in text and report["landmarks"] == 300 and len(report["meshes"]) == 5, "report", "the report is not the expected one")
    opens = [r for r in log if r[0] == "op" and r[1] == "wm.path_open" and r[2] == "Open import report"]
    need(len(opens) == 1 and opens[0][4].filepath.endswith("import_report.json") and Path(opens[0][4].filepath).is_file(), "report",
         "no Open import report button for an existing file")
    need("Landmarks show the rest positions" not in text, "landmarks", "the hidden-while-a-result-plays line is shown with no result on the asset")
    print(f"  landmarks: {len(rest)} dots of {per} vertices ({size:.2f} mm across) centred on the rest positions in scene.json (worst {worst:.1e} mm), "
          f"Show landmarks on by default, units and report lines drawn")


def check_landmarks_hidden_with_result(sc):
    lm = sc.asrp_asset_landmarks
    need(sc.asrp_asset_run and lm.hide_viewport and lm.hide_render, "landmarks", "the landmark dots are still shown while a result is on the asset")
    text = " ".join(labels_of(asset_log()))
    need("Landmarks show the rest positions; hidden while a result plays." in text, "landmarks", f"the panel does not say why the dots are hidden: {text}")
    sc.asrp_show_landmarks = True
    need(lm.hide_viewport, "landmarks", "Show landmarks showed the dots over a result")


EXPECT_SETUP = {  # what the Physics setup says about the lab asset (read off the card by hand, not from the add-on)
    "tissues": ["lips: 26721 tets, fine mesh"],
    "material": "neo-Hookean: 12 kPa, nu 0.4, 1060 kg/m3 (measured in Ziva)",
    "bones": ["jaw: follows jaw01", "skull: follows head", "teeth_upper: display only (follows head)", "teeth_lower: display only (follows jaw01)"],
    "attachments": ["lips to skull: 74 vertices, hard", "lips to jaw: 76 vertices, spring 1.94 N/mm (our value)",
                    "lips to lip_corner_anchor (left): 348 vertices, spring 1.94 N/mm (our value)",
                    "lips to lip_corner_anchor (right): 309 vertices, spring 1.94 N/mm (our value)"],
}


def expected_setup(data, choice):
    """The sentences the Physics setup must say for the lab asset: Fine from the card (EXPECT_SETUP), Coarse from the numbers in the
    imported scene.json (the soft attachments' stiffness is computed by the import, so it is read from the file)."""
    if choice == "fine":
        return EXPECT_SETUP
    n = tet_file_facts("lips_lattice.json")[0]
    atts = []
    pairs = [(a["from"], a["to"]) for a in data["attachments"]]
    for a in data["attachments"]:
        k = a["stiffness"]
        side = f" ({a['name'].split('_')[0]})" if pairs.count((a["from"], a["to"])) > 1 else ""  # left / right, from the attachment's own name
        atts.append(f"{a['from']} to {a['to']}{side}: {len(a['weights'])} vertices, spring {k['value']:g} N/mm (Ziva's stiffness, our area rule)")
        need("measured" not in atts[-1], "setup", "an attachment's stiffness is called measured")
    return dict(EXPECT_SETUP, tissues=[f"lips: {n} tets, lattice mesh"], attachments=atts)


def check_setup_rows(sc, choice="coarse"):
    """R-02: the Physics setup rows, one button each, the sentences read from scene.json; the last line of the section."""
    data = scene_data(sc)
    expect = expected_setup(data, choice)
    tet = json.loads((Path(sc.asrp_asset_scene).parent / data["soft_tissues"][0]["tet_mesh"]["path"]).read_text(encoding="utf-8"))
    need(len(tet["tets"]) == (126 if choice == "coarse" else 26721) and tet.get("kind", "fine") == ("lattice" if choice == "coarse" else "fine"), "setup",
         f"the lips tet mesh has {len(tet['tets'])} tets and kind {tet.get('kind')!r}")
    need(asrp_blender.asset.read_tet_summary(REPO / "data" / "tetmesh" / "lips_lattice.json") == (126, "lattice"), "setup", "a lattice tet mesh is not reported as lattice")
    log = draw_panel(asrp_blender.ASRP_PT_setup)
    text = " ".join(labels_of(log)).replace(" ", "")
    for key in ("tissues", "bones", "attachments"):
        for line in expect[key]:
            need(line.replace(" ", "") in text, "setup", f"the Physics setup does not say {line!r}: {labels_of(log)}")
    need(expect["material"].replace(" ", "") in text, "setup", f"the material row is missing: {labels_of(log)}")
    ops = [r for r in log if r[0] == "op" and r[1] == "asrp.highlight"]
    need([(r[4].kind, r[4].target) for r in ops] == [("part", "lips")] + [("part", b) for b in ("jaw", "skull", "teeth_upper", "teeth_lower")] +
         [("attachment", a["name"]) for a in data["attachments"]], "setup", f"the highlight buttons are {[(r[4].kind, r[4].target) for r in ops]}")
    need(all(r[2] == "" for r in ops), "setup", "a highlight button has text (it should be a small icon button)")
    need("Read-only in this version. Marking meshes as bone or tissue in Blender comes later.".replace(" ", "") in text, "setup", "the last line is missing")
    need([r[1] for r in log if r[0] == "op" and r[1] != "asrp.highlight"] == ["asrp.clear_highlight", "asrp.check_setup"], "setup", "wrong buttons")
    need(not [r for r in log if r[1] == "asrp.clear_highlight"][0][5], "setup", "Clear highlight is enabled with nothing highlighted")
    print(f"  physics setup: {len(ops)} rows with a button each, tissue / bones / attachments say what scene.json says, last line present")


def evaluated_points(obj):
    """The point cloud a geometry-nodes object makes: (number of points, flat float list of their positions in the object's own mm)."""
    import array

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)  # kept: the point cloud is owned by the evaluated object and the geometry set
    geometry = ev.evaluated_geometry()
    pc = geometry.pointcloud
    n = 0 if pc is None else len(pc.points)
    co = array.array("f", bytes(4 * 3 * n))
    if n:
        pc.attributes["position"].data.foreach_get("vector", co)
    return n, co


def check_highlight(case):
    """Highlight a part and an attachment while a result is on the asset. The attachment is shown as points in front of the lips, on the
    same vertices (they follow the result); the lips' own display (colour attributes, shading) and the result are not touched; Clear
    highlight removes the points."""
    sc = bpy.context.scene
    objs = asset_now()
    lips = objs["lips"]
    attrs = [a.name for a in lips.data.color_attributes]
    spaces = list(asrp_blender.asset.view3d_spaces(bpy.context))
    shading = [(k, sp.shading.type, sp.shading.color_type) for k, sp in spaces]
    need(spaces, "highlight", "no 3D view in this Blender: the shading part of the check would prove nothing")
    run, layer, frame = sc.asrp_asset_run, sc.asrp_asset_layer, sc.frame_current
    mods = [(o.name, [m.name for m in o.modifiers]) for o in objs.values()]
    names = {o.name for o in bpy.data.objects}
    # a part: selected and active, nothing else
    assert bpy.ops.asrp.highlight(kind="part", target="jaw") == {"FINISHED"}
    need([o.name for o in bpy.context.view_layer.objects if o.select_get()] == [objs["jaw"].name] and bpy.context.view_layer.objects.active == objs["jaw"],
         "highlight", "a part row did not select that object and make it active")
    # an attachment: points on its vertices, in front
    data = scene_data(sc)
    att = data["attachments"][0]
    verts = sorted({int(w[0]) for w in att["weights"]})
    need(len(verts) == 74, "highlight", f"the first attachment has {len(verts)} vertices, expected 74")
    assert bpy.ops.asrp.highlight(kind="attachment", target=att["name"]) == {"FINISHED"}
    h = sc.asrp_highlight_object
    need(asrp_blender.asset.is_live(h) and h.get(asrp_blender.asset.ROLE_KEY) == "highlight_points" and h.show_in_front and sc.asrp_highlight == att["name"],
         "highlight", "no highlight points object, or it is not shown in front of the lips")
    for frame_to_check in (0, 32):  # at rest and in the middle of the result: the points sit on the lips' vertices
        sc.frame_set(frame_to_check)
        n, co = evaluated_points(h)
        want = lips_local_mm(lips)
        worst = max(abs(co[3 * i + a] - want[3 * v + a]) for i, v in enumerate(verts) for a in range(3)) if n == len(verts) else 1e9
        need(n == len(verts) and worst < 1e-3, "highlight", f"frame {frame_to_check}: {n} points (expected {len(verts)}), up to {worst:.3g} mm from the lips' vertices")
    sc.frame_set(frame)
    # the lips' own display and the result are as they were
    need([a.name for a in lips.data.color_attributes] == attrs, "highlight", "the highlight added a colour attribute to the lips")
    need([(k, sp.shading.type, sp.shading.color_type) for k, sp in asrp_blender.asset.view3d_spaces(bpy.context)] == shading, "highlight", "the highlight changed the shading of a 3D view")
    need((sc.asrp_asset_run, sc.asrp_asset_layer) == (run, layer) and sc.frame_current == frame, "highlight", "the highlight changed the result's state")
    need(mods == [(o.name, [m.name for m in o.modifiers]) for o in objs.values()], "highlight", "the highlight changed the modifiers of the asset")
    verify_three_step(case)
    # another attachment replaces the first one; the points follow a layer switch
    other = data["attachments"][1]
    assert bpy.ops.asrp.highlight(kind="attachment", target=other["name"]) == {"FINISHED"}
    n, _ = evaluated_points(sc.asrp_highlight_object)
    need(n == len({int(w[0]) for w in other["weights"]}) and len([o for o in bpy.data.objects if o.name.startswith("ASRP highlight")]) == 1, "highlight",
         "a second highlight did not replace the first")
    # clear: nothing of it is left
    assert bpy.ops.asrp.clear_highlight() == {"FINISHED"}
    need(sc.asrp_highlight == "" and sc.asrp_highlight_object is None and {o.name for o in bpy.data.objects} == names, "highlight", "Clear highlight left objects behind")
    need(not [g for g in bpy.data.node_groups if g.name.startswith("ASRP highlight")], "highlight", "Clear highlight left its node group behind")
    verify_three_step(case)
    print(f"  highlight: a part is selected and active; an attachment is {len(verts)} points in front of the lips on the same vertices (at rest and mid result), "
          f"a second replaces it; the lips' colour attributes {attrs}, the shading {shading[0][1:]} and the result are untouched; Clear highlight leaves nothing")


def check_check_setup(sc):
    """Check setup: the outcome of `asrp check` in plain English, on a good scene and on one with an attachment without vertices."""
    assert bpy.ops.asrp.check_setup() == {"FINISHED"}
    need(sc.asrp_setup_check == "Setup check: No problems found.", "check-setup", f"a good scene says {sc.asrp_setup_check!r}")
    need("Setup check: No problems found." in " ".join(labels_of(draw_panel(asrp_blender.ASRP_PT_setup))), "check-setup", "the outcome is not drawn")
    folder = Path(sc.asrp_asset_scene).parent
    broken = folder.parent / (folder.name + "_broken")
    shutil.copytree(folder, broken)
    data = json.loads((broken / "scene.json").read_text(encoding="utf-8"))
    data["attachments"][0]["weights"] = []
    (broken / "scene.json").write_text(json.dumps(data), encoding="utf-8")
    good = sc.asrp_asset_scene
    sc.asrp_asset_scene = str(broken / "scene.json")
    try:
        assert bpy.ops.asrp.check_setup() == {"FINISHED"}
        lines = sc.asrp_setup_check.splitlines()
        log = draw_panel(asrp_blender.ASRP_PT_setup)
    finally:
        sc.asrp_asset_scene = good
        shutil.rmtree(broken, ignore_errors=True)
    need(lines and lines[0].startswith("Setup check: 1 errors") and len(lines) >= 2 and lines[1].startswith("Error: "), "check-setup",
         f"a scene with an empty attachment says {lines}")
    need(any(r[0] == "label" and r[2] and r[1].startswith("Error") for r in log), "check-setup", "the error line is not drawn in the alert colour")
    sc.asrp_setup_check = ""
    print(f"  check setup: good scene -> 'No problems found.'; an attachment without vertices -> {lines[0]!r}, then {lines[1][:70]!r}")


# --- one .blend is one scene: save, reopen in another Blender process ---------------------------------------------------------


def blend_child(phase, repo, tmp):
    """Inside a child Blender of case_save_and_reopen: the add-on is the repo's, registered before the file is opened (as Blender
    does at start-up)."""
    assert os.environ.get("BLENDER_USER_RESOURCES") and "ASRP_PROJECT" not in os.environ
    asrp_blender.register()
    asrp_blender.save_preferences = lambda: True
    sc = bpy.context.scene
    blend, state_file = tmp / "saved" / "scene.blend", tmp / "saved" / "state.json"
    try:
        if phase == "save":
            asrp_blender.asset.remove_objects([o for o in bpy.data.objects if o.type == "MESH"])
            assert bpy.ops.asrp.open_asset() == {"FINISHED"}
            assert sc.asrp_asset_landmarks is not None and not sc.asrp_asset_landmarks.hide_viewport
            run_dir = three_steps_run("neutral_to_AA.json")
            check_landmarks_hidden_with_result(sc)
            assert SESSION.state == "complete"
            state_file.write_text(json.dumps({"run_dir": str(run_dir), "scene": sc.asrp_asset_scene, "frame_end": sc.frame_end}), encoding="utf-8")
            assert bpy.ops.wm.save_as_mainfile(filepath=str(blend)) == {"FINISHED"}
            print(f"CHILD saved {blend.name} after Open asset and a run of neutral_to_AA ({sc.frame_end + 1} frames)")
        elif phase == "reopen":
            state = json.loads(state_file.read_text(encoding="utf-8"))
            assert bpy.ops.wm.open_mainfile(filepath=str(blend)) == {"FINISHED"}
            sc = bpy.context.scene
            reopen_checks(sc, state, tmp)
        else:
            assert bpy.ops.wm.open_mainfile(filepath=str(blend)) == {"FINISHED"}
            sc = bpy.context.scene
            missing_checks(sc, tmp)
    finally:
        SESSION.close()
        asrp_blender.unregister()


def case_from_state(sc, file, state, layer):
    motion = json.loads((REPO / "data" / "lab_export" / "trajectories" / file).read_text(encoding="utf-8"))
    _layer, mid, movers, still = MOTIONS[file]
    frames = [mid, 36 if motion["frames"] > 36 else motion["frames"] - 2, motion["frames"] - 1]
    return dict(file=file, motion=motion, run_dir=state["run_dir"], layer=layer, frames=frames, movers=movers, still=still, ident=snapshot(asset_now()))


def reopen_checks(sc, state, tmp):
    objs = asset_now()
    need(sorted(objs) == sorted(ROLES) and asrp_blender.asset_open(sc), "reopen", f"after reopening the panel knows the objects {sorted(objs)}")
    need(asrp_blender.asset.is_live(sc.asrp_asset_landmarks), "reopen", "the landmarks object is gone after reopening")
    texts = " ".join(labels_of(asset_log()))
    for part in ("Scene files:", "Material: 12 kPa, 0.4 (measured in Ziva)", "Units: mm (1 scene unit = 0.962 mm)", "Problems found: 0 errors, 0 warnings",
                 "Landmarks show the rest positions; hidden while a result plays."):
        need(part.replace(" ", "") in texts.replace(" ", ""), "reopen", f"after reopening the Asset section does not say {part!r}: {texts}")
    need(not asrp_blender.asset.files_problem(sc), "reopen", "the files are there but the panel says they are gone")
    need([m.title for m in sc.asrp_motions] == list(TITLES.values()), "reopen", "the motion list did not survive")
    setup = " ".join(labels_of(draw_panel(asrp_blender.ASRP_PT_setup))).replace(" ", "")
    need(all(x.replace(" ", "") in setup for x in expected_setup(scene_data(sc), "coarse")["attachments"]), "reopen", "the Physics setup did not survive")
    need((sc.frame_start, sc.frame_end) == (0, state["frame_end"]) and sc.asrp_asset_layer == "final" and sc.asrp_asset_run == state["run_dir"], "reopen",
         f"timeline {sc.frame_start}..{sc.frame_end}, layer {sc.asrp_asset_layer!r}")
    # the result plays: the same function the three-step check uses
    case = case_from_state(sc, "neutral_to_AA.json", state, "final")
    verify_three_step(case)
    run = draw_panel(asrp_blender.ASRP_PT_run)
    need(any(r[0] == "op" and r[1] == "screen.animation_play" for r in run), "reopen", "no Play button on the reopened result")
    # Physics only / Final shape
    for layer in ("physics", "final"):
        assert bpy.ops.asrp.set_layer(layer=layer) == {"FINISHED"}
        verify_three_step(dict(case, layer=layer))
    # another motion, Run: the result is replaced on the same five objects
    run_dir = three_steps_run("jaw_open_12deg.json", rest_check=True)
    case2 = case_from_state(sc, "jaw_open_12deg.json", {"run_dir": str(run_dir)}, "physics")
    case2["ident"] = case["ident"]
    verify_three_step(case2)
    need(sc.asrp_asset_run == str(run_dir) and sc.asrp_asset_run != state["run_dir"], "reopen", "the second run did not replace the result")
    time.sleep(asrp_blender.RUN_AGAIN_S + 0.3)  # after that second a Run is accepted again
    assert bpy.ops.asrp.run_motion() == {"FINISHED"} and SESSION.state == "running"
    drive()
    need(SESSION.state == "complete" and str(SESSION.run_dir) != str(run_dir), "run-twice", "a Run after the guard time did not run")
    print(f"CHILD reopened: panel knows the five objects and the landmarks, the Asset section keeps its lines, neutral_to_AA still plays (final and "
          f"physics layers equal their caches, bones equal the motion file, timeline 0..{state['frame_end']}); jaw_open_12deg then ran and replaced it on the same objects")
    # File > New: the panel is empty, nothing of the previous file is left
    assert bpy.ops.wm.read_homefile() == {"FINISHED"}
    sc = bpy.context.scene
    need(SESSION.state == "idle", "new-file", f"the run banner of the old file is still there: {SESSION.state}")
    need(not [o for o in bpy.data.objects if o.name.startswith("ASRP")], "new-file", "ASRP objects are left in the new file")
    need(not sc.asrp_asset_objects and not sc.asrp_asset_scene and not sc.asrp_asset_run and not sc.asrp_motions and not sc.asrp_results, "new-file", "scene properties are left")
    texts = {}
    for panel in (asrp_blender.ASRP_PT_asset, asrp_blender.ASRP_PT_setup, asrp_blender.ASRP_PT_motion, asrp_blender.ASRP_PT_run,
                  asrp_blender.ASRP_PT_results, asrp_blender.ASRP_PT_checks):
        log = draw_panel(panel)
        texts[panel.bl_label] = " ".join(labels_of(log))
        need(not [r for r in log if r[0] == "op" and r[1] in ("screen.animation_play", "wm.path_open", "asrp.highlight", "asrp.set_layer")], "new-file",
             f"{panel.bl_label} still has buttons of the old asset")
    need("No asset is open" in texts["1  Open the asset"] and "Scene files" not in texts["1  Open the asset"], "new-file", texts["1  Open the asset"])
    need("Open the asset first" in texts["Physics setup"] and "Open the asset first" in texts["2  Choose a motion"], "new-file", "the empty state of steps 2 is wrong")
    need("Complete" not in texts["3  Run"] and "No result is shown" in texts["Results"] and "No result is shown" in texts["Checks"], "new-file", str(texts))
    print("CHILD File > New: the panel is in its empty state (no asset, no motions, no result, no banner, no ASRP objects)")


def missing_checks(sc, tmp):
    """The scene and run folders the .blend points to are gone: plain words, Open asset offered, no traceback."""
    need(not Path(sc.asrp_asset_scene).exists(), "missing", "the scene folder is still there: this check would prove nothing")
    problem = asrp_blender.asset.files_problem(sc)
    need(problem and "scene files of this asset are gone" in problem and "Open asset again" in problem, "missing", f"the problem sentence is {problem!r}")
    log = asset_log()
    text = " ".join(labels_of(log))
    need("scene files of this asset are gone".replace(" ", "") in text.replace(" ", ""), "missing", f"the Asset section does not say so: {text}")
    open_buttons = [r for r in log if r[0] == "op" and r[1] == "asrp.open_asset"]
    need(len(open_buttons) == 1 and open_buttons[0][5], "missing", "Open asset is not offered (enabled)")
    need(not [r for r in log if r[0] == "op" and r[1] == "wm.path_open"], "missing", "an Open folder button for a folder that is gone")
    for panel in (asrp_blender.ASRP_PT_setup, asrp_blender.ASRP_PT_motion, asrp_blender.ASRP_PT_run, asrp_blender.ASRP_PT_results,
                  asrp_blender.ASRP_PT_checks, asrp_blender.ASRP_PT_advanced):
        draw_panel(panel)  # must not raise
    runlog = draw_panel(asrp_blender.ASRP_PT_run)
    need([r for r in runlog if r[1] == "asrp.run_motion"] and not [r for r in runlog if r[1] == "asrp.run_motion"][0][5], "missing", "Run is enabled with no scene files")
    need(not [r for r in runlog if r[1] == "screen.animation_play"], "missing", "a Play button for files that are gone")
    results = " ".join(labels_of(draw_panel(asrp_blender.ASRP_PT_results)))
    need("are gone" in results, "missing", f"the Results section does not say the result is gone: {results}")
    checks = " ".join(labels_of(draw_panel(asrp_blender.ASRP_PT_checks)))
    need("gone" in checks, "missing", f"the Checks section does not say the run folder is gone: {checks}")
    try:
        bpy.ops.asrp.run_motion()
        raise AssertionError("Run did not refuse")
    except RuntimeError as exc:
        need("gone" in str(exc) and "Traceback" not in str(exc), "missing", f"Run's refusal is {exc}")
    try:
        bpy.ops.asrp.check_setup()
    except RuntimeError:
        pass  # a refusal is fine; a traceback in the panel is not (draw above did not raise)
    # Open asset again repairs it
    assert bpy.ops.asrp.open_asset() == {"FINISHED"}
    need(not asrp_blender.asset.files_problem(sc) and len(asset_now()) == 5 and not sc.asrp_asset_run, "missing", "Open asset did not repair the scene")
    # an asset opened a second time has the plain names again (seen by hand: "ASRP jaw.001"), and the status of the run
    # on the asset before it is gone (seen by hand: "Complete" under a fresh asset with no result)
    names = sorted(o.name for o in bpy.data.objects if o.name.startswith(asrp_blender.asset.ASSET_PREFIX))
    need(all("." not in n for n in names) and len(names) == 6, "reopen-names", f"after a second Open asset the objects are called {names}")
    print("CHILD files gone: the panel says the scene files and the result are gone in plain words, offers Open asset (enabled), disables Run, "
          "draws every section without an error, and Open asset puts it right")


def case_save_and_reopen(tmp):
    """A real save and a real second Blender process (headless, isolated profile): Open asset, run, save; reopen; then the folders gone."""
    profile = tmp / "profile_blend"
    profile.mkdir()
    (tmp / "saved").mkdir()
    runs = tmp / "blend_runs"
    out = []
    for phase in ("save", "reopen"):
        done = subprocess.run([blender_exe(), "--background", "--python-exit-code", "1", "--python", str(THIS), "--", CHILD_MARK, phase, str(REPO), str(tmp)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=isolated(profile, ASRP_RUNS_DIR=runs), timeout=TIMEOUT_S)
        lines = [x for x in done.stdout.splitlines() if x.startswith("CHILD ")]
        assert done.returncode == 0 and lines, f"the save / reopen check, phase {phase}, failed (exit {done.returncode}):\n{done.stdout[-3500:]}\n{done.stderr[-1500:]}"
        out += lines
    shutil.move(str(runs), str(tmp / "moved_runs"))  # the scene folder and the run folder are gone
    done = subprocess.run([blender_exe(), "--background", "--python-exit-code", "1", "--python", str(THIS), "--", CHILD_MARK, "missing", str(REPO), str(tmp)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=isolated(profile, ASRP_RUNS_DIR=runs), timeout=TIMEOUT_S)
    lines = [x for x in done.stdout.splitlines() if x.startswith("CHILD ")]
    assert done.returncode == 0 and lines, f"the files-gone check failed (exit {done.returncode}):\n{done.stdout[-3500:]}\n{done.stderr[-1500:]}"
    print("case 13 one .blend is one scene (real save, three further Blender processes):\n  " + "\n  ".join(x[6:] for x in out + lines))


if CHILD_MARK in sys.argv:  # a child Blender of case_installed_copy: runs one phase and ends
    run_child(sys.argv[sys.argv.index(CHILD_MARK) + 1], Path(sys.argv[sys.argv.index(CHILD_MARK) + 2]), Path(sys.argv[sys.argv.index(CHILD_MARK) + 3]))
    raise SystemExit(0)

tmp = Path(tempfile.mkdtemp(prefix="asrp_panel_"))
os.environ["ASRP_RUNS_DIR"] = str(tmp / "asset_runs")  # the three steps write their scene and run folders here, not into the repo
asrp_blender.register()
# Never write the real Blender profile: this Blender is not in an isolated profile, so saving the preferences is a recorded stand-in here.
# The real save happens only in the child Blenders of case_installed_copy, which run in a temporary profile.
asrp_blender.save_preferences = lambda: True
os.environ.pop("ASRP_PROJECT", None)
try:
    if "--installed-only" in sys.argv:
        case_installed_copy(tmp)
        print("INSTALLED ONLY PASSED")
        raise SystemExit(0)
    if "--compare-only" in sys.argv:  # Open asset, the AA run, then the Compare with Ziva checks (a quick way to see them fail)
        asrp_blender.asset.remove_objects([o for o in bpy.data.objects if o.type == "MESH"])
        assert bpy.ops.asrp.open_asset() == {"FINISHED"}
        run_dir = three_steps_run("neutral_to_AA.json")
        check_compare_section(bpy.context.scene, case_from_state(bpy.context.scene, "neutral_to_AA.json", {"run_dir": str(run_dir)}, "final"))
        for line in NOT_VERIFIED:
            print(f"NOT VERIFIED (not counted as passed): {line}")
        print("COMPARE ONLY PASSED" + (f" ({len(NOT_VERIFIED)} part(s) NOT VERIFIED)" if NOT_VERIFIED else ""))
        raise SystemExit(0)
    if "--layout-only" in sys.argv:
        box = tmp / "box"
        subprocess.run([UV, "run", "--project", str(REPO), "python", str(THIS), "--make-scene", str(box)], capture_output=True, text=True, check=True)
        run1 = case_complete(box, tmp / "runs", tmp)
        case_layout(run1, tmp)
        print("LAYOUT ONLY PASSED")
        raise SystemExit(0)
    if "--blend-only" in sys.argv:
        case_save_and_reopen(tmp)
        print("BLEND ONLY PASSED")
        raise SystemExit(0)
    if "--three-steps-only" in sys.argv:
        case_three_steps()
        print("THREE STEPS ONLY PASSED")
        raise SystemExit(0)
    box = tmp / "box"
    made = subprocess.run([UV, "run", "--project", str(REPO), "python", str(THIS), "--make-scene", str(box)],
                          capture_output=True, text=True)
    assert made.returncode == 0, f"could not build the cube scene:\n{made.stdout}\n{made.stderr}"
    runs = tmp / "runs"
    case_english_only()
    case_project_order(tmp)
    case_installed_copy(tmp)
    case_save_and_reopen(tmp)
    run1 = case_complete(box, runs, tmp)
    case_layout(run1, tmp)
    case_start_fails(box, runs, "complete")
    case_old_button(run1, tmp, box, runs)
    case_not_started(box, runs)
    case_cancelled(box, runs)
    case_cancelled(box, runs, early=True)
    case_stand_in(box, runs, run1)
    case_process_cleanup(box, runs, run1)
    case_malformed_reports()
    case_close_before_folder(box, runs, run1)
    case_deleted_object()
    case_file_load_mid_run(box, runs, tmp)
    case_three_steps()
    for line in NOT_VERIFIED:
        print(f"NOT VERIFIED (not counted as passed): {line}")
    print("PANEL CHECK PASSED" + (f" ({len(NOT_VERIFIED)} part(s) NOT VERIFIED)" if NOT_VERIFIED else ""))
finally:
    SESSION.close()
    asrp_blender.unregister()
    shutil.rmtree(tmp, ignore_errors=True)
