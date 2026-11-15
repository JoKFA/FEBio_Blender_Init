"""`asrp compare` (T-11): the report, the heat-map data, Ziva's playback package, and where the output may go.

Two kinds of test. Made-up shapes and a made-up export folder have known answers and always run. The tests on the
lab's real Ziva export need the data outside the repository (tools/local_paths.py); without it they skip and say
`NOT VERIFIED`, with it they run on the real AA export of 2026-11-12 (full face, 47 frames, 10,240 vertices).
"""

import hashlib
import json
import shutil
from pathlib import Path

import local_paths
import numpy as np
import pytest

from asrp_core import cli, compare, playback, run, ziva_compare, ziva_export
from asrp_core.asset import coords

REPO = Path(__file__).resolve().parents[1]
TRIP = local_paths.ziva_trip()
AA_JOB = "lab_motions/results/job_251205-190350/251205-190358"
MM = 0.962


# --- made-up shapes -----------------------------------------------------------------------------------------


def jaw_turn(degrees: float, frames: int, start: int = 2) -> np.ndarray:
    """A jaw turning about X through the origin from frame `start`: 4x4 column-vector transforms, mm, one per frame."""
    out = np.tile(np.eye(4), (frames, 1, 1))
    for i in range(start, frames):
        a = np.radians(degrees) * (i - start + 1) / (frames - start)
        out[i, :3, :3] = [[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]]
    return out


def sides(frames=6, vertices=60, seed=1):
    rng = np.random.default_rng(seed)
    rest = rng.normal(size=(vertices, 3)) * 20
    jaw = jaw_turn(10.0, frames)
    glued = np.stack([rest @ t[:3, :3].T + t[:3, 3] for t in jaw])  # every vertex rides the jaw
    final = glued + rng.normal(size=glued.shape) * 0.5
    ours = ziva_compare.Side("ours", glued, final, jaw=jaw)
    theirs = ziva_compare.Side("ziva", glued.copy(), final.copy(), jaw=jaw.copy())
    return ours, theirs, {"lower_lip_on_jaw": np.arange(10), "other": np.arange(10, 30)}


def test_a_result_against_itself_is_zero_on_every_frame_and_both_layers():
    ours, theirs, groups = sides()
    parts, heat = ziva_compare.build_report(ours, theirs, groups)
    for layer in ("physics", "final"):
        for key in ("mean_mm", "p95_mm", "max_mm"):
            assert parts["layers"][layer][key] == [0.0] * 6
        assert heat[layer].shape == (6, 60) and not heat[layer].any()
    assert parts["rest_agreement_max_mm"] == 0.0


def test_a_one_millimetre_shift_is_reported_as_one_millimetre_and_only_in_the_layer_that_moved():
    ours, theirs, groups = sides()
    theirs.physics = theirs.physics + [0.0, 0.0, 1.0]  # along Z, mm
    parts, heat = ziva_compare.build_report(ours, theirs, groups)
    for key in ("mean_mm", "p95_mm", "max_mm"):
        assert np.allclose(parts["layers"]["physics"][key], 1.0, atol=1e-12)
        assert parts["layers"]["final"][key] == [0.0] * 6  # the two layers are reported apart
    assert np.allclose(heat["physics"], 1.0) and not heat["final"].any()


def test_vertex_numbering_off_by_one_reports_a_difference():
    ours, theirs, groups = sides()
    theirs.physics = np.roll(theirs.physics, 1, axis=1)
    parts, _ = ziva_compare.build_report(ours, theirs, groups)
    assert min(parts["layers"]["physics"]["mean_mm"]) > 1.0  # a clearly nonzero difference on every frame


def test_a_missing_final_shape_is_said_with_its_reason_not_left_out():
    ours, theirs, groups = sides()
    ours.final, ours.final_missing = None, "our run has no landmark layer"
    parts, heat = ziva_compare.build_report(ours, theirs, groups)
    assert parts["layers"]["final"] == {"available": False, "reason": "our run has no landmark layer"}
    assert "final" not in heat and "physics" in heat


def test_results_of_different_size_are_refused_never_cut_short():
    ours, theirs, groups = sides()
    theirs.physics = theirs.physics[:4]
    with pytest.raises(ziva_compare.CompareRunError, match="6 frames of 60 vertices, Ziva's 4 frames"):
        ziva_compare.build_report(ours, theirs, groups)


