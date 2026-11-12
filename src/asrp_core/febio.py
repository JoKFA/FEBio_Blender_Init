"""Run FEBio and read what it writes. Knows nothing about scenes; the .feb comes from elsewhere."""

import os
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

NORMAL_TERMINATION = "N O R M A L   T E R M I N A T I O N"
ERROR_TERMINATION = "E R R O R   T E R M I N A T I O N"


def command(feb_name: str, log_name: str, plot_name: str, exe: Path) -> list[str]:
    """The one place FEBio's command line is built. Names are relative: FEBio runs in the .feb's folder."""
    # -noconfig: results must not depend on a per-machine febio.xml (docs 05, pit 4).
    return [str(exe), "-i", feb_name, "-o", log_name, "-p", plot_name, "-noconfig", "-silent"]


@dataclass
class Run:
    feb: Path
    log: Path
    returncode: int
    normal_termination: bool
    seconds: float


def run(feb: Path, exe: Path, timeout: float = 600) -> Run:
    """Solve one .feb. The log and plot files land next to it."""
    log = feb.with_suffix(".log")
    started = time.perf_counter()
    proc = subprocess.run(
        command(feb.name, log.name, feb.with_suffix(".xplt").name, exe),
        cwd=feb.parent,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    seconds = time.perf_counter() - started
    text = log.read_text(errors="replace") if log.exists() else ""
    return Run(feb, log, proc.returncode, NORMAL_TERMINATION in text, seconds)


@dataclass
class NodeHistory:
    times: list[float]
    values: list[dict[int, tuple[float, ...]]]  # one {node id: row} per converged step


def read_node_data(log: Path, name: str, delim: str = ",") -> NodeHistory:
    """Collect one <node_data name=...> series from a logfile.

    Each record looks like:
        Data Record #1
        ======...
        Step = 0
        Time = 0
        Data = positions
        1,0,0,-5
        ...
    """
    times: list[float] = []
    values: list[dict[int, tuple[float, ...]]] = []
    lines = log.read_text(errors="replace").splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("Data Record #"):
            i += 1
            continue
        header = {}
        i += 1
        while i < len(lines) and not lines[i].startswith("Data = "):
            key, _, val = lines[i].partition(" = ")
            header[key] = val
            i += 1
        if i >= len(lines) or lines[i][len("Data = "):] != name:
            continue
        rows: dict[int, tuple[float, ...]] = {}
        i += 1
        while i < len(lines) and lines[i].strip():
            first, *rest = lines[i].split(delim)
            if not first.strip().isdigit():
                break
            rows[int(first)] = tuple(float(v) for v in rest)
            i += 1
        times.append(float(header["Time"]))
        values.append(rows)
    return NodeHistory(times, values)


def start(feb: Path, log_name: str, plot_name: str, exe: Path, out) -> subprocess.Popen:
    """Start FEBio without waiting, in the .feb's folder. `out` takes stdout and stderr (a file, never a pipe
    nobody reads). On Windows the child gets its own process group so cancelling it does not touch us."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        command(feb.name, log_name, plot_name, exe),
        cwd=feb.parent, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, creationflags=flags,
        start_new_session=sys.platform != "win32",
    )


def kill_tree(proc: subprocess.Popen, timeout: float = 10) -> None:
    """End FEBio and anything it started. Process.kill() alone leaves children behind on Windows, so taskkill
    /T goes first; if it fails, kill the process itself. Raises if the process is still alive after `timeout`."""
    if proc.poll() is None:
        if sys.platform == "win32":
            try:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=timeout)
            except (OSError, subprocess.SubprocessError):
                pass
            if proc.poll() is None:
                proc.kill()
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"FEBio (process {proc.pid}) did not stop within {timeout:g} s after being killed. "
                           "End it in Task Manager.") from None


def _controls(feb: Path) -> list[tuple[int | None, float | None]] | None:
    """(time_steps, step_size) of every active <Control> block, read with an XML parser so that settings
    left inside XML comments do not count (PR #7 review). None if the file is not readable XML."""
    try:
        root = ET.parse(feb).getroot()
    except (ET.ParseError, OSError):
        return None
    out = []
    for control in root.iter("Control"):
        n, dt = control.findtext("time_steps"), control.findtext("step_size")
        out.append((int(n) if n and n.strip() else None, float(dt) if dt and dt.strip() else None))
    return out


def total_steps(feb: Path) -> int | None:
    """Number of time steps the .feb asks for (summed over steps), or None if it does not say."""
    controls = _controls(feb)
    if not controls or any(n is None for n, _ in controls):
        return None
    return sum(n for n, _ in controls)


def end_time(feb: Path) -> float | None:
    """The time the .feb asks FEBio to reach: sum over steps of time_steps × step_size.
    None if a step does not say both."""
    controls = _controls(feb)
    if not controls or any(n is None or dt is None for n, dt in controls):
        return None
    return sum(n * dt for n, dt in controls)


def time_reached(log: Path) -> float | None:
    """The last time FEBio converged at (FEBio prints it with about 6 significant digits)."""
    try:
        found = re.findall(r"^-+ converged at time\s*:\s*([0-9.eE+-]+)", log.read_text(errors="replace"), re.M)
    except OSError:
        return None
    return float(found[-1]) if found else None


def steps_done(log: Path) -> int:
    """Time steps FEBio has finished so far. Safe to call while FEBio is still writing the log."""
    try:
        text = log.read_text(errors="replace")
    except OSError:
        return 0
    return len(re.findall(r"^-+ converged at time", text, re.M))


def version(log: Path) -> str | None:
    """FEBio's own version line from the log header, e.g. '4.13.0'."""
    try:
        head = log.read_text(errors="replace")[:4000]
    except OSError:
        return None
    m = re.search(r"^\s*version\s+(\S+)", head, re.M)
    return m.group(1) if m else None


@dataclass
class Failure:
    frame: int | None  # the time step that did not converge (1-based, as FEBio counts)
    message: str  # FEBio's own words


def read_failure(log: Path) -> Failure | None:
    """What went wrong, from the log. None if the log shows no failure."""
    try:
        text = log.read_text(errors="replace")
    except OSError:
        return None
    if ERROR_TERMINATION not in text and "failed to converge" not in text:
        return None
    steps = re.findall(r"^=+ beginning time step (\d+)", text, re.M)
    box = re.findall(r"^ \*\s+ERROR\s+\*\n((?: \*[^\n]*\n)+)", text, re.M)
    lines = []
    if box:
        for line in box[-1].splitlines():
            line = line.strip().strip("*").strip()
            if line:
                lines.append(line)
    message = " ".join(lines) or "FEBio stopped with an error"
    if "failed to converge" in text:
        message = f"did not converge: {message}" if lines else "did not converge"
    return Failure(int(steps[-1]) if steps else None, message)
