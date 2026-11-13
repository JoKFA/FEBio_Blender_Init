"""The guard that keeps the lab's files, vendors' files and this machine's own paths out of git must be able to fail."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_no_lab_files as guard  # noqa: E402
import local_paths  # noqa: E402


def test_forbidden_kinds_and_known_content_are_reported_and_ordinary_files_are_not():
    files = {"docs/readme.md": "aa", "assets/Scene.MB": "bb", "data/motion.pkl": "cc", "data/renamed.json": "dd",
             "runs/lips.points.f32": "ee", "tools/x.py": "ff"}
    found = guard.violations(files, {"dd"})
    assert [line.split(":")[0] for line in found] == ["assets/Scene.MB", "data/motion.pkl", "data/renamed.json",
                                                      "runs/lips.points.f32"]
    assert guard.violations({"docs/readme.md": "aa", "tools/x.py": "ff"}, {"dd"}) == []


def test_this_machines_settings_are_never_tracked():
    found = guard.violations({".local/paths.json": "aa", "data/lab_export/ziva_trip_pointer.json": "bb",
                              "tools/local_paths.py": "cc"}, set())
    assert [line.split(":")[0] for line in found] == [".local/paths.json", "data/lab_export/ziva_trip_pointer.json"]


def test_a_tracked_file_that_names_a_path_of_this_machine_is_reported():
    markers = guard.machine_markers(Path("Q:/people/someone/asrp"), home=Path("C:/Users/someone"))
    assert markers == ["q:/people/someone/", "c:/users/someone/"]
    texts = {
        "tools/a.py": 'DEFAULT = "Q:/people/someone/_lab/data"\n',                       # forward slashes
        "docs/b.md": "first line\nput it in `Q:\\people\\someone\\asrp\\assets\\`\n",       # backslashes, second line
        "data/c.json": '{"manifest": "Q:\\\\People\\\\Someone\\\\trip\\\\manifest.json"}',  # JSON: doubled, other case
        "notes/d.md": "the home folder is C:\\Users\\someone\\AppData",
        "tools/e.py": 'EXAMPLE = "D:/work/asrp"  # a made-up path is fine\n',
        "docs/f.md": "FEBio is in C:\\Program Files\\FEBioStudio\n",
        "AGENTS.md": "Adds to Q:\\people\\someone\\AGENTS.md.\n",                          # the owner's own file
    }
    found = guard.machine_paths(texts, markers)
    assert [line.split(": ")[0] for line in found] == ["data/c.json:1", "docs/b.md:2", "notes/d.md:1", "tools/a.py:1"]
    assert guard.machine_paths({"tools/e.py": texts["tools/e.py"], "docs/f.md": texts["docs/f.md"]}, markers) == []


def test_a_drive_root_is_not_a_marker():
    assert guard.machine_markers(Path("Q:/asrp"), home=Path("C:/Users/someone")) == ["c:/users/someone/"]


def test_locations_come_from_the_environment_or_the_local_folder_and_have_no_default(tmp_path, monkeypatch):
    monkeypatch.setattr(local_paths, "POINTER", tmp_path / "ziva_trip_pointer.json")
    monkeypatch.setattr(local_paths, "PATHS", tmp_path / "paths.json")
    monkeypatch.delenv("ASRP_ZIVA_TRIP", raising=False)
    monkeypatch.delenv("ASRP_LAB_DATA", raising=False)
    assert local_paths.ziva_trip() is None and local_paths.lab_data() is None  # nothing configured: no guess
    trip = tmp_path / "trip"
    trip.mkdir()
    (trip / "manifest.json").write_text("{}")
    (tmp_path / "ziva_trip_pointer.json").write_text(json.dumps({"manifest": (trip / "manifest.json").as_posix()}))
    (tmp_path / "paths.json").write_text(json.dumps({"lab_data": (tmp_path / "lab").as_posix()}))
    assert local_paths.ziva_trip() == trip and local_paths.lab_data() == tmp_path / "lab"
    monkeypatch.setenv("ASRP_LAB_DATA", str(tmp_path / "other"))  # the environment wins
    assert local_paths.lab_data() == tmp_path / "other"
    monkeypatch.setenv("ASRP_ZIVA_TRIP", str(tmp_path / "nowhere"))
    assert local_paths.ziva_trip() is None  # named, but not on this machine


def test_the_repo_itself_is_clean():
    assert guard.main() == 0
