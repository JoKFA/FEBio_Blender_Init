"""T-28: a head driver that moves the skull, a lip-corner blend relative to it, the solver's damping as scene
parameters, and the reported-only motion of the lips against the head (docs/04 section 5.1, docs/05)."""

import json
import math
import shutil
from pathlib import Path

import cube_scene as cs
import numpy as np
import pytest

from asrp_core import generate, plausibility, scene, simulate, trajectory
from asrp_core.doctor import febio_exe

HERE = Path(__file__).resolve().parent
S1 = HERE / "fixtures" / "s1"


def _have_febio() -> bool:
    try:
        return febio_exe().exists()
    except FileNotFoundError:
        return False


needs_febio = pytest.mark.skipif(not _have_febio(), reason="FEBio not found (asrp doctor)")


def m4(t):
    return np.array(t, dtype=float).reshape(4, 4)


def translation(x, y=0.0, z=0.0):
    m = np.eye(4)
    m[:3, 3] = [x, y, z]
    return m.ravel().tolist()


# --- blend relative_to: the formula, on a hand case ---------------------------------------------------------------


def test_relative_blend_of_base_composed_with_a_hinge_turn_is_base_composed_with_alpha_times_the_turn():
    pivot, axis = (5.0, -30.0, 2.0), (1.0, 0.0, 0.0)
    angles = [0.0, 0.1, 0.25, 0.4]
    base = [translation(3.0 * i, -1.0 * i, 0.5 * i) for i in range(len(angles))]
    turns = trajectory.hinge_transforms(pivot, axis, angles)
    of = [(m4(b) @ m4(t)).ravel().tolist() for b, t in zip(base, turns)]
    alpha = 0.3
    got = trajectory.relative_blend_transforms(base, of, alpha)
    want = [(m4(b) @ m4(t)).ravel() for b, t in zip(base, trajectory.hinge_transforms(pivot, axis, [alpha * a for a in angles]))]
    assert max(np.abs(np.array(g) - w).max() for g, w in zip(got, want)) < 1e-12
    # the plain blend of the same motion is something else: the base's translation would be scaled too
    plain = trajectory.blend_transforms(of, alpha)
    assert max(np.abs(np.array(g) - np.array(p)).max() for g, p in zip(got, plain)) > 1.0
    # factor 0 is the base, factor 1 the source
    assert np.allclose(trajectory.relative_blend_transforms(base, of, 0.0), base, atol=1e-12)
    assert np.allclose(trajectory.relative_blend_transforms(base, of, 1.0), of, atol=1e-12)


# --- the scene: relative_to and absent_means_rest -----------------------------------------------------------------


def copy_s1(tmp_path) -> Path:
    out = tmp_path / "s1"
    shutil.copytree(S1, out, ignore=shutil.ignore_patterns("build.py", "__pycache__"))
    return out


def edit(folder: Path, change) -> Path:
    path = folder / "scene.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data, indent=2))
    return path


def with_head(data, relative_to="head", rest=True, skull_follows=True):
    """S1 plus a head driver the skull follows, and a lip-corner style anchor relative to it."""
    data["drivers"].append({"name": "head", "hinge": None, **({"absent_means_rest": True} if rest else {})})
    blend = {"of": "jaw_hinge", "factor": {"value": 0.5, "source": "ours"}}
    if relative_to is not None:
        blend["relative_to"] = relative_to
    data["drivers"].append({"name": "corner_blend", "hinge": None, "blend": blend})
    data["anchors"] = [{"name": "corner_anchor", "driver": "corner_blend"}]
    data["attachments"].append({"name": "corner", "from": "tissue", "to": "corner_anchor", "kind": "spring",
                                "stiffness": {"value": 2.0, "source": "ours"}, "weights": [[0, 1.0]]})
    if skull_follows:
        skull = next(b for b in data["bones"] if b["name"] == "skull")
        skull["motion"], skull["driver"] = "prescribed", "head"


def errors(path, traj=None):
    report = scene.check(path, traj)
    return report, "\n".join(report.errors)


