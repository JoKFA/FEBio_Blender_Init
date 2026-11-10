import itertools
import json
import math
from pathlib import Path

import numpy as np
import pytest

from asrp_core import tetmesh
from asrp_core.doctor import febio_exe
from asrp_core.tetmesh import TetMesh, min_dihedral_deg, quality, signed_volumes, surface_volume, tetrahedralize

REPO = Path(__file__).resolve().parents[1]
LIPS = REPO / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj"
SAVED = REPO / "data" / "tetmesh" / "lips.json"

# 10 mm cube, outward-wound triangles.
CUBE = np.array([(x, y, z) for z in (0, 10) for y in (0, 10) for x in (0, 10)], dtype=float)
CUBE_TRIANGLES = np.array([
    (0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6), (0, 1, 5), (0, 5, 4),
    (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5),
])  # fmt: skip
# The corner tet of a unit cube: three right angles at the origin edges, arccos(1/sqrt 3) at the rest.
CORNER = TetMesh(np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], dtype=float), np.array([(0, 1, 2, 3)]))


def voxels(cells, origin=(0, 0, 0)) -> TetMesh:
    """Unit cubes at integer (i, j, k), each split into 6 positive tets that conform across faces."""
    ids: dict[tuple, int] = {}
    tets = []
    for cell in sorted(cells):
        for axes in itertools.permutations(range(3)):
            corner = list(cell)
            tet = [ids.setdefault(tuple(corner), len(ids))]
            for axis in axes:
                corner[axis] += 1
                tet.append(ids.setdefault(tuple(corner), len(ids)))
            tets.append(tet)
    nodes = np.zeros((len(ids), 3))
    for p, i in ids.items():
        nodes[i] = np.add(p, origin)
    tets = np.array(tets)
    flip = signed_volumes(nodes, tets) < 0
    tets[flip] = tets[flip][:, [0, 2, 1, 3]]
    return TetMesh(nodes, tets)


def lips_model(weld=()) -> TetMesh:
    """A ring like the lips, x from -6 to 6: lower lip z 0-1, upper lip z 2-3, joined at the corners
    (|x| > 4) and, for each x cell index in `weld`, across the slit too. 2 deep in y."""
    cells = set()
    for i in range(12):
        for j in range(2):
            cells |= {(i, j, 0), (i, j, 2)}
            if i < 2 or i >= 10 or i in weld:
                cells.add((i, j, 1))
    return voxels(cells, origin=(-6, 0, 0))


LIPS_SURFACE = lips_model()  # its boundary is the "surface" the welded models are checked against


def surface_of(mesh: TetMesh):
    return mesh.nodes, tetmesh.boundary_faces(mesh.tets)


# --- measures --------------------------------------------------------------------------------


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


def test_boundary_faces_point_outward():
    cube = voxels({(0, 0, 0)})
    faces = tetmesh.boundary_faces(cube.tets)
    assert len(faces) == 12
    assert surface_volume(cube.nodes, faces) == pytest.approx(1.0)  # negative if wound inward


# --- fTetWild --------------------------------------------------------------------------------


def test_cube_is_filled_with_positive_tets():
    mesh = tetrahedralize(CUBE, CUBE_TRIANGLES, edge_mm=4, envelope_mm=0.1)
    volumes = signed_volumes(mesh.nodes, mesh.tets)

    assert (volumes > 0).all()
    assert volumes.sum() == pytest.approx(1000, rel=0.01)
    assert len(mesh.tets) > 6  # finer than the cube's own corners


def test_nothing_is_left_in_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tetrahedralize(CUBE, CUBE_TRIANGLES, edge_mm=4, envelope_mm=0.1)
    assert list(tmp_path.iterdir()) == []


def test_bad_input_is_explained():
    with pytest.raises(ValueError, match="split quads"):
        tetrahedralize(CUBE, [(0, 1, 2, 3)], edge_mm=4, envelope_mm=0.1)
    with pytest.raises(ValueError, match="positive"):
        tetrahedralize(CUBE, CUBE_TRIANGLES, edge_mm=0, envelope_mm=0.1)


# --- topology --------------------------------------------------------------------------------


def test_one_cube_is_one_closed_piece_of_genus_0():
    t = tetmesh.topology(voxels({(0, 0, 0), (1, 0, 0)}))
    assert (t.components, t.nonmanifold_edges, t.nonmanifold_vertices, t.boundary_components, t.boundary_genus) == (
        1, 0, 0, 1, 0)  # fmt: skip


def test_two_apart_cubes_are_two_pieces():
    t = tetmesh.topology(voxels({(0, 0, 0), (2, 0, 0)}))
    assert t.components == 2 and t.boundary_components == 2


def test_cubes_touching_along_an_edge_are_not_manifold():
    t = tetmesh.topology(voxels({(0, 0, 0), (1, 1, 0)}))
    assert t.components == 2  # an edge does not join two tets
    assert t.nonmanifold_edges > 0


