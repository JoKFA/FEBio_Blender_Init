"""Fail when git tracks something that must not leave this machine.

    uv run python tools/check_no_lab_files.py

Three tests on everything in the index (committed or staged):
1. the name: scene files, pickles, caches, plug-in binaries and licence files are never ours; nothing under
   `.local/` (this machine's own settings) and no trip pointer file is ever tracked;
2. the content: a SHA-256 that is listed in the manifest of a lab-machine trip. The manifest lives with
   the data, outside the repo; tools/local_paths.py says where it is on this machine. On a machine that
   does not have the data only the other tests run, and the output says so;
3. this machine's own paths: no tracked text file names the folder this checkout sits in, or this user's
   home folder. A path like that is useful to one person on one machine and to nobody else, and it tells
   others where private data lives.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_paths  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN = (".mb", ".ma", ".pkl", ".abc", ".f32", ".zbuilder", ".mll", ".lic")
LOCAL_ONLY = (".local/", "ziva_trip_pointer.json")
# The owner's instruction file names his own folders on purpose; tools do not edit it (see the file itself).
PATHS_ALLOWED_IN = ("AGENTS.md", "CLAUDE.md")
TEXT_LIMIT = 5_000_000


def violations(files: dict[str, str], lab_hashes: set[str]) -> list[str]:
    """files maps a tracked path to its SHA-256; returns one line per file that must not be tracked."""
    found = []
    for path, digest in sorted(files.items()):
        if path.lower().endswith(FORBIDDEN):
            found.append(f"{path}: files of this kind are never committed")
        elif path.startswith(LOCAL_ONLY[0]) or path.endswith(LOCAL_ONLY[1]):
            found.append(f"{path}: this machine's own settings are never committed")
        elif digest in lab_hashes:
            found.append(f"{path}: same content as a file brought back from the lab's machine")
    return found


def machine_markers(repo: Path = REPO, home: Path | None = None) -> list[str]:
    """Lower-case, forward-slash prefixes that mean "a path on this machine": the folder the checkout sits
    in and the user's home. A drive root alone is not a marker (it would match every path on that drive)."""
    out = []
    for folder in (repo.resolve().parent, (home or Path.home()).resolve()):
        if len(folder.parts) >= 2:
            out.append(folder.as_posix().lower().rstrip("/") + "/")
    return out


def _normal(text: str) -> str:
    """Backslashes (also doubled, as in JSON) to single forward slashes, lower case."""
    text = text.lower().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def machine_paths(texts: dict[str, str], markers: list[str]) -> list[str]:
    """texts maps a tracked path to its text; returns one line per file that names a path of this machine."""
    found = []
    for path, text in sorted(texts.items()):
        if path in PATHS_ALLOWED_IN:
            continue
        normal = _normal(text)
        hit = next((m for m in markers if _normal(m) in normal), None)
        if hit:
            line = next(i for i, row in enumerate(text.splitlines(), 1) if _normal(hit) in _normal(row + "/"))
            found.append(f"{path}:{line}: names a path of this machine ({hit}...); read the location from "
                         "tools/local_paths.py instead, or use a made-up example path")
    return found


def lab_hashes() -> tuple[set[str], str]:
    manifest = local_paths.ziva_trip_manifest()
    if manifest is None:
        return set(), "NOT VERIFIED against the lab's files: this machine does not say where the trip data is"
    if not manifest.is_file():
        return set(), f"NOT VERIFIED against the lab's files: {manifest} is not on this machine"
    entries = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    if not entries:
        sys.exit(f"check FAILED: {manifest} lists no files")
    return {e["sha256"] for e in entries}, f"{len(entries)} hashes of the lab's files"


def main() -> int:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout.decode().split("\0")
    data = {p: (REPO / p).read_bytes() for p in tracked if p and (REPO / p).is_file()}
    if not data:
        sys.exit("check FAILED: git lists no tracked file")
    files = {p: hashlib.sha256(b).hexdigest() for p, b in data.items()}
    texts = {p: b.decode("utf-8", errors="ignore") for p, b in data.items() if len(b) <= TEXT_LIMIT and b"\0" not in b}
    hashes, how = lab_hashes()
    found = violations(files, hashes) + machine_paths(texts, machine_markers())
    print(f"{len(files)} tracked files checked ({how}; {len(texts)} text files searched for this machine's paths)")
    for line in found:
        print("NOT ALLOWED: " + line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
