import math
from pathlib import Path

import numpy as np
import pytest

from asrp_core.tetmesh import TetMesh, min_dihedral_deg, quality, signed_volumes, surface_volume, tetrahedralize

LIPS = Path(__file__).resolve().parents[1] / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj"
MM_PER_UNIT = 0.962  # provisional, docs/11 Q3

# 10 mm cube, outward-wound triangles.
CUBE = np.array([(x, y, z) for z in (0, 10) for y in (0, 10) for x in (0, 10)], dtype=float)
CUBE_TRIANGLES = np.array([
    (0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6), (0, 1, 5), (0, 5, 4),
    (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5),
])
# The corner tet of a unit cube: three right angles at the origin edges, arccos(1/sqrt 3) at the rest.
CORNER = TetMesh(np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], dtype=float), np.array([(0, 1, 2, 3)]))


def read_lips_mm():
    """The lip OBJ in mm, Z up, triangles: the conversion T-02 will own (docs/03 section 10)."""
    vertices, triangles = [], []
    with LIPS.open(encoding="ascii") as f:
        for line in f:
            if line.startswith("v "):
                x, y, z = (float(c) * MM_PER_UNIT for c in line.split()[1:4])
                vertices.append((x, -z, y))
            elif line.startswith("f "):
                face = [int(c.split("/")[0]) - 1 for c in line.split()[1:]]
                triangles += [(face[0], face[i], face[i + 1]) for i in range(1, len(face) - 1)]
    return np.array(vertices), np.array(triangles)


def test_corner_tet_measures():
    q = quality(CORNER)
    assert q.volume_mm3 == pytest.approx(1 / 6)
    assert q.min_dihedral_deg == pytest.approx(math.degrees(math.acos(1 / math.sqrt(3))))
    assert q.median_edge_mm == pytest.approx(math.sqrt(2) / 2 + 0.5)  # three edges of 1, three of sqrt 2


def test_flattened_tet_has_no_volume_and_a_zero_angle():
    flat = TetMesh(np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 1e-9)]), np.array([(0, 1, 2, 3)]))
    assert abs(signed_volumes(flat.nodes, flat.tets)[0]) < 1e-9
    assert min_dihedral_deg(flat.nodes, flat.tets)[0] < 1e-3


def test_swapping_two_corners_flips_the_sign():
    assert signed_volumes(CORNER.nodes, np.array([(0, 2, 1, 3)]))[0] == pytest.approx(-1 / 6)


def test_surface_volume_of_cube():
    assert surface_volume(CUBE, CUBE_TRIANGLES) == pytest.approx(1000)


def test_cube_is_filled_with_positive_tets():
    mesh = tetrahedralize(CUBE, CUBE_TRIANGLES, edge_mm=4)
    volumes = signed_volumes(mesh.nodes, mesh.tets)

    assert (volumes > 0).all()
    assert volumes.sum() == pytest.approx(1000, rel=0.01)
    assert len(mesh.tets) > 6  # finer than the cube's own corners


def test_nothing_is_left_in_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tetrahedralize(CUBE, CUBE_TRIANGLES, edge_mm=4)
    assert list(tmp_path.iterdir()) == []


def test_bad_input_is_explained():
    with pytest.raises(ValueError, match="split quads"):
        tetrahedralize(CUBE, [(0, 1, 2, 3)], edge_mm=4)
    with pytest.raises(ValueError, match="positive"):
        tetrahedralize(CUBE, CUBE_TRIANGLES, edge_mm=0)


@pytest.mark.skipif(not LIPS.is_file(), reason="lab export missing: data/lab_export comes from tools/maya_export.py")
def test_real_lip_mesh_despite_self_intersection():
    vertices, triangles = read_lips_mm()
    mesh = tetrahedralize(vertices, triangles, edge_mm=25.4)  # tetSz 26.37 x 0.962
    q = quality(mesh)
    volumes = signed_volumes(mesh.nodes, mesh.tets)

    assert (volumes > 0).all()
    assert q.min_tet_volume_mm3 > 0.01
    assert q.min_dihedral_deg > 5
    # The envelope lets the boundary cut ~1 mm inside the surface; more than 6 % lost means it ran off.
    assert q.volume_mm3 == pytest.approx(abs(surface_volume(vertices, triangles)), rel=0.06)
    # Every node stays within the lips' bounding box, give or take the 1.27 mm envelope.
    assert (mesh.nodes >= vertices.min(axis=0) - 1.27).all() and (mesh.nodes <= vertices.max(axis=0) + 1.27).all()
