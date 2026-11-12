import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest
from hinge import hinge_angle

from asrp_core import trajectory
from asrp_core.trajectory import TrajectoryError, apply, hinge_transforms

S1 = Path(__file__).resolve().parent / "fixtures" / "s1"


def close(a, b, tol=1e-3):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_a_quarter_turn_about_a_known_hinge_moves_points_where_hand_working_says():
    # Hinge through (1, 2, 3) along +z (given as a non-unit vector). A quarter turn, right-handed,
    # takes +x to +y: (2, 2, 3) is 1 mm along +x from the pivot, so it ends 1 mm along +y.
    [m] = hinge_transforms((1, 2, 3), (0, 0, 5), [math.pi / 2])
    assert close(apply(m, (2, 2, 3)), (1, 3, 3))
    assert close(apply(m, (1, 4, 3)), (-1, 2, 3))  # +y 2 mm -> -x 2 mm
    assert close(apply(m, (1, 2, 10)), (1, 2, 10))  # on the axis: stays put
    # About +x through the same pivot: +y goes to +z.
    [m] = hinge_transforms((1, 2, 3), (1, 0, 0), [math.pi / 2])
    assert close(apply(m, (1, 3, 3)), (1, 2, 4))
    assert close(apply(m, (5, 2, 3)), (5, 2, 3))


def test_the_hinge_matches_the_s1_spike_rotation():
    spec = importlib.util.spec_from_file_location("s1", Path(__file__).resolve().parents[1] / "spikes" / "s1_dynamic_jaw.py")
    s1 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s1)
    angles = [0.0, -0.05, s1.JAW_OPEN, 0.3]
    for m, angle in zip(hinge_transforms(s1.PIVOT, (1, 0, 0), angles), angles):
        for p in [(0, 0, 0), (10, 10, -5), (3, -7, 30)]:
            assert close(apply(m, p), s1.hinge_rotate(p, angle), 1e-9)


def test_every_hinge_transform_is_rigid():
    for m in hinge_transforms((5, -30, 0), (0.3, -0.2, 1.0), [0.0, 0.1, -2.0, math.pi]):
        assert trajectory.rigid_problem(m) is None


def test_a_zero_axis_is_refused():
    with pytest.raises(ValueError, match="zero vector"):
        hinge_transforms((0, 0, 0), (0, 0, 0), [0.1])


def test_the_example_trajectory_reads_back_unchanged(tmp_path):
    first = trajectory.read(S1 / "trajectory.json")
    assert first.frames == len(first.drivers["jaw_hinge"]) == 46 and first.fps == 30
    trajectory.write(tmp_path / "t.json", first)
    assert (tmp_path / "t.json").read_bytes() == (S1 / "trajectory.json").read_bytes()
    assert trajectory.read(tmp_path / "t.json") == first


def write(tmp_path, data) -> Path:
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data))
    return path


def example() -> dict:
    return json.loads((S1 / "trajectory.json").read_text())


def test_source_tag_is_optional_round_trips_and_a_bad_value_is_refused(tmp_path):
    assert trajectory.read(write(tmp_path, example())).source_tag is None
    assert "source_tag" not in trajectory.read(write(tmp_path, example())).to_json()
    for tag in ("lab_setting", "ziva_default", "ours"):
        t = trajectory.read(write(tmp_path, example() | {"source_tag": tag}))
        assert t.source_tag == tag and t.to_json()["source_tag"] == tag
        trajectory.write(tmp_path / "again.json", t)
        assert trajectory.read(tmp_path / "again.json").source_tag == tag
    with pytest.raises(TrajectoryError, match="source_tag is 'mine'.*lab_setting, ziva_default, ours"):
        trajectory.read(write(tmp_path, example() | {"source_tag": "mine"}))


def test_settle_until_frame_is_optional_round_trips_and_must_be_a_frame_of_the_file(tmp_path):
    assert trajectory.read(write(tmp_path, example())).settle_until_frame is None
    assert "settle_until_frame" not in trajectory.read(write(tmp_path, example())).to_json()
    for n in (0, 14, 45):  # the example has 46 frames
        t = trajectory.read(write(tmp_path, example() | {"settle_until_frame": n}))
        assert t.settle_until_frame == n and t.to_json()["settle_until_frame"] == n
        trajectory.write(tmp_path / "again.json", t)
        assert trajectory.read(tmp_path / "again.json").settle_until_frame == n
    for bad in (-1, 46, 3.5, True, "14"):
        with pytest.raises(TrajectoryError, match=r"settle_until_frame is .*from 0 to 45"):
            trajectory.read(write(tmp_path, example() | {"settle_until_frame": bad}))


def test_an_unknown_version_is_refused(tmp_path):
    data = example() | {"format_version": "asrp-trajectory/9"}
    with pytest.raises(TrajectoryError, match="asrp-trajectory/1"):
        trajectory.read(write(tmp_path, data))


def test_a_driver_with_too_few_frames_is_refused(tmp_path):
    data = example()
    data["drivers"]["jaw_hinge"].pop()
    with pytest.raises(TrajectoryError, match="45 transforms but the file says frames = 46"):
        trajectory.read(write(tmp_path, data))


@pytest.mark.parametrize(
    "matrix, why",
    [
        ([2, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], "stretches"),
        ([-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], "mirror"),
        ([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1], "last row"),
        ([1, 0, 0], "16 finite numbers"),
    ],
)
def test_a_frame_that_is_not_a_rigid_transform_is_refused(tmp_path, matrix, why):
    data = example()
    data["drivers"]["jaw_hinge"][3] = matrix
    with pytest.raises(TrajectoryError, match=f"frame 3: not a rigid transform.*{why}"):
        trajectory.read(write(tmp_path, data))


