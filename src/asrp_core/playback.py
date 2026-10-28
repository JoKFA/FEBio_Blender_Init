"""Turn a solved tet mesh into something Blender can play: a surface mesh plus a PC2 point cache.

The bundle is a directory with:
- playback.json: surface vertices (rest, mm), faces, per-face material, and for each
  vertex the FEBio node id it came from;
- playback.pc2: per-frame surface vertex positions in the same order, read by
  Blender's Mesh Cache modifier.
Data stays in mm here; the add-on converts to Blender units at the boundary.
"""

import hashlib
import json
import struct
from collections.abc import Sequence
from pathlib import Path

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


def write_pc2(path: Path, frames: Sequence[Sequence[Sequence[float]]]) -> None:
    """PC2: 'POINTCACHE2\\0', version 1, point count, start frame, sample rate, sample count, float32 xyz.

    Sample rate is in frames per sample (1 = one sample per frame), not fps.
    """
    points = len(frames[0])
    with path.open("wb") as f:
        f.write(struct.pack("<12siiffi", b"POINTCACHE2\0", 1, points, 0.0, 1.0, len(frames)))
        for frame in frames:
            assert len(frame) == points, "every frame needs the same number of points"
            f.write(struct.pack(f"<{3 * points}f", *(c for p in frame for c in p)))


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
