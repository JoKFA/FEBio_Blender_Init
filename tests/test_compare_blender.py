"""Ziva's playback package, played in a real Blender (headless), against the export's own Alembic file, frame by
frame (docs/09 T-11): every frame 0 to 46, 30 frames per second, same vertex numbering, millimetres, largest
difference under 1e-4 mm. The control sets the timeline to 24 frames per second and must NOT agree (the card's
pit: at 24 the Alembic's frame 14 is read as 17.5). Skips, with a printed reason, when Blender or the lab's data
is not on this machine."""

import json
import subprocess
from pathlib import Path

import local_paths
import pytest

from asrp_core import ziva_compare

REPO = Path(__file__).resolve().parents[1]
BLENDER = Path("C:/Program Files/Blender Foundation/Blender 5.2/blender.exe")
SCRIPT = REPO / "tests" / "blender_ziva_alembic.py"


def blender(package: Path, abc: Path, result: Path, *extra: str) -> dict:
    done = subprocess.run([str(BLENDER), "--background", "--factory-startup", "--python-exit-code", "1", "--python",
                           str(SCRIPT), "--", str(package), str(abc), "0.962", str(result), *extra],
                          capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    return json.loads(result.read_text(encoding="utf-8"))


def test_the_package_in_blender_is_the_alembic_on_every_frame(tmp_path):
    trip = local_paths.ziva_trip()
    if trip is None:
        pytest.skip("NOT VERIFIED: the Ziva trip data is not on this machine; " + local_paths.HOW_TO_SET)
    if not BLENDER.is_file():
        pytest.skip(f"NOT VERIFIED: no Blender at {BLENDER}")
    export = sorted((trip / "ziva_reference").glob("neutral_to_AA_export_*"))[-1]
    z = ziva_compare.read_ziva(export, 0.962, 47)
    ziva_compare.write_ziva_package(tmp_path, z, export.name, 30.0)
    package = tmp_path / ziva_compare.PACKAGE
    good = blender(package, export / "lips_physics.abc", tmp_path / "good.json")
    assert good["fps"] == 30 and good["frames"] == 47 and len(good["per_frame_max_mm"]) == 47
    assert good["max_mm"] < 1e-4, good["max_mm"]
    bad = blender(package, export / "lips_physics.abc", tmp_path / "bad.json", "24")
    assert bad["fps"] == 24 and bad["max_mm"] > 1.0, "read at 24 frames per second the frames must NOT agree"
