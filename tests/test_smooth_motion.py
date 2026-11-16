"""A driven bone moving as a smooth curve between frames (T-33): solver.motion_between_frames "smooth" in the scene,
`generate.smooth_samples` / `hermite_tangents` in the generator. The default stays the straight pieces."""

import json
import math
import re
from pathlib import Path

import cube_scene as cs
import numpy as np
import pytest
from test_generate import TURN, at_z, display, needs_febio, plate_box, run

from asrp_core import generate, scene

REPO = Path(__file__).resolve().parents[1]
S1 = REPO / "tests" / "fixtures" / "s1"


# --- the curve against a function we know -----------------------------------------------------------------------


def sampled_sine(frames_per_period: int, n_per_frame: int, periods: int = 3):
    """x(t) = sin(2 pi t) sampled at `frames_per_period` frames per period, then the smooth curve through them. Returns
    the curve's points and the exact value and exact slope (per unit time) of the sine at each point."""
    frames = frames_per_period * periods + 1
    times = [f / frames_per_period for f in range(frames)]
    values = [math.sin(2 * math.pi * t) for t in times]
    pts = generate.smooth_samples(times, values, n_per_frame)
    t = np.array([p[0] for p in pts])
    return t, np.array([p[1] for p in pts]), np.sin(2 * np.pi * t), 2 * np.pi * np.cos(2 * np.pi * t)


def errors_of(frames_per_period: int, n: int = 8):
    t, v, exact, slope = sampled_sine(frames_per_period, n)
    # the curve's own velocity: the slope of the straight piece between two neighbouring samples, at its middle
    mid = (t[1:] + t[:-1]) / 2
    vel = np.diff(v) / np.diff(t)
    keep = (mid > 0.25) & (mid < 2.75)  # away from the two ends, where the curve has the one-sided slope
    exact_vel = 2 * np.pi * np.cos(2 * np.pi * mid)
    return float(np.abs(v - exact)[(t > 0.25) & (t < 2.75)].max()), float(np.abs(vel - exact_vel)[keep].max())


def test_the_curve_reaches_the_sine_and_its_velocity_as_the_frames_get_closer():
    # position and velocity of the smooth curve go to the analytic sine as the frame spacing shrinks (the plain
    # straight pieces have the right positions only at the frames and a velocity that is a step per frame)
    pos = [errors_of(f)[0] for f in (10, 20, 40)]
    vel = [errors_of(f)[1] for f in (10, 20, 40)]
    assert pos[0] > pos[1] > pos[2] and vel[0] > vel[1] > vel[2]
    assert pos[0] / pos[1] > 3.5 and pos[1] / pos[2] > 3.5  # at least about second order
    assert vel[0] / vel[1] > 3.0 and vel[1] / vel[2] > 3.0
    assert pos[2] < 1e-3 and vel[2] < 0.05  # (the sine's own top speed is 6.28)


def test_velocity_jump_at_a_frame_is_removed():
    # the straight pieces' velocity jumps at every frame by about (frame spacing) x (acceleration); the smooth curve's
    # velocity does not jump there
    f = 10
    times = [i / f for i in range(f * 3 + 1)]
    values = [math.sin(2 * math.pi * t) for t in times]
    lin_v = np.diff(values) / np.diff(times)
    lin_jump = np.abs(np.diff(lin_v))
    pts = generate.smooth_samples(times, values, 16)
    t = np.array([p[0] for p in pts])
    v = np.array([p[1] for p in pts])
    vel = np.diff(v) / np.diff(t)  # 16 pieces per frame: the frame i sits between piece 16 i - 1 and piece 16 i
    smooth_jump = np.abs(vel[16::16] - vel[15:-1:16])[2:-2]
    assert lin_jump[2:-2].max() > 0.5  # the straight pieces really jump (top speed 6.28, jump about 0.6 at 10 frames)
    assert smooth_jump.max() < lin_jump[2:-2].max() / 8


def test_the_curve_goes_through_every_frame_value_and_never_leaves_the_band_between_neighbours():
    times = [i / 30 for i in range(12)]
    # a held bone, a ramp up to a strict peak, a ramp down, a plateau, held again
    values = [0.0, 0.0, 0.0, 0.0, 0.5, 2.0, 3.0, 2.9, 1.0, 1.0, 0.0, 0.0]
    pts = generate.smooth_samples(times, values, 8)
    assert [p for i, p in enumerate(pts) if i % 8 == 0] == list(zip(times, values))  # bit for bit
    for i in range(len(values) - 1):
        lo, hi = sorted((values[i], values[i + 1]))
        inside = [p[1] for p in pts[8 * i:8 * i + 9]]
        assert min(inside) >= lo - 1e-12 and max(inside) <= hi + 1e-12, (i, inside)
    assert all(p[1] == 0.0 for p in pts[:8 * 3 + 1])  # held at rest stays exactly at rest: no ringing before it moves


def test_two_frames_is_a_straight_line_and_one_frame_is_a_point():
    assert generate.smooth_samples([0.0, 1.0], [0.0, 1.0], 4) == [(0.0, 0.0), (0.25, 0.25), (0.5, 0.5), (0.75, 0.75), (1.0, 1.0)]
    assert generate.hermite_tangents([3.0]) == [0.0]


