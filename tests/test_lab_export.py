import math

from check_lab_export import apply_matrix, health_problem, mesh_health, parse_obj, worst_distance
from ziva_machine_export import (
    IDENTITY,
    check_motion,
    check_simulation,
    file_name,
    mesh_mismatch,
    placing_matrix,
    rotation_between,
    split_accepted,
)
from ziva_machine_export import apply_matrix as ziva_apply_matrix

QUADS = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]  # closed box
SCALE_2_MOVE_Z = [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 0, 0, 10, 1]


def test_closed_box_is_healthy():
    h = mesh_health(8, QUADS)
    assert (h["boundary_edges"], h["non_manifold_edges"], h["components"], h["unused_vertices"]) == (0, 0, 1, 0)


def test_missing_face_leaves_open_edges():
    assert mesh_health(8, QUADS[:-1])["boundary_edges"] == 4


def test_three_faces_on_one_edge_is_non_manifold():
    assert mesh_health(9, QUADS + [(0, 1, 8)])["non_manifold_edges"] == 1


def test_separate_pieces_are_counted():
    second_box = [tuple(i + 8 for i in face) for face in QUADS]
    assert mesh_health(16, QUADS + second_box)["components"] == 2


def test_unused_vertices_are_counted():
    assert mesh_health(9, QUADS)["unused_vertices"] == 1


def test_matrix_uses_maya_row_vector_order():
    assert apply_matrix([(1, 2, 3)], SCALE_2_MOVE_Z) == [(2, 4, 16)]


def test_applying_the_transform_twice_is_detected():
    points = [(1, 2, 3), (4, 5, 6)]
    once = apply_matrix(points, SCALE_2_MOVE_Z)
    assert worst_distance(once, apply_matrix(once, SCALE_2_MOVE_Z)) > 1


def test_swapped_vertices_are_detected():
    points = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
    assert worst_distance(points, [points[1], points[0], points[2]]) == 1


def test_empty_or_different_lengths_never_match():
    assert worst_distance([], []) == math.inf
    assert worst_distance([(0, 0, 0)], []) == math.inf


def test_obj_keeps_order_and_is_zero_based(tmp_path):
    path = tmp_path / "a.obj"
    path.write_text("# c\nv 1 2 3\nv 4 5 6\nv 7 8 9\nf 1 2 3\nf 3/1 2/1 1/1\n")
    vertices, faces = parse_obj(path)
    assert vertices == [(1, 2, 3), (4, 5, 6), (7, 8, 9)]
    assert faces == [(0, 1, 2), (2, 1, 0)]


def test_mesh_not_in_measured_state_is_reported():
    healthy = {"boundary_edges": 0, "non_manifold_edges": 0, "components": 1, "unused_vertices": 0}
    assert health_problem("middleres_Jaw", healthy) is None
    assert health_problem("middleres_Jaw", {**healthy, "boundary_edges": 4})
    assert health_problem("middleres_Jaw", {**healthy, "components": 2})
    assert health_problem("middleres_Jaw", {**healthy, "unused_vertices": 1})


SOLVED = {"gravity_sag": 1.0, "motion_move": 20.0, "frozen_frames": 0, "rest_offset": 0.0, "finite": True,
          "largest_move": 25.0, "jaw_degrees": 12.0}


def test_a_good_solve_passes():
    assert check_simulation(SOLVED) == ([], [])


def test_a_run_with_no_solve_fails():
    assert check_simulation({**SOLVED, "gravity_sag": 0.0, "motion_move": 0.0})[0]


def test_a_solve_that_stops_part_way_fails():
    assert check_simulation({**SOLVED, "frozen_frames": 3})[0]


def test_a_solve_that_did_not_reset_fails():
    assert check_simulation({**SOLVED, "rest_offset": 5.0})[0]


def test_a_diverged_solve_fails():
    assert check_simulation({**SOLVED, "finite": False})[0]
    assert check_simulation({**SOLVED, "largest_move": 900.0})[0]


def test_little_gravity_sag_is_a_note_not_a_failure():
    problems, notes = check_simulation({**SOLVED, "gravity_sag": 0.0})
    assert problems == [] and len(notes) == 1


def test_accepted_problems_stay_on_the_record():
    problems, notes = split_accepted(["zCache nodes exist", "other"], ["zCache"])
    assert problems == ["other"] and "zCache" in notes[0]


def test_a_run_with_no_motion_fails_the_motion_check():
    played = {"frames_sampled": 50, "frames_expected": 50, "jaw_degrees": 12.0, "landmark_travel": 8.0,
              "final_vs_physics": 6.0}
    assert check_motion(played) == []
    assert check_motion({**played, "jaw_degrees": 0.0}, jaw_turns=True)  # T-37 item 8: only when it must turn
    assert check_motion({**played, "jaw_degrees": 0.0}) == []  # IY, UW, T leave the jaw still
    assert check_motion({**played, "landmark_travel": 0.0})
    assert check_motion({**played, "final_vs_physics": 0.0})
    assert check_motion({**played, "frames_sampled": 49})


def test_rotation_between_measures_a_turn_about_z():
    a = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    c, s = math.cos(math.radians(10)), math.sin(math.radians(10))
    b = [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    assert abs(rotation_between(a, b) - 10) < 1e-9


def test_ziva_meshes_use_the_lab_export_matrix_convention():
    points = [(1, 2, 3), (4, 5, 6)]
    assert ziva_apply_matrix(points, SCALE_2_MOVE_Z) == apply_matrix(points, SCALE_2_MOVE_Z)


def test_worldmesh_data_is_placed_by_its_own_matrix():
    assert placing_matrix(SCALE_2_MOVE_Z, IDENTITY) == (SCALE_2_MOVE_Z, "mesh data matrix")


def test_stored_copy_is_placed_by_the_zgeo_matrix():
    assert placing_matrix(IDENTITY, SCALE_2_MOVE_Z) == (SCALE_2_MOVE_Z, "iNMx")


def test_copy_with_no_matrix_says_so():
    assert placing_matrix(IDENTITY, None) == (IDENTITY, "none")


def test_mesh_off_its_scene_mesh_is_a_note():
    assert "zGeo1" in mesh_mismatch("zGeo1", "lips", 0.5)
    assert mesh_mismatch("zGeo1", "lips", 1e-6) is None
    assert mesh_mismatch("zGeo15", None, None) is None


def test_node_names_become_safe_file_names():
    assert file_name("ns:zGeo|1") == "ns_zGeo_1"