def test_the_target_distance_is_zero_on_the_target_and_not_available_without_one():
    ours, theirs, groups = sides()
    parts, _ = ziva_compare.build_report(ours, theirs, groups)
    assert parts["indicators"]["distance_to_target"] == {
        "available": False, "reason": "no target pose file was given (--target)"}
    target = {"file": "t.py", "end": ours.final[5].copy(), "start": ours.physics[0].copy()}
    training = ours.final.copy()
    parts, _ = ziva_compare.build_report(ours, theirs, groups, training=training, target=target)
    d = parts["indicators"]["distance_to_target"]
    for who in ("training_shape", "ours_final", "ziva_final"):
        at = d[who]["at_frame"]
        assert (at["mean_mm"], at["p95_mm"], at["max_mm"]) == (0.0, 0.0, 0.0) and at["frame"] == 5, who
        assert d[who]["final_over_initial"]["mean_mm"] == 0.0 and d[who]["initial_distance_mm"]["mean_mm"] > 1.0
    target["end"] = target["end"] + [0.0, 0.0, 2.0]  # control: a target 2 mm away is 2 mm away
    parts, _ = ziva_compare.build_report(ours, theirs, groups, training=training, target=target)
    assert np.isclose(parts["indicators"]["distance_to_target"]["training_shape"]["at_frame"]["mean_mm"], 2.0)
    parts, _ = ziva_compare.build_report(ours, theirs, groups, target=target)
    assert parts["indicators"]["distance_to_target"]["training_shape"]["available"] is False


def test_the_follow_ratio_is_one_for_a_lip_glued_to_the_jaw_and_not_applicable_when_the_jaw_is_still():
    ours, theirs, groups = sides()
    parts, _ = ziva_compare.build_report(ours, theirs, groups)
    f = parts["indicators"]["lower_lip_follow"]
    assert f["available"] and f["measured_at_frame"] == 5
    for who in ("ours", "ziva"):
        assert np.isclose(f["by_reference_frame"]["0"][who]["ratio"], 1.0)
    still = np.tile(np.eye(4), (6, 1, 1))
    ours.jaw = theirs.jaw = still
    parts, _ = ziva_compare.build_report(ours, theirs, groups)
    assert parts["indicators"]["lower_lip_follow"] == {"available": False, "reason": "the jaw does not move in this motion"}
    ours.jaw, ours.jaw_missing = None, "the trajectory has no driver 'jaw01'"
    parts, _ = ziva_compare.build_report(ours, theirs, groups)
    assert "no driver 'jaw01'" in parts["indicators"]["lower_lip_follow"]["reason"]


# --- the heat-map files and the package ---------------------------------------------------------------------


def test_the_heat_map_files_hold_exactly_the_distances_and_say_what_they_are(tmp_path):
    ours, theirs, groups = sides()
    theirs.physics = theirs.physics + [0.0, 0.6, 0.8]
    _, heat = ziva_compare.build_report(ours, theirs, groups)
    layers = ziva_compare.write_heatmaps(tmp_path, heat, {"format": ziva_compare.HEATMAP_FORMAT, "units": "mm",
                                                          "frames": 6, "vertex_count": 60, "_unavailable": {}})
    header = json.loads((tmp_path / "heatmap.json").read_text(encoding="utf-8"))
    assert (header["units"], header["frames"], header["vertex_count"]) == ("mm", 6, 60)
    back = np.fromfile(tmp_path / layers["physics"]["file"], dtype="<f4")
    assert back.size == 6 * 60 and np.allclose(back, 1.0, atol=1e-6)  # frame-major: index f * 60 + v
    assert layers["physics"]["size_bytes"] == 6 * 60 * 4 and abs(layers["physics"]["max_mm"] - 1.0) < 1e-6


