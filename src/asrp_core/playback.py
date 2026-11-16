"""Turn a solved tet mesh into something Blender can play: a surface mesh plus a PC2 point cache.

The bundle is a directory with:
- playback.json: surface vertices (rest, mm), faces, per-face material, and for each
  vertex the FEBio node id it came from (null for a display mesh carried by the tet
  mesh, `write_surface_bundle`, T-06a);
- playback.pc2: per-frame surface vertex positions in the same order, read by
  Blender's Mesh Cache modifier;
- playback_final.pc2, only when the run has a landmark layer (T-09): the same vertices with the landmarks
  moved. playback.json then also has "versions": {"physics": "playback.pc2", "final": "playback_final.pc2"}
  and the add-on loads either one; "cache" is always the physics version.
Data stays in mm here; the add-on converts to Blender units at the boundary.
"""

import hashlib
import json
import struct
from collections.abc import Sequence
from pathlib import Path

import numpy as np

FORMAT = "asrp-playback/1"

# Outward faces of a positively oriented tet (a, b, c, d).
_TET_FACES = ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3))


def boundary_faces(domains: dict[str, Sequence[Sequence[int]]]) -> list[tuple[tuple[int, int, int], str]]:
    """Faces that belong to exactly one tet across all domains, outward-wound, tagged with their domain.

    A face shared by two tets (inside a domain or on the interface between domains) is interior.
    """
    seen: dict[tuple[int, ...], tuple[tuple[int, int, int], str] | None] = {}
    for name, tets in domains.items():
        for tet in tets:
            for i, j, k in _TET_FACES:
                face = (tet[i], tet[j], tet[k])
                key = tuple(sorted(face))
                seen[key] = None if key in seen else (face, name)
    return [entry for entry in seen.values() if entry is not None]


def write_pc2(path: Path, frames: Sequence[Sequence[Sequence[float]]] | np.ndarray) -> None:
    """PC2: 'POINTCACHE2\\0', version 1, point count, start frame, sample rate, sample count, float32 xyz.

    `frames` is a numpy array (frames, points, 3) or nested lists of that shape. Sample rate is in frames per
    sample (1 = one sample per frame), not fps.
    """
    try:
        data = np.asarray(frames, dtype=np.float64)
    except ValueError:
        raise ValueError("every frame needs the same number of points") from None
    if data.ndim != 3 or data.shape[2] != 3 or data.shape[0] == 0:
        raise ValueError(f"a point cache needs frames of (x, y, z) points, got an array of shape {list(data.shape)}")
    with path.open("wb") as f:
        f.write(struct.pack("<12siiffi", b"POINTCACHE2\0", 1, data.shape[1], 0.0, 1.0, data.shape[0]))
        f.write(data.astype("<f4").tobytes())


def write_bundle(
    out: Path,
    nodes: dict[int, Sequence[float]],
    domains: dict[str, Sequence[Sequence[int]]],
    frames: Sequence[dict[int, Sequence[float]]],
    fps: float,
    feb: Path,
) -> Path:
    faces = boundary_faces(domains)
    node_ids = sorted({n for face, _ in faces for n in face})
    index = {n: i for i, n in enumerate(node_ids)}
    materials = list(domains)
    manifest = {
        "format": FORMAT,
        "units": "mm",
        "fps": fps,
        "frame_count": len(frames),
        "node_ids": node_ids,
        "vertices": [list(nodes[n]) for n in node_ids],
        "faces": [[index[n] for n in face] for face, _ in faces],
        "face_materials": [materials.index(name) for _, name in faces],
        "materials": materials,
        "cache": "playback.pc2",
        "source": {"feb": feb.name, "feb_sha256": hashlib.sha256(feb.read_bytes()).hexdigest()},
    }
    write_pc2(out / "playback.pc2", [[frame[n] for n in node_ids] for frame in frames])
    path = out / "playback.json"
    path.write_text(json.dumps(manifest))
    return path


