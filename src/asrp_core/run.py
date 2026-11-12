"""One run = one folder (docs 04 sections 4, 8, 9): inputs copied in, FEBio run, progress, cancel, provenance.

The seam for the generator (T-06a): build a `Prepared` -- a ready .feb, the extra input files to keep with it,
the parameters and the command line to record -- and hand it to `execute`. Stand-in mode (`standin`) builds
one from an existing .feb. Nothing below the seam knows where the .feb came from.

A run ends in exactly one of: complete (physics/ written), failed, cancelled. Only a complete run has result
files; failed and cancelled runs keep the log and a provenance record that says why.
"""

import datetime
import json
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from asrp_core import febio, provenance

FEB_NAME = "model.feb"
LOG_NAME = "model.log"
PLOT_NAME = "model.xplt"
CANCEL_FILE = "cancel"  # create this in a running run folder to cancel it from another process
POSITIONS = "physics/positions.json"  # the header; the numbers are in POSITIONS_ARRAY
POSITIONS_ARRAY = "physics/positions.npy"
POSITIONS_FORMAT = "asrp-positions/2"
POLL_SECONDS = 0.1


class RunError(Exception):
    """Something stopped the run. The message says what to do."""


@dataclass
class Prepared:
    """What the shell needs to run. Scene, trajectory and meshes are the generator's business, not the shell's."""

    feb: Path
    mode: str  # "stand-in" now; "generated" once T-06a plugs in
    command: list[str]  # the asrp command line, paths reduced to names, as recorded in provenance
    parameters: dict = field(default_factory=dict)
    extra_inputs: dict[str, Path] = field(default_factory=dict)  # name inside the run folder -> source file
    # ADR-36: the .feb is written at real size with coordinates x k; FEBio's positions come back scaled by k
    # and are divided by it before they are saved, so positions.npy is always geometric mm.
    length_scale: float = 1.0


@dataclass
class Progress:
    done: int
    total: int | None
    status: str  # running | complete | failed | cancelled


@dataclass
class Result:
    run_dir: Path
    status: str  # complete | failed | cancelled
    frames: int  # time steps FEBio finished
    failure: febio.Failure | None
    febio_pid: int | None


def standin(feb: Path) -> Prepared:
    """Stand-in mode: run an existing .feb as is (no input generation)."""
    if not feb.is_file():
        raise RunError(f"Cannot find the FEBio input {feb}. Check the path.")
    return Prepared(feb, "stand-in", ["asrp", "run", "--feb", feb.name], {"stand_in": True})


def require_ascii(path: Path) -> None:
    # FEBio may fail to open non-ASCII paths on Windows (docs 05, pit 3).
    if not str(path.resolve()).isascii():
        raise RunError(f"{path} has non-English characters in its path, which FEBio may not open. "
                       "Use a folder with only English letters and digits.")


def new_run_dir(runs_dir: Path, name: str) -> Path:
    """runs/<date>_<name>_<nnn>/, the first free number. mkdir is the claim, so two runs cannot share one."""
    stem = re.sub(r"[^A-Za-z0-9-]+", "-", name).strip("-") or "run"
    day = datetime.date.today().isoformat()
    runs_dir.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        path = runs_dir / f"{day}_{stem}_{n:03d}"
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue
    raise RunError(f"Too many runs named {stem} today in {runs_dir}.")


def read_progress(run_dir: Path) -> Progress:
    """Frame i / N of a run, from its provenance and FEBio's log. Works while the run is going."""
    record = provenance.read(run_dir)
    return Progress(febio.steps_done(run_dir / LOG_NAME), record["parameters"].get("total_frames"), record["status"])


_ABS_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|(?<![\w.])/(?=[\w.-]+/))[^\s'\"<>|,;]*")


def scrub_paths(text: str, run_dir: Path) -> str:
    """Reduce local absolute paths in a message to names relative to the run folder (or just the file name)."""
    for base in {str(run_dir), str(run_dir.resolve()), run_dir.as_posix(), run_dir.resolve().as_posix()}:
        text = re.sub(re.escape(base) + r"[\\/]*", "", text)
    return _ABS_PATH.sub(lambda m: re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1], text)


