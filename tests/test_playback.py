import json
import struct

import numpy as np
import pytest

from asrp_core.playback import boundary_faces, write_bundle, write_pc2, write_surface_bundle

# Unit tet, positively oriented, and a second tet sharing face (1, 2, 3) on the other side.
NODES = {1: (0, 0, 0), 2: (1, 0, 0), 3: (0, 1, 0), 4: (0, 0, 1), 5: (1, 1, 1)}
TET_A = (1, 2, 3, 4)
TET_B = (2, 3, 4, 5)


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def test_single_tet_faces_point_outward():
    faces = boundary_faces({"tissue": [TET_A]})
    centroid = [sum(NODES[n][i] for n in TET_A) / 4 for i in range(3)]

    assert len(faces) == 4
    for (a, b, c), name in faces:
        normal = cross(sub(NODES[b], NODES[a]), sub(NODES[c], NODES[a]))
        face_centre = [(NODES[a][i] + NODES[b][i] + NODES[c][i]) / 3 for i in range(3)]
        assert dot(normal, sub(face_centre, centroid)) > 0
        assert name == "tissue"


def test_face_shared_across_domains_is_interior():
    faces = boundary_faces({"tissue": [TET_A], "jaw": [TET_B]})

    keys = {tuple(sorted(face)) for face, _ in faces}
    assert len(faces) == 6
    assert (2, 3, 4) not in keys
    assert {name for _, name in faces} == {"tissue", "jaw"}


def test_pc2_layout(tmp_path):
    path = tmp_path / "c.pc2"
    write_pc2(path, [[(0, 0, 0), (1, 2, 3)], [(4, 5, 6), (7, 8, 9)]])

    data = path.read_bytes()
    magic, version, points, start, rate, samples = struct.unpack("<12siiffi", data[:32])
    assert (magic, version, points, start, rate, samples) == (b"POINTCACHE2\0", 1, 2, 0.0, 1.0, 2)
    assert len(data) == 32 + 2 * 2 * 3 * 4
    assert struct.unpack("<3f", data[32 + 12 * 3 : 32 + 12 * 4]) == (7.0, 8.0, 9.0)


def test_pc2_from_an_array_is_byte_identical_to_the_old_per_value_packing(tmp_path):
    rng = np.random.default_rng(3)
    frames = rng.normal(scale=40.0, size=(5, 7, 3))  # float64 values that do not fit float32 exactly
    write_pc2(tmp_path / "array.pc2", frames)
    write_pc2(tmp_path / "lists.pc2", frames.tolist())

    old = struct.pack("<12siiffi", b"POINTCACHE2\0", 1, 7, 0.0, 1.0, 5)  # what the module wrote before: struct, per value
    for frame in frames.tolist():
        old += struct.pack("<21f", *(c for p in frame for c in p))
    assert (tmp_path / "array.pc2").read_bytes() == (tmp_path / "lists.pc2").read_bytes() == old
    assert not np.array_equal(frames, frames.astype("<f4"))  # the test does exercise the float32 rounding


def test_pc2_refuses_frames_with_different_point_counts_or_a_wrong_shape(tmp_path):
    with pytest.raises(ValueError, match="same number of points"):
        write_pc2(tmp_path / "c.pc2", [[(0, 0, 0), (1, 2, 3)], [(4, 5, 6)]])
    with pytest.raises(ValueError, match="shape"):
        write_pc2(tmp_path / "c.pc2", np.zeros((3, 4)))


def test_bundle_keeps_vertex_order_consistent(tmp_path):
    feb = tmp_path / "m.feb"
    feb.write_text("<febio_spec/>")
    frames = [NODES, {n: (x + 10, y, z) for n, (x, y, z) in NODES.items()}]

    manifest = json.loads(write_bundle(tmp_path, NODES, {"tissue": [TET_A]}, frames, 30, feb).read_text())

    # Node 5 belongs to no tet, so it must not become a vertex.
    assert manifest["node_ids"] == [1, 2, 3, 4]
    assert manifest["vertices"][1] == list(NODES[2])
    data = (tmp_path / "playback.pc2").read_bytes()
    second_frame_vertex_1 = struct.unpack("<3f", data[32 + 4 * 12 + 12 : 32 + 4 * 12 + 24])
    assert second_frame_vertex_1 == (11.0, 0.0, 0.0)
    assert len(manifest["faces"]) == len(manifest["face_materials"]) == 4


def test_a_surface_bundle_gains_a_second_cache_and_versions_only_when_given_final_frames(tmp_path):
    feb = tmp_path / "m.feb"
    feb.write_text("<febio_spec/>")
    verts, faces = [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)]
    frames = np.array([verts, verts], dtype=float)
    final = frames + np.array([0.0, 0.0, 2.0])
    plain, layered = tmp_path / "plain", tmp_path / "layered"
    plain.mkdir()
    layered.mkdir()
    write_surface_bundle(plain, verts, faces, frames, 30, feb, "tissue", "t.obj")
    write_surface_bundle(layered, verts, faces, frames, 30, feb, "tissue", "t.obj", final)

    assert not (plain / "playback_final.pc2").exists() and "versions" not in json.loads((plain / "playback.json").read_text())
    assert (plain / "playback.pc2").read_bytes() == (layered / "playback.pc2").read_bytes()  # the physics cache is unchanged
    manifest = json.loads((layered / "playback.json").read_text())
    assert manifest.pop("versions") == {"physics": "playback.pc2", "final": "playback_final.pc2"}
    assert manifest == json.loads((plain / "playback.json").read_text())
    write_pc2(tmp_path / "expected.pc2", final)
    assert (layered / "playback_final.pc2").read_bytes() == (tmp_path / "expected.pc2").read_bytes()