# --- the scene option ----------------------------------------------------------------------------------------------


def with_option(folder: Path, value) -> Path:
    path = folder / "scene.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if value is not None:
        data["solver"]["motion_between_frames"] = value
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def curve_points(feb: str, lc: int) -> list[tuple[float, float]]:
    block = re.search(rf'<load_controller id="{lc}" .*?</load_controller>', feb, re.S).group(0)
    return [tuple(map(float, m)) for m in re.findall(r"<pt>([^,<]+),([^<]+)</pt>", block)]


def plate(tmp_path, value=None, substeps=2):
    c, _ = plate_box(tmp_path, "hard")
    folder = c["scene"].parent
    path = folder / "scene.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["solver"]["substeps_per_frame"]["value"] = substeps
    path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    with_option(folder, value)
    return c, folder, cs.motion(folder, TURN)


def test_absent_and_linear_give_the_same_bytes_and_smooth_does_not(tmp_path):
    c, folder, traj = plate(tmp_path / "a")
    absent = generate.build(c["scene"], traj)
    c2, folder2, traj2 = plate(tmp_path / "b", {"value": "linear", "source": "ours"})
    linear = generate.build(c2["scene"], traj2)
    assert absent.feb_text == linear.feb_text and "motion_between_frames" not in absent.report["solver"]
    c3, folder3, traj3 = plate(tmp_path / "c", {"value": "smooth", "source": "ours"})
    smooth = generate.build(c3["scene"], traj3)
    assert smooth.feb_text != absent.feb_text and smooth.report["solver"]["motion_between_frames"] == "smooth"
    # only the six curves of the plate differ; everything before the load data is the same, and so is the gravity curve
    head = lambda t: t[:t.index("<LoadData>")]  # noqa: E731
    assert head(smooth.feb_text) == head(absent.feb_text)


def test_the_smooth_curves_have_four_points_per_substep_and_the_linear_ones_one_per_frame(tmp_path):
    c, folder, traj = plate(tmp_path / "a", substeps=2)
    lin = generate.build(c["scene"], traj).feb_text
    c2, _, traj2 = plate(tmp_path / "b", {"value": "smooth", "source": "ours"}, substeps=2)
    smo = generate.build(c2["scene"], traj2).feb_text
    frames = len(TURN)
    for lc in range(3, 9):  # 1 gravity, 2 must points, 3..8 the plate's six curves
        a, b = curve_points(lin, lc), curve_points(smo, lc)
        assert len(a) == frames and len(b) == (frames - 1) * 2 * generate.SMOOTH_SAMPLES_PER_SUBSTEP + 1
        assert b[::2 * generate.SMOOTH_SAMPLES_PER_SUBSTEP] == a  # through every frame value, to the last digit
    assert len(curve_points(smo, 1)) == 2 and len(curve_points(smo, 2)) == frames  # gravity and must points untouched


@pytest.mark.parametrize("bad", ["cubic", "", None, 3, ["smooth"]])
def test_an_unknown_value_is_an_error_in_words(tmp_path, bad):
    c, folder, _ = plate(tmp_path, None)
    with_option(folder, {"value": bad, "source": "ours"})
    with pytest.raises(ValueError, match='motion_between_frames must be "linear"'):
        scene.load(c["scene"])


def test_a_scene_with_the_option_is_written_back_with_it_and_one_without_is_not_changed():
    raw = (S1 / "scene.json").read_bytes()
    s = scene.load(S1 / "scene.json")
    assert s.solver.motion_between_frames is None
    assert (json.dumps(s.to_json(), indent=2, ensure_ascii=False) + "\n").encode("utf-8") == raw
    s.solver.motion_between_frames = scene.Param("smooth", "ours", "T-33")
    assert s.to_json()["solver"]["motion_between_frames"] == {"value": "smooth", "source": "ours", "note": "T-33"}


@needs_febio
def test_real_febio_follows_a_plate_moved_by_the_smooth_curve(tmp_path):
    # the plate passes through the same frame values either way, so the frame-end positions must agree with the
    # straight-piece run's; the hard nodes and the display vertices of the plate follow it (check b), and the curves differ
    c, folder, traj = plate(tmp_path / "s", {"value": "smooth", "source": "ours"}, substeps=2)
    r = run(folder, TURN, "smooth")
    assert r.status == "complete" and r.report["checks"]["b"]["passed"], r.report["checks"]["b"]
    assert r.report["checks"]["b"]["numbers"]["hard_nodes_max_deviation_mm"] < 1e-6
    c2, folder2, _ = plate(tmp_path / "l", None, substeps=2)
    r2 = run(folder2, TURN, "linear")
    top = at_z(10.0)(c["display"])
    a, b = display(r.run_dir), display(r2.run_dir)
    assert np.abs(a[:, top] - b[:, top]).max() < 1e-6
    assert np.abs(a[-1, top] - c["display"][top]).max() > 5.0  # the plate really moved