def test_the_reference_package_reads_back_and_carries_the_topology_note(tmp_path):
    rng = np.random.default_rng(2)
    frames, faces = rng.normal(size=(4, 9, 3)) * 30, [[0, 1, 2], [3, 4, 5], [6, 7, 8]]
    manifest = playback.write_reference_bundle(tmp_path, frames[0], faces, frames, 30.0, {"feb": "ziva_x"},
                                               "fixed topology note", final_frames=frames + 1.0)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["format"] == playback.FORMAT and data["fps"] == 30.0 and data["frame_count"] == 4
    assert data["topology"] == "fixed topology note" and data["versions"]["final"] == "playback_final.pc2"
    assert data["source"]["feb"] == "ziva_x" and data["node_ids"] is None
    assert np.abs(playback.read_pc2(tmp_path / "playback.pc2") - frames).max() < 1e-4
    assert np.abs(playback.read_pc2(tmp_path / "playback_final.pc2") - (frames + 1.0)).max() < 1e-4
    with pytest.raises(ValueError, match="'feb'"):
        playback.write_reference_bundle(tmp_path, frames[0], faces, frames, 30.0, {}, "n")
    (tmp_path / "bad.pc2").write_bytes(b"POINTCACHE2\0" + b"\0" * 8)
    with pytest.raises(ValueError):
        playback.read_pc2(tmp_path / "bad.pc2")


# --- where the output may go --------------------------------------------------------------------------------


def test_the_output_folder_must_be_outside_the_repository_or_under_its_ignored_runs(tmp_path):
    assert ziva_compare.check_out_folder(tmp_path / "somewhere") == (tmp_path / "somewhere").resolve()
    allowed = REPO / "runs" / "a" / "compare"  # runs/ is git-ignored: this one is fine
    assert ziva_compare.check_out_folder(allowed) == allowed.resolve()
    for inside in (REPO / "docs" / "x", REPO / "data" / "lab_export" / "x", REPO / "tests" / "x", REPO):
        with pytest.raises(ziva_compare.CompareRunError, match="inside the repository"):
            ziva_compare.check_out_folder(inside)


def test_the_command_refuses_an_output_inside_the_repository_and_writes_nothing(tmp_path, capsys):
    target = REPO / "docs" / "t11_must_not_exist"
    code = cli.main(["compare", str(tmp_path / "no_run"), str(tmp_path / "no_export"), "--out", str(target)])
    out = capsys.readouterr().out
    assert code == 1 and "inside the repository" in out and "compare FAILED" in out
    assert not target.exists()


# --- a made-up export folder: identity, prefixes, frame rate ------------------------------------------------


def make_export(folder: Path, frames=5, listed=None, requested=None, fps=30.0, motion=True, vertices=4, seal=True):
    """An export folder with the two lip streams, in the machine's format, with `frames` real frames in the file."""
    folder.mkdir(parents=True)
    listed = list(range(frames if listed is None else listed))
    rng = np.random.default_rng(4)
    streams, files = [], {}
    for sid in ("lips_physics", "lips_final"):
        points = (rng.normal(size=(frames, vertices, 3)) * 10).astype("<f4")
        (folder / f"{sid}.points.f32").write_bytes(points.tobytes())
        (folder / f"{sid}.obj").write_text("".join(f"v {p[0]} {p[1]} {p[2]}\n" for p in points[0]) + "f 1 2 3\nf 1 3 4\n")
        files[f"{sid}.points.f32"] = {"bytes": points.nbytes, "sha256": hashlib.sha256(points.tobytes()).hexdigest()}
        streams.append({"id": sid, "role": sid.split("_")[1], "vertices": vertices, "topology": "abc", "frames": listed,
                        "rest_obj": f"{sid}.obj", "samples": f"{sid}.points.f32", "topology_varies": True})
    (folder / "session_report.json").write_text(json.dumps({
        "streams": streams, "requested_frames": requested or [0, len(listed) - 1], "fps": fps, "linear_unit": "cm"}))
    if motion:
        key = "|head|jaw01"
        (folder / "motion.json").write_text(json.dumps({
            "frame_ids": list(range(frames)), "frames": [{key: list(np.eye(4).ravel())} for _ in range(frames)]}))
    if seal:
        (folder / "seal.json").write_text(json.dumps({"files": files}))
    (folder / "readback_report.json").write_text(json.dumps({"ok": True, "alembic_verified": True,
                                                             "streams_checked": 2, "max_error": 1e-6, "problems": []}))
    return folder


