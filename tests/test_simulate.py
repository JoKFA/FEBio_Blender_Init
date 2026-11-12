"""The scene run announces its run folder as soon as it exists (the Blender panel needs it while the run goes), and
applies the landmark layer (T-09) on top of the physics when the trajectory has a landmarks section."""

import dataclasses
import hashlib
import json

import cube_scene as cs
import numpy as np
import pytest

from asrp_core import cli, playback, simulate, skinning, tetmesh, trajectory
from asrp_core import scene as scene_module
from asrp_core.doctor import febio_exe

try:
    EXE = febio_exe()
except FileNotFoundError:
    pytest.skip("FEBio not installed", allow_module_level=True)

FRAMES = 6
NAMES = ["lm_a", "lm_b", "lm_c"]


def test_the_cli_prints_the_run_folder_before_the_first_progress_line_and_again_at_the_end(tmp_path, capsys):
    cs.write(tmp_path / "box")
    traj = cs.motion(tmp_path / "box", cs.still(6))
    code = cli.main(["run", str(tmp_path / "box" / "scene.json"), str(traj), "--runs-dir", str(tmp_path / "runs")])
    lines = capsys.readouterr().out.splitlines()
    folders = [i for i, line in enumerate(lines) if line.startswith("run folder ")]
    progress = [i for i, line in enumerate(lines) if line.startswith("progress ")]
    assert code == 0 and len(folders) == 2 and lines[folders[0]] == lines[folders[1]]
    assert progress and folders[0] < progress[0] and folders[1] > progress[-1]
    [run_dir] = (tmp_path / "runs").iterdir()
    assert lines[folders[0]] == f"run folder {run_dir}"


def test_on_start_gets_an_existing_run_folder_before_febio_starts(tmp_path):
    cs.write(tmp_path / "box")
    traj = cs.motion(tmp_path / "box", cs.still(6))
    seen = []
    seen_progress_after = []

    def on_start(run_dir):
        seen.append((run_dir, run_dir.is_dir(), list(run_dir.iterdir())))

    r = simulate.run_scene(tmp_path / "box" / "scene.json", traj, tmp_path / "runs", EXE, "start", on_start=on_start,
                           on_progress=lambda p: seen_progress_after.append(len(seen)))
    assert len(seen) == 1 and seen[0][0] == r.run_dir and seen[0][1]
    assert seen[0][2] == []  # called the moment the folder is claimed: nothing in it yet
    assert seen_progress_after and all(n == 1 for n in seen_progress_after)


# --- the landmark layer ---------------------------------------------------------------------------------


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def weights_for(vertices: int) -> np.ndarray:
    """A dense (vertices, 3) skin whose rows sum to 1 and differ from vertex to vertex."""
    w = np.random.default_rng(7).uniform(0.05, 1.0, size=(vertices, len(NAMES)))
    w[::5, 2] = 0.0  # some vertices are not touched by every landmark
    return w / w.sum(axis=1, keepdims=True)


def landmark_scene(folder, vertices_in_skin=None, scene_names=NAMES):
    """The cube scene with a `landmarks` section: three landmarks and a skin file in asrp-skin/1 (built here)."""
    c = cs.write(folder)
    v = len(c["display"]) if vertices_in_skin is None else vertices_in_skin
    w = weights_for(v)
    eye = np.eye(4).ravel().tolist()
    skin = {"format": skinning.FORMAT, "units": "mm", "axes": "test", "convention": "column vectors, row by row",
            "mesh": "tissue", "names": NAMES, "rest_world": [eye] * 3, "bind_pre": [eye] * 3, "geom": eye,
            "weights": [[[k, float(w[i, k])] for k in range(3) if w[i, k] != 0.0] for i in range(v)]}
    (folder / "skin_mm.json").write_text(json.dumps(skin), encoding="utf-8", newline="\n")
    s = scene_module.load(c["scene"])
    ref = scene_module.FileRef("skin_mm.json", tetmesh.file_sha256(folder / "skin_mm.json"))
    s = dataclasses.replace(s, landmarks=scene_module.Landmarks(list(scene_names), [[0.0, 0.0, 0.0]] * 3, ref))
    scene_module.write(c["scene"], s)
    return c, w


