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

from asrp_core import febio, provenance

FEB_NAME = "model.feb"
LOG_NAME = "model.log"
PLOT_NAME = "model.xplt"
CANCEL_FILE = "cancel"  # create this in a running run folder to cancel it from another process
POSITIONS = "physics/positions.json"
POSITIONS_FORMAT = "asrp-positions/1"
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


def write_positions(log: Path, out: Path) -> int:
    """physics/positions.json: every node's position (mm) at every frame, parsed from the log. Returns frames."""
    hist = febio.read_node_data(log, "positions")
    if not hist.times:
        raise RunError("The FEBio log has no node positions. The .feb must output "
                       '<node_data data="x;y;z" name="positions"> in its <logfile>.')
    ids = sorted(hist.values[0])
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "format": POSITIONS_FORMAT, "units": "mm", "times_s": hist.times, "node_ids": ids,
        "positions": [[list(frame[n]) for n in ids] for frame in hist.values],
    }), encoding="utf-8")
    return len(hist.times)


def read_positions(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _wait(proc, run_dir, total, on_progress, cancel, timeout) -> tuple[bool, febio.Failure | None]:
    """Poll a running FEBio: report progress, honour cancel and timeout. Returns (cancelled, failure)."""
    started, last = time.perf_counter(), -1
    try:
        while proc.poll() is None:
            if (cancel is not None and cancel.is_set()) or (run_dir / CANCEL_FILE).exists():
                febio.kill_tree(proc)
                return True, None
            if time.perf_counter() - started > timeout:
                febio.kill_tree(proc)
                return False, febio.Failure(None, f"FEBio did not finish within {timeout:g} s and was stopped")
            done = febio.steps_done(run_dir / LOG_NAME)
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
) -> Result:
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
        "parameters": {**prepared.parameters, "total_frames": total, "timeout_s": timeout,
                       "febio_args": febio.command(FEB_NAME, LOG_NAME, PLOT_NAME, Path("febio4"))[1:]},
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
            proc = febio.start(feb, LOG_NAME, PLOT_NAME, exe, console)
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
                if total is not None and frames != total:
                    failure = febio.Failure(None, f"FEBio finished {frames} of {total} time steps")
                else:
                    record["result"] = {"frames_written": write_positions(log, run_dir / POSITIONS)}
                    record["outputs"] = provenance.hash_files(run_dir, [POSITIONS])
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
    (run_dir / PLOT_NAME).unlink(missing_ok=True)  # derived, large, not part of the run folder (04 sec. 4)
    (run_dir / CANCEL_FILE).unlink(missing_ok=True)
    if status == "cancelled":
        failure = febio.Failure(None, "cancelled by the user")
    record["status"] = status
    record["failure"] = {"frame": failure.frame, "message": failure.message} if failure else None
    record["timing"]["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    provenance.write(run_dir, record)
    return Result(run_dir, status, frames, failure, proc.pid if proc else None)