def test_a_translation_is_a_valid_frame(tmp_path):
    # Head shake (paper 4.4.6): the whole skull moves; a pure translation must be accepted.
    data = example()
    data["drivers"]["jaw_hinge"][3] = [1, 0, 0, 4.5, 0, 1, 0, -2, 0, 0, 1, 0.25, 0, 0, 0, 1]
    t = trajectory.read(write(tmp_path, data))
    assert apply(t.drivers["jaw_hinge"][3], (1, 1, 1)) == (5.5, -1, 1.25)


# --- derived (blended) drivers: a fraction of a hinge turn (T-06a, docs/04 section 5.1) ------------

PIVOT, AXIS = (3.0, -121.7, -54.65), (1.0, 0.0, 0.0)
POINTS = [(0.0, 0.0, 0.0), (10.0, -80.0, 40.0), (-25.0, 140.0, -30.0), (3.0, -121.7, -54.65)]


def max_gap(ms_a, ms_b):
    return max(abs(p - q) for a, b in zip(ms_a, ms_b) for pt in POINTS for p, q in zip(apply(a, pt), apply(b, pt)))


def test_blend_factor_zero_is_the_identity_and_one_is_the_parent():
    jaw = hinge_transforms(PIVOT, AXIS, [math.radians(a) for a in (0, 5, 12, -3, 20)])
    ident = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]] * len(jaw)
    assert max_gap(trajectory.blend_transforms(jaw, 0.0), ident) < 1e-9
    assert max_gap(trajectory.blend_transforms(jaw, 1.0), jaw) < 1e-9
    assert max_gap(jaw, ident) > 1.0  # the jaw really moves the points, so the two checks above can fail


def test_blend_of_a_pure_hinge_turn_is_the_turn_by_factor_times_the_angle_about_the_same_hinge():
    angles = [math.radians(a) for a in (0, 5, 12, -3, 20, 90, 150)]
    jaw = hinge_transforms(PIVOT, AXIS, angles)
    for factor in (0.0, 0.25, 0.5, 1.0):
        got = trajectory.blend_transforms(jaw, factor)
        want = hinge_transforms(PIVOT, AXIS, [factor * a for a in angles])
        assert max(abs(p - q) for u, v in zip(got, want) for p, q in zip(u, v)) < 1e-12, factor
    half = trajectory.blend_transforms(jaw[4:5], 0.5)
    assert abs(hinge_angle(half[0], AXIS) - math.radians(10)) < 1e-12
    assert max_gap(half, jaw[4:5]) > 1.0  # and it is not the 20 degree turn
    assert all(abs(a - b) < 1e-9 for a, b in zip(apply(half[0], PIVOT), PIVOT))  # the pivot stays


def general_motion(angle, axis, shift):
    """A turn about a tilted axis through a pivot, then a translation: not a hinge turn."""
    [m] = hinge_transforms((4.0, -20.0, 7.0), axis, [angle])
    m = list(m)
    m[3] += shift[0]
    m[7] += shift[1]
    m[11] += shift[2]
    return m


def compose(a, b):
    return [float(v) for v in (np.array(a).reshape(4, 4) @ np.array(b).reshape(4, 4)).ravel()]


def test_blending_a_general_motion_twice_adds_the_factors():
    motion = [general_motion(0.7, (1.0, 2.0, -0.5), (3.0, -1.0, 2.0)), general_motion(-0.2, (0.0, 1.0, 1.0), (0.0, 5.0, 0.1)),
              general_motion(1e-10, (1.0, 0.0, 0.0), (0.2, 0.0, 0.0))]
    for a, b in ((0.3, 0.45), (0.5, 0.5), (0.1, 0.9)):
        got = [compose(x, y) for x, y in zip(trajectory.blend_transforms(motion, a), trajectory.blend_transforms(motion, b))]
        want = trajectory.blend_transforms(motion, a + b)
        assert max(abs(p - q) for u, v in zip(got, want) for p, q in zip(u, v)) < 1e-12, (a, b)
    # and it is not nothing: half of the first motion moves a point by millimetres
    assert max_gap(trajectory.blend_transforms(motion, 0.5), trajectory.blend_transforms(motion, 0.0)) > 1.0


def test_blend_keeps_the_translation_of_a_pure_translation():
    [m] = trajectory.blend_transforms([[1, 0, 0, 4.0, 0, 1, 0, -2.0, 0, 0, 1, 0.5, 0, 0, 0, 1]], 0.5)
    assert [m[3], m[7], m[11]] == pytest.approx([2.0, -1.0, 0.25], abs=1e-12)


def test_blend_refuses_a_turn_of_180_degrees():
    [m] = hinge_transforms(PIVOT, AXIS, [math.pi])
    with pytest.raises(ValueError, match="180 degrees"):
        trajectory.blend_transforms([m], 0.5)


def test_hinge_angle_is_signed_and_works_for_a_tilted_axis():
    axis = (1.0, 2.0, -0.5)
    for deg in (-35, -1, 0, 7, 90, 170):
        [m] = hinge_transforms((1, 2, 3), axis, [math.radians(deg)])
        assert abs(hinge_angle(m, axis) - math.radians(deg)) < 1e-12, deg