def test_the_identity_of_a_stream_holds_what_the_card_lists(tmp_path):
    ident = ziva_export.identity(make_export(tmp_path / "AA_export_1"), "lips_physics")
    assert ident["run_id"] == "AA_export_1" and ident["stream_id"] == "lips_physics"
    assert ident["real_frames"] == {"first": 0, "last": 4, "count": 5, "listed_in_report": 5}
    assert ident["file"]["bytes"] == 5 * 4 * 12 and ident["file"]["sha256_matches_seal"] is True
    assert ident["motion_coverage"] == {"first": 0, "last": 4}
    assert ident["readback"]["alembic_verified"] is True and ident["complete"] and not ident["why_not_complete"]


def test_a_prefix_is_not_a_complete_run_and_is_refused(tmp_path):
    # the report plans frames 0 to 6 (as Y's did: 0 to 46) but the file holds 4: the FILE decides
    export = make_export(tmp_path / "Y_like", frames=4, listed=7, requested=[0, 6], motion=False)
    ident = ziva_export.identity(export, "lips_physics")
    assert ident["real_frames"]["count"] == 4 and ident["real_frames"]["listed_in_report"] == 7
    assert not ident["complete"] and any("prefix" in why for why in ident["why_not_complete"])
    assert any("no motion.json" in why for why in ident["why_not_complete"])
    with pytest.raises(ziva_compare.CompareRunError, match="prefix is not compared"):
        ziva_compare.read_ziva(export, MM, 7)


def test_a_file_that_does_not_match_its_seal_is_not_complete(tmp_path):
    export = make_export(tmp_path / "e")
    data = bytearray((export / "lips_physics.points.f32").read_bytes())
    data[0] ^= 0x01
    (export / "lips_physics.points.f32").write_bytes(bytes(data))
    ident = ziva_export.identity(export, "lips_physics")
    assert ident["file"]["sha256_matches_seal"] is False and not ident["complete"]


def test_another_frame_rate_than_30_is_refused(tmp_path):
    with pytest.raises(ziva_compare.CompareRunError, match="30 only"):
        ziva_compare.read_ziva(make_export(tmp_path / "e24", fps=24.0), MM, 5)
    assert ziva_compare.read_ziva(make_export(tmp_path / "e30"), MM, 5).side.physics.shape == (5, 4, 3)


def test_frames_that_are_not_ours_are_refused_with_both_ranges(tmp_path):
    with pytest.raises(ziva_compare.CompareRunError, match=r"frames 0 to 4 \(5 frames\).*frames 0 to 5"):
        ziva_compare.read_ziva(make_export(tmp_path / "e"), MM, 6)


# --- the lab's real Ziva export -----------------------------------------------------------------------------


def need_trip() -> Path:
    if TRIP is None:
        pytest.skip("NOT VERIFIED: the Ziva trip data is not on this machine; " + local_paths.HOW_TO_SET)
    return TRIP


def export_folder(pattern: str) -> Path:
    found = sorted((need_trip() / "ziva_reference").glob(pattern))
    if not found:
        pytest.skip(f"NOT VERIFIED: no Ziva export matches {pattern} in the trip data")
    return found[-1]


@pytest.fixture(scope="module")
def aa() -> Path:
    return export_folder("neutral_to_AA_export_*")


@pytest.fixture(scope="module")
def ziva(aa):
    return ziva_compare.read_ziva(aa, MM, 47)


def test_ziva_against_itself_is_zero_on_all_47_frames_and_a_shift_of_one_millimetre_is_one(ziva):
    groups = {"lower_lip_on_jaw": np.arange(76)}
    parts, heat = ziva_compare.build_report(ziva.side, ziva.side, groups)
    assert parts["frames"] == 47 and parts["vertices"] == 10240
    for layer in ("physics", "final"):
        for key in ("mean_mm", "p95_mm", "max_mm"):
            values = parts["layers"][layer][key]
            assert len(values) == 47 and max(values) == 0.0, (layer, key)
        assert heat[layer].shape == (47, 10240) and heat[layer].max() == 0.0
    from copy import copy
    shifted = copy(ziva.side)
    shifted.physics = ziva.side.physics + [0.0, 0.0, 1.0]  # 1 mm along our Z (mm, Z up already)
    shifted.final = ziva.side.final + [0.0, 0.0, 1.0]
    parts, _ = ziva_compare.build_report(ziva.side, shifted, groups)
    for layer in ("physics", "final"):
        for key in ("mean_mm", "p95_mm", "max_mm"):
            assert len(parts["layers"][layer][key]) == 47
            assert np.allclose(parts["layers"][layer][key], 1.0, atol=1e-9), (layer, key)
    off = copy(ziva.side)
    off.physics = np.roll(ziva.side.physics, 1, axis=1)  # the numbering off by one
    parts, _ = ziva_compare.build_report(ziva.side, off, groups)
    assert min(parts["layers"]["physics"]["mean_mm"][1:]) > 0.0 and parts["layers"]["physics"]["mean_mm"][0] > 0.0


