"""spikes/audit_cycles_aa.py: the ten-round-trip motion builder, on a tiny synthetic trajectory (T-29)."""

import importlib.util
import math
from pathlib import Path

import numpy as np

from asrp_core import trajectory

REPO = Path(__file__).resolve().parents[1]
SETTLE, RAMP, K = 14, 36, 2
IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def load_spike():
    spec = importlib.util.spec_from_file_location("audit_cycles_aa", REPO / "spikes" / "audit_cycles_aa.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def one_way() -> trajectory.Trajectory:
    """15 still frames, then 36 ramp frames; every ramp frame differs from every other (no accidental equalities)."""
    angles = [0.0] * (SETTLE + 1) + [0.2 * (1 - math.cos(math.pi * i / RAMP)) / 2 for i in range(1, RAMP + 1)]
    jaw = trajectory.hinge_transforms([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], angles)
    t = np.zeros((len(angles), K, 3))
    for f in range(SETTLE + 1, len(angles)):
        t[f] = [[f * 0.1, -f * 0.2, f * 0.3], [f * 0.01, f * 0.02, -f * 0.03]]
    return trajectory.Trajectory(fps=30.0, frames=len(angles), drivers={"jaw01": jaw}, source="synthetic", source_tag="ours",
                                 settle_until_frame=SETTLE, landmarks={"names": ["a", "b"], "translations_mm": t.tolist()})


def test_frame_count_and_header():
    long = load_spike().build(one_way(), 10)
    assert long.frames == SETTLE + 1 + 10 * 2 * RAMP == 735
    assert len(long.drivers["jaw01"]) == 735 and len(long.landmarks["translations_mm"]) == 735
    assert long.settle_until_frame == SETTLE and long.source_tag == "ours"
    assert long.fps == 30.0 and long.landmarks["names"] == ["a", "b"]


def test_every_return_frame_is_exactly_the_rest_frame():
    spike = load_spike()
    long = spike.build(one_way(), 10)
    back, _ = spike.frame_numbers(SETTLE, RAMP, 10)
    assert len(back) == 10 and back[0] == 86 and back[-1] == 734
    _, t = trajectory.landmark_translations(long)
    for f in [*range(SETTLE + 1), *back]:
        assert long.drivers["jaw01"][f] == IDENTITY, f
        assert not t[f].any(), f
    # and nothing else is at rest: the frame after a return is already moving
    assert long.drivers["jaw01"][back[0] + 1] != IDENTITY and t[back[0] + 1].any()


def test_every_open_frame_is_exactly_the_one_way_files_last_frame_and_nothing_accumulates():
    spike = load_spike()
    base = one_way()
    long = spike.build(base, 10)
    _, open_ = spike.frame_numbers(SETTLE, RAMP, 10)
    assert open_[0] == 50 and open_[-1] == 698
    _, t_base = trajectory.landmark_translations(base)
    _, t = trajectory.landmark_translations(long)
    for f in open_:
        assert long.drivers["jaw01"][f] == base.drivers["jaw01"][-1], f
        assert np.array_equal(t[f], t_base[-1]), f
    # nothing accumulated: no frame holds a value the one-way file does not hold, and the largest is the file's largest
    assert np.abs(t).max() == np.abs(t_base).max()
    one_way_rows = {tuple(r) for r in base.drivers["jaw01"]}
    assert all(tuple(r) in one_way_rows for r in long.drivers["jaw01"])
    # every cycle is the same as the first
    for c in range(1, 10):
        a, b = SETTLE + 1, SETTLE + 1 + 72 * c
        assert np.array_equal(t[a:a + 72], t[b:b + 72])
        assert long.drivers["jaw01"][a:a + 72] == long.drivers["jaw01"][b:b + 72]


def test_the_back_half_is_the_out_half_reversed():
    long = load_spike().build(one_way(), 1)
    _, t = trajectory.landmark_translations(long)
    out, back = t[SETTLE + 1:SETTLE + 1 + RAMP], t[SETTLE + 1 + RAMP:]
    # out = O_1..O_36, back = O_35..O_1, O_0 (rest)
    assert np.array_equal(back[:-1], out[:-1][::-1]) and not back[-1].any()


def test_series_reports_first_last_largest_and_the_sign_of_the_slope():
    s = load_spike().series([1.0, 2.0, 3.0])
    assert (s["first"], s["last"], s["largest"], s["slope_sign"]) == (1.0, 3.0, 3.0, "up")
    assert load_spike().series([3.0, 2.0, 1.0])["slope_sign"] == "down"
    assert load_spike().series([2.0, 2.0, 2.0])["slope_sign"] == "flat"
