"""The scene run announces its run folder as soon as it exists (the Blender panel needs it while the run goes)."""

import cube_scene as cs
import pytest

from asrp_core import cli, simulate
from asrp_core.doctor import febio_exe

try:
    EXE = febio_exe()
except FileNotFoundError:
    pytest.skip("FEBio not installed", allow_module_level=True)


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
