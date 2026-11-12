"""The real prototype run (T-06a acceptance): the lab's lips, the placeholder jaw motion, the whole pipeline,
twice. About two minutes, so it runs only when asked:

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
import pytest

import placeholder_jaw_motion
from asrp_core import scene, simulate, trajectory
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


def test_the_whole_motion_runs_and_all_three_checks_pass(prototype):
    _, runs = prototype
    for r in runs:
        assert r.status == "complete" and r.passed, r.report["checks"]
        checks = r.report["checks"]
        assert checks["a"]["numbers"]["frames_logged"] == 50
        assert checks["b"]["numbers"]["hard_display_vertices_max_deviation_mm"] < 1e-3
        assert 0.067 <= checks["c"]["numbers"]["mean_sag_along_gravity_mm"] <= 6.7
        assert not any(s["flag"] for s in r.report["spring_slip"].values()), r.report["spring_slip"]


def test_the_jaw_carries_the_lower_lip_down(prototype):
    _, runs = prototype
    d = np.array(json.loads((runs[0].run_dir / "physics" / "display.json").read_text())["positions"])
    s = scene.load(runs[0].run_dir / "scene.json")
    lower = [v for v, _ in next(a for a in s.attachments if a.name == "lower_lip_on_jaw").weights]
    upper = [v for v, _ in next(a for a in s.attachments if a.name == "upper_lip_on_skull").weights]
    open_at = placeholder_jaw_motion.OPEN_AT
    assert d[open_at, lower, 2].mean() - d[14, lower, 2].mean() < -2.0  # mm
    assert abs(d[open_at, upper, 2].mean() - d[14, upper, 2].mean()) < 1e-6  # hard on the fixed skull


def test_same_input_twice_gives_bit_identical_playback(prototype):
    _, (a, b) = prototype
    for name in ("playback.json", "playback.pc2", "physics/display.json", "physics/settled_frame14.obj"):
        assert (a.run_dir / name).read_bytes() == (b.run_dir / name).read_bytes(), name


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
    assert report["timing"]["febio_s_per_frame"] > 0


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