def test_a_trajectory_without_the_head_keeps_working_and_gives_exactly_the_plain_blend(tmp_path):
    folder = copy_s1(tmp_path)
    report = scene.check(edit(folder, with_head), folder / "trajectory.json")  # S1's trajectory has only jaw_hinge
    assert report.ok, report.errors
    motion = scene.driver_motion(report.scene, report.trajectory)
    assert "head" not in motion
    plain = trajectory.blend_transforms(report.trajectory.drivers["jaw_hinge"], 0.5)
    assert motion["corner_blend"] == plain  # the same numbers, to the last bit
    s = report.scene
    assert s.drivers[1].absent_means_rest and s.drivers[2].blend.relative_to == "head"
    scene.write(tmp_path / "again.json", s)
    assert scene.load(tmp_path / "again.json") == s


def test_without_absent_means_rest_a_missing_head_motion_is_still_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    report, text = errors(edit(folder, lambda d: with_head(d, rest=False)), folder / "trajectory.json")
    assert not report.ok
    assert "bone 'skull' follows driver 'head', but the trajectory has no motion for it" in text
    assert "relative to 'head', but the trajectory has no motion for 'head'" in text


def test_a_moving_head_is_composed_in(tmp_path):
    folder = copy_s1(tmp_path)
    path = edit(folder, with_head)
    t = trajectory.read(folder / "trajectory.json")
    t.drivers["head"] = [translation(0.1 * f) for f in range(t.frames)]
    t.drivers["jaw_hinge"] = [(m4(h) @ m4(j)).ravel().tolist() for h, j in zip(t.drivers["head"], t.drivers["jaw_hinge"])]
    trajectory.write(folder / "shake.json", t)
    report = scene.check(path, folder / "shake.json")
    assert report.ok, report.errors
    motion = scene.driver_motion(report.scene, report.trajectory)
    want = trajectory.relative_blend_transforms(t.drivers["head"], t.drivers["jaw_hinge"], 0.5)
    assert motion["corner_blend"] == want and motion["head"] == t.drivers["head"]
    assert max(abs(m[3]) for m in motion["head"]) > 0.5  # the head really moves


@pytest.mark.parametrize("change, message", [
    (lambda d: with_head(d, relative_to="nowhere"), "is relative to driver 'nowhere' (blend.relative_to), which the scene does not list"),
    (lambda d: with_head(d, relative_to="jaw_hinge"), "which is always the plain 'jaw_hinge'"),
    (lambda d: (with_head(d), d["drivers"].append({"name": "second", "hinge": None, "blend": {
        "of": "jaw_hinge", "factor": {"value": 0.2, "source": "ours"}, "relative_to": "corner_blend"}})),
     "is relative to 'corner_blend', which is itself derived"),
    (lambda d: (with_head(d), d["drivers"][1].update(absent_means_rest="yes")), "absent_means_rest must be true or false"),
    (lambda d: (with_head(d), d["drivers"][2].update(absent_means_rest=True)), "'absent_means_rest' means nothing for it"),
])
def test_relative_to_and_absent_means_rest_mistakes_are_errors_in_words(tmp_path, change, message):
    folder = copy_s1(tmp_path)
    report, text = errors(edit(folder, change))
    assert not report.ok and message in text, text


def test_a_scene_without_the_new_fields_is_written_as_before():
    raw = (S1 / "scene.json").read_bytes()
    s = scene.load(S1 / "scene.json")
    text = json.dumps(s.to_json(), indent=2, ensure_ascii=False) + "\n"
    assert text.encode("utf-8") == raw
    assert "relative_to" not in text and "absent_means_rest" not in text and "numerical_damping_rhoi" not in text


# --- the solver's damping as scene parameters ---------------------------------------------------------------------


def damped_box(tmp_path, damping=0.0, rhoi=None):
    c = cs.write(tmp_path / f"box_{damping}_{rhoi}", attachments=[("top", "skull", "hard", None, lambda v: [
        i for i, p in enumerate(v) if abs(p[2] - 10.0) < 1e-9])])

    def change(d):
        d["solver"]["damping"]["value"] = damping
        if rhoi is not None:
            d["solver"]["numerical_damping_rhoi"] = {"value": rhoi, "source": "ours", "note": "test"}

    edit(c["scene"].parent, change)
    traj = cs.motion(c["scene"].parent, cs.still(3))
    return c["scene"], traj


