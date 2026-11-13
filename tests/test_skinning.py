import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest

from asrp_core import skinning
from asrp_core.asset import coords
from asrp_core.asset import skin as skin_module

REPO = Path(__file__).resolve().parents[1]
EXPORT = REPO / "data" / "lab_export"
LAB_DATA = Path(os.environ.get("ASRP_LAB_DATA", "E:/Codebase/_lab/data"))
HAVE_EXPORT = (EXPORT / "mesh_report.json").is_file() and (REPO / "data" / "tetmesh" / "lips.json").is_file()
HAVE_LAB = (LAB_DATA / "oor_skin_weights.json").is_file() and (LAB_DATA / "oor_bind_pose.json").is_file()


def small_skin(weights=((1.0, 0.0), (0.25, 0.75), (0.0, 1.0))) -> skinning.Skin:
    w = np.array(weights)
    k = w.shape[1]
    eye = np.tile(np.eye(4), (k, 1, 1))
    return skinning.Skin([f"l{i}" for i in range(k)], eye.copy(), eye.copy(), np.eye(4), w)


# --- the kernel, by hand ---------------------------------------------------------------------------


def test_deform_by_hand():
    # Vertex 1 has weights 0.25 / 0.75, landmark 0 moves (4, 0, 0), landmark 1 moves (0, 8, -4):
    # it moves 0.25 * (4, 0, 0) + 0.75 * (0, 8, -4) = (1, 6, -3).
    w = np.array([[1.0, 0.0], [0.25, 0.75], [0.0, 1.0]])
    base = np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0], [1.0, 2.0, 3.0]])
    t = np.array([[4.0, 0.0, 0.0], [0.0, 8.0, -4.0]])
    out = skinning.deform(base, w, t)
    assert out.tolist() == [[4.0, 0.0, 0.0], [11.0, 16.0, 7.0], [1.0, 10.0, -1.0]]


def test_deform_takes_frames_for_the_translations_or_for_both():
    w = np.array([[1.0, 0.0], [0.5, 0.5]])
    base = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    t = np.array([[[2.0, 0.0, 0.0], [0.0, 0.0, 0.0]], [[0.0, 0.0, 0.0], [0.0, 6.0, 0.0]]])  # 2 frames
    out = skinning.deform(base, w, t)
    assert out.shape == (2, 2, 3)
    assert out[0].tolist() == [[2.0, 0.0, 0.0], [2.0, 1.0, 1.0]]
    assert out[1].tolist() == [[0.0, 0.0, 0.0], [1.0, 4.0, 1.0]]
    both = skinning.deform(np.stack([base, base + 1]), w, t)
    assert np.array_equal(both[1], out[1] + 1)


def test_landmarks_at_zero_leave_the_vertices_bit_identical():
    rng = np.random.default_rng(1)
    w = rng.random((50, 7))
    w /= w.sum(axis=1, keepdims=True)
    base = rng.normal(size=(50, 3)) * 100
    out = skinning.deform(base, w, np.zeros((7, 3)))
    assert out.tobytes() == base.tobytes()
    frames = skinning.deform(base, w, np.zeros((4, 7, 3)))
    assert frames.shape == (4, 50, 3) and all(f.tobytes() == base.tobytes() for f in frames)


@pytest.mark.parametrize("base,weights,t,message", [
    (np.zeros((3, 2)), np.eye(3), np.zeros((3, 3)), "base must be"),
    (np.zeros((4, 3)), np.eye(3), np.zeros((3, 3)), "base must be"),
    (np.zeros((3, 3)), np.eye(3), np.zeros((2, 3)), "translations must be"),
    (np.zeros((3, 3)), np.eye(3), np.zeros((3, 3, 2)), "translations must be"),
    (np.zeros((3, 3)), np.ones(3), np.zeros((3, 3)), "weights must be"),
    (np.zeros((2, 3, 3)), np.eye(3), np.zeros((5, 3, 3)), "must match"),
])
def test_deform_refuses_shapes_that_do_not_fit(base, weights, t, message):
    with pytest.raises(skinning.SkinError, match=message):
        skinning.deform(base, weights, t)


def test_matrices_by_hand_with_a_rotated_landmark():
    # One landmark whose world matrix turns a quarter about z around the origin, bind_pre = identity:
    # (1, 0, 0) -> (0, 1, 0). The other landmark is at rest. Vertex weights 0.5 / 0.5.
    skin = small_skin(((0.5, 0.5),))
    turn = np.eye(4)
    turn[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    world = np.stack([turn, np.eye(4)])
    out = skinning.deform_matrices(np.array([[1.0, 0.0, 0.0]]), skin, world)
    assert np.allclose(out, [[0.5, 0.5, 0.0]])


def test_translations_to_world_adds_to_the_translation_column():
    skin = small_skin()
    skin.rest_world[1, :3, 3] = [5.0, 6.0, 7.0]
    world = skinning.translations_to_world(skin, [[1, 2, 3], [10, 20, 30]])
    assert world[0, :3, 3].tolist() == [1, 2, 3] and world[1, :3, 3].tolist() == [15, 26, 37]
    assert skin.rest_world[0, :3, 3].tolist() == [0, 0, 0]  # the rest matrices are not changed


# --- the converted file ------------------------------------------------------------------------------


def test_a_maya_matrix_becomes_a_column_matrix_in_mm_z_up():
    # Maya: row vectors, translation at 12..14, scene units, Y up. A pure translation by (1, 2, 3) scene units
    # at 2 mm per unit is (2, 4, 6) mm, which is (2, -6, 4) in Z up (x, -z, y).
    maya = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 2, 3, 1]
    m = skin_module.maya_to_core(maya, 2.0)
    assert np.allclose(m[:3, :3], np.eye(3)) and np.allclose(m[:3, 3], [2, -6, 4]) and np.allclose(m[3], [0, 0, 0, 1])
    # A quarter turn about the scene's Y axis (up): a point at scene +x goes to -z; in Z up that is +y.
    turn = [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1]  # rows: where x, y, z go
    m = skin_module.maya_to_core(turn, 1.0)
    assert np.allclose(m @ [1, 0, 0, 1], [0, 1, 0, 1])  # +x -> scene -z -> core +y
    assert np.allclose(m @ [0, 0, 1, 1], [0, 0, 1, 1])  # core +z (scene +y) is the axis: it stays
    assert np.allclose(m @ [0, 1, 0, 1], [-1, 0, 0, 1])  # core +y = scene -z, which the turn sends to scene -x