def save_array(header_path: Path, header: dict, array: np.ndarray, array_name: str) -> None:
    """A result as a small JSON header plus a .npy next to it (float64, no pickle): the header gets the array's
    file name and shape. The same array always gives the same bytes."""
    header_path.parent.mkdir(exist_ok=True)
    with (header_path.parent / array_name).open("wb") as f:
        np.save(f, np.ascontiguousarray(array, dtype=np.float64), allow_pickle=False)
    header_path.write_text(json.dumps({**header, "array": array_name, "shape": list(array.shape)}),
                           encoding="utf-8", newline="\n")


def load_array(header_path: Path, key: str) -> dict:
    """The header of `save_array` plus the array under `key`. Refuses a header that does not describe its array."""
    header = json.loads(header_path.read_text(encoding="utf-8"))
    name = header.get("array")
    if not isinstance(name, str) or Path(name).name != name:
        raise RunError(f"{header_path} does not name its array file as a plain file name next to it.")
    try:
        array = np.load(header_path.parent / name, allow_pickle=False)
    except (OSError, ValueError) as e:
        raise RunError(f"Cannot read {name} next to {header_path.name} ({e}). The two files go together; "
                       "copy both or run again.") from e
    if list(array.shape) != header.get("shape"):
        raise RunError(f"{header_path.name} says the array has shape {header.get('shape')} but {name} has shape "
                       f"{list(array.shape)}. The two files do not belong together; run again.")
    return {**header, key: array}


def write_positions(feb: Path, log: Path, out: Path, length_scale: float = 1.0) -> int:
    """physics/positions.json + positions.npy: every node's position (geometric mm: FEBio's coordinates / k) at
    every frame, read from the data file the .feb names or else from the log. Returns frames."""
    try:
        series = febio.read_node_series(feb, log)
    except ValueError as e:
        raise RunError(str(e)) from e
    if not len(series.times):
        raise RunError("FEBio wrote no node positions. The .feb must output "
                       f'<node_data data="x;y;z" name="{febio.NODE_DATA_NAME}"> in its <logfile>.')
    save_array(out, {"format": POSITIONS_FORMAT, "units": "mm", "times_s": series.times.tolist(),
                     "node_ids": series.node_ids.tolist()},
               series.values / length_scale, Path(POSITIONS_ARRAY).name)
    return len(series.times)


def read_positions(path: Path) -> dict:
    """The positions header plus "positions": a float64 array (frames, nodes, 3), geometric mm."""
    data = load_array(path, "positions")
    shape = data["positions"].shape
    if len(shape) != 3 or shape[0] != len(data["times_s"]) or shape[1] != len(data["node_ids"]) or shape[2] != 3:
        raise RunError(f"{path.name} lists {len(data['times_s'])} frames and {len(data['node_ids'])} nodes but its "
                       f"array has shape {list(shape)}. Run again.")
    return data


def _wait(proc, run_dir, total, on_progress, cancel, timeout) -> tuple[bool, febio.Failure | None]:
    """Poll a running FEBio: report progress, honour cancel and timeout. Returns (cancelled, failure)."""
    started, last = time.perf_counter(), -1
    steps = febio.StepCounter(run_dir / LOG_NAME)  # reads only what FEBio appended since the last poll
    try:
        while proc.poll() is None:
            if (cancel is not None and cancel.is_set()) or (run_dir / CANCEL_FILE).exists():
                febio.kill_tree(proc)
                return True, None
            if time.perf_counter() - started > timeout:
                febio.kill_tree(proc)
                return False, febio.Failure(None, f"FEBio did not finish within {timeout:g} s and was stopped")
            done = steps.poll()
            if done != last and on_progress:
                last = done
                on_progress(Progress(done, total, "running"))
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:  # Ctrl-C in the terminal is a cancel; FEBio must not outlive us
        febio.kill_tree(proc)
        return True, None
    done = febio.steps_done(run_dir / LOG_NAME)
    if done != last and on_progress:
        on_progress(Progress(done, total, "running"))
    return False, None


