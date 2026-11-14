"""The difference measures of asrp_core.compare (T-34): made-up shapes with known answers, then Ziva's own lips
against themselves (zero) and against themselves shifted by 1 mm (one), when the trip data is on this machine."""

import json
from pathlib import Path

import local_paths
import numpy as np
import pytest

from asrp_core import compare, plausibility, trajectory
from asrp_core.asset import coords

REPO = Path(__file__).resolve().parents[1]


def _cloud(frames=5, vertices=40, seed=3) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=(frames, vertices, 3)) * 10


def test_a_result_against_itself_is_zero_and_a_shift_is_the_shift():
    a = _cloud()
    same = compare.per_frame(a, a.copy())
    assert same["frames"] == 5 and same["vertices"] == 40
    assert same["mean_mm"] == [0.0] * 5 and same["p95_mm"] == [0.0] * 5 and same["max_mm"] == [0.0] * 5
    shifted = compare.per_frame(a, a + [0.6, 0.0, 0.8])  # a shift of exactly 1 mm
    for key in ("mean_mm", "p95_mm", "max_mm"):
        assert np.allclose(shifted[key], 1.0, atol=1e-12) and len(shifted[key]) == 5
    assert abs(shifted["worst"]["max_mm"]["value"] - 1.0) < 1e-12


def test_the_three_numbers_are_mean_p95_and_max_per_frame():
    a = np.zeros((2, 100, 3))
    b = a.copy()
    b[1, :, 0] = np.arange(100)  # frame 1: vertex i is i mm away
    b[0, 7] = [0.0, 3.0, 4.0]  # frame 0: one vertex 5 mm away
    out = compare.per_frame(a, b)
    assert out["max_mm"] == [5.0, 99.0] and np.allclose(out["mean_mm"], [0.05, 49.5])
    assert np.isclose(out["p95_mm"][1], np.percentile(np.arange(100), 95)) and out["p95_mm"][0] == 0.0
    assert out["worst"]["max_mm"] == {"value": 99.0, "frame": 1} and out["worst"]["mean_mm"]["frame"] == 1
    group = compare.per_frame(a, b, vertices=[7, 8])
    assert group["vertices"] == 2 and group["max_mm"] == [5.0, 8.0] and group["mean_mm"] == [2.5, 7.5]
    mask = np.zeros(100, dtype=bool)
    mask[[7, 8]] = True
    assert compare.per_frame(a, b, vertices=mask)["mean_mm"] == [2.5, 7.5]


def test_sizes_that_differ_are_an_error_never_cut_short():
    a = _cloud()
    with pytest.raises(compare.CompareError, match="5 frames of 40 vertices against 4 frames"):
        compare.per_frame(a, a[:4])
    with pytest.raises(compare.CompareError, match="against 5 frames of 39 vertices"):
        compare.per_frame(a, a[:, :39])
    with pytest.raises(compare.CompareError, match="vertex group is empty"):
        compare.per_frame(a, a, vertices=[])
    with pytest.raises(compare.CompareError, match="must be"):
        compare.per_frame(np.zeros((3, 2)), np.zeros((3, 2)))


def test_displacement_reports_the_sag_along_gravity():
    f = np.zeros((4, 10, 3))
    for i in range(4):
        f[i, :, 2] = -0.5 * i  # every vertex sinks 0.5 mm per frame
        f[i, 0, 0] = 2.0 * i  # one vertex also slides sideways
    out = compare.displacement(f, 0, direction=(0, 0, -9810.0))
    assert np.allclose(out["along_mm"], [0.0, 0.5, 1.0, 1.5])  # the component along gravity, sideways not counted
    assert np.allclose(out["max_mm"], [0.0, np.hypot(2, 0.5), np.hypot(4, 1.0), np.hypot(6, 1.5)])
    assert np.allclose(out["mean_mm"][1], (9 * 0.5 + np.hypot(2, 0.5)) / 10)
    assert np.allclose(compare.displacement(f, 2, direction=(0, 0, -1))["along_mm"], [-1.0, -0.5, 0.0, 0.5])
    assert "along_mm" not in compare.displacement(f)
    with pytest.raises(compare.CompareError, match="reference frame 9"):
        compare.displacement(f, 9)
    with pytest.raises(compare.CompareError, match="direction"):
        compare.displacement(f, 0, direction=(0, 0, 0))