def test_zivas_own_numbers_are_the_documented_ones(ziva, imported):
    """The follow ratio's inputs are right when Ziva's lower lip moves the documented 11.80 mm on average (docs/13
    E-15: the 76 vertices glued to the jaw, frame 36 against frame 0) and the jaw's own rigid prediction is nearly
    the same distance. A wrong axis, a transpose or a unit here would move one of the two."""
    data = json.loads((imported["scene"] / "scene.json").read_text(encoding="utf-8"))
    group = np.array(sorted(int(v) for v, w in next(a for a in data["attachments"] if a["name"] == "lower_lip_on_jaw")
                            ["weights"] if w > 0))
    assert len(group) == 76
    f = compare.follow_ratio(ziva.side.physics, ziva.side.jaw, 0, group)
    assert abs(f["moved_mean_mm"][36] - 11.80) < 0.01, f["moved_mean_mm"][36]
    assert abs(f["rigid_mean_mm"][36] - 11.86) < 0.01
    assert 0.98 < f["per_frame"][36] < 1.0 and f["per_frame"][0] is None and f["per_frame"][10] is None
    # the control: the jaw's transform of ANOTHER frame gives a different prediction and so a different ratio
    wrong = compare.follow_ratio(ziva.side.physics, np.roll(ziva.side.jaw, 5, axis=0), 0, group)
    assert abs(wrong["per_frame"][36] - f["per_frame"][36]) > 0.1


def test_the_package_reads_back_within_1e_4_mm_of_the_export_on_every_frame(ziva, aa, tmp_path):
    info = ziva_compare.write_ziva_package(tmp_path, ziva, aa.name, 30.0)
    assert info["frames"] == 47 and info["fps"] == 30.0 and info["topology"]["fixed"]
    folder = tmp_path / ziva_compare.PACKAGE
    manifest = json.loads((folder / "playback.json").read_text(encoding="utf-8"))
    assert manifest["fps"] == 30.0 and manifest["frame_count"] == 47 and manifest["units"] == "mm"
    assert len(manifest["vertices"]) == 10240 and "frame 0" in manifest["topology"]
    for version, name, points in (("physics", "playback.pc2", ziva.side.physics),
                                  ("final", "playback_final.pc2", ziva.side.final)):
        back = playback.read_pc2(folder / name).astype(np.float64)
        assert back.shape == (47, 10240, 3)
        worst = np.linalg.norm(back - points, axis=2).max(axis=1)  # per frame
        assert len(worst) == 47 and worst.max() < 1e-4, (version, worst.max())
        assert np.linalg.norm(back[36] - back[0], axis=1).max() > 5.0  # control: the cache is not still
    # and against the export's own bytes, not only against what this module computed from them
    raw = np.fromfile(aa / "lips_physics.points.f32", dtype="<f4").reshape(47, 10240, 3).astype(np.float64)
    again = np.stack([coords.to_mm_zup(f, MM) for f in raw])
    assert np.linalg.norm(playback.read_pc2(folder / "playback.pc2") - again, axis=2).max() < 1e-4


def test_every_real_export_is_identified_and_the_prefixes_are_not_complete():
    root = need_trip() / "ziva_reference"
    known = {"neutral_to_AA_export_*": (47, True), "neutral_to_Y_export_*": (34, False),
             "AA_substeps4_export_*": (2, False), "AA_substeps4_newton20_export_*": (5, False),
             "head_shake_export_*": (127, True), "AA_round_trip_x10_export_*": (605, True)}
    for pattern, (frames, complete) in known.items():
        found = sorted(root.glob(pattern))
        if not found:
            pytest.skip(f"NOT VERIFIED: no export matches {pattern}")
        ident = ziva_export.identity(found[-1], "lips_physics")
        assert ident["real_frames"]["count"] == frames and ident["complete"] is complete, (pattern, ident["why_not_complete"])
        assert ident["file"]["sha256_matches_seal"] is True
    with pytest.raises(ziva_compare.CompareRunError, match="prefix is not compared"):
        ziva_compare.read_ziva(sorted(root.glob("neutral_to_Y_export_*"))[-1], MM, 47)