def test_without_the_new_settings_the_feb_has_rhoi_0_and_no_damping_load(tmp_path):
    s, t = damped_box(tmp_path)
    m = generate.build(s, t)
    assert "<rhoi>0.0</rhoi>" in m.feb_text and "mass damping" not in m.feb_text
    assert m.report["solver"] == {"rhoi": 0.0, "rhoi_from": "generator default (generate.RHOI)",
                                  "mass_damping_per_s": 0.0, "substeps_per_frame": 1}


def test_damping_and_rhoi_from_the_scene_reach_the_feb_and_the_report(tmp_path):
    s, t = damped_box(tmp_path, damping=6.5, rhoi=0.5)
    m = generate.build(s, t)
    assert "<rhoi>0.5</rhoi>" in m.feb_text
    assert '<body_load name="damping" type="mass damping">\n      <C>6.5</C>\n    </body_load>' in m.feb_text
    assert m.report["solver"]["rhoi_from"] == "scene.solver.numerical_damping_rhoi"
    rows = {r["where"]: r for r in simulate._parameters(m, t)}
    assert rows["scene.solver.numerical_damping_rhoi"]["value"] == 0.5
    assert rows["scene.solver.damping"]["value"] == 6.5
    assert rows["generator.rhoi"]["value"] == 0.5 and "from the scene" in rows["generator.rhoi"]["note"]


@pytest.mark.parametrize("rhoi", [1.5, -0.1, -1.0])
def test_a_rhoi_outside_what_febio_takes_is_an_error(tmp_path, rhoi):
    folder = copy_s1(tmp_path)
    report, text = errors(edit(folder, lambda d: d["solver"].update(
        numerical_damping_rhoi={"value": rhoi, "source": "ours"})))
    assert not report.ok and "numerical_damping_rhoi must be between 0" in text


@pytest.mark.parametrize("rhoi", [0.0, 1.0, -2.0])
def test_rhoi_0_1_and_newmark_are_allowed(tmp_path, rhoi):
    folder = copy_s1(tmp_path)
    assert scene.check(edit(folder, lambda d: d["solver"].update(
        numerical_damping_rhoi={"value": rhoi, "source": "ours"}))).ok


def test_a_body_following_a_resting_head_the_trajectory_leaves_out_gives_the_fixed_bodys_feb(tmp_path):
    s_fixed, t = damped_box(tmp_path)
    folder = tmp_path / "head"
    shutil.copytree(s_fixed.parent, folder)

    def follow_head(d):
        d["drivers"].append({"name": "head", "hinge": None, "absent_means_rest": True})
        skull = next(b for b in d["bones"] if b["name"] == "skull")
        skull["motion"], skull["driver"] = "prescribed", "head"

    s_head = edit(folder, follow_head)
    fixed, head = generate.build(s_fixed, t), generate.build(s_head, folder / t.name)
    assert head.feb_text == fixed.feb_text
    assert head.bodies["skull"].motion == "fixed"
    # with the head in the trajectory the skull is a prescribed body
    traj = trajectory.read(folder / t.name)
    traj.drivers["head"] = [translation(0.2 * f) for f in range(traj.frames)]
    trajectory.write(folder / "moving.json", traj)
    moving = generate.build(s_head, folder / "moving.json")
    assert moving.bodies["skull"].motion == "prescribed" and moving.feb_text != fixed.feb_text


# --- the motion against the head, and checks b, b2 with a moving skull --------------------------------------------


