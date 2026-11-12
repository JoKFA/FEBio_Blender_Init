"""tools/aa_standin.py: the fitting pieces on synthetic data (no lab file, no FEBio run)."""

import re

import aa_standin as aa
import numpy as np
import pytest

from asrp_core import skinning


def test_ridge_fit_recovers_known_translations():
    rng = np.random.default_rng(1)
    weights = rng.random((200, 12))
    weights /= weights.sum(axis=1, keepdims=True)
    truth = rng.normal(size=(12, 3)) * 3
    d, left = aa.ridge_fit(weights, weights @ truth, ridge=0.0)
    assert np.allclose(d, truth, atol=1e-8)
    assert np.abs(left).max() < 1e-8
    d_small, _ = aa.ridge_fit(weights, weights @ truth, ridge=1e-10)
    assert np.allclose(d_small, truth, atol=1e-4)


def test_ridge_lowers_the_largest_translation_on_an_ill_conditioned_problem():
    # two landmarks that nearly share their vertices: the plain fit pushes them far apart in opposite
    # directions to explain a small difference; the ridge keeps them small.
    v = np.linspace(0, 1, 50)
    weights = np.stack([0.5 + 0.0005 * v, 0.5 - 0.0005 * v], axis=1)
    gap = np.zeros((50, 3))
    gap[:, 0] = 0.001 * v
    d0, _ = aa.ridge_fit(weights, gap, ridge=0.0)
    d1, left1 = aa.ridge_fit(weights, gap, ridge=1e-3)
    assert np.linalg.norm(d0, axis=1).max() > 10 * np.linalg.norm(d1, axis=1).max() > 0
    assert np.abs(left1).max() < 2 * np.abs(gap).max()


def test_ramp_is_zero_through_the_settle_and_reaches_the_fitted_values():
    f = aa.ramp_fractions()
    assert len(f) == aa.SETTLE + 1 + aa.STEPS == 51
    assert f[: aa.SETTLE + 1] == [0.0] * (aa.SETTLE + 1)
    assert f[-1] == 1.0
    assert all(b > a for a, b in zip(f[aa.SETTLE:], f[aa.SETTLE + 1:]))
    t = np.arange(12.0).reshape(4, 3) - 5
    r = aa.ramp_translations(t, f)
    assert r.shape == (51, 4, 3)
    assert not r[: aa.SETTLE + 1].any()
    assert np.array_equal(r[-1], t)


def test_variant_a_misses_the_target_by_exactly_physics_minus_settled():
    # W = identity: every vertex is its own landmark. A is fitted against the settled shape S and applied on
    # the physics result P, so it lands on P + (target - S), missing the target by exactly P - S. B lands on it.
    n = 6
    rng = np.random.default_rng(2)
    settled, physics, target = (rng.normal(size=(n, 3)) for _ in range(3))
    weights = np.eye(n)
    d_a, d_b = aa.fit_both(weights, target, settled, physics, ridge=0.0)
    final_a = skinning.deform(physics, weights, d_a)
    final_b = skinning.deform(physics, weights, d_b)
    assert np.allclose(final_a, physics + (target - settled))
    assert np.allclose(final_a - target, physics - settled)
    assert np.allclose(final_b, target)


def test_follow_ratio_and_histogram():
    riding = np.array([[1.0, 0, 0], [0, 2.0, 0], [0, 0, 0]])
    motion = 0.25 * riding
    assert aa.follow_ratio(motion, riding, np.array([0, 1])) == pytest.approx(0.25)
    h = aa.histogram(np.array([0.5, 1.0, 1.5, 3.0, 7.0, 15.0, 25.0, 100.0]))
    assert list(h.values()) == [1, 2, 1, 1, 1, 2]


def test_rigid_fit_recovers_a_known_turn():
    rng = np.random.default_rng(3)
    a = rng.normal(size=(30, 3))
    angle = np.radians(5.74)
    r = np.array([[1, 0, 0], [0, np.cos(angle), -np.sin(angle)], [0, np.sin(angle), np.cos(angle)]])
    move, residual = aa.rigid_fit(a, a @ r.T + [1.0, 2.0, 3.0])
    assert residual < 1e-9
    assert aa.rotation_degrees(move) == pytest.approx(5.74)


def test_the_recorded_command_line_has_no_local_path():
    cmd = aa.recorded_command(["--work", "C:/Users/someone/AppData/Local/Temp/aa_work",
                               "--target=E:/Codebase/_lab/data/dataV22_phoneme_AA_for_d2.py",
                               "--report", str(aa.REPO / "data" / "preview" / "aa_standin_report.json"),
                               "--export", "D:/somewhere/else/lab_export"])
    assert cmd == ("uv run python tools/aa_standin.py --work <work> --target <lab data> "
                   "--report data/preview/aa_standin_report.json --export <export>")
    assert "Users" not in cmd and ":/" not in cmd and "\\" not in cmd


def test_the_archived_files_hold_no_local_absolute_path():
    names = ("aa_standin_report", "aa_a_run_report", "aa_a_provenance", "aa_b_run_report", "aa_b_provenance",
             "landmark_layer_check")
    pattern = re.compile(r"[A-Za-z]:[\\/]|\\\\|/Users/|/home/")
    for name in names:
        text = (aa.REPO / "data" / "preview" / f"{name}.json").read_text(encoding="utf-8")
        assert len(text) > 200, name
        assert not pattern.search(text), f"{name}.json holds a local absolute path"
