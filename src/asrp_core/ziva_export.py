"""Reading a Ziva export folder (T-11; docs/07 section 4.1, docs/13 E-15). numpy and the standard library only.

An export folder is what tools/ziva_machine_export.py wrote on the lab's Ziva machine: per stream a
`<id>.points.f32` (little-endian float32 x y z, frame-major then vertex-major, scene units, Y up), `<id>.obj`
(the rest shape's connectivity), `<id>.abc`, plus `session_report.json`, `readback_report.json`, `seal.json` and
`motion.json`. The data stays outside the repository; nothing here copies it anywhere.

A stream is taken for what its FILE holds, not for what the report plans: the real frames come from the file's
length (a report can say 0 to 46 over a file that has 34 frames), a stream whose frames do not reach the
requested range is a prefix and is marked so, and the export's overall status is not read at all (E-15).

Nothing here converts units: points come back as they are, in scene units. The caller owns the conversion to mm,
Z up (asrp_core.asset.coords).
"""

import hashlib
import json
from pathlib import Path

import numpy as np

from asrp_core.asset import coords


class ZivaExportError(ValueError):
    """The folder cannot be read as an export; the message says what is wrong."""


def _json(folder: Path, name: str, required: bool = True) -> dict | None:
    path = folder / name
    if not path.is_file():
        if required:
            raise ZivaExportError(f"{folder.name} has no {name}; it is not a Ziva export folder")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ZivaExportError(f"{folder.name}/{name} is not valid JSON (line {e.lineno}: {e.msg})") from None
    if not isinstance(data, dict):
        raise ZivaExportError(f"{folder.name}/{name} is not a JSON object")
    return data


def session(folder) -> dict:
    """session_report.json of an export folder."""
    return _json(Path(folder), "session_report.json")


def _stream(report: dict, stream_id: str, folder: Path) -> dict:
    for entry in report.get("streams", []):
        if entry.get("id") == stream_id:
            return entry
    raise ZivaExportError(f"{folder.name} has no stream {stream_id!r}; it has "
                          f"{', '.join(sorted(str(e.get('id')) for e in report.get('streams', [])))[:200]}")


def identity(folder, stream_id: str) -> dict:
    """What the card asks of every stream (docs/09 T-11): the run id (the export folder's name), the stream id, the
    real frames, the file's length, how far the motion file covers, and the read-back result. Plus whether the
    stream may be used as a complete run: it may not when its file is a prefix of the requested frames or does
    not match its own seal. "complete" and "why_not_complete" say so; the export's overall status is ignored."""
    folder = Path(folder)
    report = session(folder)
    entry = _stream(report, stream_id, folder)
    samples = folder / entry["samples"]
    if not samples.is_file():
        raise ZivaExportError(f"{folder.name} lists {entry['samples']} for {stream_id} but the file is not there")
    vertices, listed = int(entry["vertices"]), [int(f) for f in entry["frames"]]
    size, row = samples.stat().st_size, int(entry["vertices"]) * 12
    problems = []
    if size % row:
        problems.append(f"the file's length {size} is not a whole number of frames of {vertices} vertices")
    real_count = size // row
    real = listed[:real_count]
    if len(real) < real_count:
        problems.append(f"the file holds {real_count} frames but the report lists only {len(listed)}")
        real_count = len(real)
    wanted = report.get("requested_frames") or [listed[0], listed[-1]]
    prefix = bool(real) and real[-1] < int(wanted[1])
    if prefix:
        problems.append(f"only a prefix: the file's frames end at {real[-1]}, the requested range was "
                        f"{wanted[0]} to {wanted[1]}")
    motion = _json(folder, "motion.json", required=False)
    coverage = None
    if motion is not None:
        ids = [int(i) for i in motion.get("frame_ids", [])]
        coverage = {"first": min(ids), "last": max(ids)} if ids else None
    if coverage is None:
        problems.append("there is no motion.json, so what motion the frames cover is not recorded")
    elif real and coverage["last"] < real[-1]:
        problems.append(f"the motion record ends at frame {coverage['last']}, before the stream's frame {real[-1]}")
    seal = _json(folder, "seal.json", required=False)
    sealed = None if seal is None else seal.get("files", {}).get(samples.name)
    sha_ok = None
    if sealed is not None:
        sha_ok = hashlib.sha256(samples.read_bytes()).hexdigest() == sealed["sha256"]
        if not sha_ok:
            problems.append(f"{samples.name} does not match the sha256 in seal.json")
    back = _json(folder, "readback_report.json", required=False)
    readback = None if back is None else {
        "alembic_verified": back.get("alembic_verified"), "ok": back.get("ok"),
        "streams_checked": back.get("streams_checked"), "max_error_scene_units": back.get("max_error"),
        "problems": len(back.get("problems", [])),
        "note": "as written on the Ziva machine, for the whole export, not for this stream alone"}
    return {
        "run_id": folder.name, "stream_id": stream_id, "role": entry.get("role"), "vertices": vertices,
        "real_frames": {"first": real[0] if real else None, "last": real[-1] if real else None, "count": len(real),
                        "listed_in_report": len(listed)},
        "file": {"name": samples.name, "bytes": int(size), "bytes_expected_for_listed_frames": len(listed) * row,
                 "sha256_matches_seal": sha_ok},
        "motion_coverage": coverage, "readback": readback,
        "topology": {"hash": entry.get("topology"), "varies_per_frame": entry.get("topology_varies")},
        "complete": not problems, "why_not_complete": problems,
    }


