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
    folder.mkdir(parents=True, exist_ok=True)
    print(f"env PYTHONIOENCODING={os.environ.get('PYTHONIOENCODING')}", flush=True)
    print(f"run folder {folder}", flush=True)
    print("progress   frame 1 / 3", flush=True)
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

import asrp_blender  # noqa: E402
import bpy  # noqa: E402

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


def case_old_button(source, tmp):
    """The old Load Result button goes through the same list: shown alone, and hidden when a new run starts (item 4)."""
    sc = bpy.context.scene
    count = len(sc.asrp_results)
    copy = tmp / "legacy"
    shutil.copytree(source, copy)
    assert bpy.ops.asrp.load_playback(directory=str(copy)) == {"FINISHED"}
    assert len(sc.asrp_results) == count + 1 and sc.asrp_results[count].obj is not None
    assert visible() == [sc.asrp_results[count].obj.name] and sc.asrp_shown == count, visible()
    assert bpy.context.view_layer.objects.active == sc.asrp_results[count].obj
    print(f"case 1b old Load Result button: entry {sc.asrp_results[count].label!r} added to the list ({len(sc.asrp_results)} entries), "
          f"visible {visible()}")
    return sc.asrp_results[count].obj.name


def case_start_fails(box, runs, old_state):
    """The command cannot even be built (uv not found, Popen raising): the old outcome must not stay on show (item 2)."""
    sc = bpy.context.scene
    count, before = len(sc.asrp_results), make_visible()
    assert SESSION.state == old_state == "complete"

    def no_uv(*args):
        raise RuntimeError("uv not found on PATH")

    SESSION.launcher = no_uv
    try:
        try:
            start(box / "scene.json", box / "motion.json", runs, "never")
            raise AssertionError("the operator did not refuse")
        except RuntimeError as exc:  # an operator that reports an ERROR raises in a script
            assert "uv not found" in str(exc), exc
    finally:
        SESSION.launcher = asrp_blender.core_command
    assert SESSION.state == "not_started" and "uv not found" in SESSION.error, (SESSION.state, SESSION.error)
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


def case_close_before_folder(box, runs):
    """Closing the session before the run folder is known must not leave uv / python running (item 3)."""
    start(box / "scene.json", box / "long.json", runs, "closed")
    t0 = time.monotonic()
    tree = set()
    while not tree and time.monotonic() - t0 < 20:
        tree = descendants(SESSION.proc.pid)
    assert tree, "no child process of the run was seen: this case would prove nothing"
    assert SESSION.run_dir is None and alive(tree | {SESSION.proc.pid}), "the run is not running"
    SESSION.close()
    time.sleep(2)
    left = alive(tree | {SESSION.proc.pid})
    assert not left, f"processes left running after close(): {left}"
    assert SESSION.proc.poll() is not None
    print(f"case 6 close before the folder is known: {len(tree) + 1} processes (uv + {len(tree)} children) were running, 2 s after close() "
          f"left: {sorted(left)}")


def case_file_load_mid_run(box, runs):
    """File > Open while a run goes: the timer survives, the run is polled to its end, the result goes to the new file's scene (item 1)."""
    start(box / "scene.json", box / "motion.json", runs, "reload")
    handlers = bpy.app.handlers.load_post
    handlers.remove(asrp_blender.on_load_post)  # first: the timer's own persistence, without the handler's help
    try:
        assert bpy.ops.wm.read_homefile() == {"FINISHED"}
    finally:
        handlers.append(asrp_blender.on_load_post)
    sc = bpy.context.scene
    assert len(sc.asrp_results) == 0 and SESSION.state == "running"
    assert bpy.app.timers.is_registered(asrp_blender.tick), "the timer did not survive the file load"
    bpy.app.timers.unregister(asrp_blender.tick)  # then: the handler alone re-arms a missing timer
    asrp_blender.on_load_post()
    assert bpy.app.timers.is_registered(asrp_blender.tick), "the load_post handler did not re-arm the timer"
    assert asrp_blender.on_load_post in handlers
    drive()
    sc = bpy.context.scene
    assert SESSION.state == "complete" and not SESSION.load_error, (SESSION.state, SESSION.load_error)
    assert len(sc.asrp_results) == 2 and len(visible()) == 1, (len(sc.asrp_results), visible())
    print(f"case 5 file load mid-run: timer still registered, state {SESSION.state}, the result went to the new file's scene "
          f"({len(sc.asrp_results)} entries, visible {visible()})")


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


tmp = Path(tempfile.mkdtemp(prefix="asrp_panel_"))
asrp_blender.register()
try:
    box = tmp / "box"
    made = subprocess.run([UV, "run", "--project", str(REPO), "python", str(THIS), "--make-scene", str(box)],
                          capture_output=True, text=True)
    assert made.returncode == 0, f"could not build the cube scene:\n{made.stdout}\n{made.stderr}"
    runs = tmp / "runs"
    case_english_only()
    run1 = case_complete(box, runs, tmp)
    case_old_button(run1, tmp)
    case_start_fails(box, runs, "complete")
    case_not_started(box, runs)
    case_cancelled(box, runs)
    case_cancelled(box, runs, early=True)
    case_stand_in(box, runs, run1)
    case_malformed_reports()
    case_close_before_folder(box, runs)
    case_deleted_object()
    case_file_load_mid_run(box, runs)
    print("PANEL CHECK PASSED")
finally:
    SESSION.close()
    asrp_blender.unregister()
    shutil.rmtree(tmp, ignore_errors=True)
