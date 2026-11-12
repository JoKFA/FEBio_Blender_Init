"""T-08: the run shell (stand-in mode) against real FEBio, on the small S1 model (46 nodes x 45 frames, <1 s)."""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import pytest

from asrp_core import cli, febio, provenance, run
from asrp_core.doctor import febio_exe

try:
    EXE = febio_exe()
except FileNotFoundError:
    pytest.skip("FEBio not installed", allow_module_level=True)

from s1_dynamic_jaw import FRAMES, build_feb  # noqa: E402

PHYSICS_FILES = {"model.feb", "model.log", "physics/positions.json", "provenance.json"}


def make_feb(path, time_steps=None, jaw_open=None, drop_output=False):
    """The S1 model, optionally with a different step count, a jaw angle that breaks it, or no node output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    build_feb(path)
    text = path.read_text()
    if time_steps is not None:
        text = text.replace(f"<time_steps>{FRAMES}</time_steps>", f"<time_steps>{time_steps}</time_steps>")
    if jaw_open is not None:
        text = re.sub(r'(<value lc="2">)[^<]*', rf"\g<1>{jaw_open}", text)
    if drop_output:
        text = re.sub(r"<Output>.*</Output>", "", text, flags=re.S)
    path.write_text(text)
    return path


def files_in(folder):
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def execute(feb, runs, **kw):
    return run.execute(run.standin(feb), runs, EXE, **kw)


def positions(result):
    return run.read_positions(result.run_dir / run.POSITIONS)["positions"]


def max_diff(a, b):
    assert len(a) == len(b) > 0
    return max(abs(x - y) for fa, fb in zip(a, b) for pa, pb in zip(fa, fb) for x, y in zip(pa, pb))


def pid_alive(pid):
    """True if a process with this id is still running (Windows API; tasklist output is localized)."""
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return False  # no such process
    try:
        return k32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102  # WAIT_TIMEOUT: still running
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))


def febio_processes_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq febio4.exe", "/NH"], capture_output=True).stdout
    return b"febio4.exe" in out


def start_in_background(feb, runs, **kw):
    """Run in a thread; returns (thread, box). box['result'] is filled when the run ends."""
    box = {}
    t = threading.Thread(target=lambda: box.update(result=execute(feb, runs, **kw)))
    t.start()
    return t, box


def wait_for(condition, seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_run_folder_has_exactly_what_this_step_produces(tmp_path, capsys):
    feb = make_feb(tmp_path / "in" / "jaw.feb")

    code = cli.main(["run", "--feb", str(feb), "--runs-dir", str(tmp_path / "runs")])

    out = capsys.readouterr().out
    assert code == 0, out
    (folder,) = (tmp_path / "runs").iterdir()
    assert re.fullmatch(r"\d{4}-\d\d-\d\d_jaw_001", folder.name)
    # No scene.json, trajectory.json, meshes/, playback or compare/ yet (T-06a); and no stray plot file.
    assert files_in(folder) == PHYSICS_FILES
    assert f"progress   frame {FRAMES} / {FRAMES}" in out and "run COMPLETE" in out

    record = provenance.read(folder)
    assert record["status"] == "complete" and record["failure"] is None
    assert record["inputs"]["model.feb"]["sha256"] == provenance.sha256_file(feb)
    assert record["software"]["febio"] == "4.13.0"
    assert record["software"]["asrp"] and record["software"]["python"]
    assert record["parameters"]["total_frames"] == FRAMES and "-noconfig" in record["parameters"]["febio_args"]
    assert record["command"] == ["asrp", "run", "--feb", "jaw.feb"]
    assert set(record["outputs"]) == {run.POSITIONS}
    assert provenance.mismatches(folder) == []
    # Nothing machine-specific anywhere in it: no drive letter, no temp folder, no user name.
    raw = (folder / "provenance.json").read_text()
    assert not re.search(r"[A-Za-z]:[\\/]|\\\\", raw) and str(tmp_path) not in raw
    data = run.read_positions(folder / run.POSITIONS)
    assert len(data["times_s"]) == FRAMES + 1 and len(data["node_ids"]) == 72


def test_a_tampered_input_is_noticed(tmp_path):
    result = execute(make_feb(tmp_path / "a.feb"), tmp_path / "runs")
    (result.run_dir / "model.feb").write_text("changed")

    assert provenance.mismatches(result.run_dir) == ["model.feb"]


def test_progress_is_readable_while_the_run_goes(tmp_path):
    feb = make_feb(tmp_path / "long.feb", time_steps=20000)  # far longer than the test waits
    seen = []
    t, box = start_in_background(feb, tmp_path / "runs", on_progress=seen.append, cancel=(stop := threading.Event()))
    try:
        assert wait_for(lambda: list((tmp_path / "runs").glob("*/provenance.json")))
        folder = next((tmp_path / "runs").iterdir())
        # Poll the way the Blender add-on will: only the run folder, from outside the running process.
        assert wait_for(lambda: run.read_progress(folder).done >= 3)
        p = run.read_progress(folder)
        assert (p.status, p.total) == ("running", 20000) and 3 <= p.done < 20000
        assert wait_for(lambda: any(0 < s.done < s.total for s in seen))  # the shell polls every 0.1 s
    finally:
        stop.set()
        t.join(60)
    assert box["result"].status == "cancelled"


def test_cancel_really_ends_febio(tmp_path):
    feb = make_feb(tmp_path / "long.feb", time_steps=20000)
    pids = []
    cancel = threading.Event()
    t, box = start_in_background(feb, tmp_path / "runs", cancel=cancel, on_progress=lambda p: pids.append(p))
    assert wait_for(lambda: pids and pids[-1].done >= 2)
    folder = next((tmp_path / "runs").iterdir())
    # FEBio is a live process of the right name right now (so the later "gone" check can fail).
    assert febio_processes_running()

    cancel.set()
    t.join(60)

    result = box["result"]
    assert not t.is_alive() and result.status == "cancelled" and result.febio_pid
    assert not pid_alive(result.febio_pid)
    record = provenance.read(folder)
    assert record["status"] == "cancelled" and "cancel" in record["failure"]["message"]
    assert files_in(folder) == {"model.feb", "model.log", "provenance.json"}  # no result files


def test_cancel_file_from_another_process_cancels(tmp_path):
    feb = make_feb(tmp_path / "long.feb", time_steps=20000)
    t, box = start_in_background(feb, tmp_path / "runs")
    assert wait_for(lambda: list((tmp_path / "runs").glob("*/model.log")))
    folder = next((tmp_path / "runs").iterdir())
    (folder / run.CANCEL_FILE).write_text("")

    t.join(60)

    assert box["result"].status == "cancelled" and not pid_alive(box["result"].febio_pid)
    assert not (folder / run.CANCEL_FILE).exists()


def test_runs_are_reproducible_to_1e_9_mm(tmp_path):
    feb = make_feb(tmp_path / "jaw.feb")

    a = execute(feb, tmp_path / "runs")
    b = execute(feb, tmp_path / "runs")

    assert a.run_dir != b.run_dir and a.status == b.status == "complete"
    pa, pb = positions(a), positions(b)
    # The same numbers come out of the raw log as out of the saved file; the log itself is never compared.
    from_log = febio.read_node_data(a.run_dir / "model.log", "positions").values
    assert max_diff(pa, [[list(f[n]) for n in sorted(f)] for f in from_log]) == 0
    moved = max_diff(pa, [pa[0]] * len(pa))
    assert moved > 1.0  # the model really moves (the jaw opens), so "equal" is not "nothing happened"
    assert max_diff(pa, pb) <= 1e-9


def test_one_thread_is_bit_identical_and_the_threads_actually_used_are_recorded(tmp_path):
    feb = make_feb(tmp_path / "jaw.feb")
    a = execute(feb, tmp_path / "runs", threads=1)
    b = execute(feb, tmp_path / "runs", threads=1)
    assert max_diff(positions(a), positions(b)) == 0  # exactly, not within 1e-9
    assert provenance.read(a.run_dir)["parameters"]["febio_env"] == {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    default = execute(feb, tmp_path / "runs")
    want = str(min(febio.DEFAULT_THREADS, os.cpu_count()))
    assert provenance.read(default.run_dir)["parameters"]["febio_env"] == {"OMP_NUM_THREADS": want, "MKL_NUM_THREADS": want}
    assert max_diff(positions(a), positions(default)) <= 1e-9


def test_the_thread_count_is_capped_at_the_cpus_and_a_bad_one_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert febio.DEFAULT_THREADS == 4 and febio.threads_used() == 2 and febio.threads_used(1) == 1
    assert febio.threads_used(16) == 2
    env = febio.environment(16)
    assert env["OMP_NUM_THREADS"] == "2" and env["MKL_NUM_THREADS"] == "2"
    monkeypatch.setattr(os, "cpu_count", lambda: 32)
    assert febio.threads_used() == 4 and febio.environment()["OMP_NUM_THREADS"] == "4"
    for bad in (0, -1, 2.5, True):
        with pytest.raises(ValueError, match="threads must be a whole number, at least 1"):
            febio.threads_used(bad)
    feb = make_feb(tmp_path / "jaw.feb")
    with pytest.raises(ValueError, match="threads must be"):
        execute(feb, tmp_path / "runs", threads=0)
    assert not (tmp_path / "runs").exists()  # refused before a run folder was made
    with pytest.raises(SystemExit):
        cli.main(["run", "--feb", str(feb), "--threads", "0"])
    assert "not a thread count" in capsys.readouterr().err


def test_a_copied_run_folder_reruns_from_its_own_files_alone(tmp_path):
    original = execute(make_feb(tmp_path / "src" / "jaw.feb"), tmp_path / "runs")
    reference = positions(original)
    elsewhere = tmp_path / "somewhere" / "else" / "copy_of_run"
    shutil.copytree(original.run_dir, elsewhere)
    shutil.rmtree(original.run_dir)  # the source folder and the source .feb are gone: only the copy exists
    (tmp_path / "src" / "jaw.feb").unlink()

    assert provenance.mismatches(elsewhere) == []
    again = run.execute(run.standin(elsewhere / "model.feb"), tmp_path / "other_runs", EXE)

    assert again.status == "complete"
    assert max_diff(reference, positions(again)) <= 1e-9
    assert provenance.read(again.run_dir)["inputs"] == provenance.read(elsewhere)["inputs"]


def test_non_convergence_names_the_frame_and_leaves_no_results(tmp_path, capsys):
    feb = make_feb(tmp_path / "bad.feb", jaw_open=-9.0)  # the jaw turns far too fast: negative jacobians at step 20

    code = cli.main(["run", "--feb", str(feb), "--runs-dir", str(tmp_path / "runs")])

    out = capsys.readouterr().out
    assert code == 1
    assert "frame 20" in out and "no results written" in out and "negative jacobians" in out
    (folder,) = (tmp_path / "runs").iterdir()
    assert files_in(folder) == {"model.feb", "model.log", "provenance.json"}
    record = provenance.read(folder)
    assert record["status"] == "failed" and record["failure"]["frame"] == 20
    assert "negative jacobians" in record["failure"]["message"] and record["outputs"] == {}


def test_a_feb_without_node_output_fails_and_says_why(tmp_path):
    result = execute(make_feb(tmp_path / "quiet.feb", drop_output=True), tmp_path / "runs")

    assert result.status == "failed" and "node_data" in result.failure.message
    assert not (result.run_dir / "physics").exists()


def test_a_missing_feb_or_a_non_english_path_is_refused_in_plain_words(tmp_path):
    with pytest.raises(run.RunError, match="Cannot find"):
        run.standin(tmp_path / "nope.feb")
    with pytest.raises(run.RunError, match="non-English"):
        run.require_ascii(tmp_path / "运行")


def test_run_with_half_the_arguments_says_what_to_do(capsys):
    assert cli.main(["run", "scene.json"]) == 2
    assert "<scene.json> <trajectory.json>" in capsys.readouterr().out
    assert cli.main(["run"]) == 2


def test_run_of_a_missing_scene_starts_nothing(tmp_path, capsys):
    assert cli.main(["run", str(tmp_path / "scene.json"), str(tmp_path / "traj.json"), "--runs-dir",
                     str(tmp_path / "runs")]) == 1
    out = capsys.readouterr().out
    assert "does not exist" in out and "run NOT STARTED" in out
    assert not (tmp_path / "runs").exists()


def test_the_installed_entry_point_works(tmp_path):
    feb = make_feb(tmp_path / "jaw.feb")

    proc = subprocess.run([sys.executable, "-m", "asrp_core.cli", "run", "--feb", str(feb), "--runs-dir",
                           str(tmp_path / "runs")], capture_output=True, text=True)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads((next((tmp_path / "runs").iterdir()) / "provenance.json").read_text())["status"] == "complete"


def test_the_process_check_can_tell_alive_from_gone():
    """Guards test_cancel_really_ends_febio: the check must say True for a live process and False after a kill."""
    import os

    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    assert pid_alive(os.getpid()) and pid_alive(sleeper.pid)
    febio.kill_tree(sleeper)
    assert not pid_alive(sleeper.pid)


def test_positions_are_divided_by_k_and_the_recorded_hash_matches(tmp_path):
    feb = make_feb(tmp_path / "jaw.feb")
    one = execute(feb, tmp_path / "runs")
    prepared = run.standin(feb)
    prepared.length_scale = 2.0

    two = run.execute(prepared, tmp_path / "runs", EXE)

    raw = positions(one)  # k = 1: FEBio's own coordinates
    assert max_diff([[[c / 2 for c in p] for p in f] for f in raw], positions(two)) <= 1e-9
    assert max_diff(raw, positions(two)) > 1.0  # the scaling really changed the numbers
    record = provenance.read(two.run_dir)
    assert record["parameters"]["length_scale"] == 2.0 and provenance.read(one.run_dir)["parameters"]["length_scale"] == 1.0
    assert provenance.mismatches(two.run_dir) == []


def test_a_run_whose_step_count_differs_from_time_steps_but_reaches_the_end_time_completes(tmp_path):
    # FEBio's time stepper may change the step (retries after a cut, growth when convergence is easy): a run that
    # reaches the requested end time is complete whatever its step count (PR #7 review). Here the stepper grows
    # the step, so FEBio converges fewer times than <time_steps>; the old step-count check called this a failure.
    feb = make_feb(tmp_path / "in" / "adaptive.feb")
    text = feb.read_text()
    dt = 1.0 / 30
    stepper = (f"<time_stepper type=\"default\"><max_retries>5</max_retries><opt_iter>200</opt_iter>"
               f"<dtmin>{dt / 16!r}</dtmin><dtmax>{4 * dt!r}</dtmax></time_stepper>\n    <solver")
    feb.write_text(text.replace("<solver", stepper, 1))
    result = execute(feb, tmp_path / "runs")
    record = json.loads((result.run_dir / "provenance.json").read_text())
    steps = febio.steps_done(result.run_dir / "model.log")
    assert steps != FRAMES, f"the stepper did not change the step count ({steps}); the test proves nothing"
    assert record["status"] == "complete", record.get("failure")
    assert abs(febio.time_reached(result.run_dir / "model.log") - febio.end_time(feb)) < 1e-4


def test_provenance_records_the_source_commit(tmp_path):
    # 04 section 5.4 (PR #7 review): the package version does not change between milestones, the commit does.
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=provenance.SOURCE_ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    result = execute(make_feb(tmp_path / "in" / "s1.feb"), tmp_path / "runs")
    source = json.loads((result.run_dir / "provenance.json").read_text())["software"]["asrp_source"]
    assert len(head) == 40 and source["commit"] == head
    assert source["dirty"] in (True, False)


def test_control_settings_inside_xml_comments_do_not_count(tmp_path):
    # PR #7 review: a .feb keeping old settings in a comment was failed after a normal solve.
    feb = make_feb(tmp_path / "in" / "commented.feb")
    old = "<!-- <Control><time_steps>60</time_steps><step_size>0.1</step_size></Control> -->\n  <Control>"
    feb.write_text(feb.read_text().replace("<Control>", old, 1))
    assert "<time_steps>60</time_steps>" in feb.read_text()
    assert febio.total_steps(feb) == FRAMES
    assert febio.end_time(feb) == pytest.approx(FRAMES / 30)
    result = execute(feb, tmp_path / "runs")
    record = json.loads((result.run_dir / "provenance.json").read_text())
    assert record["status"] == "complete", record.get("failure")


def test_a_run_that_stops_short_of_the_end_time_is_not_complete(tmp_path):
    log = tmp_path / "model.log"
    log.write_text("------- converged at time : 0.0333333\n------- converged at time : 0.0666667\n")
    feb = make_feb(tmp_path / "short.feb")
    assert febio.end_time(feb) == pytest.approx(FRAMES / 30)
    assert febio.time_reached(log) == pytest.approx(0.0666667)


def test_local_paths_in_a_failure_message_are_reduced_to_names(tmp_path):
    run_dir = tmp_path / "runs" / "2026-11-11_x_001"
    msg = f"cannot open {run_dir}\\model.feb and C:\\Users\\someone\\data\\mesh.json and /home/u/proj/a.obj ok"
    out = run.scrub_paths(msg, run_dir)
    assert out == "cannot open model.feb and mesh.json and a.obj ok"
    assert run.scrub_paths("plain text, no path", run_dir) == "plain text, no path"