def test_relative_motion_cancels_the_body_and_reports_what_is_left():
    rng = np.random.default_rng(3)
    rest = rng.normal(size=(20, 3))
    turns = trajectory.hinge_transforms((0.5, 1.0, -2.0), (0.2, 1.0, 0.3), [0.0, 0.2, 0.5, 0.3])
    body = [(m4(translation(4.0 * f, 1.0, -f)) @ m4(t)).ravel().tolist() for f, t in enumerate(turns)]
    frames = np.stack([rest @ m4(b)[:3, :3].T + m4(b)[:3, 3] for b in body])
    free = np.arange(5, 20)
    r = plausibility.relative_motion(rest, frames, free, body, 0)
    assert r["max_mm"] < 1e-12  # carried rigidly: nothing against the body
    extra = frames.copy()
    extra[2, 7] += m4(body[2])[:3, :3] @ np.array([0.0, 0.3, 0.4])  # 0.5 mm against the body, at frame 2
    r = plausibility.relative_motion(rest, extra, free, body, 0)
    assert abs(r["max_mm"] - 0.5) < 1e-12 and r["frame"] == 2
    # against the world instead, the body's own motion dominates
    assert plausibility.relative_motion(rest, frames, free, None, 0)["max_mm"] > 5.0
    # an offset already there at the reference frame is subtracted
    late = frames.copy()
    late[1:, 9] += [m4(b)[:3, :3] @ np.array([0.0, 0.0, 0.2]) for b in body[1:]]
    r = plausibility.relative_motion(rest, late, free, body, 1)
    per_frame = r["per_frame_max_mm"]
    assert max(per_frame[1:]) < 1e-12 and abs(per_frame[0] - 0.2) < 1e-12  # frame 0 did not have it
    assert r["max_mm"] < 1e-12 and r["frame"] > 1  # the maximum is over the frames after the reference only


@needs_febio
def test_a_moving_skull_with_hard_tissue_passes_b_and_b2_and_a_wrong_expected_transform_fails_b(tmp_path):
    top = lambda v: [i for i, p in enumerate(v) if abs(p[2] - 10.0) < 1e-9]  # noqa: E731
    # The "plate" plays the skull: it translates rigidly, the top face is hard on it, the rest of the box hangs free.
    c = cs.write(tmp_path / "skull", attachments=[("top", "plate", "hard", None, top),
                                                  ("side", "plate", "spring", 5.0,
                                                   lambda v: [i for i, p in enumerate(v) if abs(p[1]) < 1e-9 and p[2] > 7])])
    shake = cs.shift(30, 20, (3.0, 0.0, 0.0))
    traj = cs.motion(c["scene"].parent, shake, settle=None)
    r = simulate.run_scene(c["scene"], traj, tmp_path / "runs", febio_exe(), "skull", threads=1)
    assert r.status == "complete"
    checks = r.report["checks"]
    assert checks["b"]["passed"] and checks["b2"]["passed"], checks
    assert checks["b"]["numbers"]["hard_nodes_max_deviation_mm"] < 1e-6
    head = r.report["relative_to_head"]
    assert head["body"] == "plate" and head["reference_frame"] == 0 and len(head["per_frame_max_mm"]) == 30
    assert head["max_mm"] < 3.0  # against the moving skull, less than its own 3 mm travel
    moved = simulate.read_display(r.run_dir / simulate.DISPLAY)["positions"]
    assert np.linalg.norm(moved[-1][top(c["display"])] - c["display"][top(c["display"])], axis=1).min() > 2.9

    # The same results judged against a skull that does not move: check b must fail.
    model = generate.build(c["scene"], traj)
    groups = [{"name": g.name, "kind": g.kind, "target": g.target, "nodes": g.nodes, "vertices": g.vertices}
              for g in model.groups]
    positions = simulate.run.read_positions(r.run_dir / simulate.run.POSITIONS)
    logged = [round(t * model.fps) for t in positions["times_s"]]
    tissue = simulate._node_frames(model, positions, logged)
    right = {"plate": model.bodies["plate"].transforms}
    wrong = {"plate": None}  # "where the bone puts the point" with the skull left at rest
    assert plausibility.follows_bones(groups, model.mesh.nodes, tissue, model.display, moved, right).passed
    assert plausibility.follows_bones(groups, model.mesh.nodes, tissue, model.display, moved, wrong).passed is False
    assert math.isfinite(head["max_mm"])
