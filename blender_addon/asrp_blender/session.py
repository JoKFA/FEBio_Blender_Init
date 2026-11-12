"""One `asrp run` started from the panel, followed to its end. Plain Python: no bpy in here, so a headless check can drive it.

The add-on does no computation. A run is the `asrp` command line as a subprocess; this class only starts it, reads
the lines it prints (a reader thread feeds a queue, `poll()` drains it from the UI timer), and cancels it by
creating the file `cancel` in the run folder (docs/04 section 9).

Lines it understands (src/asrp_core/cli.py): `run folder <path>` as soon as the folder exists, `progress   frame N / M`,
`ERROR  <text>`, and one final `run COMPLETE` / `run FAILED` / `run CANCELLED` / `run NOT STARTED`.
Exit codes: 0 complete and plausible, 1 failed or a plausibility check failed, 2 cancelled or wrong usage.
"""

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
        raise RuntimeError("asrp project not found; set ASRP_PROJECT")
    if uv is None:
        raise RuntimeError("uv not found on PATH")
    return [uv, "run", "--project", str(project), "asrp", *args]


class RunSession:
    """state: idle | running | complete | failed | cancelled | not_started."""

    def __init__(self):
        self.state = "idle"
        self.reset()

    def reset(self):
        self.proc = None
        self.run_dir: Path | None = None
        self.frame = 0
        self.total: int | None = None
        self.progress_lines = 0
        self.error = ""
        self.exit_code: int | None = None
        self.passed: bool | None = None  # complete only: False when a plausibility check failed
        self.cancel_requested = False
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
            raise RuntimeError("a run is already going")
        cmd = core_command("run", str(scene), str(trajectory), "--runs-dir", str(runs_dir), *(["--name", name] if name else []))
        self.reset()
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                     errors="replace", bufsize=1, env=env, stdin=subprocess.DEVNULL, **kw)
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
                self.error = tail[0] if tail else f"the solver process ended with exit code {code} and printed nothing"
        if final == "complete":
            self.passed = code == 0
        if final == "failed" and not self.error:
            self.error = f"the run failed (exit code {code})"
        self.state = final

    def cancel(self) -> None:
        """Ask the run to stop. If the run folder is not known yet the request is kept and written when it is."""
        if not self.running:
            return
        self.cancel_requested = True
        if self.run_dir is not None:
            self._write_cancel()

    def _write_cancel(self) -> None:
        try:
            (self.run_dir / CANCEL_FILE).write_text("", encoding="ascii")
        except OSError as exc:
            self.error = f"could not write the cancel file: {exc}"

    def close(self) -> None:
        """Add-on unregister: do not leave a solver running behind a closed panel. The cancel file lets the core stop
        FEBio itself (terminating the uv process would leave FEBio running)."""
        self.cancel()
        self.state = "idle"
