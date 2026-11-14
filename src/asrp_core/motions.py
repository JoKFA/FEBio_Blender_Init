"""The motions an export folder offers: the trajectory files in <export folder>/trajectories/*.json (docs/06 section 3.3).

`list_motions` reads each file with the normal trajectory reader (so a file the solver would refuse is refused
here too) and reports what the Blender panel shows in its list: file name, frames, fps, source tag, whether the
file has a landmark section. A file that cannot be read is listed with its error, not skipped: the researcher then
sees that the file exists and why it cannot be used.
"""

import json
from pathlib import Path

from asrp_core import trajectory

FOLDER = "trajectories"


class MotionsError(ValueError):
    """The folder has no motions to list; the message says what to do."""


def motions_folder(path) -> Path:
    """<export folder>/trajectories, or the folder itself when it holds the trajectory files directly."""
    path = Path(path)
    if (path / FOLDER).is_dir():
        return path / FOLDER
    if path.is_dir() and any(path.glob("*.json")):
        return path
    raise MotionsError(f"{path} has no '{FOLDER}' folder; give the export folder (for example data/lab_export)")


def list_motions(path) -> list[dict]:
    """One entry per trajectory file, sorted by file name. An unreadable file has "error" instead of the numbers."""
    folder = motions_folder(path)
    out = []
    for file in sorted(folder.glob("*.json"), key=lambda p: p.name.lower()):
        try:
            t = trajectory.read(file)
        except trajectory.TrajectoryError as e:
            out.append({"file": file.name, "error": str(e)})
            continue
        except (OSError, ValueError) as e:  # not readable, or not text at all (a UnicodeDecodeError is a ValueError)
            out.append({"file": file.name, "error": f"the file cannot be read as text ({type(e).__name__}: {e})"})
            continue
        out.append({"file": file.name, "frames": t.frames, "fps": t.fps, "source_tag": t.source_tag or "unstated",
                    "landmarks": t.landmarks is not None})
    return out


def lines(motions: list[dict]) -> list[str]:
    """The machine-readable output: one JSON object per line (the add-on reads it back with json.loads)."""
    return [json.dumps(m, ensure_ascii=True) for m in motions]
