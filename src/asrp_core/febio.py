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

import numpy as np

NORMAL_TERMINATION = "N O R M A L   T E R M I N A T I O N"
ERROR_TERMINATION = "E R R O R   T E R M I N A T I O N"

# The node positions the generator asks FEBio for: one named series, written to its own data file next to the
# .feb. In the logfile they would be every node's position at every frame (20 MB for the lip run). Both names
# live here. FEBio 4.13 writes the file as '*Step  = n', '*Time  = t', '*Data  = positions', then 'id,x,y,z'
# lines (CRLF, 12 significant digits like the log, no blank line between records).
NODE_DATA_NAME = "positions"
NODE_DATA_FILE = "positions.txt"


# FEBio's multi-threaded solver gives positions that differ in the last logged digit (about 1e-10 mm on the lips)
# from run to run; with one thread the log is the same every time (docs/05 pit 17, T-06a). Four threads halve the
# time of the lip run (56 s -> 27 s, ADR-38), so that is the default; `--threads 1` gives
# bit-identical results. The standard at the default: the same input twice agrees within 1e-9 mm at every node
# and frame.
DEFAULT_THREADS = 4


def threads_used(requested: int = DEFAULT_THREADS) -> int:
    """The thread count FEBio will really get: the request, but never more than this machine's CPUs."""
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
        raise ValueError(f"threads must be a whole number, at least 1, got {requested!r}")
    return min(requested, os.cpu_count() or 1)


def thread_env(threads: int = DEFAULT_THREADS) -> dict:
    """The two variables that set FEBio's thread count (OpenMP and MKL), as recorded in provenance."""
    n = str(threads_used(threads))
    return {"OMP_NUM_THREADS": n, "MKL_NUM_THREADS": n}


def environment(threads: int = DEFAULT_THREADS) -> dict:
    return {**os.environ, **thread_env(threads)}


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


def run(feb: Path, exe: Path, timeout: float = 600, threads: int = DEFAULT_THREADS) -> Run:
    """Solve one .feb. The log and plot files land next to it."""
    log = feb.with_suffix(".log")
    started = time.perf_counter()
    proc = subprocess.run(
        command(feb.name, log.name, feb.with_suffix(".xplt").name, exe),
        cwd=feb.parent,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment(threads),
    )
    seconds = time.perf_counter() - started
    text = log.read_text(errors="replace") if log.exists() else ""
    return Run(feb, log, proc.returncode, NORMAL_TERMINATION in text, seconds)


def _records(lines, name: str, delim: str = ","):
    """Yield (time, rows) for every record of the series `name` in a stream of text lines; rows are the record's
    'id,x,y,z' lines as text. Two layouts are read, one function: a record in the logfile starts with
    'Data Record #n', a record in a node_data file with '*Step'. Then come Step, Time and Data lines (a leading
    '*' and the spacing around '=' differ), one line per node, and the record ends at a blank line, the next
    record or the end:
        Data Record #1          *Step  = 0
        ======                  *Time  = 0
        Step = 0                *Data  = positions
        Time = 0                1,0,0,-5
        Data = positions        2,5,0,-5
        1,0,0,-5
        2,5,0,-5
    """
    header: dict[str, str] | None = None  # Step/Time/Data of the record being started, None between records
    rows: list[str] | None = None  # the rows of a record of `name` being read
    for line in lines:
        text = line.strip()
        if rows is not None:
            if text.partition(delim)[0].isdigit():
                rows.append(text)
                continue
            yield float(header["Time"]), rows
            header = rows = None
        if text.startswith("Data Record #") or text.startswith("*Step"):
            header = {}
        if header is None:
            continue
        key, _, val = text.lstrip("*").partition("=")
        header[key.strip()] = val.strip()
        if key.strip() == "Data":
            if val.strip() == name:
                rows = []
            else:
                header = None
    if rows is not None:
        yield float(header["Time"]), rows


@dataclass
class NodeHistory:
    times: list[float]
    values: list[dict[int, tuple[float, ...]]]  # one {node id: row} per converged step