def landmark_motion(folder, translations, names=NAMES):
    """The still motion plus a landmarks section; translations: (frames, len(names), 3) mm."""
    path = cs.motion(folder, cs.still(FRAMES))
    t = trajectory.read(path)
    t = dataclasses.replace(t, landmarks={"names": names, "translations_mm": np.asarray(translations).tolist()})
    trajectory.write(path, t)
    trajectory.read(path)  # it must be a valid trajectory
    return path


def ramp(count=3, mm=5.0):
    """Landmark i moves along its own axis, 0 at frame 2 and `mm` at the last frame (0 before frame 2)."""
    t = np.zeros((FRAMES, count, 3))
    for f in range(2, FRAMES):
        for i in range(count):
            t[f, i, i % 3] = mm * (f - 2) / (FRAMES - 3) * (i + 1)
    return t


def run(folder, traj, name, **kw):
    # one thread: only then are two runs bit-identical, which the byte comparisons below rely on
    return simulate.run_scene(folder / "scene.json", traj, folder.parent / "runs", EXE, name, threads=1, **kw)


def test_without_a_landmarks_section_nothing_of_the_layer_exists(tmp_path):
    cs.write(tmp_path / "box")
    r = run(tmp_path / "box", cs.motion(tmp_path / "box", cs.still(FRAMES)), "plain")
    assert r.status == "complete" and r.passed
    assert r.report["landmark_layer"] == {"applied": False, "reason": "the trajectory has no landmarks section"}
    assert not (r.run_dir / "final").exists() and not (r.run_dir / simulate.FINAL_PLAYBACK).exists()
    assert "versions" not in json.loads((r.run_dir / "playback.json").read_text(encoding="utf-8"))
    assert simulate.FINAL_DISPLAY not in json.loads((r.run_dir / "provenance.json").read_text())["outputs"]


def test_landmarks_at_rest_give_a_final_that_is_the_physics_exactly(tmp_path):
    c, _ = landmark_scene(tmp_path / "box")
    plain = run(tmp_path / "box", cs.motion(tmp_path / "box", cs.still(FRAMES)), "plain")
    r = run(tmp_path / "box", landmark_motion(tmp_path / "box", np.zeros((FRAMES, 3, 3)), NAMES), "rest")
    assert r.status == "complete" and r.passed
    d = r.run_dir
    assert (d / "final" / "display.npy").stat().st_size > 0
    assert sha(d / "final" / "display.npy") == sha(d / "physics" / "display.npy")
    assert sha(d / simulate.FINAL_PLAYBACK) == sha(d / "playback.pc2") and (d / "playback.pc2").stat().st_size > 32
    assert r.report["landmark_layer"] == {"applied": True, "landmarks_moved": 0, "max_translation_mm": 0.0,
                                          "max_final_minus_physics_mm": 0.0, "frame": 0}
    # the landmarks never reach the physics, only the manifest names the second cache
    assert sha(d / "physics" / "positions.npy") == sha(plain.run_dir / "physics" / "positions.npy")
    assert sha(d / "physics" / "display.npy") == sha(plain.run_dir / "physics" / "display.npy")
    assert sha(d / "playback.pc2") == sha(plain.run_dir / "playback.pc2")
    manifest = json.loads((d / "playback.json").read_text(encoding="utf-8"))
    assert manifest.pop("versions") == {"physics": "playback.pc2", "final": "playback_final.pc2"}
    assert manifest == json.loads((plain.run_dir / "playback.json").read_text(encoding="utf-8"))
    out = json.loads((d / "provenance.json").read_text())["outputs"]
    assert {simulate.FINAL_DISPLAY, simulate.FINAL_ARRAY, simulate.FINAL_PLAYBACK} <= set(out)


