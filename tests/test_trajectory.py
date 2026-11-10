import importlib.util
import json
import math
from pathlib import Path

import pytest

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
