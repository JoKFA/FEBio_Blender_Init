"""The real prototype run (T-06a acceptance): the lab's lips, the placeholder jaw motion, the whole pipeline,
twice (at most two lip runs in this whole file, about a minute each). Slow, so it runs only with ASRP_SLOW=1;
`tools/verify.py` sets it, so the definition of done includes the real lips:

    ASRP_SLOW=1 uv run python -m pytest tests/test_prototype.py -q

It is the test form of the command lines in docs/09's T-06a card:

    uv run asrp import-asset data/lab_export <out>
    uv run python tools/placeholder_jaw_motion.py <out>/scene.json <out>/placeholder_jaw.json
    uv run asrp run <out>/scene.json <out>/placeholder_jaw.json
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import placeholder_jaw_motion
import pytest

from asrp_core import run, scene, simulate, trajectory
from asrp_core.asset import lab
from asrp_core.doctor import febio_exe

REPO = Path(__file__).resolve().parents[1]
EXPORT = REPO / "data" / "lab_export"
TET = REPO / "data" / "tetmesh" / "lips.json"

pytestmark = pytest.mark.skipif(
    os.environ.get("ASRP_SLOW") != "1" or not (EXPORT / "mesh_report.json").is_file() or not TET.is_file(),
    reason="the full lip run takes minutes: set ASRP_SLOW=1 (needs data/lab_export and data/tetmesh/lips.json)")


@pytest.fixture(scope="module")
def prototype(tmp_path_factory):
    out = tmp_path_factory.mktemp("prototype")
    lab.import_asset(EXPORT, out / "asset", TET)
    traj = out / "asset" / "placeholder_jaw.json"
    trajectory.write(traj, placeholder_jaw_motion.build(out / "asset" / "scene.json"))
    runs = [simulate.run_scene(out / "asset" / "scene.json", traj, out / "runs", febio_exe(), "prototype")
            for _ in range(2)]
    return out, runs


def test_the_placeholder_opens_the_jaw_downwards(prototype):
    out, _ = prototype
    s = scene.load(out / "asset" / "scene.json")
    t = trajectory.read(out / "asset" / "placeholder_jaw.json")
    jaw = next(b for b in s.bones if b.name == "jaw")
    from asrp_core.asset import coords
    centre = coords.read_obj(out / "asset" / jaw.mesh.path)[0].mean(axis=0)
    drop = centre[2] - trajectory.apply(t.drivers["jaw01"][placeholder_jaw_motion.OPEN_AT], centre)[2]
    assert drop > 5.0  # mm: the jaw's centre goes down when it opens
    assert t.frames == 51 and all(m == t.drivers["jaw01"][0] for m in t.drivers["jaw01"][:15])


def test_the_whole_motion_runs_and_all_five_checks_pass(prototype):
    _, runs = prototype
    for r in runs:
        assert r.status == "complete" and r.passed, r.report["checks"]
        checks = r.report["checks"]
        assert checks["a"]["numbers"]["frames_logged"] == 50
        assert checks["b"]["numbers"]["hard_display_vertices_max_deviation_mm"] < 1e-3
        c = checks["c"]["numbers"]  # the model's estimate on the lips is about 0.146 mm (L = 25 mm); measured about 0.095
        assert checks["c"]["passed"] and 0.1 < c["expected_sag_mm"] < 0.2 and 20 < c["free_length_mm"] < 30
        assert c["expected_sag_mm"] / 10 <= c["mean_sag_along_gravity_mm"] <= c["expected_sag_mm"] * 10
        assert not any(s["flag"] for s in r.report["spring_slip"].values()), r.report["spring_slip"]
        assert {k: c["passed"] for k, c in checks.items()} == {"a": True, "b": True, "b2": True, "c": True, "d": True}
        assert checks["d"]["numbers"]["inverted_tets"] == 0 and checks["d"]["numbers"]["min_volume_ratio"] > 0
        assert {k: r.report["settled_shape"][k] for k in ("available", "frame")} == {"available": True, "frame": 14}  # + reported-only tissue_step keys
        back = r.report["return_to_settled"]  # the jaw is closed again at frame 50 only
        assert back["frames"] == [50] and 0 < back["max_mm"] < 0.1 and back["mean_mm"] <= back["max_mm"]


def test_the_jaw_carries_the_lower_lip_down(prototype):
    _, runs = prototype
    d = simulate.read_display(runs[0].run_dir / simulate.DISPLAY)["positions"]
    s = scene.load(runs[0].run_dir / "scene.json")
    lower = [v for v, _ in next(a for a in s.attachments if a.name == "lower_lip_on_jaw").weights]
    upper = [v for v, _ in next(a for a in s.attachments if a.name == "upper_lip_on_skull").weights]
    open_at = placeholder_jaw_motion.OPEN_AT
    assert d[open_at, lower, 2].mean() - d[14, lower, 2].mean() < -2.0  # mm
    assert abs(d[open_at, upper, 2].mean() - d[14, upper, 2].mean()) < 1e-6  # hard on the fixed skull


def test_same_input_twice_agrees_within_1e_9_mm_at_the_default_threads(prototype):
    _, (a, b) = prototype
    for reader, header in ((run.read_positions, run.POSITIONS), (simulate.read_display, simulate.DISPLAY)):
        name = header
        pa = reader(a.run_dir / header)["positions"]
        pb = reader(b.run_dir / header)["positions"]
        assert pa.shape == pb.shape and pa.size > 0 and np.abs(pa - pb).max() <= 1e-9, name
        assert np.abs(pa - pa[0]).max() > 1.0  # the lips really move, so "equal" is not "nothing happened"
    assert len(json.loads((a.run_dir / "physics" / "settled_frame14.json").read_text())["display"]) > 0
    # Bit-identical playback is a one-thread property (asrp run --threads 1; tests/test_generate.py, test_run.py):
    # it is not asserted here because a third lip run would double this file's time.
    assert json.loads((a.run_dir / "provenance.json").read_text())["parameters"]["febio_env"]["OMP_NUM_THREADS"]         == str(min(4, os.cpu_count()))


def test_the_run_report_lists_every_temporary_value_and_the_unbuilt_attachments(prototype):
    _, runs = prototype
    report = json.loads((runs[0].run_dir / "run_report.json").read_text(encoding="utf-8"))
    where = {p["where"]: p for p in report["parameters"]}
    in_scene = list(scene.parameters(json.loads((runs[0].run_dir / "scene.json").read_text(encoding="utf-8"))))
    assert len(in_scene) == 18 and all(f"scene.{w}" in where for w, _ in in_scene)
    assert where["scene.soft_tissues[lips].material.E_mpa"]["value"] == 0.015
    assert all(p["source"] in scene.SOURCES for p in report["parameters"])
    assert sum(p["source"] == "ours" for p in report["parameters"]) > 15
    assert len(report["simplifications"]) == 3 and "6 muscles" in report["simplifications"][0]
    assert report["simplifications"] == scene.load(runs[0].run_dir / "scene.json").simplifications
    assert where["trajectory.source"]["source"] == "ours" and "attachments_not_built" not in report
    assert report["timing"]["febio_s_per_frame"] > 0 and not {"budget_s_per_frame", "budget_note"} & set(report["timing"])


@pytest.mark.skipif(sys.platform != "win32", reason="Blender path is the Windows default here")
def test_the_playback_loads_in_blender_frame_for_frame(prototype):
    from asrp_core.doctor import BLENDER_CANDIDATES, locate
    blender = locate("ASRP_BLENDER", ["blender"], BLENDER_CANDIDATES)
    if blender.path is None:
        pytest.skip("Blender not found")
    _, runs = prototype
    proc = subprocess.run([str(blender.path), "--background", "--factory-startup", "--python-exit-code", "1", "--python",
                           str(REPO / "tools" / "render_prototype.py"), "--", str(runs[0].run_dir), "--check-only"],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "PROTOTYPE PLAYBACK CHECK PASSED" in proc.stdout
    frame = json.loads((runs[0].run_dir / "run_report.json").read_text(encoding="utf-8"))["settled_shape"]["frame"]
    assert f"at frames [0, {frame}, " in proc.stdout  # the settled frame comes from the run's report, not a constant