def read_node_data(log: Path, name: str, delim: str = ",") -> NodeHistory:
    """Collect one <node_data name=...> series from a logfile, as a dict per frame. For the tests and tools
    on small models; a run's own positions come through `read_node_series`."""
    times: list[float] = []
    values: list[dict[int, tuple[float, ...]]] = []
    with log.open(errors="replace") as f:
        for t, rows in _records(f, name, delim):
            times.append(t)
            values.append({int(r.split(delim)[0]): tuple(float(v) for v in r.split(delim)[1:]) for r in rows})
    return NodeHistory(times, values)


@dataclass
class NodeSeries:
    times: np.ndarray  # (F,) seconds
    node_ids: np.ndarray  # (N,) FEBio node ids, in the order the records list them
    values: np.ndarray  # (F, N, 3) FEBio's coordinates


def data_file(feb: Path, name: str) -> str | None:
    """The file the .feb says <node_data name=...> writes to (a plain name, next to the .feb), or None if
    that series goes into the logfile."""
    try:
        root = ET.parse(feb).getroot()
    except (ET.ParseError, OSError):
        return None
    for node_data in root.iter("node_data"):
        file = node_data.get("file")
        if node_data.get("name") == name and file:
            if Path(file).name != file:
                raise ValueError(f"{feb.name} writes node data to {file}, which is not a plain file name next to "
                                 "the .feb. Use a name without folders.")
            return file
    return None


def read_node_series(feb: Path, log: Path, name: str = NODE_DATA_NAME) -> NodeSeries:
    """One node-data series as numpy arrays: from the data file the .feb names, else from the log (stand-in
    .feb files log into the logfile). Read as a stream, never held as text. Every frame must list the same node
    ids in the same order, otherwise ValueError. No frames at all gives empty arrays."""
    file = data_file(feb, name)
    source = feb.parent / file if file else log
    if file and not source.is_file():
        raise ValueError(f"FEBio did not write {file} next to {feb.name}. {log.name} says what went wrong.")
    times: list[float] = []
    frames: list[np.ndarray] = []
    ids: np.ndarray | None = None
    with source.open(errors="replace") as f:
        for t, rows in _records(f, name):
            try:
                data = np.array([r.split(",") for r in rows], dtype=float).reshape(len(rows), 4)
            except ValueError:
                raise ValueError(f"{source.name}: the record at time {t:g} does not hold 'id,x,y,z' on every line") from None
            frame_ids = data[:, 0].astype(np.int64)
            if ids is None:
                ids = frame_ids
            elif not np.array_equal(frame_ids, ids):
                raise ValueError(f"{source.name}: the record at time {t:g} lists other nodes than the first record "
                                 f"({len(frame_ids)} against {len(ids)}, or in another order), so the frames cannot "
                                 "be lined up. Run again; if it happens again, the .feb is at fault.")
            times.append(t)
            frames.append(data[:, 1:])
    if not frames:
        return NodeSeries(np.zeros(0), np.zeros(0, np.int64), np.zeros((0, 0, 3)))
    return NodeSeries(np.array(times), ids, np.stack(frames))


class StepCounter:
    """`steps_done` for a log that is still growing: each poll reads only what was appended since the last
    one, counts the finished lines in it and keeps a half-written last line for the next poll."""

    def __init__(self, log: Path):
        self.log, self.done, self._offset, self._tail = log, 0, 0, b""

    def poll(self) -> int:
        try:
            with self.log.open("rb") as f:
                f.seek(self._offset)
                new = f.read()
        except OSError:
            return self.done
        self._offset += len(new)
        data = self._tail + new
        cut = data.rfind(b"\n") + 1  # up to and including the last full line
        self._tail = data[cut:]
        self.done += len(re.findall(rb"^-+ converged at time", data[:cut], re.M))
        return self.done


def start(feb: Path, log_name: str, plot_name: str, exe: Path, out, threads: int = DEFAULT_THREADS) -> subprocess.Popen:
    """Start FEBio without waiting, in the .feb's folder. `out` takes stdout and stderr (a file, never a pipe
    nobody reads). On Windows the child gets its own process group so cancelling it does not touch us."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    return subprocess.Popen(
        command(feb.name, log_name, plot_name, exe),
        cwd=feb.parent, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, creationflags=flags,
        env=environment(threads),
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