def execute(
    prepared: Prepared,
    runs_dir: Path,
    exe: Path,
    name: str | None = None,
    on_progress: Callable[[Progress], None] | None = None,
    cancel: threading.Event | None = None,
    timeout: float = 3600,
    threads: int = febio.DEFAULT_THREADS,
) -> Result:
    febio.threads_used(threads)  # refuse a bad count before a run folder exists
    require_ascii(runs_dir)
    run_dir = new_run_dir(runs_dir, name or prepared.feb.stem)
    feb = run_dir / FEB_NAME
    shutil.copyfile(prepared.feb, feb)
    input_names = [FEB_NAME]
    for rel, src in prepared.extra_inputs.items():
        (run_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, run_dir / rel)
        input_names.append(rel)

    total = febio.total_steps(feb)
    record = {
        "run_id": run_dir.name,
        "status": "running",
        "mode": prepared.mode,
        "command": prepared.command,
        "inputs": provenance.hash_files(run_dir, input_names),
        # The FEBio arguments (-noconfig, fixed names) are part of the recipe: they decide what FEBio reads.
        "parameters": {**prepared.parameters, "length_scale": prepared.length_scale, "total_frames": total, "timeout_s": timeout,
                       "febio_args": febio.command(FEB_NAME, LOG_NAME, PLOT_NAME, Path("febio4"))[1:],
                       "febio_env": febio.thread_env(threads)},  # the threads actually used
        "software": provenance.software(None),
        "outputs": {},
        "failure": None,
        "timing": {"started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")},
    }
    provenance.write(run_dir, record)

    status, failure, proc, frames = "failed", None, None, 0
    log = run_dir / LOG_NAME
    try:
        with tempfile.TemporaryFile() as console:  # FEBio's console text; read only if the log explains nothing
            t0 = time.perf_counter()
            proc = febio.start(feb, LOG_NAME, PLOT_NAME, exe, console, threads)
            cancelled, failure = _wait(proc, run_dir, total, on_progress, cancel, timeout)
            proc.wait()
            record["timing"]["febio_seconds"] = round(time.perf_counter() - t0, 3)
            console.seek(0)
            console_text = console.read().decode(errors="replace").strip()
        frames = febio.steps_done(log)
        record["software"] = provenance.software(febio.version(log))
        if cancelled:
            status = "cancelled"
        elif failure is None:
            text = log.read_text(errors="replace") if log.exists() else ""
            if proc.returncode == 0 and febio.NORMAL_TERMINATION in text:
                # Judge completion by the time reached, not the step count: FEBio may cut the step and retry
                # (dtmin / max_retries), which is a success with more converged steps than <time_steps> (07 section 3).
                want, got = febio.end_time(feb), febio.time_reached(log)
                if want is not None and (got is None or abs(got - want) > 1e-5 * want):
                    failure = febio.Failure(None, f"FEBio stopped at time {got} of {want:g}")
                else:
                    record["result"] = {"frames_written": write_positions(feb, log, run_dir / POSITIONS, prepared.length_scale)}
                    record["outputs"] = provenance.hash_files(run_dir, [POSITIONS, POSITIONS_ARRAY])
                    status = "complete"
            else:
                failure = febio.read_failure(log) or febio.Failure(
                    None, f"FEBio stopped with exit code {proc.returncode}"
                    + (f": {console_text[-500:]}" if console_text else ""))
    except BaseException as e:
        # Our own failure (e.g. a .feb without node output): leave an honest record, never leave FEBio running.
        if proc is not None:
            febio.kill_tree(proc)
        failure = febio.Failure(None, str(e))
        status = "failed"
        if isinstance(e, RunError):
            return _finish(run_dir, record, status, failure, frames, proc)
        _finish(run_dir, record, status, failure, frames, proc)
        raise
    return _finish(run_dir, record, status, failure, frames, proc)


def _finish(run_dir: Path, record: dict, status: str, failure, frames: int, proc) -> Result:
    if status != "complete":
        shutil.rmtree(run_dir / "physics", ignore_errors=True)  # a failed run shows no results, ever (04 sec. 9)
        record["outputs"] = {}
    try:
        data_file = febio.data_file(run_dir / FEB_NAME, febio.NODE_DATA_NAME)
    except ValueError:
        data_file = None  # not a plain name: it was refused when the results were read, and nothing is deleted
    for attempt in range(50):  # Windows may hold the killed FEBio's file handle for a moment
        try:
            (run_dir / PLOT_NAME).unlink(missing_ok=True)  # derived, large, not part of the run folder (04 sec. 4)
            if data_file:  # likewise the raw node data: it is read into physics/positions.npy and not kept
                (run_dir / data_file).unlink(missing_ok=True)
            break
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.1)
    (run_dir / CANCEL_FILE).unlink(missing_ok=True)
    if status == "cancelled":
        failure = febio.Failure(None, "cancelled by the user")
    record["status"] = status
    record["failure"] = ({"frame": failure.frame, "message": scrub_paths(failure.message, run_dir)}
                         if failure else None)
    record["timing"]["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    provenance.write(run_dir, record)
    return Result(run_dir, status, frames, failure, proc.pid if proc else None)
