"""tools/render_prototype.py refuses a run that has no settled shape. Needs Blender (the tool runs inside it) but no
FEBio run, so unlike tests/test_prototype.py it is not slow and always runs where Blender is installed."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != "win32", reason="Blender path is the Windows default here")
def test_the_render_tool_refuses_a_run_without_a_settled_shape(tmp_path):
    from asrp_core.doctor import BLENDER_CANDIDATES, locate
    blender = locate("ASRP_BLENDER", ["blender"], BLENDER_CANDIDATES)
    if blender.path is None:
        pytest.skip("Blender not found")
    (tmp_path / "run_report.json").write_text(json.dumps({"settled_shape": {"available": False, "frame": None}}))
    proc = subprocess.run([str(blender.path), "--background", "--factory-startup", "--python-exit-code", "1", "--python",
                           str(REPO / "tools" / "render_prototype.py"), "--", str(tmp_path), "--check-only"],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode != 0 and "has no settled shape" in proc.stdout + proc.stderr
    assert "Nothing was rendered" in proc.stdout + proc.stderr
