"""One `asrp run` started from the panel, followed to its end. Plain Python: no bpy in here, so a headless check can drive it.

The add-on does no computation. A run is the `asrp` command line as a subprocess; this class only starts it, reads
the lines it prints (a reader thread feeds a queue, `poll()` drains it from the UI timer), and cancels it by
creating the file `cancel` in the run folder (docs/04 section 9).

Lines it understands (src/asrp_core/cli.py): `run folder <path>` as soon as the folder exists, `progress   frame N / M`,
`ERROR  <text>`, and one final `run COMPLETE` / `run FAILED` / `run CANCELLED` / `run NOT STARTED`.
Exit codes: 0 complete and plausible, 1 failed or a plausibility check failed, 2 cancelled or wrong usage.
"""

import atexit
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

CANCEL_FILE = "cancel"
PROGRESS = re.compile(r"^progress\s+frame\s+(\d+)\s*/\s*(\d+|\?)")
FINAL_LINES = (("run COMPLETE", "complete"), ("run CANCELLED", "cancelled"), ("run NOT STARTED", "not_started"),
               ("run FAILED", "failed"))
ENDED = ("complete", "failed", "cancelled", "not_started")
CANCEL_WAIT_S = 10.0  # a cancel asked for before the run folder is known: kill the process after this many seconds
EOF_GRACE_S = 5.0  # the process is gone but the pipe is still open (a grandchild holds it): stop waiting after this


def core_project() -> Path | None:
    """The asrp project whose venv runs the core: $ASRP_PROJECT, else the repo this add-on lives in."""
    override = os.environ.get("ASRP_PROJECT")
    if override:
        return Path(override)
    repo = Path(__file__).resolve().parents[2]
    return repo if (repo / "pyproject.toml").is_file() else None


def core_command(*args: str) -> list[str]:
    project = core_project()
    uv = shutil.which("uv")
    if project is None:
        raise RuntimeError("ASRP project not found; set ASRP_PROJECT")
    if uv is None:
        raise RuntimeError("Cannot find uv on PATH")
    return [uv, "run", "--project", str(project), "asrp", *args]


