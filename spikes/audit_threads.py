"""One-off measurement (not product code): what does running FEBio single-threaded cost, and what does it buy?

Runs one existing .feb (for example a prototype run folder's model.feb) with 1, 4, 8 and 16 threads, straight
through FEBio (no run folder), and prints the wall time and the largest difference of any logged node
coordinate from the 1-thread result. docs/13 E-08 quotes the numbers; ADR-37 item 1 is the decision it tests.

    uv run python spikes/audit_threads.py <model.feb> <an empty work folder>
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from asrp_core import febio
from asrp_core.doctor import febio_exe

THREADS = (1, 4, 8, 16)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    feb, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    exe = febio_exe()
    base = None
    for threads in THREADS:
        d = work / f"t{threads}"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        shutil.copyfile(feb, d / "model.feb")
        env = {**os.environ, "OMP_NUM_THREADS": str(threads), "MKL_NUM_THREADS": str(threads)}
        t0 = time.perf_counter()
        subprocess.run(febio.command("model.feb", "model.log", "model.xplt", exe), cwd=d, env=env,
                       capture_output=True, timeout=3600)
        seconds = time.perf_counter() - t0
        hist = febio.read_node_data(d / "model.log", "positions")
        ids = sorted(hist.values[0])
        pos = np.array([[frame[n] for n in ids] for frame in hist.values])
        if base is None:
            base = pos
        diff = float(np.abs(pos - base).max()) if pos.shape == base.shape else float("nan")
        print(f"threads {threads:2d}: {seconds:6.1f} s, {seconds / max(len(hist.times), 1):.3f} s per frame, "
              f"{len(hist.times)} frames, largest difference from 1 thread {diff:.3e} mm (FEBio coordinates)", flush=True)
        (d / "model.xplt").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