def test_moved_landmarks_add_weights_times_translations_and_leave_the_physics_alone(tmp_path, capsys):
    c, w = landmark_scene(tmp_path / "box")
    plain = run(tmp_path / "box", cs.motion(tmp_path / "box", cs.still(FRAMES)), "plain")
    moves = ramp(2)  # only two of the three landmarks are named; lm_c does not move
    traj = landmark_motion(tmp_path / "box", moves, NAMES[:2])
    r = run(tmp_path / "box", traj, "moved")
    assert r.status == "complete" and r.passed
    d = r.run_dir
    for f in ("positions.npy", "display.npy"):
        assert sha(d / "physics" / f) == sha(plain.run_dir / "physics" / f)
    physics = simulate.read_display(d / simulate.DISPLAY)["positions"]
    final = simulate.read_display(d / simulate.FINAL_DISPLAY)
    assert final["note"].startswith("physics + landmark layer") and final["format"] == simulate.DISPLAY_FORMAT
    t = np.zeros((FRAMES, 3, 3))
    t[:, :2] = moves  # rebuilt here, from the numbers the test wrote
    want = np.einsum("vk,fkc->fvc", w, t)  # independent of skinning.deform
    assert np.abs((final["positions"] - physics) - want).max() < 1e-12 and np.abs(want).max() > 1.0
    layer = r.report["landmark_layer"]
    assert layer["applied"] and layer["landmarks_moved"] == 2 and layer["frame"] == FRAMES - 1
    assert layer["max_translation_mm"] == pytest.approx(np.linalg.norm(moves, axis=2).max())
    assert layer["max_final_minus_physics_mm"] == pytest.approx(np.linalg.norm(want, axis=2).max())
    assert layer["max_final_minus_physics_mm"] > 1.0
    pc2 = (d / simulate.FINAL_PLAYBACK).read_bytes()
    assert pc2 != (d / "playback.pc2").read_bytes() and len(pc2) == len((d / "playback.pc2").read_bytes())
    # and the command line says it
    code = cli.main(["run", str(tmp_path / "box" / "scene.json"), str(traj), "--runs-dir", str(tmp_path / "cli")])
    out = capsys.readouterr().out
    assert code == 0 and "landmarks  applied: 2 moved, largest translation" in out and f"(frame {FRAMES - 1})" in out


def test_the_cli_says_when_the_layer_was_not_applied(tmp_path, capsys):
    cs.write(tmp_path / "box")
    code = cli.main(["run", str(tmp_path / "box" / "scene.json"), str(cs.motion(tmp_path / "box", cs.still(FRAMES))),
                     "--runs-dir", str(tmp_path / "runs")])
    assert code == 0 and "landmarks  not applied: the trajectory has no landmarks section" in capsys.readouterr().out


def assert_failed_and_clean(r, text):
    assert r.status == "failed" and r.passed is False
    for gone in ("physics", "final", "playback.json", "playback.pc2", simulate.FINAL_PLAYBACK):
        assert not (r.run_dir / gone).exists(), gone
    prov = json.loads((r.run_dir / "provenance.json").read_text())
    assert prov["status"] == "failed" and prov["outputs"] == {} and text in prov["failure"]["message"]
    report = cs.report(r.run_dir)
    assert report["status"] == "failed" and "landmark_layer" not in report and "motion" not in report


def test_a_failure_inside_the_landmark_stage_leaves_no_results(tmp_path, monkeypatch):
    landmark_scene(tmp_path / "box")
    traj = landmark_motion(tmp_path / "box", ramp())

    def boom(*a, **k):
        raise RuntimeError("deform exploded")

    monkeypatch.setattr(skinning, "deform", boom)
    assert_failed_and_clean(run(tmp_path / "box", traj, "boom"), "deform exploded")


def test_a_failure_after_final_was_written_removes_it_too(tmp_path, monkeypatch):
    landmark_scene(tmp_path / "box")
    traj = landmark_motion(tmp_path / "box", ramp())
    real = playback.write_surface_bundle

    def half_then_boom(run_dir, *a, **k):
        real(run_dir, *a, **k)
        assert (run_dir / "final" / "display.npy").is_file() and (run_dir / simulate.FINAL_PLAYBACK).is_file()
        raise OSError("disk full")

    monkeypatch.setattr(simulate.playback, "write_surface_bundle", half_then_boom)
    assert_failed_and_clean(run(tmp_path / "box", traj, "late"), "disk full")


def test_weights_for_another_mesh_are_refused_in_words(tmp_path):
    landmark_scene(tmp_path / "box", vertices_in_skin=10)
    r = run(tmp_path / "box", landmark_motion(tmp_path / "box", ramp()), "rows")
    assert_failed_and_clean(r, "10 rows but the display mesh has")


def test_a_scene_that_lists_the_landmarks_in_another_order_than_the_weights_is_refused(tmp_path):
    """The weight columns follow the skin file's names; a scene with the same names reordered must not run through."""
    landmark_scene(tmp_path / "box", scene_names=[NAMES[1], NAMES[0], NAMES[2]])
    r = run(tmp_path / "box", landmark_motion(tmp_path / "box", ramp()), "order")
    assert_failed_and_clean(r, "same landmarks in the same order")
