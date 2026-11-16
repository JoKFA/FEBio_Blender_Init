"""The regular-lattice tet mesh (ADR-44): its builder, its own checks, and the committed file."""

import json
from pathlib import Path

import numpy as np
import pytest
from test_tetmesh import CUBE, CUBE_TRIANGLES, LIPS, LIPS_SURFACE, META, surface_of

from asrp_core import tetmesh
from asrp_core.tetmesh import TetMesh

REPO = Path(__file__).resolve().parents[1]
SAVED_FINE = REPO / "data" / "tetmesh" / "lips.json"
SAVED_LATTICE = REPO / "data" / "tetmesh" / "lips_lattice.json"


def cube_lattice(size=30.0, cell=7.0):
    vertices = CUBE * (size / 10.0) + 0.37  # not on a grid plane
    return vertices, CUBE_TRIANGLES, tetmesh.lattice_tetrahedralize(vertices, CUBE_TRIANGLES, cell)


# --- the builder -----------------------------------------------------------------------------


def test_a_lattice_is_positive_conforming_and_one_piece():
    _, _, mesh = cube_lattice()
    assert (tetmesh.signed_volumes(mesh.nodes, mesh.tets) > 0).all()
    assert len(mesh.tets) % 6 == 0  # 6 per cube
    assert tetmesh.tet_components(mesh.tets) == 1
    # Welded: every node is used, and no two nodes sit at the same place.
    assert len(np.unique(mesh.tets)) == len(mesh.nodes)
    assert len(np.unique(mesh.nodes.round(9), axis=0)) == len(mesh.nodes)
    # Every Kuhn tet of a cube of edge c has volume c^3 / 6, with a smallest dihedral angle of 45 degrees.
    assert np.allclose(tetmesh.signed_volumes(mesh.nodes, mesh.tets), 7.0**3 / 6)
    assert tetmesh.quality(mesh).min_dihedral_deg == pytest.approx(45.0)


def test_the_same_input_gives_the_same_bytes(tmp_path):
    vertices, triangles, first = cube_lattice()
    second = tetmesh.lattice_tetrahedralize(vertices, triangles, 7.0)
    assert tetmesh.content_sha256(first.nodes, first.tets) == tetmesh.content_sha256(second.nodes, second.tets)
    tetmesh.save(tmp_path / "a.json", first, META)
    tetmesh.save(tmp_path / "b.json", second, META)
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_the_origin_is_the_bounding_box_minimum_corner_and_a_shift_moves_it():
    vertices, triangles, mesh = cube_lattice()
    assert np.array_equal(mesh.nodes.min(axis=0), vertices.min(axis=0))  # the lattice starts at the corner
    shifted = tetmesh.lattice_tetrahedralize(vertices, triangles, 7.0, shift_mm=(0, 0, 3.5))
    assert shifted.nodes[:, 2].min() == pytest.approx(vertices[:, 2].min() - 3.5)
    assert tetmesh.content_sha256(shifted.nodes, shifted.tets) != tetmesh.content_sha256(mesh.nodes, mesh.tets)


def test_a_closed_shell_is_filled_inside():
    vertices, triangles, _ = cube_lattice(size=60.0, cell=7.0)
    cubes, touched = tetmesh.lattice_cubes(vertices, triangles, 7.0)
    assert len(cubes) > touched  # the inside cubes no sample touches are kept all the same
    assert (4, 4, 4) in {tuple(c) for c in cubes.tolist()}  # the middle of a 60 mm cube


def test_a_slit_narrower_than_a_cell_is_not_kept_apart():
    """By design (ADR-44): the surface has the lips apart, the lattice does not."""
    ring_nodes, ring_faces = surface_of(LIPS_SURFACE)
    vertices = ring_nodes * 3.0  # a slit 3 mm wide; cells of 10 mm
    mesh = tetmesh.lattice_tetrahedralize(vertices, ring_faces, 10.0)
    xs = tetmesh.slice_positions(vertices, step_mm=1.0)
    assert tetmesh.separation(vertices, ring_faces, xs).width_mm > 0
    assert tetmesh.separation(mesh.nodes, mesh.tets, xs).width_mm == 0