class RunSession:
    """state: idle | running | complete | failed | cancelled | not_started."""

    def __init__(self, launcher=None):
        self.launcher = launcher or core_command  # builds the command line; a test can put a stand-in here
        self.cancel_wait_s = CANCEL_WAIT_S  # how long a cancel may wait for the run folder before the process is killed
        self.proc = None
        self.reset()

    def reset(self):
        self.kill_tree()  # a session that is dropped must not leave its process tree behind (no-op if there is none)
        self.state = "idle"
        self.cancel_too_late = False  # a cancel was asked for, but the run had already finished and completed
        self.proc = None
        self.run_dir: Path | None = None
        self.frame = 0
        self.total: int | None = None
        self.progress_lines = 0
        self.error = ""
        self.exit_code: int | None = None
        self.passed: bool | None = None  # complete only: False when a plausibility check failed
        self.cancel_requested = False
        self.cancel_requested_at = 0.0
        self.handled = False  # the UI has taken the outcome (loaded the results)
        self.load_error = ""
        self.started_at = 0.0
        self.ended_at = 0.0
        self.lines = deque(maxlen=300)
        self._queue: queue.Queue = queue.Queue()
        self._final = None
        self._eof = False
        self._exit_seen_at = None

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def elapsed(self) -> float:
        if self.state == "idle":
            return 0.0
        return (self.ended_at or time.monotonic()) - self.started_at

    def start(self, scene: str, trajectory: str, runs_dir: str, name: str = "") -> None:
        if self.running:
            raise RuntimeError("A run is already going")
        self.reset()  # an earlier run's outcome must not stay on show if this one cannot even start
        try:
            cmd = self.launcher("run", str(scene), str(trajectory), "--runs-dir", str(runs_dir),
                                *(["--name", name] if name else []))
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
            kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                         errors="replace", bufsize=1, env=env, stdin=subprocess.DEVNULL, **kw)
        except (RuntimeError, OSError) as exc:
            self.state, self.error, self.handled = "not_started", f"The run could not be started: {exc}", True
            raise
        self.state = "running"
        self.started_at = time.monotonic()
        threading.Thread(target=self._read, args=(self.proc, self._queue), daemon=True).start()

    @staticmethod
    def _read(proc, q) -> None:
        try:
            for line in proc.stdout:
                q.put(line.rstrip("\r\n"))
        finally:
            q.put(None)

    def poll(self) -> str:
        """Take in what the process printed since the last call; returns the state."""
        if self.state != "running":
            return self.state
        while True:
            try:
                line = self._queue.get_nowait()
            except queue.Empty:
                break
            if line is None:
                self._eof = True
            else:
                self._take(line)
        if (self.cancel_requested and self.run_dir is None and self._final is None
                and time.monotonic() - self.cancel_requested_at > self.cancel_wait_s):
            self.kill_tree()  # no run folder, so no cancel file can be written: stop the process, end as cancelled
            self._final = "cancelled"
        code = self.proc.poll()
        if code is not None:
            if self._exit_seen_at is None:
                self._exit_seen_at = time.monotonic()
            if self._eof or time.monotonic() - self._exit_seen_at > EOF_GRACE_S:
                self._finish(code)
        return self.state

    def _take(self, line: str) -> None:
        self.lines.append(line)
        m = PROGRESS.match(line)
        if m:
            self.progress_lines += 1
            self.frame = int(m.group(1))
            self.total = None if m.group(2) == "?" else int(m.group(2))
        elif line.startswith("run folder "):
            if self.run_dir is None:
                self.run_dir = Path(line[len("run folder "):].strip())
                if self.cancel_requested:
                    self._write_cancel()
        elif line.startswith("ERROR"):
            self.error = line[len("ERROR"):].strip()
        else:
            for prefix, state in FINAL_LINES:
                if line.startswith(prefix):
                    self._final = state
                    break

    def _finish(self, code: int) -> None:
        self.exit_code = code
        self.ended_at = time.monotonic()
        final = self._final
        if final is None and code == 2 and self.cancel_requested:
            final = "cancelled"
        if final is None:  # the process died without a closing line (a crash, or wrong usage)
            final = "failed"
            if not self.error:
                tail = [line for line in self.lines if line.strip()][-1:]
                self.error = tail[0] if tail else f"The solver process ended with exit code {code} and printed nothing"
        if final == "complete" and code not in (0, 1):  # exit 1 means "a plausibility check failed"; anything else is a crash
            final = "failed"
            self.error = f"The solver process ended with exit code {code} after reporting the run complete; no results are loaded"
        if final == "complete":
            self.passed = code == 0
            self.cancel_too_late = self.cancel_requested
        if final in ("failed", "not_started") and not self.error:
            self.error = f"The run ended with exit code {code} and gave no reason"
        self.state = final

    def cancel(self) -> None:
        """Ask the run to stop. If the run folder is not known yet the request is kept and written when it is."""
        if not self.running:
            return
        if not self.cancel_requested:
            self.cancel_requested_at = time.monotonic()
        self.cancel_requested = True
        if self.run_dir is not None:
            self._write_cancel()

    def _write_cancel(self) -> None:
        try:
            (self.run_dir / CANCEL_FILE).write_text("", encoding="ascii")
        except OSError as exc:
            self.error = f"Could not write the cancel file: {exc}"

    def kill_tree(self) -> None:
        """Stop the process and everything it started (uv -> python -> FEBio). On Windows: `taskkill /PID <pid> /T /F`."""
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            proc.terminate()

    def close(self, wait: float = 0.0) -> None:
        """The panel goes away (add-on unregister, Blender quits): leave no solver running behind it.
        Folder known: ask the core to cancel (it stops FEBio itself); with `wait` seconds given, wait for it and kill
        the tree if it is still there after that. Folder not known yet (FEBio has not started): kill the tree at once."""
        if self.running:
            self.poll()  # a run folder line that is still in the queue counts
        if self.running and self.proc is not None:
            if self.run_dir is None:
                self.kill_tree()
            else:
                self.cancel()
                if wait:
                    try:
                        self.proc.wait(timeout=wait)
                    except subprocess.TimeoutExpired:
                        self.kill_tree()
        self.state = "idle"


EXIT_WAIT_S = 3.0  # how long Blender's exit waits for a cancelled run to stop (the core needs about 2 s) before killing the tree


def register_exit_handler(session: RunSession):
    """Fallback for a Blender that exits without calling unregister(): the same cleanup, from atexit. Returns the handler."""

    def handler():
        session.close(wait=EXIT_WAIT_S)

    atexit.register(handler)
    return handler