def test_cubes_touching_at_a_corner_are_not_manifold():
    t = tetmesh.topology(voxels({(0, 0, 0), (1, 1, 1)}))
    assert t.nonmanifold_edges == 0
    assert t.nonmanifold_vertices == 1


def test_ring_has_genus_1():
    ring = voxels({(i, j, 0) for i in range(3) for j in range(3) if (i, j) != (1, 1)})
    assert tetmesh.topology(ring).boundary_genus == 1
    assert tetmesh.topology(LIPS_SURFACE).boundary_genus == 1


# --- upper and lower lip apart ---------------------------------------------------------------


def test_slice_counts_the_lips_and_the_corner():
    m = LIPS_SURFACE
    assert tetmesh.slice_pieces(m.nodes, m.tets, 0.5) == 2  # upper and lower lip
    assert tetmesh.slice_pieces(m.nodes, m.tets, 5.5) == 1  # corner
    assert tetmesh.slice_pieces(m.nodes, m.tets, 7.0) == 0  # past the end


def test_separation_of_the_surface_and_of_its_own_tets_agree():
    nodes, faces = surface_of(LIPS_SURFACE)
    xs = tetmesh.slice_positions(nodes)
    want = tetmesh.separation(nodes, faces, xs)
    got = tetmesh.separation(LIPS_SURFACE.nodes, LIPS_SURFACE.tets, xs)
    assert want.width_mm == pytest.approx(7.75, abs=0.01)  # slit is |x| < 4; slices every 0.25 mm
    assert (got.start_mm, got.end_mm) == (want.start_mm, want.end_mm)


def test_a_weld_cuts_the_separation_short():
    xs = tetmesh.slice_positions(LIPS_SURFACE.nodes)
    welded = lips_model(weld={7})  # x 1..2
    got = tetmesh.separation(welded.nodes, welded.tets, xs)
    assert got.end_mm < 1 and got.start_mm < -3.5


def test_crossing_pieces_are_not_apart():
    # Two strips along x whose cross-sections are the diagonals of the same square: they cross.
    def strip(y0, z0, y1, z1, first):
        pts = [(-1, y0, z0), (1, y0, z0), (-1, y1, z1), (1, y1, z1)]
        return pts, [(first, first + 1, first + 2), (first + 1, first + 3, first + 2)]

    a, ta = strip(-1, -1, 1, 1, 0)
    b, tb = strip(-1, 1, 1, -1, 4)
    assert not tetmesh.surface_apart(np.array(a + b, float), np.array(ta + tb), 0.1)
    b_up = [(x, y, z + 5) for x, y, z in b]
    assert tetmesh.surface_apart(np.array(a + b_up, float), np.array(ta + tb), 0.1)


def crossed_surface():
    """LIPS_SURFACE's boundary with the slit faces pushed through each other at x = 2 and 3, like
    the real lips at a mouth corner: the slit is crossed shut from about x = 1.5 to 3.5 and opens
    again from 3.5 to the corner at 4, a pocket. Still one closed surface of genus 1."""
    nodes, faces = surface_of(LIPS_SURFACE)
    nodes = nodes.copy()
    band = np.isin(nodes[:, 0], (2.0, 3.0))
    lower_top, upper_bottom = band & (nodes[:, 2] == 1), band & (nodes[:, 2] == 2)
    nodes[lower_top, 2], nodes[upper_bottom, 2] = 2.3, 0.7
    return nodes, faces


def test_a_crossing_that_opens_again_is_a_pocket():
    nodes, faces = crossed_surface()
    assert tetmesh.surface_topology(faces)[3] == 1
    sep = tetmesh.separation(nodes, faces, tetmesh.slice_positions(nodes))
    assert sep.pockets == 1
    assert 1.0 < sep.end_mm < 2.0  # the central run stops where the crossing starts


def test_a_weld_is_not_a_pocket():
    nodes, faces = surface_of(lips_model(weld={7}))
    assert tetmesh.separation(nodes, faces, tetmesh.slice_positions(nodes)).pockets == 0
    assert tetmesh.surface_topology(faces)[3] == 2  # already a handle of the surface itself


# --- the whole check ---------------------------------------------------------------------------


def test_check_passes_a_mesh_true_to_its_surface():
    report = tetmesh.check(LIPS_SURFACE, *surface_of(LIPS_SURFACE))
    assert report.failures == []
    assert report.separation_ratio == pytest.approx(1.0)
    assert report.outside_fraction == 0.0


def test_check_fails_a_weld_on_one_side():
    report = tetmesh.check(lips_model(weld={7}), *surface_of(LIPS_SURFACE))
    assert any("apart over" in f for f in report.failures)
    assert any("more on one side" in f for f in report.failures)


def test_check_fails_a_filled_slit_on_genus_and_separation():
    report = tetmesh.check(lips_model(weld=set(range(12))), *surface_of(LIPS_SURFACE))
    assert report.topology.boundary_genus == 0
    assert any("genus 0" in f for f in report.failures)
    assert report.separation.width_mm == 0