def test_bad_input_is_explained():
    with pytest.raises(ValueError, match="cell size must be positive"):
        tetmesh.lattice_tetrahedralize(CUBE, CUBE_TRIANGLES, 0)
    with pytest.raises(ValueError, match="split quads"):
        tetmesh.lattice_tetrahedralize(CUBE, CUBE_TRIANGLES[:, :2], 5)


# --- its checks ------------------------------------------------------------------------------


def test_check_lattice_passes_a_good_lattice():
    vertices, triangles, mesh = cube_lattice()
    report = tetmesh.check_lattice(mesh, vertices, triangles, 7.0)
    assert report.failures == []
    assert report.outside_count == 0 and report.rebuild_identical and report.components == 1
    assert report.embedded_rest_max_mm < 1e-9 and report.overused_faces == 0


def test_check_lattice_fails_an_inverted_tet():
    vertices, triangles, mesh = cube_lattice()
    tets = mesh.tets.copy()
    tets[0] = tets[0][[0, 2, 1, 3]]
    report = tetmesh.check_lattice(TetMesh(mesh.nodes, tets), vertices, triangles, 7.0)
    assert "some tets are inverted or flat" in report.failures


def test_check_lattice_fails_a_display_vertex_outside_every_tet():
    vertices, triangles, mesh = cube_lattice()
    moved = vertices.copy()
    moved[0] -= 2.0  # one display vertex pushed out of the cubes: the mesh no longer holds the surface
    report = tetmesh.check_lattice(mesh, moved, triangles, 7.0)
    assert report.outside_count >= 1
    assert any("outside every tet" in f for f in report.failures)


def test_check_lattice_fails_a_mesh_that_is_not_what_the_rule_gives():
    vertices, triangles, mesh = cube_lattice()
    other = tetmesh.lattice_tetrahedralize(vertices, triangles, 6.0)  # another cell size: not this mesh
    report = tetmesh.check_lattice(other, vertices, triangles, 7.0)
    assert not report.rebuild_identical
    assert any("different bytes" in f for f in report.failures)


def test_check_lattice_fails_two_pieces():
    vertices, triangles, mesh = cube_lattice()
    far = TetMesh(np.concatenate([mesh.nodes, mesh.nodes + 500.0]), np.concatenate([mesh.tets, mesh.tets + len(mesh.nodes)]))
    report = tetmesh.check_lattice(far, vertices, triangles, 7.0)
    assert report.components == 2 and any("2 pieces" in f for f in report.failures)


@pytest.mark.filterwarnings("ignore:invalid value encountered")
def test_check_lattice_fails_a_sliver():
    vertices, triangles, mesh = cube_lattice()
    nodes = mesh.nodes.copy()
    nodes[mesh.tets[0, 3]] = nodes[mesh.tets[0, 0]] + 1e-3 * (nodes[mesh.tets[0, 1]] - nodes[mesh.tets[0, 0]])
    report = tetmesh.check_lattice(TetMesh(nodes, mesh.tets), vertices, triangles, 7.0)
    assert report.failures  # flat or inverted tet, whatever else follows


def test_the_fine_mesh_check_still_refuses_what_a_lattice_is():
    """check() keeps asking for separation and a manifold boundary; a welded lattice does not give them."""
    ring_nodes, ring_faces = surface_of(LIPS_SURFACE)
    vertices = ring_nodes * 3.0
    mesh = tetmesh.lattice_tetrahedralize(vertices, ring_faces, 10.0)
    report = tetmesh.check(mesh, vertices, ring_faces)
    assert report.failures  # the slit is gone and/or the boundary is not a manifold


