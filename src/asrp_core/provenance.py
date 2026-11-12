"""The provenance record of one run: what went in, what ran it, what came out, how it ended.

Written as provenance.json in the run folder (docs 04 sections 4, 9). Nothing in it names a place on this
machine: inputs are keyed by their name inside the run folder, tools by version. That is what lets a copied
run folder be compared and rerun elsewhere. Only the "timing" block changes between identical runs.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from asrp_core import __version__

FORMAT = "asrp-provenance/1"
FILE = "provenance.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_files(root: Path, names: list[str]) -> dict[str, dict]:
    """{name relative to root (forward slashes): {sha256, bytes}}."""
    return {n: {"sha256": sha256_file(root / n), "bytes": (root / n).stat().st_size} for n in names}


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def source_revision() -> dict | None:
    """The git commit of the asrp source that ran, and whether it had uncommitted changes (04 section 5.4:
    the package version alone does not change between milestones). None outside a git checkout."""
    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", "-C", str(SOURCE_ROOT), *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    if not commit:
        return None
    status = git("status", "--porcelain", "--untracked-files=no")
    return {"commit": commit, "dirty": bool(status) if status is not None else None}


def software(febio_version: str | None) -> dict:
    return {
        "asrp": __version__,
        "asrp_source": source_revision(),
        "python": platform.python_version(),
        "febio": febio_version,
        "os": sys.platform,
    }


def write(run_dir: Path, record: dict) -> None:
    """Replace provenance.json in one step, so a reader polling during the run never sees half a file."""
    tmp = run_dir / (FILE + ".tmp")
    tmp.write_text(json.dumps({"format": FORMAT, **record}, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, run_dir / FILE)


def read(run_dir: Path) -> dict:
    return json.loads((run_dir / FILE).read_text(encoding="utf-8"))


def mismatches(run_dir: Path) -> list[str]:
    """Recorded files that are missing or no longer match their hash (empty list = the folder is intact)."""
    record = read(run_dir)
    bad = []
    for group in ("inputs", "outputs"):
        for name, info in record.get(group, {}).items():
            path = run_dir / name
            if not path.is_file() or sha256_file(path) != info["sha256"]:
                bad.append(name)
    return bad