def test_check_passes_a_welded_ring_true_to_its_own_surface():
    welded = lips_model(weld={7})
    assert tetmesh.check(welded, *surface_of(welded)).failures == []


def test_check_wants_the_pocket_kept():
    keeps_pocket = tetmesh.check(lips_model(weld={8}), *crossed_surface())  # x 2..3 solid, 3..4 open
    fills_pocket = tetmesh.check(lips_model(weld={8, 9}), *crossed_surface())
    assert keeps_pocket.expected_genus == 2 == keeps_pocket.topology.boundary_genus
    assert not any("genus" in f for f in keeps_pocket.failures)
    assert any("genus 1, expected 2" in f for f in fills_pocket.failures)


def test_check_fails_two_pieces_and_inverted_tets():
    two = voxels({(0, 0, 0), (2, 0, 0)})
    assert any("2 pieces" in f for f in tetmesh.check(two, *surface_of(two)).failures)
    inverted = TetMesh(two.nodes, two.tets[:, [0, 2, 1, 3]])
    assert any("inverted" in f for f in tetmesh.check(inverted, *surface_of(two)).failures)


def test_outside_distances():
    cube = voxels({(0, 0, 0)})
    d = tetmesh.outside_distances(cube, np.array([(0.5, 0.5, 0.5), (0.5, 0.5, 2.0), (1.0, 1.0, 1.0)]))
    assert d == pytest.approx([0.0, 1.0, 0.0])


# --- on disk ----------------------------------------------------------------------------------

META = {"units": "mm", "source": {"path": "x.obj", "sha256": "0" * 64}}


def test_save_and_load_round_trip_bit_for_bit(tmp_path):
    mesh = TetMesh(LIPS_SURFACE.nodes + 1 / 3, LIPS_SURFACE.tets)  # floats that need all 17 digits
    digest = tetmesh.save(tmp_path / "m.json", mesh, META)
    back, meta = tetmesh.load(tmp_path / "m.json")
    assert np.array_equal(back.nodes, mesh.nodes) and np.array_equal(back.tets, mesh.tets)
    assert meta["content_sha256"] == digest == tetmesh.content_sha256(back.nodes, back.tets)
    assert meta["format_version"] == tetmesh.FORMAT_VERSION and meta["units"] == "mm"


def test_load_refuses_an_edited_mesh(tmp_path):
    path = tmp_path / "m.json"
    tetmesh.save(path, LIPS_SURFACE, META)
    text = path.read_text()
    path.write_text(text.replace("[-6.0, 0.0, 0.0]", "[-6.0, 0.0, 0.001]", 1))
    with pytest.raises(ValueError, match="changed since it was written"):
        tetmesh.load(path)


def test_load_refuses_another_format_version(tmp_path):
    path = tmp_path / "m.json"
    tetmesh.save(path, LIPS_SURFACE, META)
    data = json.loads(path.read_text())
    data["format_version"] = 99
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="not an asrp-tetmesh v1"):
        tetmesh.load(path)


def test_check_source_notices_a_new_surface(tmp_path):
    surface = tmp_path / "s.obj"
    surface.write_text("v 0 0 0\n")
    meta = {"source": {"sha256": tetmesh.file_sha256(surface)}}
    tetmesh.check_source(meta, surface)
    surface.write_text("v 0 0 1\n")
    with pytest.raises(ValueError, match="not the surface"):
        tetmesh.check_source(meta, surface)


# --- the committed lip mesh -------------------------------------------------------------------


def test_saved_lip_mesh_is_intact_and_passes_the_checks():
    """data/tetmesh/lips.json is committed (ADR-19); everything downstream reads it."""
    mesh, meta = tetmesh.load(SAVED)
    assert meta["units"] == "mm" and meta["up_axis"] == "Z" and meta["mm_per_scene_unit"] == 0.962
    if not LIPS.is_file():
        pytest.skip("lab export missing: the saved mesh is intact, but cannot be checked against the surface")
    tetmesh.check_source(meta, LIPS)
    from build_tetmesh import read_lips_mm

    report = tetmesh.check(mesh, *read_lips_mm(LIPS))
    assert report.failures == []
    assert report.quality.nodes == meta["checks"]["quality"]["nodes"] > 0
    assert report.separation.width_mm == pytest.approx(meta["checks"]["separation"]["width_mm"])


def test_saved_lip_mesh_settles_under_gravity_in_real_febio(tmp_path):
    """T-04 M4: the committed mesh in FEBio, back band fixed, gravity only, dynamic."""
    try:
        febio_exe()
    except FileNotFoundError:
        pytest.skip("FEBio not installed")
    from s2_lips_febio import SMOKE_FRAMES, passed, smoke

    r = smoke(tmp_path)

    assert r["result"].normal_termination, f"FEBio failed, see {r['result'].log}"
    assert r["frames"] == SMOKE_FRAMES
    assert r["fixed"] > 0 and r["fixed_move"] < 1e-6
    assert r["mean_sag"] < -0.01  # down: the gravity sign is right (docs/05 pit 1)
    assert passed(r)