def test_the_conversion_matrix_is_the_coords_function_and_nothing_else():
    c = skin_module.conversion_matrix(0.962)
    p = np.array([[1.5, -2.0, 7.25], [0.0, 3.0, -1.0]])
    homogeneous = np.concatenate([p, np.ones((2, 1))], axis=1)
    assert np.allclose((homogeneous @ c.T)[:, :3], coords.to_mm_zup(p, 0.962), atol=1e-12)


def test_load_refuses_a_wrong_format_wrong_shapes_and_weights_that_do_not_sum_to_one(tmp_path):
    good = {"format": "asrp-skin/1", "names": ["a", "b"], "rest_world": [list(np.eye(4).ravel())] * 2,
            "bind_pre": [list(np.eye(4).ravel())] * 2, "geom": list(np.eye(4).ravel()),
            "weights": [[[0, 0.5], [1, 0.5]], [[1, 1.0]]]}

    def write(**change):
        path = tmp_path / "s.json"
        path.write_text(json.dumps({**good, **change}))
        return path

    skin = skinning.load(write())
    assert skin.weights.tolist() == [[0.5, 0.5], [0.0, 1.0]] and skin.rest_world.shape == (2, 4, 4)
    with pytest.raises(skinning.SkinError, match="format"):
        skinning.load(write(format="asrp-skin/2"))
    with pytest.raises(skinning.SkinError, match="do not fit"):
        skinning.load(write(geom=[1.0] * 15))
    with pytest.raises(skinning.SkinError, match="do not sum to 1"):
        skinning.load(write(weights=[[[0, 0.5], [1, 0.4]]]))
    with pytest.raises(skinning.SkinError, match="landmark 2"):
        skinning.load(write(weights=[[[2, 1.0]]]))
    with pytest.raises(skinning.SkinError, match="negative"):
        skinning.load(write(weights=[[[0, 1.5], [1, -0.5]]]))
    with pytest.raises(skinning.SkinError, match="not a finite number"):  # json.dumps writes NaN, json.loads reads it
        skinning.load(write(weights=[[[0, float("nan")], [1, 0.5]]]))
    with pytest.raises(skinning.SkinError, match="does not exist"):
        skinning.load(tmp_path / "nope.json")


# --- the real asset (acceptance items 1 and 4) ---------------------------------------------------------


@pytest.fixture(scope="module")
def check(tmp_path_factory):
    if not HAVE_EXPORT:
        pytest.skip("needs data/lab_export and data/tetmesh/lips.json")
    if not HAVE_LAB:
        pytest.skip(f"needs the lab's own files in {LAB_DATA} (set ASRP_LAB_DATA); they stay outside the repo")
    spec = importlib.util.spec_from_file_location("landmark_layer_check", REPO / "tools" / "landmark_layer_check.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool.run(LAB_DATA, tmp_path_factory.mktemp("layer"))


def test_the_converted_matrices_put_the_rest_lips_back_within_a_thousandth_of_a_millimetre(check):
    assert check["vertices"] == 10240 and check["landmarks"] == 300
    assert check["conversion_rest_max_mm"] < 0.001


def test_the_fast_formula_equals_the_general_matrix_skinning_when_landmarks_move(check):
    assert check["max_translation_applied_mm"] > 10  # the motion was real, not a run of zeros
    assert check["deform_vs_deform_matrices_max_mm"] < 1e-9


def test_our_result_matches_the_labs_own_formula_on_the_labs_own_files(check):
    assert check["ours_vs_lab_formula_max_mm"] < 1e-4


def test_the_comparison_can_fail_lab_weights_shifted_by_one_landmark_miss_the_threshold(check):
    assert check["control_shifted_columns_max_mm"] > 1.0  # millimetres off, against the threshold of 1e-4


def test_landmarks_at_zero_keep_a_negative_zero():
    """base + 0.0 would turn -0.0 into +0.0 and change the bytes of the result."""
    base = np.array([[-0.0, 1.0, -0.0], [2.0, -0.0, 3.0]])
    out = skinning.deform(base, np.array([[1.0, 0.0], [0.5, 0.5]]), np.zeros((2, 3)))
    assert out.tobytes() == base.tobytes() and out is not base
