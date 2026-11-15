"""`asrp list-motions` and asrp_core.motions: the list the panel's motion picker shows (T-35)."""

import json
from pathlib import Path

import pytest

from asrp_core import cli, motions, trajectory

EYE = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
REPO = Path(__file__).resolve().parents[1]


def write_motion(folder: Path, name: str, frames: int, *, tag="ours", landmarks=False, title=None) -> None:
    section = {"names": ["a"], "translations_mm": [[[0.0, 0.0, 0.0]] for _ in range(frames)]} if landmarks else None
    trajectory.write(folder / name, trajectory.Trajectory(fps=30, frames=frames, drivers={"jaw01": [EYE] * frames},
                                                          source_tag=tag, landmarks=section, title=title))


def test_lists_each_file_with_its_numbers(tmp_path):
    export = tmp_path / "export"
    (export / "trajectories").mkdir(parents=True)
    write_motion(export / "trajectories", "b_motion.json", 5, landmarks=True)
    write_motion(export / "trajectories", "a_motion.json", 3, tag="lab_setting")
    got = motions.list_motions(export)
    assert got == [
        {"file": "a_motion.json", "title": "a_motion.json", "frames": 3, "fps": 30, "source_tag": "lab_setting", "landmarks": False},
        {"file": "b_motion.json", "title": "b_motion.json", "frames": 5, "fps": 30, "source_tag": "ours", "landmarks": True},
    ]


def test_an_unreadable_file_is_listed_with_its_error_not_skipped(tmp_path):
    (tmp_path / "trajectories").mkdir()
    write_motion(tmp_path / "trajectories", "good.json", 2)
    (tmp_path / "trajectories" / "broken.json").write_text("{not json", encoding="utf-8")
    got = {m["file"]: m for m in motions.list_motions(tmp_path)}
    assert set(got) == {"good.json", "broken.json"}
    assert "not valid JSON" in got["broken.json"]["error"] and "frames" not in got["broken.json"]
    assert got["good.json"]["frames"] == 2


def test_a_folder_of_trajectory_files_works_directly_and_a_folder_without_any_is_refused(tmp_path):
    write_motion(tmp_path, "m.json", 2)
    assert [m["file"] for m in motions.list_motions(tmp_path)] == ["m.json"]
    with pytest.raises(motions.MotionsError, match="no 'trajectories' folder"):
        motions.list_motions(tmp_path / "nothing_here")


