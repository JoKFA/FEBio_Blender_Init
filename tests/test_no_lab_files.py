"""The guard that keeps the lab's and vendors' files out of git must be able to fail."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_no_lab_files as guard  # noqa: E402


def test_forbidden_kinds_and_known_content_are_reported_and_ordinary_files_are_not():
    files = {"docs/readme.md": "aa", "assets/Scene.MB": "bb", "data/motion.pkl": "cc", "data/renamed.json": "dd",
             "runs/lips.points.f32": "ee", "tools/x.py": "ff"}
    found = guard.violations(files, {"dd"})
    assert [line.split(":")[0] for line in found] == ["assets/Scene.MB", "data/motion.pkl", "data/renamed.json",
                                                      "runs/lips.points.f32"]
    assert guard.violations({"docs/readme.md": "aa", "tools/x.py": "ff"}, {"dd"}) == []


def test_the_repo_itself_is_clean():
    assert guard.main() == 0