# --- the whole command on a run folder made from Ziva's own numbers -----------------------------------------


@pytest.fixture(scope="module")
def imported(tmp_path_factory) -> dict:
    """The lab asset imported with the lab's tissue settings, and the lab's AA motion converted (the product's own
    commands), once for the module."""
    trip = need_trip()
    motion = trip / AA_JOB / "combined_checkpoints.pkl"
    if not motion.is_file():
        pytest.skip("NOT VERIFIED: the lab's AA motion file is not in the trip data")
    work = tmp_path_factory.mktemp("compare_import")
    scene = work / "scene"
    assert cli.main(["import-asset", str(REPO / "data" / "lab_export"), str(scene), "--tissue-settings", "lab"]) == 0
    assert cli.main(["convert-motion", str(motion), str(scene / "scene.json"), str(work / "aa.json"),
                     "--starts-at-rest"]) == 0
    return {"scene": scene, "motion": work / "aa.json"}


def fake_run(tmp: Path, imported: dict, ziva, shift=(0.0, 0.0, 0.0), roll=0, frames=47) -> Path:
    """A run folder whose physics and final shapes ARE Ziva's (mm, Z up), moved as asked: what `asrp compare` must
    then report is known exactly."""
    folder = tmp / "run"
    shutil.copytree(imported["scene"], folder)
    shutil.copy(imported["motion"], folder / "trajectory.json")
    (folder / "run_report.json").write_text(json.dumps({"run_id": "fake_run", "status": "complete", "frames": frames}))
    header = {"format": "asrp-display/2", "units": "mm", "fps": 30.0, "frames": frames, "vertex_count": 10240,
              "mesh": "meshes/lips.obj", "note": "made from Ziva's numbers for a test"}
    (folder / "physics").mkdir()
    (folder / "final").mkdir()
    physics = np.roll(ziva.side.physics, roll, axis=1) + np.array(shift)
    final = np.roll(ziva.side.final, roll, axis=1) + np.array(shift)
    run.save_array(folder / "physics" / "display.json", header, physics[:frames], "display.npy")
    run.save_array(folder / "final" / "display.json", header, final[:frames], "display.npy")
    return folder


def run_command(capsys, run_folder, export, out, *extra):
    code = cli.main(["compare", str(run_folder), str(export), "--out", str(out), *extra])
    return code, capsys.readouterr().out


