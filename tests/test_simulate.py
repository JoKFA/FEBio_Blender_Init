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
    assert "surface_health" not in report and "settled_shape" not in report


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


# --- surface_health and the settle step: reported only ----------------------------------------------------


def naive_edge_ratios(rest, shape, faces):
    """Every edge of the triangles once, shape length over rest length, by plain loops (independent of plausibility)."""
    seen, out = set(), []
    for f in faces:
        for i in range(3):
            a, b = sorted((int(f[i]), int(f[(i + 1) % 3])))
            if (a, b) not in seen:
                seen.add((a, b))
                out.append(np.linalg.norm(shape[a] - shape[b]) / np.linalg.norm(rest[a] - rest[b]))
    return out


def test_surface_health_has_physics_and_final_when_there_is_a_landmark_layer(tmp_path, capsys):
    landmark_scene(tmp_path / "box")
    traj = landmark_motion(tmp_path / "box", ramp())
    r = run(tmp_path / "box", traj, "health")
    assert r.status == "complete" and r.passed
    health = r.report["surface_health"]
    assert health["physics"] and health["final"] and "not a proof of self-intersection" in health["note"]
    d = r.run_dir
    faces = json.loads((d / "playback.json").read_text(encoding="utf-8"))["faces"]
    triangles = [(f[0], f[i], f[i + 1]) for f in faces for i in range(1, len(f) - 1)]
    for version, display in (("physics", simulate.DISPLAY), ("final", simulate.FINAL_DISPLAY)):
        shape = simulate.read_display(d / display)["positions"]
        ratios = naive_edge_ratios(shape[0], shape[-1], triangles)
        last = health[version]["last"]
        assert last["faces"] == len(triangles) and last["edges"] == len(ratios)
        assert last["edges_longer_than_double"] == sum(x > 2 for x in ratios)
        assert last["edges_shorter_than_half"] == sum(x < 0.5 for x in ratios)
        assert last["edge_ratio_min"] == pytest.approx(min(ratios)) and last["edge_ratio_max"] == pytest.approx(max(ratios))
        assert 0 <= health[version]["worst"]["frame"] < FRAMES
        assert health[version]["worst"]["flipped_faces"] >= last["flipped_faces"]
    # the landmark layer moves the surface, so the final numbers are not the physics numbers
    assert health["final"]["last"]["edge_ratio_max"] > health["physics"]["last"]["edge_ratio_max"] + 0.1
    code = cli.main(["run", str(tmp_path / "box" / "scene.json"), str(traj), "--runs-dir", str(tmp_path / "cli")])
    out = capsys.readouterr().out
    assert code == 0 and "surface    physics, last frame: " in out and "surface    final, last frame: " in out
    assert "flipped faces of" in out and "edges < 0.5x" in out and "(reported only)" in out


def test_without_a_landmarks_section_surface_health_has_no_final(tmp_path):
    cs.write(tmp_path / "box")
    r = run(tmp_path / "box", cs.motion(tmp_path / "box", cs.still(FRAMES)), "plain")
    health = r.report["surface_health"]
    assert health["final"] is None and health["physics"]["last"]["faces"] > 0
    assert health["physics"]["last"]["flipped_faces"] == 0 and 0.5 < health["physics"]["last"]["edge_ratio_min"] <= 1.5


def test_a_failed_post_processing_leaves_no_surface_health(tmp_path, monkeypatch):
    cs.write(tmp_path / "box")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(simulate.playback, "write_surface_bundle", boom)
    r = run(tmp_path / "box", cs.motion(tmp_path / "box", cs.still(FRAMES), settle=2), "late")
    assert_failed_and_clean(r, "disk full")  # includes: no surface_health, no settled_shape


def test_the_settle_step_is_how_far_the_tet_nodes_moved_in_the_settle_frames_last_step(tmp_path, capsys):
    c = cs.write(tmp_path / "box")
    traj = cs.motion(tmp_path / "box", cs.still(FRAMES), settle=2)
    r = run(tmp_path / "box", traj, "settle")
    settled = r.report["settled_shape"]
    assert settled["available"] is True and settled["frame"] == 2
    assert settled["tissue_step_frames"] == [1, 2]
    # from the raw FEBio result: positions.npy has frames 1..N-1 (no frame 0), the tet nodes are ids 1..n
    data = np.load(r.run_dir / "physics" / "positions.npy", allow_pickle=False)
    header = json.loads((r.run_dir / "physics" / "positions.json").read_text(encoding="utf-8"))
    assert [round(t * 30) for t in header["times_s"]] == list(range(1, FRAMES))
    tissue = [header["node_ids"].index(n + 1) for n in range(len(c["nodes"]))]
    step = np.linalg.norm(data[1][tissue] - data[0][tissue], axis=1)  # frame 2 minus frame 1
    assert step.max() > 0
    assert settled["tissue_step_max_mm"] == pytest.approx(step.max(), rel=1e-9)
    assert settled["tissue_settled"] is bool(step.max() < settled["tissue_settled_limit_mm"])
    assert settled["tissue_settled_limit_mm"] == simulate.plausibility.TISSUE_SETTLED_LIMIT_MM == 0.001
    assert settled["tissue_step_mean_mm"] == pytest.approx(step.mean(), rel=1e-9)
    code = cli.main(["run", str(tmp_path / "box" / "scene.json"), str(traj), "--runs-dir", str(tmp_path / "cli")])
    assert code == 0 and "settle     frame 2: the tissue moved at most " in capsys.readouterr().out


