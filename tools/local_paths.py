"""Where the data that stays outside the repository lives ON THIS MACHINE.

Nothing here is a default path. A location comes from an environment variable or from a file in `.local/`,
a folder at the repository root that git ignores and tools/check_no_lab_files.py refuses to see tracked:

    .local/ziva_trip_pointer.json   written by tools/lab_trip_manifest.py: {"manifest": "<path>", ...}
    .local/paths.json               written by hand: {"lab_data": "<folder with the lab's own files>"}

    ASRP_ZIVA_TRIP   the trip folder (the one that holds manifest.json); wins over the pointer file
    ASRP_LAB_DATA    the lab data folder; wins over paths.json

A function returns None when the location is not known on this machine. Callers then skip and say so.
"""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCAL = REPO / ".local"
POINTER = LOCAL / "ziva_trip_pointer.json"
PATHS = LOCAL / "paths.json"


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def ziva_trip_manifest() -> Path | None:
    """The manifest.json of the Ziva machine trip, or None."""
    folder = os.environ.get("ASRP_ZIVA_TRIP")
    if folder:
        return Path(folder) / "manifest.json"
    manifest = _read(POINTER).get("manifest")
    return Path(manifest) if manifest else None


def ziva_trip() -> Path | None:
    """The trip folder, or None when it is not known or not on this machine."""
    manifest = ziva_trip_manifest()
    return manifest.parent if manifest is not None and manifest.is_file() else None


def lab_data() -> Path | None:
    """The folder with the lab's own files (target poses, bind data), or None."""
    folder = os.environ.get("ASRP_LAB_DATA") or _read(PATHS).get("lab_data")
    return Path(folder) if folder else None


HOW_TO_SET = ("set ASRP_ZIVA_TRIP / ASRP_LAB_DATA, or write .local/ziva_trip_pointer.json / .local/paths.json "
              "(tools/local_paths.py); the data stays outside the repo")