def test_the_command_on_ziva_against_itself_reports_zero_and_writes_every_file(tmp_path, imported, ziva, aa, capsys):
    folder = fake_run(tmp_path, imported, ziva)
    out = tmp_path / "out"
    code, text = run_command(capsys, folder, aa, out)
    assert code == 0 and "compare DONE" in text, text
    report = json.loads((out / "compare_report.json").read_text(encoding="utf-8"))
    assert report["format"] == "asrp-compare/1" and report["frames"]["count"] == 47
    for layer in ("physics", "final"):
        for key in ("mean_mm", "p95_mm", "max_mm"):
            assert len(report["layers"][layer][key]) == 47 and max(report["layers"][layer][key]) == 0.0
    streams = {s["stream_id"]: s for s in report["ziva"]["streams"]}
    assert set(streams) == {"lips_physics", "lips_final"}
    for s in streams.values():  # the identity the card lists
        assert s["run_id"] == aa.name and s["real_frames"]["count"] == 47 and s["file"]["bytes"] == 5775360
        assert s["motion_coverage"] == {"first": 0, "last": 46} and s["readback"]["alembic_verified"] is True
    assert report["indicators"]["distance_to_target"]["reason"].startswith("no target pose")
    assert report["indicators"]["lower_lip_follow"]["available"]
    assert sorted(p.name for p in out.iterdir()) == ["compare_report.json", "heatmap.json", "heatmap_final.f32",
                                                     "heatmap_physics.f32", "ziva_playback"]
    header = json.loads((out / "heatmap.json").read_text(encoding="utf-8"))
    assert (header["units"], header["frames"], header["vertex_count"]) == ("mm", 47, 10240)
    assert header["reference"]["export"] == aa.name
    assert (out / "heatmap_physics.f32").stat().st_size == 47 * 10240 * 4
    text_all = (out / "compare_report.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text_all and "vertices\": [[" not in text_all  # numbers only: no path, no mesh


def test_the_command_reports_a_shift_of_one_millimetre_and_a_renumbering(tmp_path, imported, ziva, aa, capsys):
    shifted = fake_run(tmp_path / "s", imported, ziva, shift=(0.0, 0.0, 1.0))
    code, _ = run_command(capsys, shifted, aa, tmp_path / "out_s")
    assert code == 0
    report = json.loads((tmp_path / "out_s" / "compare_report.json").read_text(encoding="utf-8"))
    for layer in ("physics", "final"):
        for key in ("mean_mm", "p95_mm", "max_mm"):
            assert np.allclose(report["layers"][layer][key], 1.0, atol=1e-5), (layer, key)
    heat = np.fromfile(tmp_path / "out_s" / "heatmap_physics.f32", dtype="<f4")
    assert np.allclose(heat, 1.0, atol=1e-5)
    rolled = fake_run(tmp_path / "r", imported, ziva, roll=1)
    code, _ = run_command(capsys, rolled, aa, tmp_path / "out_r")
    assert code == 0
    report = json.loads((tmp_path / "out_r" / "compare_report.json").read_text(encoding="utf-8"))
    assert min(report["layers"]["physics"]["mean_mm"]) > 0.0


def test_the_command_refuses_a_prefix_export_and_our_run_of_other_frames(tmp_path, imported, ziva, capsys):
    y = sorted((need_trip() / "ziva_reference").glob("neutral_to_Y_export_*"))
    if not y:
        pytest.skip("NOT VERIFIED: no Y export in the trip data")
    folder = fake_run(tmp_path, imported, ziva)
    code, text = run_command(capsys, folder, y[-1], tmp_path / "out_y")
    assert code == 1 and "prefix is not compared" in text and not (tmp_path / "out_y").exists()
    aa = sorted((need_trip() / "ziva_reference").glob("neutral_to_AA_export_*"))[-1]
    code, text = run_command(capsys, tmp_path / "no_such_run", aa, tmp_path / "out_n")
    assert code == 1 and "run_report.json" in text


def test_the_target_distance_is_zero_for_the_training_shape_on_a_target_that_is_that_shape(tmp_path, imported, ziva,
                                                                                         aa, capsys):
    folder = fake_run(tmp_path, imported, ziva)
    ours = ziva_compare.read_run(folder)
    assert ours.training is not None and ours.training.shape == (47, 10240, 3)
    end = int(np.flatnonzero(np.abs(np.diff(ours.side.jaw, axis=0)).reshape(46, -1).max(axis=1) > 1e-9)[-1]) + 1
    assert end == 36
    target = tmp_path / "target.py"  # the lab's file format: python assignments of nested lists, scene units, Y up
    lines = [f"{name} = {coords.from_mm_zup(shape, MM).tolist()!r}\n"
             for name, shape in (("x_middleres_OrbicularisOris0", ours.training[0]),
                                 ("x_middleres_OrbicularisOris1", ours.training[end]))]
    target.write_text("".join(lines), encoding="utf-8")
    code, text = run_command(capsys, folder, aa, tmp_path / "out", "--target", str(target))
    assert code == 0 and "target     training_shape at frame 36: mean 0.000" in text, text
    report = json.loads((tmp_path / "out" / "compare_report.json").read_text(encoding="utf-8"))
    d = report["indicators"]["distance_to_target"]
    assert d["training_shape"]["at_frame"]["max_mm"] < 1e-6 and d["training_shape"]["final_over_initial"]["mean_mm"] == 0.0
    assert d["ours_final"]["at_frame"]["mean_mm"] > 1.0  # control: the final shape of playback is not the target
    follow = report["indicators"]["lower_lip_follow"]
    assert follow["measured_at_frame"] == 36 and 0.98 < follow["by_reference_frame"]["0"]["ziva"]["ratio"] < 1.0