# --- the kind field --------------------------------------------------------------------------


def test_the_two_kinds_are_told_apart_by_a_field(tmp_path):
    _, fine = tetmesh.load(SAVED_FINE)
    assert "kind" not in fine and tetmesh.mesh_kind(fine) == tetmesh.KIND_FINE  # lips.json stays as it was
    _, lattice = tetmesh.load(SAVED_LATTICE)
    assert lattice["kind"] == "lattice" and tetmesh.mesh_kind(lattice) == tetmesh.KIND_LATTICE
    path = tmp_path / "m.json"
    tetmesh.save(path, LIPS_SURFACE, {**META, "kind": "fancy"})
    with pytest.raises(ValueError, match="kind 'fancy'"):
        tetmesh.load(path)


# --- the committed lattice -------------------------------------------------------------------


def test_the_committed_lattice_says_the_lips_are_not_separated_and_where_its_cell_comes_from():
    mesh, meta = tetmesh.load(SAVED_LATTICE)
    assert meta["upper_and_lower_lip_separated"] is False
    assert "NOT separated" in meta["warning"]
    assert meta["params"]["cell_mm"] == pytest.approx(26.37 * 0.962)  # Ziva's tetSz, not a tuned number
    assert "tetSz" in meta["params"]["cell_mm_source"] and meta["params"]["shift_mm"] == [0.0, 0.0, 0.0]
    assert (len(mesh.nodes), len(mesh.tets)) == (56, 126)  # pinned: a regenerated file must be looked at
    c = meta["checks"]
    assert c["rebuild_identical"] is True and c["outside_count"] == 0 and c["components"] == 1
    assert c["quality"]["min_dihedral_deg"] > 44.9 and c["quality"]["min_tet_volume_mm3"] > 2700
    assert c["embedded_rest_max_mm"] < 1e-9


def test_the_committed_lattice_passes_its_checks_and_rebuilds_to_the_same_mesh():
    if not LIPS.is_file():
        pytest.skip("lab export missing")
    from build_tetmesh import read_lips_mm

    mesh, meta = tetmesh.load(SAVED_LATTICE, surface=LIPS)
    vertices, triangles = read_lips_mm(LIPS, mm_per_scene_unit=0.962)
    report = tetmesh.check_lattice(mesh, vertices, triangles, meta["params"]["cell_mm"])
    assert report.failures == []
    # The origin rule, read off the surface itself.
    assert np.array_equal(mesh.nodes.min(axis=0), vertices.min(axis=0))
    # Every display vertex is inside a tet (not just near one).
    assert tetmesh.inside_any_tet(mesh.nodes, mesh.tets, vertices).all()


def test_the_lattice_builder_writes_the_same_mesh_twice_and_leaves_lips_json_alone(tmp_path):
    if not LIPS.is_file():
        pytest.skip("lab export missing")
    import build_tetmesh

    before = SAVED_FINE.read_bytes()
    build_tetmesh.build_lattice(tmp_path / "a.json")
    build_tetmesh.build_lattice(tmp_path / "b.json")
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    _, made = tetmesh.load(tmp_path / "a.json")
    _, committed = tetmesh.load(SAVED_LATTICE)
    assert made["content_sha256"] == committed["content_sha256"]
    assert SAVED_FINE.read_bytes() == before


def test_the_product_imports_the_lattice(tmp_path):
    if not LIPS.is_file():
        pytest.skip("lab export missing")
    from asrp_core.asset import lab

    result = lab.import_asset(LIPS.parent, tmp_path / "scene", SAVED_LATTICE)
    assert result.check.ok, result.check.errors
    scene = json.loads((tmp_path / "scene" / "scene.json").read_text(encoding="utf-8"))
    assert scene["soft_tissues"][0]["tet_mesh"]["content_sha256"] == tetmesh.load(SAVED_LATTICE)[1]["content_sha256"]