def test_the_reported_only_keys_change_nothing_else(tmp_path, monkeypatch):
    cs.write(tmp_path / "box")
    traj = cs.motion(tmp_path / "box", cs.still(FRAMES), settle=2)
    with_keys = run(tmp_path / "box", traj, "with")
    monkeypatch.setattr(simulate, "_surface_health", lambda *a: "left out")
    monkeypatch.setattr(simulate.plausibility, "tissue_step", lambda *a: {})
    without = run(tmp_path / "box", traj, "without")
    new = ("tissue_step_max_mm", "tissue_step_mean_mm", "tissue_step_frames", "tissue_settled", "tissue_settled_limit_mm")
    assert all(k in with_keys.report["settled_shape"] for k in new) and "surface_health" in with_keys.report
    assert not any(k in without.report["settled_shape"] for k in new) and without.report["surface_health"] == "left out"

    def core(report):
        out = {k: v for k, v in report.items() if k not in ("run_id", "timing", "surface_health", "surface_flags")}
        out["settled_shape"] = {k: v for k, v in report["settled_shape"].items() if k not in new and k != "comparable"}
        return out

    assert core(with_keys.report) == core(without.report)
    assert with_keys.passed is without.passed is True and with_keys.report["settled_shape"]["available"] is True
    for f in ("physics/positions.npy", "physics/display.npy", "playback.pc2"):
        assert sha(with_keys.run_dir / f) == sha(without.run_dir / f)


# --- T-37 item 13: a PASSED run with a flipped display surface says so on its own line ------------------------


def test_a_passed_run_whose_surface_has_flipped_faces_reports_them_on_their_own_line(tmp_path, monkeypatch, capsys):
    cs.write(tmp_path / "box")
    traj = cs.motion(tmp_path / "box", cs.still(FRAMES), settle=2)
    real = simulate._surface_health

    def flipped(model, display, final):
        health = real(model, display, final)
        health["physics"]["worst"]["flipped_faces"] = 4  # what the prototype run had at frame 32
        health["physics"]["worst"]["frame"] = 3
        return health

    monkeypatch.setattr(simulate, "_surface_health", flipped)
    r = run(tmp_path / "box", traj, "flipped")
    assert r.status == "complete" and r.passed  # the five checks look at the tet mesh: still PASSED, as before
    flags = r.report["surface_flags"]
    assert flags["any_flipped"] is True and flags["flipped_faces"]["physics"]["worst"] == 4
    assert flags["flipped_faces"]["physics"]["worst_frame"] == 3 and flags["flipped_faces"]["final"] is None
    assert flags["line"] in r.report["warnings"] and "4 in the physics version at frame 3" in flags["line"]
    assert "not a check" in flags["line"] and "can still have them" in flags["line"]
    code = cli.main(["run", str(tmp_path / "box" / "scene.json"), str(traj), "--runs-dir", str(tmp_path / "cli")])
    out = capsys.readouterr().out
    assert code == 0 and "WARNING  display surface: flipped faces, 4 in the physics version" in out
    assert "plausibility PASSED" in out


def test_a_run_without_flipped_faces_has_no_such_line(tmp_path):
    cs.write(tmp_path / "box")
    r = run(tmp_path / "box", cs.motion(tmp_path / "box", cs.still(FRAMES), settle=2), "clean")
    flags = r.report["surface_flags"]
    assert flags["any_flipped"] is False and flags["line"] is None and flags["flipped_faces"]["physics"]["worst"] == 0
    assert not any("display surface" in w for w in r.report["warnings"])


def test_available_tissue_settled_and_comparable_are_three_facts(tmp_path):
    cs.write(tmp_path / "box")
    r = run(tmp_path / "box", cs.motion(tmp_path / "box", cs.still(FRAMES), settle=2), "settle")
    s = r.report["settled_shape"]
    assert s["available"] is True and s["comparable"] is s["tissue_settled"]
    assert r.report["settled_shape"]["tissue_settled"] is False  # the box is still falling at frame 2: three facts differ
    none = run(tmp_path / "box", cs.motion(tmp_path / "box", cs.still(FRAMES)), "no_settle")
    assert none.report["settled_shape"]["available"] is False and none.report["settled_shape"]["comparable"] is False
    assert "tissue_settled" not in none.report["settled_shape"]
