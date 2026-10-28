"""Run FEBio and read what it writes. Knows nothing about scenes; the .feb comes from elsewhere."""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

NORMAL_TERMINATION = "N O R M A L   T E R M I N A T I O N"


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
        # -noconfig: results must not depend on a per-machine febio.xml.
        [str(exe), "-i", feb.name, "-o", log.name, "-p", feb.with_suffix(".xplt").name, "-noconfig", "-silent"],
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
