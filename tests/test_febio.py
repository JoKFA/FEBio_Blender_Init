import pytest

from asrp_core import febio
from asrp_core.doctor import febio_exe

LOG = """\
 Data Record #1
===========================================================================
Step = 0
Time = 0
Data = positions
1,0,0,-5
2,5,0,-5

Data Record #2
===========================================================================
Step = 0
Time = 0
Data = stress
1,9,9,9

 N O N L I N E A R   I T E R A T I O N   I N F O R M A T I O N
Data Record #1
===========================================================================
Step = 1
Time = 0.0333333333
Data = positions
1,0,-0.25,-5.5
2,5,-0.25,-5.5
"""


def test_read_node_data_keeps_only_the_named_series(tmp_path):
    log = tmp_path / "run.log"
    log.write_text(LOG)

    hist = febio.read_node_data(log, "positions")

    assert hist.times == [0.0, 0.0333333333]
    assert hist.values[0] == {1: (0.0, 0.0, -5.0), 2: (5.0, 0.0, -5.0)}
    assert hist.values[1][2] == (5.0, -0.25, -5.5)


def test_read_node_data_unknown_name_is_empty(tmp_path):
    log = tmp_path / "run.log"
    log.write_text(LOG)

    assert febio.read_node_data(log, "velocity").times == []


DATA_FILE = (
    "*Step  = 0\r\n*Time  = 0\r\n*Data  = positions\r\n1,0,0,-5\r\n2,5,0,-5\r\n"
    "*Step  = 1\r\n*Time  = 0.0333333333\r\n*Data  = positions\r\n1,0,-0.25,-5.5\r\n2,5,-0.25,-5.5\r\n"
)


def feb_naming(tmp_path, file=None):
    """A .feb with only the Output part, which is all `read_node_series` looks at."""
    attr = f' file="{file}"' if file else ""
    feb = tmp_path / "m.feb"
    feb.write_text('<febio_spec version="4.0"><Output><logfile>'
                   f'<node_data data="x;y;z" name="positions" delim=","{attr}/></logfile></Output></febio_spec>')
    return feb


def test_read_node_series_from_the_data_file_gives_numpy_arrays(tmp_path):
    feb = feb_naming(tmp_path, "positions.txt")
    (tmp_path / "positions.txt").write_bytes(DATA_FILE.encode())

    series = febio.read_node_series(feb, tmp_path / "m.log")

    assert series.times.tolist() == [0.0, 0.0333333333]
    assert series.node_ids.tolist() == [1, 2]
    assert series.values.shape == (2, 2, 3)
    assert series.values[1, 1].tolist() == [5.0, -0.25, -5.5]


def test_read_node_series_falls_back_to_the_log_when_the_feb_names_no_file(tmp_path):
    feb = feb_naming(tmp_path)
    (tmp_path / "m.log").write_text(LOG)

    series = febio.read_node_series(feb, tmp_path / "m.log")

    assert series.times.tolist() == [0.0, 0.0333333333]
    assert series.node_ids.tolist() == [1, 2]
    assert series.values[0, 1].tolist() == [5.0, 0.0, -5.0]  # the stress record in the log is not mixed in


def test_read_node_series_refuses_frames_that_list_different_nodes(tmp_path):
    feb = feb_naming(tmp_path, "positions.txt")
    other = DATA_FILE.replace("1,0,-0.25,-5.5\r\n2,5", "1,0,-0.25,-5.5\r\n3,5")  # frame 1 lists nodes 1 and 3
    (tmp_path / "positions.txt").write_bytes(other.encode())
    with pytest.raises(ValueError, match="other nodes than the first record"):
        febio.read_node_series(feb, tmp_path / "m.log")

    shorter = DATA_FILE.rsplit("2,5,-0.25,-5.5\r\n", 1)[0]  # frame 1 lists only node 1
    (tmp_path / "positions.txt").write_bytes(shorter.encode())
    with pytest.raises(ValueError, match="1 against 2"):
        febio.read_node_series(feb, tmp_path / "m.log")

    swapped = DATA_FILE.replace("1,0,-0.25,-5.5\r\n2,5,-0.25,-5.5", "2,5,-0.25,-5.5\r\n1,0,-0.25,-5.5")  # same nodes, new order
    (tmp_path / "positions.txt").write_bytes(swapped.encode())
    with pytest.raises(ValueError, match="other nodes"):
        febio.read_node_series(feb, tmp_path / "m.log")


def test_read_node_series_refuses_a_missing_file_a_bad_row_and_a_folder_in_the_name(tmp_path):
    feb = feb_naming(tmp_path, "positions.txt")
    with pytest.raises(ValueError, match="did not write positions.txt"):
        febio.read_node_series(feb, tmp_path / "m.log")

    (tmp_path / "positions.txt").write_bytes(DATA_FILE.replace("2,5,0,-5", "2,5,0").encode())
    with pytest.raises(ValueError, match="id,x,y,z"):
        febio.read_node_series(feb, tmp_path / "m.log")

    with pytest.raises(ValueError, match="plain file name"):
        febio.read_node_series(feb_naming(tmp_path, "../positions.txt"), tmp_path / "m.log")


def test_step_counter_agrees_with_steps_done_however_the_log_arrives(tmp_path):
    log = tmp_path / "grow.log"
    text = "\n".join(f"{'-' * 5} converged at time : {i}\nother text {i}\n" for i in range(40)).encode()
    for piece in (1, 7, 64, 1000):  # arbitrary cuts, including ones inside a line
        log.write_bytes(b"")
        counter = febio.StepCounter(log)
        assert counter.poll() == 0
        for i in range(0, len(text), piece):
            with log.open("ab") as f:
                f.write(text[i:i + piece])
            now = counter.poll()
            assert now <= febio.steps_done(log) and now >= febio.steps_done(log) - 1  # a half-written line may lag by one
        assert counter.poll() == febio.steps_done(log) == 40
    assert febio.StepCounter(tmp_path / "missing.log").poll() == 0


def test_s1_dynamic_jaw_runs_in_real_febio(tmp_path):
    """Spike S1 as a regression check: dynamic analysis, rigid hinge, gravity sign."""
    try:
        febio_exe()
    except FileNotFoundError:
        pytest.skip("FEBio not installed")
    from s1_dynamic_jaw import FRAMES, run_and_check

    result = run_and_check(tmp_path)

    assert result["frames"] == FRAMES + 1
    assert result["jaw_error"] < 1e-6
    assert result["settle_mean"] < 0


def test_s1_repeats_within_tolerance(tmp_path):
    """Reproducibility standard (docs ADR-15, ADR-37): at the default threads the same input twice agrees within
    1e-9 mm at every node and frame; with one thread the playback cache is identical byte for byte.

    The raw FEBio log is not compared: it contains timestamps.
    """
    try:
        febio_exe()
    except FileNotFoundError:
        pytest.skip("FEBio not installed")
    import math

    from s1_dynamic_jaw import run_and_check

    runs = [run_and_check(tmp_path / name) for name in ("a", "b")]
    a, b = (febio.read_node_data(tmp_path / name / "s1.log", "positions") for name in ("a", "b"))
    assert a.times == b.times and len(a.values) == runs[0]["frames"]
    worst = max(math.dist(fa[n], fb[n]) for fa, fb in zip(a.values, b.values) for n in fa)
    assert worst <= 1e-9

    for name in ("c", "d"):
        run_and_check(tmp_path / name, threads=1)
    assert (tmp_path / "c" / "playback.pc2").read_bytes() == (tmp_path / "d" / "playback.pc2").read_bytes()
