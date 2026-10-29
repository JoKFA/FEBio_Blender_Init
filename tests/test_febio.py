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
    """Reproducibility standard (docs ADR-15): same input -> positions within 1e-9 mm, identical playback cache.

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
    assert (tmp_path / "a" / "playback.pc2").read_bytes() == (tmp_path / "b" / "playback.pc2").read_bytes()
