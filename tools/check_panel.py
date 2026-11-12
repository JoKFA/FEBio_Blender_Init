"""The Blender panel's run / results / checks logic, driven headless against real `asrp run` processes.

    blender --background --factory-startup --python-exit-code 1 --python tools/check_panel.py

`bpy.app.timers` do not fire in --background, so this drives the same function the timer calls
(`asrp_blender.tick()`) from a sleep loop, and starts / cancels runs through the panel's operators.
Scenes come from tests/cube_scene.py (a small box with a skin and a landmarks trajectory), written by this
same file run with plain Python (`uv run python tools/check_panel.py --make-scene <folder>`), because Blender's
Python has no numpy.

Three cases, each must be able to fail: (1) a complete run: progress seen, run folder learned before the process
ended, two results loaded with one visible, switching, five checks read from the report; (2) a run that cannot
start (missing trajectory): nothing loaded, the older visible result is hidden; (3) a cancelled run: exit code 2,
no results, nothing loaded. The windowed (timer) path is tools/panel_windowed_check.py.
"""

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
    import json

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


if "--make-scene" in sys.argv:
    make_scene(Path(sys.argv[sys.argv.index("--make-scene") + 1]))
    raise SystemExit(0)

sys.path.insert(0, str(REPO / "blender_addon"))

import asrp_blender  # noqa: E402
import bpy  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SESSION = asrp_blender.SESSION
TIMEOUT_S = 600


def visible():
    return [o.name for o in bpy.data.objects if o.name.startswith("ASRP") and not o.hide_viewport and not o.hide_render]


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


def case_complete(box, runs):
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
    assert bpy.ops.asrp.show_result(index=0) == {"FINISHED"}
    assert visible() == [sc.asrp_results[0].obj.name] and sc.asrp_shown == 0, visible()
    report = asrp_blender.read_report(sc.asrp_results[0].run_dir)
    rows = asrp_blender.check_rows(report)
    assert len(rows) == 5 and [r[0] for r in rows] == ["a", "b", "b2", "c", "d"], rows
    assert rows[0][2] == "PASS", rows[0]
    assert "applied" in report["landmark_layer"] and asrp_blender.landmark_summary(report)
    print(f"case 1 complete: state {SESSION.state}, passed {SESSION.passed}, {SESSION.progress_lines} progress lines, folder known "
          f"{len(folder_before_end)} ticks before the end, {len(sc.asrp_results)} results "
          f"({', '.join(e.label for e in sc.asrp_results)}), visible {visible()}, checks "
          + ", ".join(f"{k}={v}" for k, _, v, _ in rows))


def case_not_started(box, runs):
    sc = bpy.context.scene
    before, count = visible(), len(sc.asrp_results)
    assert before, "case 2 needs a visible result to start from"
    start(box / "scene.json", box / "no_such_motion.json", runs, "missing")
    assert visible() == [], "an old result is still visible after a new run started"
    assert sc.asrp_shown == -1
    drive()
    assert SESSION.state == "not_started", (SESSION.state, SESSION.error, list(SESSION.lines)[-5:])
    assert SESSION.error.strip(), "the ERROR text was not captured"
    assert len(sc.asrp_results) == count, "a failed run added an entry"
    assert visible() == [] and sc.asrp_shown == -1, visible()
    print(f"case 2 not started: state {SESSION.state}, exit {SESSION.exit_code}, error {SESSION.error[:100]!r}, entries {len(sc.asrp_results)} "
          f"(was {count}), visible before {before} -> after {visible()}")


def case_cancelled(box, runs, early=False):
    sc = bpy.context.scene
    count = len(sc.asrp_results)
    start(box / "scene.json", box / "long.json", runs, "cancel_early" if early else "cancel")
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
          f"{(SESSION.run_dir / 'playback.json').exists()}, entries {len(sc.asrp_results)}, visible {visible()}")


tmp = Path(tempfile.mkdtemp(prefix="asrp_panel_"))
asrp_blender.register()
try:
    box = tmp / "box"
    made = subprocess.run([shutil.which("uv"), "run", "--project", str(REPO), "python", str(Path(__file__).resolve()), "--make-scene", str(box)],
                          capture_output=True, text=True)
    assert made.returncode == 0, f"could not build the cube scene:\n{made.stdout}\n{made.stderr}"
    runs = tmp / "runs"
    case_complete(box, runs)
    case_not_started(box, runs)
    case_cancelled(box, runs)
    case_cancelled(box, runs, early=True)
    print("PANEL CHECK PASSED")
finally:
    SESSION.close()
    asrp_blender.unregister()
    shutil.rmtree(tmp, ignore_errors=True)