def test_wobble_is_the_motion_left_after_the_bodys_own_motion_is_taken_out():
    rest = _cloud(frames=1)[0]
    pivot = np.array([1.0, 2.0, 3.0])
    angles = [0.0, 0.1, 0.2, 0.3, 0.3, 0.3]
    body = trajectory.hinge_transforms(pivot, (0, 1, 0), angles)
    frames = np.stack([rest @ np.array(t).reshape(4, 4)[:3, :3].T + np.array(t).reshape(4, 4)[:3, 3] for t in body])
    rigid = compare.wobble(frames, body, reference_frame=0)
    assert max(rigid["per_frame_max_mm"]) < 1e-12  # it rides on the body exactly: no wobble
    frames[4, 5] += [0.0, 0.0, 0.25]  # one vertex 0.25 mm off the body in frame 4, in world axes
    out = compare.wobble(frames, body, reference_frame=1)
    assert abs(out["max_mm"] - 0.25) < 1e-12 and out["frame"] == 4 and out["per_frame_max_mm"][3] < 1e-12
    assert compare.wobble(frames, body, 1, vertices=[0, 1, 2])["max_mm"] < 1e-12  # the group leaves that vertex out
    world = compare.wobble(frames, [np.eye(4)] * 6, reference_frame=0)
    assert world["max_mm"] > 1.0  # control: without taking the body out, its own turn is counted as wobble
    with pytest.raises(compare.CompareError, match="6 frames but the body has 5"):
        compare.wobble(frames, body[:5], 0)


def test_decay_tells_first_below_from_stays_below():
    #          stop v
    values = [0.0, 2.0, 0.5, 0.03, 0.08, 0.03, 0.02, 0.01]
    out = compare.decay(values, stop_frame=1, limit_mm=0.04)
    assert out == {"stop_frame": 1, "limit_mm": 0.04, "window": 6, "first_below": 2, "stays_below": 4}
    short = compare.decay(values, stop_frame=1, limit_mm=0.04, window=3)  # ends on the rebound: it does not stay
    assert short["first_below"] == 2 and short["stays_below"] is None and short["window"] == 3
    never = compare.decay(values, stop_frame=1, limit_mm=0.001)
    assert never["first_below"] is None and never["stays_below"] is None
    assert compare.decay(values, 5, 0.04) == {"stop_frame": 5, "limit_mm": 0.04, "window": 2, "first_below": 0,
                                              "stays_below": 0}
    with pytest.raises(compare.CompareError, match="needs frames up to"):
        compare.decay(values, stop_frame=1, limit_mm=0.04, window=7)


def test_flipped_faces_says_which_and_counts_like_the_plausibility_check():
    rest = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 0, 0]])
    faces = np.array([[0, 1, 2], [1, 3, 2], [1, 4, 3]])
    shape = rest.copy()
    shape[4] = [0.5, 1.5, 0.0]  # drags the third triangle's corner across its opposite edge: it turns over
    mask = compare.flipped_faces(rest, shape, faces)
    assert mask.tolist() == [False, False, True]
    assert int(plausibility.fold_counts(rest, shape[None], faces)["flipped"][0]) == int(mask.sum()) == 1
    assert not compare.flipped_faces(rest, rest, faces).any()


@pytest.fixture(scope="module")
def ziva_lips() -> dict:
    root = local_paths.ziva_trip()
    folders = [] if root is None else sorted((root / "ziva_reference").glob("neutral_to_AA_export_*"))
    if not folders:
        pytest.skip("NOT VERIFIED: the Ziva trip data is not on this machine; " + local_paths.HOW_TO_SET)
    report = json.loads((folders[-1] / "session_report.json").read_text(encoding="utf-8"))
    out = {}
    for name in ("lips_physics", "lips_final"):
        entry = next(s for s in report["streams"] if s["id"] == name)
        points = np.fromfile(folders[-1] / entry["samples"], dtype="<f4").astype(np.float64)
        points = points.reshape(len(entry["frames"]), entry["vertices"], 3)
        out[name] = np.stack([coords.to_mm_zup(frame, 0.962) for frame in points])
    return out


def test_ziva_against_itself_is_zero_and_shifted_by_one_millimetre_is_one(ziva_lips):
    physics, final = ziva_lips["lips_physics"], ziva_lips["lips_final"]
    assert physics.shape == (47, 10240, 3)
    same = compare.per_frame(physics, physics.copy())
    assert max(same["max_mm"]) == 0.0 and same["frames"] == 47 and same["vertices"] == 10240
    shifted = compare.per_frame(physics, physics + [0.0, 0.0, 1.0])
    assert np.allclose(shifted["mean_mm"], 1.0, atol=1e-9) and np.allclose(shifted["max_mm"], 1.0, atol=1e-9)
    layers = compare.per_frame(physics, final)  # the two layers are equal through frame 14 and differ after it
    assert max(layers["max_mm"][:15]) == 0.0 and layers["max_mm"][36] > 5.0
    # the known sag of this run (docs/13 E-15): frame 14 against frame 0, all vertices, mean 0.293 mm
    sag = compare.displacement(physics[:15], 0, direction=(0, 0, -1))
    assert abs(sag["mean_mm"][14] - 0.293) < 0.001 and 0 < sag["along_mm"][14] <= sag["mean_mm"][14]
    triangles = coords.triangulate(coords.read_obj(REPO / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj")[1])
    flipped = [int(compare.flipped_faces(final[0], final[f], triangles).sum()) for f in (0, 20, 46)]
    assert flipped == [0, 4, 3]  # the same counts as plausibility.fold_counts (tests/test_lab_facts.py)