def write_surface_bundle(
    out: Path,
    vertices: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    frames: Sequence[Sequence[Sequence[float]]],
    fps: float,
    feb: Path,
    material: str,
    surface: str,
    final_frames: Sequence[Sequence[Sequence[float]]] | None = None,
) -> Path:
    """The same bundle for a display mesh carried by the tet mesh (T-06a, asrp_core.embed): the surface is
    that mesh as it is (its own faces, triangles or quads), so there is no FEBio node per vertex and
    `node_ids` is null. `surface` names the mesh file it came from.
    `final_frames` (T-09): the same surface with the landmark layer applied; it gets its own cache,
    playback_final.pc2, and the manifest then names both under "versions". Without it nothing changes: the
    files are exactly what they were before the layer existed."""
    manifest = {
        "format": FORMAT,
        "units": "mm",
        "fps": fps,
        "frame_count": len(frames),
        "node_ids": None,
        "vertices": [[float(c) for c in v] for v in vertices],
        "faces": [[int(i) for i in f] for f in faces],
        "face_materials": [0] * len(faces),
        "materials": [material],
        "cache": "playback.pc2",
        "source": {"feb": feb.name, "feb_sha256": hashlib.sha256(feb.read_bytes()).hexdigest(), "surface": surface},
    }
    if final_frames is not None:
        manifest["versions"] = {"physics": "playback.pc2", "final": "playback_final.pc2"}
        write_pc2(out / "playback_final.pc2", final_frames)
    write_pc2(out / "playback.pc2", frames)
    path = out / "playback.json"
    path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    return path


def read_pc2(path: Path) -> np.ndarray:
    """A PC2 file back as float32 (frames, points, 3); what `write_pc2` wrote, and what Blender's Mesh Cache
    modifier reads. The header is checked against the file's length."""
    raw = Path(path).read_bytes()
    head = struct.calcsize("<12siiffi")
    if len(raw) < head:
        raise ValueError(f"{path} is shorter than a PC2 header")
    magic, version, points, _start, _rate, samples = struct.unpack("<12siiffi", raw[:head])
    if magic != b"POINTCACHE2\0" or version != 1:
        raise ValueError(f"{path} is not a version 1 PC2 file")
    if len(raw) != head + samples * points * 12:
        raise ValueError(f"{path} says {samples} frames of {points} points but its length does not fit")
    return np.frombuffer(raw, dtype="<f4", offset=head).reshape(samples, points, 3)


def write_reference_bundle(
    out: Path,
    vertices: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    frames: Sequence[Sequence[Sequence[float]]],
    fps: float,
    source: dict,
    topology_note: str,
    material: str = "ziva",
    final_frames: Sequence[Sequence[Sequence[float]]] | None = None,
) -> Path:
    """The same bundle for a result that was not solved here (T-11: Ziva's lips from an export). The files are
    the ones `write_surface_bundle` writes (playback.json, playback.pc2, playback_final.pc2 with "versions"), so
    the add-on loads them like a run of ours. `source` is written as it is; the add-on names the object from
    source["feb"], so give it a name there (the export folder's). `topology_note` goes into the manifest as
    "topology": a fixed-topology package cannot carry a connectivity that changes per frame, and it says so."""
    if "feb" not in source:
        raise ValueError("source needs a 'feb' entry: the add-on names the object after it")
    manifest = {
        "format": FORMAT,
        "units": "mm",
        "fps": fps,
        "frame_count": len(frames),
        "node_ids": None,
        "vertices": [[float(c) for c in v] for v in vertices],
        "faces": [[int(i) for i in f] for f in faces],
        "face_materials": [0] * len(faces),
        "materials": [material],
        "cache": "playback.pc2",
        "source": source,
        "topology": topology_note,
    }
    if final_frames is not None:
        manifest["versions"] = {"physics": "playback.pc2", "final": "playback_final.pc2"}
        write_pc2(out / "playback_final.pc2", final_frames)
    write_pc2(out / "playback.pc2", frames)
    path = out / "playback.json"
    path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    return path
