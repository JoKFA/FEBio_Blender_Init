"""Fail when a file that belongs to the lab or to a vendor is tracked by git.

    uv run python tools/check_no_lab_files.py

Two tests on everything in the index (committed or staged):
1. the name: scene files, pickles, caches, plug-in binaries and licence files are never ours;
2. the content: a SHA-256 that is listed in the manifest of a lab-machine trip. The manifest lives with
   the data, outside the repo; `data/lab_export/ziva_trip_pointer.json` says where. On a machine that
   does not have the data only the name test runs, and the output says so.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POINTER = REPO / "data" / "lab_export" / "ziva_trip_pointer.json"
FORBIDDEN = (".mb", ".ma", ".pkl", ".abc", ".f32", ".zbuilder", ".mll", ".lic")


def violations(files: dict[str, str], lab_hashes: set[str]) -> list[str]:
    """files maps a tracked path to its SHA-256; returns one line per file that must not be tracked."""
    found = []
    for path, digest in sorted(files.items()):
        if path.lower().endswith(FORBIDDEN):
            found.append(f"{path}: files of this kind are never committed")
        elif digest in lab_hashes:
            found.append(f"{path}: same content as a file brought back from the lab's machine")
    return found


def lab_hashes() -> tuple[set[str], str]:
    if not POINTER.is_file():
        return set(), "no pointer file, name test only"
    manifest = Path(json.loads(POINTER.read_text(encoding="utf-8"))["manifest"])
    if not manifest.is_file():
        return set(), f"{manifest} is not on this machine, name test only"
    entries = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    if not entries:
        sys.exit(f"check FAILED: {manifest} lists no files")
    return {e["sha256"] for e in entries}, f"{len(entries)} hashes from {manifest}"


def main() -> int:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout.decode().split("\0")
    files = {p: hashlib.sha256((REPO / p).read_bytes()).hexdigest() for p in tracked if p and (REPO / p).is_file()}
    if not files:
        sys.exit("check FAILED: git lists no tracked file")
    hashes, how = lab_hashes()
    found = violations(files, hashes)
    print(f"{len(files)} tracked files checked ({how})")
    for line in found:
        print("NOT ALLOWED: " + line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
