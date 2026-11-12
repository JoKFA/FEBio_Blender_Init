"""Spike: can the Blender panel run `asrp run` without freezing the UI, show progress, cancel and detect failure?

Answers, from inside Blender's Python (Windows, Blender 5.2):
  Q1  Popen of `uv run --project <repo> asrp run ...` + a reader thread (queue.Queue) + a timer that drains the queue:
      does the timer keep firing while the run goes (largest gap between ticks), is output line-buffered?
  Q2  cancel by creating `cancel` in the run folder (found as the single new subfolder of a fresh --runs-dir):
      seconds to exit, exit code, febio4.exe left over, run folder content, run_report.json status.
  Q3  a run that must fail fast: what the panel receives (exit code, ERROR line).
  Q4  after a successful run, load playback.json with the add-on's build_playback_object from the timer callback.

Run (windowed, the real timer path; Blender quits itself at the end):
    "<blender.exe>" --factory-startup --python spikes/blender_background_run.py -- --repo <repo> --scene <scene.json> --trajectory <jaw.json> --scratch <dir> [--unbuffered-env]
Run headless (--background): bpy.app.timers do NOT fire there once the script is running its own loop, so the script
calls the same tick function from a plain loop that sleeps 50 ms (the timer mechanism is then NOT what is measured):
    "<blender.exe>" --background --factory-startup --python spikes/blender_background_run.py -- ... --mode loop
Flags: --mode timer|loop (default timer), --no-pythonunbuffered (leave PYTHONUNBUFFERED out of the child env),
--phases success,cancel,fail (default all), --frames-before-cancel N (default 3).
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


REPO = Path(opt("--repo"))
SCENE, TRAJ = opt("--scene"), opt("--trajectory")
SCRATCH = Path(opt("--scratch"))
MODE = opt("--mode", "timer")
UNBUFFERED = "--no-pythonunbuffered" not in argv
PHASES = opt("--phases", "success,cancel,fail").split(",")
CANCEL_AFTER = int(opt("--frames-before-cancel", "3"))
TICK = 0.25

sys.path.insert(0, str(REPO / "blender_addon"))
import asrp_blender  # noqa: E402

t0 = time.perf_counter()


def now():
    return time.perf_counter() - t0


def log(msg):
    print(f"[{now():7.2f}] {msg}", flush=True)


def febio_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq febio4.exe", "/NH"], capture_output=True).stdout
    return b"febio4.exe" in out


class Job:
    """What the panel would hold: process, reader thread, queue, tick times."""

    def __init__(self, args, runs_dir=None):
        uv = shutil.which("uv")
        env = dict(os.environ)
        if UNBUFFERED:
            env["PYTHONUNBUFFERED"] = "1"
        self.cmd = [uv, "run", "--project", str(REPO), "asrp", *args]
        self.runs_dir = runs_dir
        self.q = queue.Queue()
        self.lines = []  # (t, line)
        self.ticks = []  # t of every drain
        self.started = now()
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
                                     env=env, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()
        self.cancel_at = None
        self.exit_at = None

    def _read(self):
        for line in self.proc.stdout:
            self.q.put((now(), line.rstrip("\n")))
        self.q.put((now(), None))

    def drain(self):
        self.ticks.append(now())
        got = []
        while True:
            try:
                t, line = self.q.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                self.lines.append((t, line))
                got.append(line)
        if self.exit_at is None and self.proc.poll() is not None:
            self.exit_at = now()
        return got

    def frames(self):
        return [(t, ln) for t, ln in self.lines if ln.startswith("progress")]

    def run_folder(self):
        subs = [p for p in self.runs_dir.iterdir() if p.is_dir()] if self.runs_dir and self.runs_dir.exists() else []
        return subs[0] if len(subs) == 1 else None


results = {}


def gaps(ticks, lo, hi):
    inside = [t for t in ticks if lo <= t <= hi]
    return max((b - a for a, b in zip(inside, inside[1:])), default=float("nan")), len(inside)


class Phases:
    """A state machine advanced by tick(); returns False when all phases are done."""

    def __init__(self):
        self.queue = list(PHASES)
        self.job = None
        self.name = None
        self.state = "idle"

    def start(self, name):
        self.name = name
        runs = SCRATCH / f"runs_{name}"
        if runs.exists():
            shutil.rmtree(runs)
        runs.mkdir(parents=True)
        if name == "fail":
            args = ["run", str(SCENE), str(SCRATCH / "does_not_exist.json"), "--runs-dir", str(runs), "--name", "spike"]
        else:
            args = ["run", str(SCENE), str(TRAJ), "--runs-dir", str(runs), "--name", "spike"]
        self.job = Job(args, runs)
        log(f"phase {name}: started {' '.join(args[:2])} ... (cmd uses uv run --project)")
        self.state = "running"

    def tick(self):
        if self.state == "idle":
            if not self.queue:
                return False
            self.start(self.queue.pop(0))
            return True
        job = self.job
        for line in job.drain():
            if line.startswith(("progress", "ERROR", "run ", "run folder")) or "Traceback" in line:
                log(f"  {self.name} line: {line[:110]}")
        if self.name == "cancel" and job.cancel_at is None and len(job.frames()) >= CANCEL_AFTER:
            folder = job.run_folder()
            if folder is not None:
                (folder / "cancel").write_text("")
                job.cancel_at = now()
                log(f"  cancel file created in {folder.name} after {len(job.frames())} progress lines")
        if job.exit_at is not None and job.q.empty():
            self.finish()
        return True

    def finish(self):
        job, name = self.job, self.name
        job.drain()
        code = job.proc.returncode
        fr = job.frames()
        r = {"exit_code": code, "wall_s": round(job.exit_at - job.started, 2), "progress_lines": len(fr)}
        if fr:
            r["first_progress_after_s"] = round(fr[0][0] - job.started, 2)
            r["last_progress_after_s"] = round(fr[-1][0] - job.started, 2)
            # buffered output would show all lines arriving within a very short window at the end
            r["progress_arrival_spread_s"] = round(fr[-1][0] - fr[0][0], 2)
        g, n = gaps(job.ticks, fr[0][0] if fr else job.started, job.exit_at)
        r["ticks_during_run"] = n
        r["largest_tick_gap_s_during_run"] = round(g, 3)
        r["tick_interval_wanted_s"] = TICK if MODE == "timer" else 0.05
        r["errors"] = [ln for _, ln in job.lines if ln.startswith("ERROR")]
        r["last_lines"] = [ln for _, ln in job.lines[-3:]]
        folder = job.run_folder()
        if name == "cancel":
            r["seconds_cancel_to_exit"] = round(job.exit_at - job.cancel_at, 2) if job.cancel_at else None
            time.sleep(1.0)
            r["febio_left_running"] = febio_running()
            if folder:
                r["run_folder_content"] = sorted(p.name for p in folder.iterdir())
                r["has_physics_dir"] = (folder / "physics").exists()
                r["has_playback"] = any((folder / n).exists() for n in ("playback.json", "playback.pc2"))
                rep = folder / "run_report.json"
                r["report_status"] = json.loads(rep.read_text(encoding="utf-8")).get("status") if rep.exists() else "no run_report.json"
        if name == "success" and folder:
            r["run_folder_content"] = sorted(p.name for p in folder.iterdir())
            r["q4"] = self.load_playback(folder)
        results[name] = r
        log(f"phase {name} done: {json.dumps(r)}")
        self.state = "idle"

    def load_playback(self, folder):
        """Q4: runs inside the tick (timer callback when MODE == timer)."""
        out = {"in_timer_callback": MODE == "timer"}
        try:
            manifest = json.loads((folder / "playback.json").read_text(encoding="utf-8"))
            ctx = bpy.context
            before = len(bpy.data.objects)
            obj = asrp_blender.build_playback_object(ctx, manifest, folder)
            out.update(ok=True, object=obj.name, new_objects=len(bpy.data.objects) - before,
                       frames=manifest["frame_count"], frame_end=ctx.scene.frame_end)
            # set a frame and evaluate: the data API path the panel would use after loading
            ctx.scene.frame_set(25)
            ev = obj.evaluated_get(ctx.evaluated_depsgraph_get())
            m = ev.to_mesh()
            z = [v.co.z for v in m.vertices]
            out["evaluated_vertices"] = len(z)
            ev.to_mesh_clear()
            # an operator from the callback
            try:
                out["operator_from_callback"] = str(bpy.ops.asrp.load_playback(directory=str(folder)))
            except Exception as e:  # noqa: BLE001
                out["operator_from_callback"] = f"{type(e).__name__}: {e}"
        except Exception as e:  # noqa: BLE001
            out.update(ok=False, error=f"{type(e).__name__}: {e}")
        return out


def finish_all():
    print("SPIKE_RESULTS " + json.dumps(results, indent=1), flush=True)
    (SCRATCH / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    asrp_blender.unregister()


asrp_blender.register()
phases = Phases()
log(f"mode={MODE} unbuffered_env={UNBUFFERED} blender={bpy.app.version_string} background={bpy.app.background}")

if MODE == "timer":
    timer_fires = [0]

    def cb():
        timer_fires[0] += 1
        if not phases.tick():
            finish_all()
            bpy.ops.wm.quit_blender()
            return None
        return TICK

    bpy.app.timers.register(cb, first_interval=TICK)
    if bpy.app.background:
        # find out whether timers fire at all while the script is alive in --background
        time.sleep(3)
        log(f"background: timer callback fired {timer_fires[0]} times during a 3 s sleep inside the script")
        finish_all() if timer_fires[0] == 0 else None
else:
    while phases.tick():
        _ = bpy.context.scene.frame_current  # cheap bpy read to stand in for UI work
        time.sleep(0.05)
    finish_all()