def read_points(folder, stream_id: str) -> tuple[np.ndarray, list[int]]:
    """A stream's points, float64 (frames, vertices, 3), scene units as the export wrote them, and the real frame
    numbers (the ones the file holds). A file that is not a whole number of frames is an error."""
    folder = Path(folder)
    ident = identity(folder, stream_id)
    if ident["file"]["bytes"] % (ident["vertices"] * 12):
        raise ZivaExportError(f"{folder.name}/{ident['file']['name']}: {ident['why_not_complete'][0]}")
    count = ident["real_frames"]["count"]
    points = np.fromfile(folder / ident["file"]["name"], dtype="<f4").astype(np.float64)
    points = points.reshape(-1, ident["vertices"], 3)[:count]
    first = ident["real_frames"]["first"]
    return points, list(range(first, first + count)) if count else []


def rest_faces(folder, stream_id: str) -> tuple[np.ndarray, np.ndarray]:
    """The stream's rest OBJ: its vertices (scene units) and triangles (0-based). In Ziva the triangle connectivity
    changes every frame (polyTriangulate); this file holds one frame's, which is frame 0 of the export."""
    folder = Path(folder)
    entry = _stream(session(folder), stream_id, folder)
    name = entry.get("rest_obj")
    if not name or not (folder / name).is_file():
        raise ZivaExportError(f"{folder.name} has no rest OBJ for {stream_id}")
    vertices, faces = coords.read_obj(folder / name)
    tri = coords.triangulate(faces)
    return np.asarray(vertices, dtype=np.float64), np.asarray(tri, dtype=np.int64)


def body_transforms(folder, key_ends_with: str, mm_per_scene_unit: float, frames: list[int]) -> np.ndarray:
    """The motion of one joint or bone of motion.json as 4x4 column-vector transforms in mm, Z up, relative to its
    own pose at the first of `frames`, one per frame: (len(frames), 4, 4).

    motion.json holds Maya world matrices for ROW vectors with the translation at indices 12 to 14, in scene units
    and Maya's axes. The relative motion is inverse(M0) taken in world axes (so the object's own scale and rest
    orientation drop out), then changed to mm and the core's axes (x, y, z) -> (x, -z, y) by the same linear map
    as the points: R' = L R L^-1, t' = L t."""
    folder = Path(folder)
    motion = _json(folder, "motion.json")
    ids = [int(i) for i in motion["frame_ids"]]
    names = [k for k in motion["frames"][0] if k.split("|")[-1] == key_ends_with]
    if len(names) != 1:
        raise ZivaExportError(f"{folder.name}/motion.json has {len(names)} bodies called {key_ends_with!r}, expected 1")
    where = {frame: i for i, frame in enumerate(ids)}
    missing = [f for f in frames if f not in where]
    if missing:
        raise ZivaExportError(f"{folder.name}/motion.json has no frame {missing[0]} (it covers {ids[0]} to {ids[-1]})")
    world = [np.asarray(motion["frames"][where[f]][names[0]], dtype=np.float64).reshape(4, 4).T for f in frames]
    to_mm = mm_per_scene_unit * np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    back = np.linalg.inv(to_mm)
    out = np.empty((len(frames), 4, 4))
    base = np.linalg.inv(world[0])
    for i, w in enumerate(world):
        rel = w @ base
        out[i] = np.eye(4)
        out[i, :3, :3] = to_mm @ rel[:3, :3] @ back
        out[i, :3, 3] = to_mm @ rel[:3, 3]
    return out