def test_the_command_prints_one_json_object_per_line(tmp_path, capsys):
    (tmp_path / "trajectories").mkdir()
    write_motion(tmp_path / "trajectories", "m.json", 4, landmarks=True)
    assert cli.main(["list-motions", str(tmp_path)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(x) for x in lines] == [{"file": "m.json", "title": "m.json", "frames": 4, "fps": 30, "source_tag": "ours", "landmarks": True}]


def test_the_command_says_what_is_wrong_for_a_missing_folder(tmp_path, capsys):
    assert cli.main(["list-motions", str(tmp_path / "missing")]) == 1
    assert capsys.readouterr().out.startswith("ERROR  ")


def test_the_committed_head_shake_is_listed_as_ours_without_landmarks():
    got = {m["file"]: m for m in motions.list_motions(REPO / "data" / "lab_export")}
    shake = got["head_shake.json"]
    assert (shake["frames"], shake["fps"], shake["source_tag"], shake["landmarks"]) == (87, 30, "ours", False)


def test_one_file_that_is_not_text_does_not_take_the_whole_list_down(tmp_path, capsys):
    """Found by an outside review: a .json file that is not UTF-8 text made list-motions die with a traceback, and
    with it Open asset in the panel. It is listed with its error like any other unreadable file."""
    export = tmp_path / "export"
    (export / "trajectories").mkdir(parents=True)
    write_motion(export / "trajectories", "good.json", 4)
    (export / "trajectories", )[0].joinpath("broken.json").write_bytes(bytes([0xFF, 0xFE, 0x00, 0x80]))
    got = motions.list_motions(export)
    assert [m["file"] for m in got] == ["good.json", "broken.json"]  # an unreadable file comes last
    assert "cannot be read as text" in got[1]["error"] and "frames" not in got[1]
    assert got[0] == {"file": "good.json", "title": "good.json", "frames": 4, "fps": 30, "source_tag": "ours", "landmarks": False}
    assert cli.main(["list-motions", str(export)]) == 0
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [m["file"] for m in printed] == ["good.json", "broken.json"] and "error" in printed[1]


def test_motions_are_ordered_by_the_group_in_the_title_then_lab_motion_first_and_a_title_replaces_the_file_name(tmp_path):
    folder = tmp_path / "trajectories"
    folder.mkdir()
    write_motion(folder, "a_ours.json", 2, title="Group 2: A (test motion)")
    write_motion(folder, "z_lab.json", 2, tag="lab_setting", title="Group 2: Z (lab motion)")
    write_motion(folder, "m_first.json", 2, title="Group 1: M (test motion)")
    write_motion(folder, "b_plain.json", 2)
    (folder / "c_broken.json").write_text("{", encoding="utf-8")
    got = motions.list_motions(tmp_path)
    assert [m["file"] for m in got] == ["b_plain.json", "m_first.json", "z_lab.json", "a_ours.json", "c_broken.json"]
    assert got[0]["title"] == "b_plain.json" and got[2]["title"] == "Group 2: Z (lab motion)"


def test_set_motion_title_changes_only_the_title_and_refuses_a_bad_one(tmp_path, capsys):
    folder = tmp_path / "trajectories"
    folder.mkdir()
    write_motion(folder, "m.json", 3, landmarks=True)
    before = (folder / "m.json").read_text(encoding="utf-8")
    assert cli.main(["set-motion-title", str(folder / "m.json"), "Some motion (test motion)"]) == 0
    after = (folder / "m.json").read_text(encoding="utf-8")
    assert after != before and after.replace('  "title": "Some motion (test motion)",\n', "") == before
    assert cli.main(["set-motion-title", str(folder / "m.json"), "x" * 61]) == 1
    assert "ERROR  title is" in capsys.readouterr().out
    assert (folder / "m.json").read_text(encoding="utf-8") == after


def test_the_three_committed_motions_have_their_titles_in_the_prototype_order():
    got = motions.list_motions(REPO / "data" / "lab_export")
    assert [(m["file"], m["title"]) for m in got] == [
        ("jaw_open_12deg.json", "Prototype 1: jaw opens 12 degrees (test motion)"),
        ("neutral_to_AA.json", "Prototype 2: neutral to AA (lab motion)"),
        ("head_shake.json", "Prototype 2: head shake (test motion)")]
    assert got[1]["source_tag"] == "lab_setting" and got[0]["source_tag"] == "ours" and got[0]["frames"] == 51


def test_the_committed_test_motions_are_what_their_tools_write_for_a_freshly_imported_scene(tmp_path):
    """jaw_open_12deg.json and head_shake.json are written by tools/placeholder_jaw_motion.py and tools/head_shake_motion.py,
    not by hand: the tools' output equals the committed files byte for byte (so a changed tool shows up here)."""
    import head_shake_motion
    import placeholder_jaw_motion

    from asrp_core.asset import lab

    if not (REPO / "data" / "tetmesh" / "lips.json").is_file():
        pytest.skip("needs data/tetmesh/lips.json")
    result = lab.import_asset(REPO / "data" / "lab_export", tmp_path / "scene", REPO / "data" / "tetmesh" / "lips.json",
                              tissue_settings="lab")
    for name, build in (("jaw_open_12deg.json", placeholder_jaw_motion.build), ("head_shake.json", head_shake_motion.build)):
        trajectory.write(tmp_path / name, build(result.scene_path))
        committed = (REPO / "data" / "lab_export" / "trajectories" / name).read_bytes()
        assert (tmp_path / name).read_bytes() == committed, name
