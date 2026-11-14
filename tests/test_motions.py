"""`asrp list-motions` and asrp_core.motions: the list the panel's motion picker shows (T-35)."""

import json
from pathlib import Path

import pytest

from asrp_core import cli, motions, trajectory

EYE = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
REPO = Path(__file__).resolve().parents[1]


def write_motion(folder: Path, name: str, frames: int, *, tag="ours", landmarks=False) -> None:
    section = {"names": ["a"], "translations_mm": [[[0.0, 0.0, 0.0]] for _ in range(frames)]} if landmarks else None
    trajectory.write(folder / name, trajectory.Trajectory(fps=30, frames=frames, drivers={"jaw01": [EYE] * frames},
                                                          source_tag=tag, landmarks=section))


def test_lists_each_file_with_its_numbers(tmp_path):
    export = tmp_path / "export"
    (export / "trajectories").mkdir(parents=True)
    write_motion(export / "trajectories", "b_motion.json", 5, landmarks=True)
    write_motion(export / "trajectories", "a_motion.json", 3, tag="lab_setting")
    got = motions.list_motions(export)
    assert got == [
        {"file": "a_motion.json", "frames": 3, "fps": 30, "source_tag": "lab_setting", "landmarks": False},
        {"file": "b_motion.json", "frames": 5, "fps": 30, "source_tag": "ours", "landmarks": True},
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
    assert [json.loads(x) for x in lines] == [{"file": "m.json", "frames": 4, "fps": 30, "source_tag": "ours", "landmarks": True}]


def test_the_command_says_what_is_wrong_for_a_missing_folder(tmp_path, capsys):
    assert cli.main(["list-motions", str(tmp_path / "missing")]) == 1
    assert capsys.readouterr().out.startswith("ERROR  ")


def test_the_committed_head_shake_is_listed_as_ours_without_landmarks():
    got = {m["file"]: m for m in motions.list_motions(REPO / "data" / "lab_export")}
    shake = got["head_shake.json"]
    assert (shake["frames"], shake["fps"], shake["source_tag"], shake["landmarks"]) == (87, 30, "ours", False)
